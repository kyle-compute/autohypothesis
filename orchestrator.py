from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scientific_process import (
    AggregateExperiment,
    EmpiricalFinding,
    ExperimentConfig,
    ExperimentPlan,
    ExperimentResult,
    FleetManifest,
    FleetWorker,
    Hypothesis,
    KnowledgeBase,
    ResearchBrief,
    ResultRow,
    WorkerStatus,
    append_jsonl,
    read_jsonl,
    utc_now_iso,
    write_json,
)


ROOT = Path(__file__).resolve().parent
RESEARCH_DIR = ROOT / "research"
BRIEF_PATH = RESEARCH_DIR / "research_brief.json"
KNOWLEDGE_PATH = RESEARCH_DIR / "knowledge_base.json"
PLANS_DIR = RESEARCH_DIR / "plans"
RUNS_DIR = RESEARCH_DIR / "runs"
LIVE_DIR = RESEARCH_DIR / "live"
LIVE_WORKERS_DIR = LIVE_DIR / "workers"
LIVE_SUMMARY_PATH = LIVE_DIR / "summary.json"
AGGREGATE_DIR = RESEARCH_DIR / "aggregate"
EXPERIMENTS_PATH = AGGREGATE_DIR / "experiments.json"
LEADERBOARD_PATH = AGGREGATE_DIR / "leaderboard.json"
FLEET_DIR = RESEARCH_DIR / "fleet"
FLEET_MANIFEST_PATH = FLEET_DIR / "manifest.json"
MAIN_AGENT_PROMPT_PATH = FLEET_DIR / "main-agent.md"
WORKER_PROMPTS_DIR = FLEET_DIR / "worker-prompts"
FLEET_BRIEF_PATH = AGGREGATE_DIR / "fleet_brief.md"
RESULTS_TSV_PATH = ROOT / "results.tsv"
PROGRESS_PNG_PATH = ROOT / "progress.png"
STALE_HEARTBEAT_SECONDS = 30.0


def has_git_metadata() -> bool:
    return (ROOT / ".git").exists()


def get_origin_remote() -> str:
    if not has_git_metadata():
        return "origin"
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "origin"
    return result.stdout.strip() or "origin"


def get_head_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "nogit"
    return result.stdout.strip() or "nogit"


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def now_utc() -> datetime:
    return datetime.now(UTC)


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def load_fleet_manifest() -> FleetManifest | None:
    payload = load_json(FLEET_MANIFEST_PATH)
    if payload is None:
        return None
    workers = [FleetWorker(**item) for item in payload.get("workers", [])]
    return FleetManifest(
        tag=payload["tag"],
        created_at=payload["created_at"],
        repository_root=payload["repository_root"],
        shared_research_dir=payload["shared_research_dir"],
        main_prompt_path=payload["main_prompt_path"],
        workers=workers,
    )


def save_fleet_manifest(manifest: FleetManifest) -> None:
    write_json(FLEET_MANIFEST_PATH, manifest.to_dict())


def write_results_tsv(rows: list[dict[str, Any]]) -> None:
    RESULTS_TSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_TSV_PATH.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["commit", "val_bpb", "memory_gb", "status", "description"])
        for row in rows:
            writer.writerow(
                [
                    row["commit"],
                    f"{row['val_bpb']:.6f}",
                    f"{row['memory_gb']:.1f}",
                    row["status"],
                    row["description"],
                ]
            )


def read_results_tsv(path: Path) -> list[ResultRow]:
    if not path.exists():
        return []
    with path.open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = []
        for row in reader:
            rows.append(
                ResultRow(
                    commit=row["commit"],
                    val_bpb=float(row["val_bpb"]),
                    memory_gb=float(row.get("memory_gb", 0.0) or 0.0),
                    status=row["status"],
                    description=row["description"],
                )
            )
        return rows


def best_result(rows: list[ResultRow]) -> ResultRow | None:
    kept = [row for row in rows if row.status == "keep"]
    if not kept:
        return None
    return min(kept, key=lambda row: row.val_bpb)


def summarize_findings(rows: list[ResultRow]) -> list[EmpiricalFinding]:
    findings: list[EmpiricalFinding] = []
    if not rows:
        return findings

    baseline = rows[0]
    best = best_result(rows)
    if best is not None:
        findings.append(
            EmpiricalFinding(
                finding_id="best-known-config",
                title="Current best scientific baseline",
                evidence=(
                    f"Best kept run is {best.commit} at val_bpb={best.val_bpb:.6f}; "
                    f"baseline was {baseline.val_bpb:.6f}."
                ),
                confidence="high",
                mechanism="Empirically strongest stack under the fixed CUDA time budget.",
                implication="Use this as the reference point for future hypotheses.",
            )
        )

    for index, row in enumerate(rows[1:], start=1):
        delta = row.val_bpb - baseline.val_bpb
        confidence = "medium" if row.status == "keep" else "low"
        findings.append(
            EmpiricalFinding(
                finding_id=f"result-{index:03d}",
                title=row.description,
                evidence=(
                    f"Observed val_bpb={row.val_bpb:.6f} ({delta:+.6f} vs baseline), "
                    f"status={row.status}."
                ),
                confidence=confidence,
                mechanism="Likely throughput, optimization, or architecture interaction under fixed wall clock.",
                implication=(
                    "Repeat or extend this family."
                    if row.status == "keep"
                    else "Treat as weak evidence."
                ),
            )
        )
    return findings


def extract_open_questions(
    rows: list[ResultRow], config: ExperimentConfig
) -> list[str]:
    descriptions = " ".join(row.description.lower() for row in rows)
    questions = []
    if "window" not in descriptions:
        questions.append(
            "Which sliding-window pattern best balances local and global context on the target GPU?"
        )
    if "warm" not in descriptions and config.warmdown_ratio > 0:
        questions.append(
            "Is the current LR schedule leaving quality on the table late in the fixed-budget run?"
        )
    if "depth" not in descriptions or config.depth <= 8:
        questions.append(
            "Has the current model reached the best depth-throughput frontier, or can a smaller model buy more useful steps?"
        )
    if "aspect" not in descriptions and "head" not in descriptions:
        questions.append(
            "Would changing width or head geometry improve attention quality without erasing throughput gains?"
        )
    if not questions:
        questions.append(
            "What combination experiment can distinguish whether current gains come from throughput, capacity, or optimizer geometry?"
        )
    return questions


def hypothesis_templates(
    config: ExperimentConfig, rows: list[ResultRow]
) -> list[Hypothesis]:
    baseline = best_result(rows)
    baseline_bpb = baseline.val_bpb if baseline is not None else math.inf
    history_text = " ".join(row.description.lower() for row in rows)
    hypotheses: list[Hypothesis] = []

    alt_window = "SLSL" if config.window_pattern != "SLSL" else "LSSL"
    hypotheses.append(
        Hypothesis(
            hypothesis_id="window-pattern-balance",
            title="Test a more balanced attention pattern",
            question="Can alternating local/global attention improve information flow more than the current grouped pattern?",
            why_now="Window pattern is a first-class architecture knob in `train.py`, but results history has not probed it yet.",
            rationale=(
                f"Current pattern `{config.window_pattern}` groups short windows. Testing `{alt_window}` probes whether alternating "
                "long-range access improves quality without changing parameter count."
            ),
            intervention={"window_pattern": alt_window},
            expected_effect={
                "val_bpb_direction": "down",
                "val_bpb_delta": "0.00 to -0.08",
                "num_steps_direction": "flat",
                "peak_vram_mb_direction": "flat",
            },
            success_criteria=f"Beat the current best val_bpb {baseline_bpb:.6f} without materially increasing memory.",
            alternative_explanations=[
                "Any gain may come from better optimization dynamics rather than better context mixing.",
                "A flat result may mean depth, not windowing, is the active bottleneck.",
            ],
            follow_if_supported=[
                "Test a second window family to map the local/global tradeoff.",
                "Combine the stronger pattern with a schedule change.",
            ],
            follow_if_not_supported=[
                "Stop spending budget on window patterns and switch to throughput or width.",
            ],
            confidence="medium",
            scientific_value="High information gain because it isolates an untested architectural mechanism.",
            family="architecture",
            score=0.76,
        )
    )

    smaller_batch = max(config.device_batch_size * 2048, config.total_batch_size // 2)
    if smaller_batch < config.total_batch_size:
        hypotheses.append(
            Hypothesis(
                hypothesis_id="throughput-more-steps",
                title="Trade batch for more optimizer steps",
                question="Can a smaller effective batch improve fixed-time quality by increasing step count?",
                why_now="Fixed-time autoresearch often benefits when extra optimizer steps outweigh noisier gradients.",
                rationale=(
                    f"Reducing `TOTAL_BATCH_SIZE` from {config.total_batch_size:,} to {smaller_batch:,} tests whether more updates still dominate "
                    "any weaker gradient estimate."
                ),
                intervention={"total_batch_size": smaller_batch},
                expected_effect={
                    "val_bpb_direction": "down",
                    "val_bpb_delta": "-0.02 to -0.10",
                    "num_steps_direction": "up",
                    "peak_vram_mb_direction": "down",
                },
                success_criteria="Improve val_bpb while increasing step count enough to support the throughput hypothesis.",
                alternative_explanations=[
                    "Any win may be due to implicit regularization from noisier gradients, not just extra steps.",
                    "A loss may mean the search has already crossed the useful small-batch regime.",
                ],
                follow_if_supported=[
                    "Map the lower-batch frontier with one more reduction or a compensating LR change.",
                    "Test whether the same step-efficiency mechanism holds at a different depth.",
                ],
                follow_if_not_supported=[
                    "Treat the current batch size as near-optimal and pivot to width or schedule.",
                ],
                confidence="medium",
                scientific_value="Builds directly on an already-supported mechanism and sharpens causal understanding.",
                family="throughput",
                score=0.81,
            )
        )

    adjusted_depth = max(2, config.depth - 2)
    if adjusted_depth != config.depth:
        hypotheses.append(
            Hypothesis(
                hypothesis_id="depth-frontier",
                title="Probe the next shallower depth frontier",
                question="Has the best model reached the optimal depth/throughput balance yet?",
                why_now="Depth strongly changes both capacity and throughput, so it is still one of the highest-value knobs.",
                rationale=(
                    f"Reducing depth from {config.depth} to {adjusted_depth} isolates whether additional step-efficiency still outweighs capacity loss."
                ),
                intervention={"depth": adjusted_depth},
                expected_effect={
                    "val_bpb_direction": "mixed",
                    "val_bpb_delta": "-0.05 to +0.08",
                    "num_steps_direction": "up",
                    "peak_vram_mb_direction": "down",
                },
                success_criteria="Either produce a clear win or clearly falsify the idea that shallower is still better.",
                alternative_explanations=[
                    "If it wins, the dominant mechanism is still throughput rather than representation depth.",
                    "If it loses, the current depth may already be near the compute-optimal boundary.",
                ],
                follow_if_supported=[
                    "Repeat once to check that the gain is robust and not a narrow artifact.",
                    "Test whether width can be added back without losing the throughput benefit.",
                ],
                follow_if_not_supported=[
                    "Freeze depth near the current best and explore orthogonal knobs.",
                ],
                confidence="medium",
                scientific_value="Critical causal test of a high-leverage architecture knob.",
                family="architecture",
                score=0.72,
            )
        )

    if "warmdown" not in history_text and "anneal" not in history_text:
        new_warmdown = 0.65 if config.warmdown_ratio < 0.65 else 0.35
        hypotheses.append(
            Hypothesis(
                hypothesis_id="schedule-tail-control",
                title="Reshape the late-training anneal",
                question="Does a different late-training schedule improve how the fixed budget is spent?",
                why_now="Schedule shape affects every experiment but has not been isolated in the current history.",
                rationale=(
                    f"Changing `WARMDOWN_RATIO` from {config.warmdown_ratio:.2f} to {new_warmdown:.2f} tests whether the current run is either decaying too early or too late."
                ),
                intervention={"warmdown_ratio": new_warmdown},
                expected_effect={
                    "val_bpb_direction": "down",
                    "val_bpb_delta": "0.00 to -0.05",
                    "num_steps_direction": "flat",
                    "peak_vram_mb_direction": "flat",
                },
                success_criteria="Improve val_bpb without changing step count, supporting a pure optimization explanation.",
                alternative_explanations=[
                    "Any gain may reflect better compatibility with the current matrix LR rather than a generally better schedule.",
                    "A null result may mean architecture dominates schedule at this scale.",
                ],
                follow_if_supported=[
                    "Jointly tune the schedule with matrix LR.",
                ],
                follow_if_not_supported=[
                    "De-prioritize schedule-only experiments for now.",
                ],
                confidence="low",
                scientific_value="Useful disambiguation of optimization vs throughput mechanisms.",
                family="optimization",
                score=0.58,
            )
        )

    return sorted(hypotheses, key=lambda item: item.score, reverse=True)


def iter_run_dirs() -> list[Path]:
    if not RUNS_DIR.exists():
        return []
    return sorted(path for path in RUNS_DIR.iterdir() if path.is_dir())


def read_live_workers() -> list[WorkerStatus]:
    workers: list[WorkerStatus] = []
    if not LIVE_WORKERS_DIR.exists():
        return workers
    now = now_utc()
    for path in sorted(LIVE_WORKERS_DIR.glob("*.json")):
        payload = json.loads(path.read_text())
        updated_at = parse_iso(payload.get("updated_at"))
        heartbeat_age = None
        if updated_at is not None:
            heartbeat_age = max(0.0, (now - updated_at).total_seconds())
        worker = WorkerStatus(
            worker_id=payload["worker_id"],
            node_id=payload["node_id"],
            gpu_id=str(payload["gpu_id"]),
            run_id=payload.get("run_id"),
            state=payload["state"],
            updated_at=payload["updated_at"],
            pid=payload.get("pid"),
            heartbeat_age_seconds=heartbeat_age,
            commit=payload.get("commit"),
            hypothesis_id=payload.get("hypothesis_id"),
            title=payload.get("title"),
            notes=payload.get("notes"),
            metrics=payload.get("metrics", {}),
            progress=payload.get("progress", {}),
            paths=payload.get("paths", {}),
        )
        workers.append(worker)
    return workers


def materialize_fleet_workers(
    manifest: FleetManifest | None, live_workers: list[WorkerStatus]
) -> list[WorkerStatus]:
    if manifest is None:
        return live_workers

    live_by_worker = {worker.worker_id: worker for worker in live_workers}
    merged: list[WorkerStatus] = []
    for manifest_worker in manifest.workers:
        live_worker = live_by_worker.pop(manifest_worker.worker_id, None)
        if live_worker is not None:
            merged.append(live_worker)
            continue
        merged.append(
            WorkerStatus(
                worker_id=manifest_worker.worker_id,
                node_id="",
                gpu_id=str(manifest_worker.gpu_id),
                run_id=None,
                state="idle",
                updated_at=manifest.created_at,
                title=manifest_worker.current_title,
                hypothesis_id=manifest_worker.current_hypothesis_id,
                paths={
                    "worktree_path": manifest_worker.worktree_path,
                    "prompt_path": manifest_worker.prompt_path,
                },
            )
        )
    merged.extend(live_by_worker.values())
    return merged


def is_worker_active(worker: WorkerStatus) -> bool:
    if worker.state not in {"launching", "running"}:
        return False
    if worker.heartbeat_age_seconds is None:
        return True
    return worker.heartbeat_age_seconds <= STALE_HEARTBEAT_SECONDS


def collect_experiments() -> list[AggregateExperiment]:
    experiments: list[AggregateExperiment] = []
    for run_dir in iter_run_dirs():
        experiment_id = run_dir.name
        config = load_json(run_dir / "config.json") or {}
        metadata = load_json(run_dir / "metadata.json") or {}
        result = load_json(run_dir / "result.json") or {}
        plan = load_json(PLANS_DIR / f"{experiment_id}.json") or {}
        events = read_jsonl(run_dir / "events.jsonl")
        latest_event = events[-1] if events else None

        title = (
            result.get("title")
            or plan.get("hypothesis", {}).get("title")
            or config.get("notes")
            or experiment_id
        )
        status = "planned"
        if result:
            status = result.get("status", "planned")
        elif latest_event is not None:
            event_type = latest_event.get("event_type")
            if event_type == "run_failed":
                status = "failed_unrecorded"
            elif event_type == "run_completed":
                status = "completed_unrecorded"
            elif event_type in {"run_started", "heartbeat"}:
                status = "running"

        run_payload = metadata.get("run", {})
        payload_identity = latest_event or {}
        worker_id = run_payload.get("worker_id") or payload_identity.get("worker_id", "")
        gpu_id = str(run_payload.get("gpu_id") or payload_identity.get("gpu_id", ""))
        commit = (
            metadata.get("runtime", {}).get("commit")
            or result.get("commit")
            or plan.get("based_on_commit", "")
        )
        created_at = (
            plan.get("created_at")
            or metadata.get("recorded_at")
            or (events[0]["recorded_at"] if events else utc_now_iso())
        )
        recorded_at = result.get("recorded_at") or metadata.get("recorded_at")
        notes = result.get("analysis", "")

        experiments.append(
            AggregateExperiment(
                experiment_id=experiment_id,
                status=status,
                title=title,
                commit=commit,
                worker_id=worker_id or "",
                gpu_id=gpu_id or "",
                created_at=created_at,
                recorded_at=recorded_at,
                metrics=result.get("metrics") or metadata.get("metrics") or {},
                config=config,
                notes=notes,
            )
        )
    return experiments


def experiments_to_results_rows(experiments: list[AggregateExperiment]) -> list[dict[str, Any]]:
    rows = []
    for item in experiments:
        if item.status not in {"keep", "discard", "crash", "replicate"}:
            continue
        metrics = item.metrics or {}
        peak_vram_mb = float(metrics.get("peak_vram_mb", 0.0) or 0.0)
        rows.append(
            {
                "experiment_id": item.experiment_id,
                "commit": item.commit or "unknown",
                "val_bpb": float(metrics.get("val_bpb", 0.0) or 0.0),
                "memory_gb": peak_vram_mb / 1024.0,
                "status": item.status,
                "description": item.title,
            }
        )
    rows.sort(key=lambda row: row["experiment_id"])
    return rows


def render_progress(rows: list[dict[str, Any]], output_path: Path) -> None:
    if not rows:
        return
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    xs = list(range(len(rows)))
    val_bpb = [row["val_bpb"] for row in rows]
    statuses = [row["status"] for row in rows]
    descriptions = [row["description"] for row in rows]

    fig, ax = plt.subplots(figsize=(16, 8))
    discard_x = [x for x, status in zip(xs, statuses) if status != "keep"]
    discard_y = [y for y, status in zip(val_bpb, statuses) if status != "keep"]
    kept_x = [x for x, status in zip(xs, statuses) if status == "keep"]
    kept_y = [y for y, status in zip(val_bpb, statuses) if status == "keep"]

    if discard_x:
        ax.scatter(discard_x, discard_y, color="lightgray", s=18, alpha=0.9, label="Discarded")
    if kept_x:
        ax.scatter(kept_x, kept_y, color="#2ecc71", edgecolor="#1f6d3f", s=48, label="Kept", zorder=3)
        running_min = []
        best = math.inf
        for y in kept_y:
            best = min(best, y)
            running_min.append(best)
        ax.step(kept_x, running_min, where="post", color="#58d68d", linewidth=2, label="Running best")
        for x, y, desc in zip(kept_x, kept_y, descriptions):
            ax.text(x, y + 0.0003, desc, rotation=28, fontsize=10, color="#3ba66b")

    n_total = len(rows)
    n_kept = sum(1 for status in statuses if status == "keep")
    ax.set_title(f"Autoresearch Progress: {n_total} Experiments, {n_kept} Kept Improvements", fontsize=18)
    ax.set_xlabel("Experiment #", fontsize=15)
    ax.set_ylabel("Validation BPB (lower is better)", fontsize=15)
    ax.grid(alpha=0.2)
    ax.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def build_leaderboard(experiments: list[AggregateExperiment], workers: list[WorkerStatus]) -> dict[str, Any]:
    decided = [item for item in experiments if item.status in {"keep", "discard", "crash", "replicate"}]
    kept = [item for item in experiments if item.status == "keep"]
    best = None
    if kept:
        best = min(kept, key=lambda item: float(item.metrics.get("val_bpb", math.inf)))
    return {
        "generated_at": utc_now_iso(),
        "total_runs": len(experiments),
        "decided_runs": len(decided),
        "active_workers": sum(1 for worker in workers if is_worker_active(worker)),
        "best_run": None if best is None else best.to_dict(),
        "keep_rate": round(len(kept) / len(decided), 3) if decided else 0.0,
    }


def best_kept_experiment(
    experiments: list[AggregateExperiment],
) -> AggregateExperiment | None:
    kept = [item for item in experiments if item.status == "keep"]
    if not kept:
        return None
    return min(kept, key=lambda item: float(item.metrics.get("val_bpb", math.inf)))


def format_progress(progress: dict[str, Any]) -> str:
    progress_pct = progress.get("progress_pct")
    if progress_pct is None:
        return "n/a"
    return f"{float(progress_pct):.1f}%"


def describe_worker(worker: WorkerStatus) -> str:
    age = "n/a" if worker.heartbeat_age_seconds is None else f"{worker.heartbeat_age_seconds:.1f}s"
    train_loss = worker.metrics.get("train_loss")
    tok_per_sec = worker.metrics.get("tok_per_sec")
    metrics = []
    if train_loss is not None:
        metrics.append(f"loss={float(train_loss):.4f}")
    if tok_per_sec is not None:
        metrics.append(f"tok/s={int(tok_per_sec):,}")
    metric_text = ", ".join(metrics) if metrics else "no metrics yet"
    return (
        f"- `{worker.worker_id}` gpu={worker.gpu_id} state={worker.state} "
        f"run={worker.run_id or '-'} age={age} progress={format_progress(worker.progress)} "
        f"title={worker.title or '-'} {metric_text}"
    )


def recent_peer_outcomes(
    experiments: list[AggregateExperiment], worker_id: str, limit: int = 5
) -> list[AggregateExperiment]:
    decided = [
        item
        for item in experiments
        if item.worker_id != worker_id
        and item.status in {"keep", "discard", "replicate", "crash"}
    ]
    decided.sort(
        key=lambda item: parse_iso(item.recorded_at or item.created_at) or now_utc(),
        reverse=True,
    )
    return decided[:limit]


def render_fleet_brief(
    experiments: list[AggregateExperiment],
    workers: list[WorkerStatus],
    hypotheses: list[Hypothesis],
) -> str:
    kept = [item for item in experiments if item.status == "keep"]
    kept.sort(key=lambda item: item.created_at)
    best = best_kept_experiment(experiments)
    recent = sorted(
        [item for item in experiments if item.status in {"keep", "discard", "crash", "replicate"}],
        key=lambda item: item.created_at,
        reverse=True,
    )[:8]
    active_workers = [worker for worker in workers if is_worker_active(worker)]

    lines = [
        "# Fleet Brief",
        "",
        f"Generated: {utc_now_iso()}",
        "",
        "## Best Known Result",
    ]
    if best is None:
        lines.append("- No kept runs yet.")
    else:
        lines.append(
            f"- `{best.experiment_id}` {best.title}: val_bpb={float(best.metrics.get('val_bpb', math.inf)):.6f}, "
            f"worker={best.worker_id}, gpu={best.gpu_id}"
        )
    lines.extend(["", "## Active Workers"])
    if not active_workers:
        lines.append("- No active workers.")
    else:
        for worker in active_workers:
            lines.append(describe_worker(worker))
    lines.extend(["", "## Recent Decided Runs"])
    if not recent:
        lines.append("- No decided runs yet.")
    else:
        for item in recent:
            val_bpb = item.metrics.get("val_bpb")
            val_text = "n/a" if val_bpb is None else f"{float(val_bpb):.6f}"
            lines.append(f"- `{item.experiment_id}` [{item.status}] {item.title} -> {val_text}")
    lines.extend(["", "## Next Hypotheses"])
    if not hypotheses:
        lines.append("- No hypotheses available.")
    else:
        for hypothesis in hypotheses[:5]:
            lines.append(f"- `{hypothesis.hypothesis_id}` {hypothesis.title}")
    return "\n".join(lines) + "\n"


def render_main_agent_prompt(manifest: FleetManifest) -> str:
    worker_list = "\n".join(
        f"- `{worker.worker_id}` gpu={worker.gpu_id} worktree=`{worker.worktree_path}` branch=`{worker.branch}`"
        for worker in manifest.workers
    )
    remote = get_origin_remote()
    return (
        "# Main Agent Protocol\n\n"
        "You are the meta-orchestrator for a multi-GPU autoresearch fleet.\n\n"
        "Repository identity:\n"
        f"- Root repo: `{ROOT}`\n"
        f"- Git remote: `{remote}`\n"
        "- Default mode: use git worktrees for parallel worker edits, not one shared branch.\n\n"
        "Responsibilities:\n"
        "- Read the shared research state before making decisions.\n"
        "- Monitor every worker's live status and recent run events.\n"
        "- Update the scientific interpretation after each run.\n"
        "- Choose the next hypotheses so workers learn from each other's wins, losses, and crashes.\n"
        "- Do not edit worker worktrees directly unless you explicitly intend to take over that worker.\n\n"
        "Read first:\n"
        f"- `{FLEET_BRIEF_PATH}`\n"
        f"- `{LIVE_SUMMARY_PATH}`\n"
        f"- `{EXPERIMENTS_PATH}`\n"
        f"- `{KNOWLEDGE_PATH}`\n\n"
        "Workers:\n"
        f"{worker_list}\n\n"
        "Loop:\n"
        "1. Keep `uv run python orchestrator.py monitor --interval 5` running in the repo root.\n"
        "2. Inspect `status` and recent experiments.\n"
        "3. Ensure each worker agent stays inside its assigned git worktree and branch.\n"
        "4. For each completed run, decide keep/discard/crash/replicate and record it.\n"
        "5. Regenerate worker briefs by running `sync` again.\n"
        "6. Dispatch new work to any free GPU worker.\n"
    )


def render_worker_prompt(manifest: FleetManifest, worker: FleetWorker) -> str:
    remote = get_origin_remote()
    return (
        f"# Worker Agent Protocol: {worker.worker_id}\n\n"
        f"You own GPU `{worker.gpu_id}` and git worktree `{worker.worktree_path}` on branch `{worker.branch}`.\n\n"
        "Repository identity:\n"
        f"- Root repo remote: `{remote}`\n"
        f"- Assigned worktree: `{worker.worktree_path}`\n"
        "- Default mode: edit and commit inside your assigned git worktree. Do not treat the root repo as your coding checkout.\n\n"
        "Responsibilities:\n"
        "- Edit only your worktree's `train.py`.\n"
        "- Before each new experiment, read shared fleet state so you learn from peer runs.\n"
        "- Monitor peer workers through the shared live summary and aggregate experiment index.\n"
        "- Run one experiment at a time on your assigned GPU.\n"
        "- Record outcomes back into the shared science log.\n\n"
        "Read first on every loop:\n"
        f"- `{FLEET_BRIEF_PATH}`\n"
        f"- `{LIVE_SUMMARY_PATH}`\n"
        f"- `{EXPERIMENTS_PATH}`\n"
        f"- `{worker.prompt_path}`\n\n"
        "Rules:\n"
        "- Stay inside your worktree when editing code.\n"
        f"- Commit experimental code on branch `{worker.branch}` so the worktree history matches the run history.\n"
        f"- Use the shared root research directory `{RESEARCH_DIR}` as the source of truth.\n"
        "- If another worker just found a strong result in the same hypothesis family, pivot rather than duplicating it.\n"
        "- If a peer crash reveals a broken idea, avoid repeating it unless you are deliberately testing a fix.\n"
    )


def update_worker_prompts(manifest: FleetManifest, experiments: list[AggregateExperiment], workers: list[WorkerStatus], hypotheses: list[Hypothesis]) -> None:
    write_text(FLEET_BRIEF_PATH, render_fleet_brief(experiments, workers, hypotheses))
    write_text(Path(manifest.main_prompt_path), render_main_agent_prompt(manifest))
    best = best_kept_experiment(experiments)
    for worker in manifest.workers:
        peer_workers = [item for item in workers if item.worker_id != worker.worker_id]
        peer_outcomes = recent_peer_outcomes(experiments, worker.worker_id)
        assignment_lines = [
            f"# Assignment Brief: {worker.worker_id}",
            "",
            f"Worktree: `{worker.worktree_path}`",
            f"Branch: `{worker.branch}`",
            f"GPU: `{worker.gpu_id}`",
        ]
        if worker.current_run_id:
            assignment_lines.append(f"Current run: `{worker.current_run_id}`")
        if worker.current_hypothesis_id:
            assignment_lines.append(f"Current hypothesis: `{worker.current_hypothesis_id}`")
        if worker.current_title:
            assignment_lines.append(f"Current title: {worker.current_title}")
        assignment_lines.extend(["", "Shared scientific state:"])
        if best is None:
            assignment_lines.append("- No kept result yet.")
        else:
            assignment_lines.append(
                f"- Best keep is `{best.experiment_id}` ({best.title}) with val_bpb={float(best.metrics.get('val_bpb', math.inf)):.6f}."
            )
        assignment_lines.extend(["", "Peer workers:"])
        if not peer_workers:
            assignment_lines.append("- No peer worker status available.")
        else:
            assignment_lines.extend(describe_worker(item) for item in peer_workers)
        assignment_lines.extend(["", "Recent peer outcomes:"])
        if not peer_outcomes:
            assignment_lines.append("- No peer outcomes recorded yet.")
        else:
            for item in peer_outcomes:
                val_bpb = item.metrics.get("val_bpb")
                val_text = "n/a" if val_bpb is None else f"{float(val_bpb):.6f}"
                assignment_lines.append(
                    f"- `{item.experiment_id}` [{item.status}] {item.title} val_bpb={val_text}"
                )
        assignment_lines.extend(
            [
                "",
                "Shared protocol:",
                f"- Read `{FLEET_BRIEF_PATH}` before choosing your next edit.",
                f"- Monitor `{LIVE_WORKERS_DIR}/*.json` for peer progress.",
                f"- Keep `uv run python {ROOT / 'orchestrator.py'} status` or `uv run python {ROOT / 'orchestrator.py'} monitor --interval 5` nearby while peers are training.",
                f"- Treat `{RESEARCH_DIR}` as shared memory across all workers.",
                "",
                render_worker_prompt(manifest, worker).rstrip(),
                "",
            ]
        )
        write_text(Path(worker.prompt_path), "\n".join(assignment_lines))


def sync_artifacts() -> dict[str, Any]:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    LIVE_WORKERS_DIR.mkdir(parents=True, exist_ok=True)
    AGGREGATE_DIR.mkdir(parents=True, exist_ok=True)

    manifest = load_fleet_manifest()
    experiments = collect_experiments()
    live_workers = read_live_workers()
    workers = materialize_fleet_workers(manifest, live_workers)
    hypotheses = hypothesis_templates(ExperimentConfig(), read_results_tsv(RESULTS_TSV_PATH))
    write_json(EXPERIMENTS_PATH, {"experiments": [item.to_dict() for item in experiments]})
    write_json(LEADERBOARD_PATH, build_leaderboard(experiments, workers))

    result_rows = experiments_to_results_rows(experiments)
    write_results_tsv(result_rows)
    render_progress(result_rows, PROGRESS_PNG_PATH)

    summary = {
        "generated_at": utc_now_iso(),
        "workers": [worker.to_dict() for worker in workers],
        "active_runs": [worker.run_id for worker in workers if is_worker_active(worker) and worker.run_id],
        "free_workers": [worker.worker_id for worker in workers if not is_worker_active(worker)],
        "best_result": None,
        "paths": {
            "results_tsv": str(RESULTS_TSV_PATH),
            "progress_png": str(PROGRESS_PNG_PATH),
            "aggregate_experiments": str(EXPERIMENTS_PATH),
        },
    }
    tsv_rows = read_results_tsv(RESULTS_TSV_PATH)
    best = best_result(tsv_rows)
    if best is not None:
        summary["best_result"] = asdict(best)
    write_json(LIVE_SUMMARY_PATH, summary)
    if manifest is not None:
        live_by_worker = {worker.worker_id: worker for worker in live_workers}
        for manifest_worker in manifest.workers:
            live_worker = live_by_worker.get(manifest_worker.worker_id)
            if live_worker is not None and is_worker_active(live_worker):
                manifest_worker.current_run_id = live_worker.run_id
                manifest_worker.current_hypothesis_id = live_worker.hypothesis_id
                manifest_worker.current_title = live_worker.title
            else:
                manifest_worker.current_run_id = None
                manifest_worker.current_hypothesis_id = None
                manifest_worker.current_title = None
        save_fleet_manifest(manifest)
        update_worker_prompts(manifest, experiments, workers, hypotheses)
    return summary


def build_research_brief() -> ResearchBrief:
    sync_artifacts()
    config = ExperimentConfig()
    rows = read_results_tsv(RESULTS_TSV_PATH)
    best = best_result(rows)
    best_payload = asdict(best) if best is not None else {}
    findings = summarize_findings(rows)
    hypotheses = hypothesis_templates(config, rows)
    constraints = [
        "Only `train.py` is editable during public autoresearch runs; `prepare.py` stays fixed.",
        "Primary metric is val_bpb from `evaluate_bpb()` on a pinned validation shard.",
        "Training budget is fixed at 300 seconds, so step-efficiency is part of the objective.",
        "Experiments must satisfy total_batch_size % (device_batch_size * MAX_SEQ_LEN) == 0.",
        "This path assumes A100/H100-class NVIDIA GPUs, one run per GPU.",
    ]
    notes = [
        f"Generated on host {platform.node()} ({platform.platform()}).",
        "Treat small single-run wins as provisional until replicated.",
    ]
    return ResearchBrief(
        generated_at=utc_now_iso(),
        repository=ROOT.name,
        objective="Optimize autoregressive pretraining quality under a fixed NVIDIA GPU time budget.",
        constraints=constraints,
        current_config=config.to_dict(),
        best_result=best_payload,
        findings=findings,
        open_questions=extract_open_questions(rows, config),
        hypothesis_queue=hypotheses,
        notes=notes,
    )


def apply_intervention(
    base_config: ExperimentConfig, intervention: dict[str, Any]
) -> ExperimentConfig:
    payload = base_config.to_dict()
    payload.update(intervention)
    return ExperimentConfig.from_dict(payload)


def next_experiment_id() -> str:
    existing = sorted(path.stem for path in PLANS_DIR.glob("exp-*.json"))
    index = len(existing) + 1
    return f"exp-{index:04d}"


def choose_hypotheses(
    brief: ResearchBrief, count: int, excluded_ids: set[str] | None = None
) -> list[Hypothesis]:
    excluded_ids = excluded_ids or set()
    chosen = []
    for hypothesis in brief.hypothesis_queue:
        if hypothesis.hypothesis_id in excluded_ids:
            continue
        chosen.append(hypothesis)
        if len(chosen) >= count:
            break
    return chosen


def build_plan_from_hypothesis(brief: ResearchBrief, chosen: Hypothesis) -> ExperimentPlan:
    experiment_id = next_experiment_id()
    config = apply_intervention(
        ExperimentConfig.from_dict(brief.current_config), chosen.intervention
    )
    config.notes = chosen.title
    config_path = RUNS_DIR / experiment_id / "config.json"
    metadata_path = RUNS_DIR / experiment_id / "metadata.json"
    config.save(config_path)
    return ExperimentPlan(
        experiment_id=experiment_id,
        created_at=utc_now_iso(),
        phase="scientific_experimentation",
        based_on_commit=get_head_commit(),
        hypothesis=chosen,
        config_path=str(config_path.relative_to(ROOT)),
        output_metadata_path=str(metadata_path.relative_to(ROOT)),
        run_command=f"uv run train.py --config {config_path.relative_to(ROOT)} --metadata-out {metadata_path.relative_to(ROOT)}",
        decision_rules={
            "keep": "Keep only if val_bpb clearly improves and the result matches the intended mechanism.",
            "replicate": "Replicate if the gain is small, surprising, or contradicts prior evidence.",
            "discard": "Discard if val_bpb worsens or the run invalidates the hypothesis.",
        },
    )


def build_plan(brief_path: Path, hypothesis_id: str | None) -> ExperimentPlan:
    if not brief_path.exists():
        brief = build_research_brief()
        brief.save(brief_path)
    else:
        payload = json.loads(brief_path.read_text())
        brief = ResearchBrief(
            generated_at=payload["generated_at"],
            repository=payload["repository"],
            objective=payload["objective"],
            constraints=payload["constraints"],
            current_config=payload["current_config"],
            best_result=payload["best_result"],
            findings=[EmpiricalFinding(**item) for item in payload["findings"]],
            open_questions=payload["open_questions"],
            hypothesis_queue=[Hypothesis(**item) for item in payload["hypothesis_queue"]],
            notes=payload.get("notes", []),
        )

    if not brief.hypothesis_queue:
        raise ValueError("No hypotheses available to plan.")

    chosen = brief.hypothesis_queue[0]
    if hypothesis_id is not None:
        for hypothesis in brief.hypothesis_queue:
            if hypothesis.hypothesis_id == hypothesis_id:
                chosen = hypothesis
                break
        else:
            raise ValueError(f"Unknown hypothesis_id: {hypothesis_id}")
    return build_plan_from_hypothesis(brief, chosen)


def compare_prediction(
    plan: ExperimentPlan, metrics: dict[str, Any], best_known: float | None
) -> str:
    direction = plan.hypothesis.expected_effect.get("val_bpb_direction")
    actual = float(metrics.get("val_bpb", math.inf))
    if direction == "down":
        if best_known is not None and actual < best_known:
            return "supported"
        return "not_supported"
    if direction == "mixed":
        return "inconclusive"
    return "unknown"


def record_result(
    plan_path: Path, metadata_path: Path, analysis: str, status: str
) -> ExperimentResult:
    plan_payload = json.loads(plan_path.read_text())
    plan = ExperimentPlan(
        experiment_id=plan_payload["experiment_id"],
        created_at=plan_payload["created_at"],
        phase=plan_payload["phase"],
        based_on_commit=plan_payload["based_on_commit"],
        hypothesis=Hypothesis(**plan_payload["hypothesis"]),
        config_path=plan_payload["config_path"],
        output_metadata_path=plan_payload["output_metadata_path"],
        run_command=plan_payload["run_command"],
        decision_rules=plan_payload["decision_rules"],
    )
    metadata = json.loads(metadata_path.read_text())
    metrics = metadata["metrics"]
    rows = read_results_tsv(RESULTS_TSV_PATH)
    current_best = best_result(rows)
    matched_prediction = compare_prediction(
        plan, metrics, None if current_best is None else current_best.val_bpb
    )
    contradiction_flags = []
    if (
        plan.hypothesis.expected_effect.get("val_bpb_direction") == "down"
        and status == "discard"
    ):
        contradiction_flags.append(
            "Predicted improvement but observed non-improvement."
        )
    result = ExperimentResult(
        experiment_id=plan.experiment_id,
        recorded_at=utc_now_iso(),
        status=status,
        hypothesis_id=plan.hypothesis.hypothesis_id,
        metrics=metrics,
        matched_prediction=matched_prediction,
        analysis=analysis,
        candidate_mechanisms=plan.hypothesis.alternative_explanations,
        next_steps=(
            plan.hypothesis.follow_if_supported
            if status == "keep"
            else plan.hypothesis.follow_if_not_supported
        ),
        contradiction_flags=contradiction_flags,
    )
    knowledge = KnowledgeBase.load(KNOWLEDGE_PATH, ROOT.name)
    knowledge.experiment_history = [
        entry
        for entry in knowledge.experiment_history
        if entry.get("experiment_id") != result.experiment_id
    ]
    knowledge.confirmed_findings = [
        entry
        for entry in knowledge.confirmed_findings
        if entry.get("experiment_id") != result.experiment_id
    ]
    knowledge.tentative_findings = [
        entry
        for entry in knowledge.tentative_findings
        if entry.get("experiment_id") != result.experiment_id
    ]
    knowledge.contradictions = [
        entry
        for entry in knowledge.contradictions
        if entry.get("experiment_id") != result.experiment_id
    ]
    history_entry = {
        "experiment_id": result.experiment_id,
        "hypothesis_id": result.hypothesis_id,
        "status": result.status,
        "matched_prediction": result.matched_prediction,
        "metrics": result.metrics,
        "analysis": result.analysis,
    }
    knowledge.experiment_history.append(history_entry)
    target_bucket = (
        knowledge.confirmed_findings
        if status == "keep"
        else knowledge.tentative_findings
    )
    target_bucket.append(
        {
            "experiment_id": result.experiment_id,
            "hypothesis_id": plan.hypothesis.hypothesis_id,
            "title": plan.hypothesis.title,
            "status": status,
            "analysis": analysis,
            "metrics": metrics,
        }
    )
    for flag in contradiction_flags:
        knowledge.contradictions.append(
            {
                "experiment_id": result.experiment_id,
                "hypothesis_id": result.hypothesis_id,
                "flag": flag,
                "analysis": analysis,
            }
        )
    keep_count = sum(1 for entry in knowledge.experiment_history if entry["status"] == "keep")
    total_count = len(knowledge.experiment_history)
    knowledge.meta_research = {
        "keep_rate": round(keep_count / total_count, 3) if total_count else 0.0,
        "contradiction_count": len(knowledge.contradictions),
        "total_scientific_experiments": total_count,
    }
    knowledge.save(KNOWLEDGE_PATH)

    run_dir = RUNS_DIR / plan.experiment_id
    append_jsonl(
        run_dir / "events.jsonl",
        {
            "event_type": "decision_recorded",
            "recorded_at": utc_now_iso(),
            "run_id": plan.experiment_id,
            "worker_id": metadata.get("run", {}).get("worker_id", ""),
            "node_id": metadata.get("run", {}).get("node_id", platform.node()),
            "gpu_id": metadata.get("run", {}).get("gpu_id", ""),
            "payload": {
                "status": status,
                "title": plan.hypothesis.title,
                "analysis": analysis,
                "metrics": metrics,
            },
        },
    )
    return result


def gpu_ids_from_nvidia_smi() -> list[str]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def get_gpu_ids(gpus_arg: str | None) -> list[str]:
    if gpus_arg:
        return [item.strip() for item in gpus_arg.split(",") if item.strip()]
    ids = gpu_ids_from_nvidia_smi()
    return ids or ["0"]


def git_branch_exists(branch: str) -> bool:
    if not has_git_metadata():
        return False
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=ROOT,
    )
    return result.returncode == 0


def ensure_worktree(branch: str, worktree_path: Path) -> None:
    if not has_git_metadata():
        raise RuntimeError(
            "git worktrees require an initialized git repository. "
            "Run `git init`, create a baseline commit, then re-run "
            "`orchestrator.py init-fleet --create-worktrees`."
        )
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    if worktree_path.exists():
        return
    if git_branch_exists(branch):
        cmd = ["git", "worktree", "add", str(worktree_path), branch]
    else:
        cmd = ["git", "worktree", "add", "-b", branch, str(worktree_path), "HEAD"]
    subprocess.run(cmd, cwd=ROOT, check=True)


def init_fleet(tag: str, gpus_arg: str | None, create_worktrees: bool) -> FleetManifest:
    gpu_ids = get_gpu_ids(gpus_arg)
    workers = []
    for gpu_id in gpu_ids:
        worker_id = f"worker-gpu{gpu_id}"
        branch = f"autoresearch/{tag}-gpu{gpu_id}"
        worktree_path = ROOT / "worktrees" / worker_id
        prompt_path = WORKER_PROMPTS_DIR / f"{worker_id}.md"
        if create_worktrees:
            ensure_worktree(branch, worktree_path)
        workers.append(
            FleetWorker(
                worker_id=worker_id,
                gpu_id=str(gpu_id),
                branch=branch,
                worktree_path=str(worktree_path),
                prompt_path=str(prompt_path),
            )
        )
    manifest = FleetManifest(
        tag=tag,
        created_at=utc_now_iso(),
        repository_root=str(ROOT),
        shared_research_dir=str(RESEARCH_DIR),
        main_prompt_path=str(MAIN_AGENT_PROMPT_PATH),
        workers=workers,
    )
    save_fleet_manifest(manifest)
    sync_artifacts()
    return manifest


def launch_status_file(
    worker_id: str,
    node_id: str,
    gpu_id: str,
    run_id: str,
    title: str,
    run_dir: Path,
    pid: int | None = None,
    hypothesis_id: str | None = None,
) -> None:
    LIVE_WORKERS_DIR.mkdir(parents=True, exist_ok=True)
    payload = WorkerStatus(
        worker_id=worker_id,
        node_id=node_id,
        gpu_id=gpu_id,
        run_id=run_id,
        state="launching",
        updated_at=utc_now_iso(),
        pid=pid,
        title=title,
        hypothesis_id=hypothesis_id,
        paths={
            "run_dir": str(run_dir),
            "live_path": str(LIVE_WORKERS_DIR / f"{worker_id}.json"),
            "events_path": str(run_dir / "events.jsonl"),
            "metadata_path": str(run_dir / "metadata.json"),
            "log_path": str(run_dir / "run.log"),
        },
    )
    write_json(LIVE_WORKERS_DIR / f"{worker_id}.json", payload.to_dict())


def launch_run(
    plan: ExperimentPlan,
    gpu_id: str,
    worker_id: str,
    dry_run: bool,
    worktree_path: Path | None = None,
) -> list[str]:
    run_dir = RUNS_DIR / plan.experiment_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"
    node_id = platform.node()
    repo_path = worktree_path or ROOT
    if not dry_run and not repo_path.exists():
        raise FileNotFoundError(f"Missing worker worktree at {repo_path}")
    cmd = [
        sys.executable,
        str(repo_path / "train.py"),
        "--config",
        str(ROOT / plan.config_path),
        "--metadata-out",
        str(ROOT / plan.output_metadata_path),
        "--run-id",
        plan.experiment_id,
        "--worker-id",
        worker_id,
        "--node-id",
        node_id,
        "--gpu-id",
        str(gpu_id),
        "--telemetry-dir",
        str(run_dir),
        "--hypothesis-id",
        plan.hypothesis.hypothesis_id,
    ]
    if dry_run:
        return cmd

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    launch_status_file(
        worker_id,
        node_id,
        str(gpu_id),
        plan.experiment_id,
        plan.hypothesis.title,
        run_dir,
        hypothesis_id=plan.hypothesis.hypothesis_id,
    )
    with log_path.open("w") as handle:
        process = subprocess.Popen(
            cmd,
            cwd=repo_path,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    launch_status_file(
        worker_id,
        node_id,
        str(gpu_id),
        plan.experiment_id,
        plan.hypothesis.title,
        run_dir,
        pid=process.pid,
        hypothesis_id=plan.hypothesis.hypothesis_id,
    )
    return cmd


def print_status() -> None:
    summary = sync_artifacts()
    workers = [WorkerStatus(**payload) for payload in summary["workers"]]
    manifest = load_fleet_manifest()
    print(f"Generated at: {summary['generated_at']}")
    if summary["best_result"] is not None:
        best = summary["best_result"]
        print(f"Best keep: {best['val_bpb']:.6f} @ {best['commit']} ({best['description']})")
    else:
        print("Best keep: none yet")
    if manifest is not None:
        print(f"Fleet tag: {manifest.tag} ({len(manifest.workers)} workers)")
    print()
    if not workers:
        print("No worker status files found.")
        return
    for worker in workers:
        age = "n/a" if worker.heartbeat_age_seconds is None else f"{worker.heartbeat_age_seconds:.1f}s"
        print(
            f"{worker.worker_id:12s} gpu={worker.gpu_id:>3s} state={worker.state:10s} "
            f"run={worker.run_id or '-':10s} age={age:>6s} title={worker.title or '-'}"
        )


def monitor_fleet(interval_seconds: float, iterations: int | None) -> None:
    loop = 0
    last_signature = None
    while True:
        summary = sync_artifacts()
        workers = [WorkerStatus(**payload) for payload in summary["workers"]]
        experiments = collect_experiments()
        best = summary.get("best_result")
        latest = None
        decided = [
            item for item in experiments if item.status in {"keep", "discard", "replicate", "crash"}
        ]
        if decided:
            decided.sort(
                key=lambda item: parse_iso(item.recorded_at or item.created_at) or now_utc(),
                reverse=True,
            )
            latest = decided[0]
        signature = json.dumps(
            {
                "workers": [
                    {
                        "worker_id": worker.worker_id,
                        "state": worker.state,
                        "run_id": worker.run_id,
                        "updated_at": worker.updated_at,
                        "progress_pct": worker.progress.get("progress_pct"),
                    }
                    for worker in workers
                ],
                "latest": None
                if latest is None
                else {
                    "experiment_id": latest.experiment_id,
                    "status": latest.status,
                    "recorded_at": latest.recorded_at,
                },
                "best": None
                if best is None
                else {
                    "commit": best["commit"],
                    "val_bpb": best["val_bpb"],
                },
            },
            sort_keys=True,
        )
        if signature != last_signature:
            active_count = sum(1 for worker in workers if is_worker_active(worker))
            free_count = len(workers) - active_count
            best_text = "none"
            if best is not None:
                best_text = f"{best['val_bpb']:.6f} @ {best['commit']}"
            latest_text = "none"
            if latest is not None:
                latest_text = f"{latest.experiment_id} [{latest.status}]"
            print(
                f"[{summary['generated_at']}] active={active_count} free={free_count} "
                f"best={best_text} latest={latest_text}"
            )
            for worker in workers:
                print(describe_worker(worker))
            print()
            last_signature = signature
        loop += 1
        if iterations is not None and loop >= iterations:
            return
        time.sleep(interval_seconds)


def dispatch_runs(gpus_arg: str | None, hypothesis_id: str | None, dry_run: bool) -> None:
    sync_artifacts()
    brief = build_research_brief()
    brief.save(BRIEF_PATH)
    workers = read_live_workers()
    busy_gpu_ids = {worker.gpu_id for worker in workers if is_worker_active(worker)}
    active_hypothesis_ids = set()
    for worker in workers:
        if not is_worker_active(worker) or not worker.run_id:
            continue
        plan_payload = load_json(PLANS_DIR / f"{worker.run_id}.json") or {}
        hypothesis = plan_payload.get("hypothesis", {})
        hypothesis_id_value = hypothesis.get("hypothesis_id")
        if hypothesis_id_value:
            active_hypothesis_ids.add(hypothesis_id_value)
    manifest = load_fleet_manifest()
    if manifest is not None:
        fleet_workers = [worker for worker in manifest.workers if worker.gpu_id not in busy_gpu_ids]
        if not fleet_workers:
            print("No free fleet workers available.")
            return
    else:
        gpu_ids = get_gpu_ids(gpus_arg)
        free_gpu_ids = [gpu_id for gpu_id in gpu_ids if gpu_id not in busy_gpu_ids]
        if not free_gpu_ids:
            print("No free GPUs available.")
            return
        fleet_workers = [
            FleetWorker(
                worker_id=f"worker-gpu{gpu_id}",
                gpu_id=str(gpu_id),
                branch="",
                worktree_path=str(ROOT),
                prompt_path="",
            )
            for gpu_id in free_gpu_ids
        ]

    if hypothesis_id is not None:
        chosen = []
        for item in brief.hypothesis_queue:
            if item.hypothesis_id == hypothesis_id:
                chosen = [item]
                break
        if not chosen:
            raise ValueError(f"Unknown hypothesis_id: {hypothesis_id}")
    else:
        chosen = choose_hypotheses(brief, len(fleet_workers), active_hypothesis_ids)

    if not chosen:
        print("No eligible hypotheses available to dispatch.")
        return

    for worker, hypothesis in zip(fleet_workers, chosen):
        plan = build_plan_from_hypothesis(brief, hypothesis)
        plan_path = PLANS_DIR / f"{plan.experiment_id}.json"
        plan.save(plan_path)
        worker.current_run_id = plan.experiment_id
        worker.current_hypothesis_id = hypothesis.hypothesis_id
        worker.current_title = hypothesis.title
        cmd = launch_run(
            plan,
            worker.gpu_id,
            worker.worker_id,
            dry_run=dry_run,
            worktree_path=Path(worker.worktree_path) if worker.worktree_path else None,
        )
        rendered = " ".join(cmd)
        if dry_run:
            print(f"[dry-run] {worker.worker_id}: {rendered}")
        else:
            print(f"Launched {plan.experiment_id} on GPU {worker.gpu_id}: {rendered}")
    if manifest is not None:
        save_fleet_manifest(manifest)
        sync_artifacts()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scientific orchestrator for CUDA autoresearch"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("briefing", help="Generate research brief from repo state")
    subparsers.add_parser("sync", help="Rebuild aggregate artifacts from run logs")
    subparsers.add_parser("status", help="Show current live worker status")
    monitor_parser = subparsers.add_parser(
        "monitor", help="Continuously refresh shared state while workers are training"
    )
    monitor_parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds between sync cycles",
    )
    monitor_parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Optional number of sync cycles before exiting",
    )

    init_fleet_parser = subparsers.add_parser(
        "init-fleet", help="Create a multi-worker fleet manifest and optional git worktrees"
    )
    init_fleet_parser.add_argument(
        "--tag",
        type=str,
        required=True,
        help="Run tag used to name worker branches",
    )
    init_fleet_parser.add_argument(
        "--gpus",
        type=str,
        default=None,
        help="Optional comma-separated GPU ids override",
    )
    init_fleet_parser.add_argument(
        "--create-worktrees",
        action="store_true",
        help="Create git worktrees for each worker",
    )

    plan_parser = subparsers.add_parser(
        "plan", help="Create a scientific experiment plan"
    )
    plan_parser.add_argument(
        "--hypothesis-id", type=str, default=None, help="Optional explicit hypothesis"
    )

    dispatch_parser = subparsers.add_parser(
        "dispatch", help="Dispatch one run per free GPU"
    )
    dispatch_parser.add_argument(
        "--gpus",
        type=str,
        default=None,
        help="Optional comma-separated GPU ids override",
    )
    dispatch_parser.add_argument(
        "--hypothesis-id",
        type=str,
        default=None,
        help="Optional explicit hypothesis to dispatch",
    )
    dispatch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print launch commands without starting runs",
    )

    record_parser = subparsers.add_parser(
        "record", help="Record a run back into the knowledge base"
    )
    record_parser.add_argument(
        "--plan", type=Path, required=True, help="Path to experiment plan JSON"
    )
    record_parser.add_argument(
        "--metadata", type=Path, required=True, help="Path to run metadata JSON"
    )
    record_parser.add_argument(
        "--analysis",
        type=str,
        required=True,
        help="Scientific interpretation of the outcome",
    )
    record_parser.add_argument(
        "--status",
        type=str,
        choices=["keep", "discard", "replicate", "crash"],
        required=True,
        help="Scientific disposition for the experiment",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    LIVE_WORKERS_DIR.mkdir(parents=True, exist_ok=True)
    AGGREGATE_DIR.mkdir(parents=True, exist_ok=True)

    if args.command == "briefing":
        brief = build_research_brief()
        brief.save(BRIEF_PATH)
        print(f"Wrote research brief to {BRIEF_PATH.relative_to(ROOT)}")
        return

    if args.command == "sync":
        sync_artifacts()
        print(f"Wrote aggregate artifacts under {AGGREGATE_DIR.relative_to(ROOT)}")
        print(f"Wrote live summary to {LIVE_SUMMARY_PATH.relative_to(ROOT)}")
        return

    if args.command == "status":
        print_status()
        return

    if args.command == "monitor":
        monitor_fleet(args.interval, args.iterations)
        return

    if args.command == "init-fleet":
        manifest = init_fleet(args.tag, args.gpus, args.create_worktrees)
        print(f"Wrote fleet manifest to {FLEET_MANIFEST_PATH.relative_to(ROOT)}")
        print(f"Wrote main prompt to {Path(manifest.main_prompt_path).relative_to(ROOT)}")
        for worker in manifest.workers:
            if worker.prompt_path:
                print(f"{worker.worker_id}: {Path(worker.prompt_path).relative_to(ROOT)}")
        return

    if args.command == "plan":
        plan = build_plan(BRIEF_PATH, args.hypothesis_id)
        plan_path = PLANS_DIR / f"{plan.experiment_id}.json"
        plan.save(plan_path)
        print(f"Wrote experiment plan to {plan_path.relative_to(ROOT)}")
        print(plan.run_command)
        return

    if args.command == "dispatch":
        dispatch_runs(args.gpus, args.hypothesis_id, args.dry_run)
        return

    if args.command == "record":
        result = record_result(args.plan, args.metadata, args.analysis, args.status)
        result_path = (
            args.plan.parent.parent / "runs" / result.experiment_id / "result.json"
        ).resolve()
        result.save(result_path)
        sync_artifacts()
        print(f"Wrote experiment result to {result_path.relative_to(ROOT)}")
        return


if __name__ == "__main__":
    main()
