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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schema import (
    AggregateExperiment,
    EmpiricalFinding,
    ExperimentConfig,
    ExperimentRecord,
    FleetManifest,
    FleetWorker,
    Hypothesis,
    KnowledgeBase,
    ResearchBrief,
    ResultRow,
    ToolEntry,
    ToolRegistry,
    WorkerStatus,
    read_jsonl,
    utc_now_iso,
    write_json,
    write_jsonl,
)


ROOT = Path(__file__).resolve().parent
RESEARCH_DIR = ROOT / "research"
BRIEF_PATH = RESEARCH_DIR / "research_brief.json"
KNOWLEDGE_PATH = RESEARCH_DIR / "knowledge_base.json"
SEARCH_MODEL_PATH = RESEARCH_DIR / "search_model.md"
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
LEGACY_MAIN_AGENT_PROMPT_PATH = FLEET_DIR / "main-agent.md"
OBSERVER_PROMPT_PATH = FLEET_DIR / "observer-agent.md"
TOOL_BUILDER_PROMPT_PATH = FLEET_DIR / "tool-builder.md"
WORKER_PROMPTS_DIR = FLEET_DIR / "worker-prompts"
FLEET_PROTOCOLS_DIR = FLEET_DIR / "protocols"
FLEET_ASSIGNMENTS_DIR = FLEET_DIR / "assignments"
WORKER_ASSIGNMENTS_DIR = FLEET_ASSIGNMENTS_DIR / "workers"
OBSERVER_ASSIGNMENT_PATH = FLEET_ASSIGNMENTS_DIR / "observer.md"
TOOL_BUILDER_ASSIGNMENT_PATH = FLEET_ASSIGNMENTS_DIR / "tool-builder.md"
OBSERVER_PROTOCOL_PATH = FLEET_PROTOCOLS_DIR / "observer.md"
TOOL_BUILDER_PROTOCOL_PATH = FLEET_PROTOCOLS_DIR / "tool-builder.md"
GPU_WORKER_PROTOCOL_PATH = FLEET_PROTOCOLS_DIR / "gpu-worker.md"
FLEET_BRIEF_PATH = AGGREGATE_DIR / "fleet_brief.md"
TOOLS_DIR = RESEARCH_DIR / "tools"
PUBLISHED_TOOLS_DIR = TOOLS_DIR / "published"
TOOLS_REGISTRY_PATH = TOOLS_DIR / "registry.json"
EXPERIMENTS_JSONL_PATH = ROOT / "experiments.jsonl"
RESULTS_TSV_PATH = ROOT / "results.tsv"
PROGRESS_PNG_PATH = ROOT / "progress.png"
STALE_HEARTBEAT_SECONDS = 180.0
CACHE_DIR = Path.home() / ".cache" / "autoresearch"


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
    return datetime.now(timezone.utc)


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    return [_safe_float(item) for item in value]


def _dashboard_status(status: str) -> str:
    return status if status in {"keep", "discard", "crash", "replicate"} else "discard"


def _experiment_sort_key(item: AggregateExperiment) -> tuple[datetime, str]:
    return (
        parse_iso(item.recorded_at or item.created_at) or now_utc(),
        item.experiment_id,
    )


def _terminal_decision_status(value: str | None) -> str:
    if value in {"keep", "discard", "crash", "replicate"}:
        return value
    return ""


def _derive_model_dim(config: dict[str, Any], metrics: dict[str, Any], depth: int, head_dim: int) -> int:
    explicit = _safe_int(
        metrics.get("model_dim")
        or config.get("model_dim")
        or config.get("dim")
        or config.get("n_embd")
    )
    if explicit > 0:
        return explicit
    aspect_ratio = _safe_int(config.get("aspect_ratio"))
    if aspect_ratio > 0 and depth > 0:
        return depth * aspect_ratio
    n_heads = _safe_int(metrics.get("n_heads") or config.get("n_heads"))
    if n_heads > 0 and head_dim > 0:
        return n_heads * head_dim
    return 0


def _derive_n_heads(config: dict[str, Any], metrics: dict[str, Any], model_dim: int, head_dim: int) -> int:
    explicit = _safe_int(metrics.get("n_heads") or config.get("n_heads"))
    if explicit > 0:
        return explicit
    if model_dim > 0 and head_dim > 0:
        return model_dim // head_dim
    return 0


def load_fleet_manifest() -> FleetManifest | None:
    payload = load_json(FLEET_MANIFEST_PATH)
    if payload is None:
        return None
    try:
        manifest = FleetManifest.from_dict(payload)
    except Exception:
        workers = [FleetWorker.from_dict(item) for item in payload.get("workers", [])]
        manifest = FleetManifest(
            tag=payload["tag"],
            created_at=payload["created_at"],
            repository_root=payload["repository_root"],
            shared_research_dir=payload["shared_research_dir"],
            observer_prompt_path=payload.get("observer_prompt_path")
            or payload.get("main_prompt_path")
            or str(OBSERVER_PROMPT_PATH),
            tool_builder_prompt_path=payload.get("tool_builder_prompt_path")
            or str(TOOL_BUILDER_PROMPT_PATH),
            workers=workers,
            main_prompt_path=payload.get("main_prompt_path", str(LEGACY_MAIN_AGENT_PROMPT_PATH)),
        )
    if not manifest.observer_prompt_path:
        manifest.observer_prompt_path = str(OBSERVER_PROMPT_PATH)
    if Path(manifest.observer_prompt_path).name == "main-agent.md":
        manifest.observer_prompt_path = str(OBSERVER_PROMPT_PATH)
    if not manifest.tool_builder_prompt_path:
        manifest.tool_builder_prompt_path = str(TOOL_BUILDER_PROMPT_PATH)
    if not manifest.main_prompt_path:
        manifest.main_prompt_path = str(LEGACY_MAIN_AGENT_PROMPT_PATH)
    return manifest


def save_fleet_manifest(manifest: FleetManifest) -> None:
    write_json(FLEET_MANIFEST_PATH, manifest.to_dict())


def write_results_tsv(rows: list[ResultRow]) -> None:
    RESULTS_TSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_TSV_PATH.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["commit", "val_bpb", "memory_gb", "status", "description"])
        for row in rows:
            writer.writerow(
                [
                    row.commit,
                    f"{row.val_bpb:.6f}",
                    f"{row.memory_gb:.1f}",
                    row.status,
                    row.description,
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


def extract_open_questions(rows: list[ResultRow], config: ExperimentConfig) -> list[str]:
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


def make_hypothesis_id(title: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in title)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug[:48] or "hypothesis"


def suggested_hypotheses(rows: list[ResultRow], config: ExperimentConfig) -> list[Hypothesis]:
    descriptions = " ".join(row.description.lower() for row in rows)
    suggestions: list[Hypothesis] = []

    def add(title: str, rationale: str, config_overrides: dict[str, Any], priority: int) -> None:
        suggestions.append(
            Hypothesis(
                hypothesis_id=make_hypothesis_id(title),
                title=title,
                rationale=rationale,
                config_overrides=config_overrides,
                priority=priority,
            )
        )

    if not rows:
        add(
            "Baseline replication",
            "Establish the reference point before branching the search.",
            {},
            100,
        )
    if "batch" not in descriptions:
        add(
            "Halve total batch size",
            "Smaller global batches can buy more optimizer steps inside the fixed 300s budget.",
            {"total_batch_size": max(2**17, config.total_batch_size // 2)},
            90,
        )
    if "depth" not in descriptions:
        add(
            "Probe depth +1",
            "A slightly deeper model may improve quality if step throughput does not collapse.",
            {"depth": config.depth + 1},
            80,
        )
    if "warm" not in descriptions:
        add(
            "Extend warmdown",
            "The current decay schedule may be too aggressive in the last third of training.",
            {"warmdown_ratio": min(0.9, round(config.warmdown_ratio + 0.15, 2))},
            70,
        )
    if "window" not in descriptions:
        next_pattern = "LLLL" if config.window_pattern != "LLLL" else "SSSL"
        add(
            "Window-pattern swap",
            "Attention locality may be the constraint rather than raw width or depth.",
            {"window_pattern": next_pattern},
            60,
        )
    if "embedding" not in descriptions:
        add(
            "Embedding LR sweep",
            "Embeddings can underfit or destabilize quickly under the fixed-budget regime.",
            {"embedding_lr": round(config.embedding_lr * 1.2, 4)},
            50,
        )
    return suggestions[:4]


def load_existing_brief() -> ResearchBrief | None:
    payload = load_json(BRIEF_PATH)
    if payload is None:
        return None
    try:
        return ResearchBrief.from_dict(payload)
    except Exception:
        return None


def merge_hypothesis_queue(
    existing: list[Hypothesis] | None, suggestions: list[Hypothesis]
) -> list[Hypothesis]:
    queue: list[Hypothesis] = list(existing or [])
    seen = {item.hypothesis_id for item in queue}
    for suggestion in suggestions:
        if suggestion.hypothesis_id in seen:
            continue
        queue.append(suggestion)
        seen.add(suggestion.hypothesis_id)
        if len(queue) >= 6:
            break
    queue.sort(key=lambda item: (-item.priority, item.hypothesis_id))
    return queue


def current_config_from_best_known(experiments: list[AggregateExperiment]) -> dict[str, Any]:
    best = best_kept_experiment(experiments)
    if best is not None:
        return ExperimentConfig.from_dict(best.config or {}).to_dict()
    return ExperimentConfig().to_dict()


def planning_result_rows(experiments: list[AggregateExperiment]) -> list[ResultRow]:
    return experiments_to_results_rows(experiments)


def build_research_brief(experiments: list[AggregateExperiment]) -> ResearchBrief:
    existing = load_existing_brief()
    rows = planning_result_rows(experiments)
    config = ExperimentConfig.from_dict(current_config_from_best_known(experiments))
    best = best_result(rows)
    best_payload = asdict(best) if best is not None else {}
    findings = summarize_findings(rows)
    constraints = [
        "Only `train.py` is editable during public autoresearch runs; `prepare.py` stays fixed.",
        "Primary metric is val_bpb from `evaluate_bpb()` on a pinned validation shard.",
        "Training budget is fixed at 300 seconds, so step-efficiency is part of the objective.",
        "Experiments must satisfy total_batch_size % (device_batch_size * MAX_SEQ_LEN) == 0.",
        "Fleet mode uses one worker agent per GPU plus a central observer and optional tool-builder.",
    ]
    notes = [
        f"Generated on host {platform.node()} ({platform.platform()}).",
        "Observer dispatch lives in `research_brief.json` via `hypothesis_queue`.",
        "Treat small single-run wins as provisional until replicated.",
    ]
    hypothesis_queue = merge_hypothesis_queue(
        existing.hypothesis_queue if existing is not None else None,
        suggested_hypotheses(rows, config),
    )
    return ResearchBrief(
        generated_at=utc_now_iso(),
        repository=ROOT.name,
        objective="Optimize autoregressive pretraining quality under a fixed NVIDIA GPU time budget.",
        constraints=constraints,
        current_config=config.to_dict(),
        best_result=best_payload,
        findings=findings,
        open_questions=extract_open_questions(rows, config),
        hypothesis_queue=hypothesis_queue,
        notes=notes,
    )


def ensure_search_model() -> None:
    if SEARCH_MODEL_PATH.exists():
        return
    write_text(
        SEARCH_MODEL_PATH,
        (
            "# Search Model\n\n"
            "This file is the observer's persistent scratchpad.\n"
            "Update it after every dispatch cycle.\n\n"
            "## Active Theory\n\n"
            "- Describe the current mechanism you believe drives val_bpb.\n\n"
            "## Search Phase\n\n"
            "- broad-exploration | focused-exploitation | diminishing-returns | stuck\n\n"
            "## Dimension Beliefs\n\n"
            "- depth:\n"
            "- window_pattern:\n"
            "- total_batch_size:\n"
            "- embedding_lr:\n"
            "- warmdown_ratio:\n\n"
            "## Next Dispatches\n\n"
            "- Keep 1-4 hypotheses here that map onto `research_brief.json`.\n"
            "- If only one worker is available, one planned experiment is sufficient.\n"
        ),
    )


def ensure_registry() -> ToolRegistry:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    PUBLISHED_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    registry = ToolRegistry.load(TOOLS_REGISTRY_PATH, PUBLISHED_TOOLS_DIR)
    registry.save(TOOLS_REGISTRY_PATH)
    return registry


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
            node_id=payload.get("node_id", ""),
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
        worktree_path = Path(manifest_worker.worktree_path)
        missing_worktree = not worktree_path.exists()
        merged.append(
            WorkerStatus(
                worker_id=manifest_worker.worker_id,
                node_id="",
                gpu_id=str(manifest_worker.gpu_id),
                run_id=None,
                state="missing_worktree" if missing_worktree else "idle",
                updated_at=manifest.created_at,
                title=manifest_worker.current_title,
                hypothesis_id=manifest_worker.current_hypothesis_id,
                notes=(
                    "Run `uv run python orchestrator.py init-fleet --create-worktrees` to materialize this worker."
                    if missing_worktree
                    else None
                ),
                paths={
                    "worktree_path": manifest_worker.worktree_path,
                    "prompt_path": manifest_worker.prompt_path,
                },
            )
        )
    merged.extend(live_by_worker.values())
    return merged


def _pid_is_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def is_worker_active(worker: WorkerStatus) -> bool:
    if worker.state not in {"launching", "running", "compiling"}:
        return False
    if worker.heartbeat_age_seconds is None:
        return True
    if worker.heartbeat_age_seconds <= STALE_HEARTBEAT_SECONDS:
        return True
    return _pid_is_alive(worker.pid)


def is_worker_dispatchable(worker: WorkerStatus) -> bool:
    return worker.state not in {"missing_worktree"} and not is_worker_active(worker)


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
        decision_markdown_path = PLANS_DIR / f"{experiment_id}.md"
        decision_markdown = (
            decision_markdown_path.read_text() if decision_markdown_path.exists() else ""
        )

        plan_hypothesis = plan.get("hypothesis", {})
        title = (
            result.get("title")
            or plan_hypothesis.get("title")
            or config.get("notes")
            or experiment_id
        )
        execution_status = ""
        if result:
            execution_status = result.get("status", "")
        elif latest_event is not None:
            event_type = latest_event.get("event_type")
            if event_type == "run_failed":
                execution_status = "failed"
            elif event_type == "run_completed":
                execution_status = "completed"
            elif event_type in {"run_started", "heartbeat"}:
                execution_status = "running"
        decision_status = result.get("decision_status", "")
        status = _terminal_decision_status(decision_status)
        if not status and execution_status in {"keep", "discard", "crash", "replicate"}:
            status = execution_status
        if not status and execution_status in {"completed", "failed"}:
            status = "review_pending"
        if not status and execution_status:
            status = execution_status or "planned"
        if not status:
            status = "planned"

        run_payload = metadata.get("run", {})
        payload_identity = latest_event or {}
        runtime_payload = metadata.get("runtime", {})
        worker_id = run_payload.get("worker_id") or payload_identity.get("worker_id", "")
        gpu_id = str(run_payload.get("gpu_id") or payload_identity.get("gpu_id", ""))
        commit = (
            runtime_payload.get("commit")
            or result.get("commit")
            or plan.get("based_on_commit", "")
        )
        parent_commit = (
            result.get("parent_commit")
            or runtime_payload.get("parent_commit")
            or plan.get("based_on_commit")
            or ""
        )
        created_at = (
            plan.get("created_at")
            or metadata.get("recorded_at")
            or (events[0]["recorded_at"] if events else utc_now_iso())
        )
        recorded_at = result.get("recorded_at") or metadata.get("recorded_at")
        notes = result.get("analysis", "")
        metrics = result.get("metrics") or metadata.get("metrics") or {}
        gpu_name = (
            metadata.get("runtime", {}).get("gpu_name")
            or result.get("gpu_name")
            or metrics.get("gpu_name")
            or (f"GPU {gpu_id}" if gpu_id else "")
        )
        hypothesis_id = (
            plan_hypothesis.get("hypothesis_id")
            or result.get("hypothesis_id")
            or metadata.get("run", {}).get("hypothesis_id")
            or ""
        )
        rationale = (
            plan_hypothesis.get("rationale")
            or result.get("rationale")
            or metadata.get("run", {}).get("rationale")
            or ""
        )
        outcome = result.get("outcome") or plan_hypothesis.get("outcome") or ""
        diff_stat = runtime_payload.get("diff_stat") or result.get("diff_stat") or ""
        diff_hash = runtime_payload.get("diff_hash") or result.get("diff_hash") or ""

        experiments.append(
            AggregateExperiment(
                experiment_id=experiment_id,
                status=status,
                title=title,
                commit=commit,
                parent_commit=parent_commit,
                execution_status=execution_status,
                decision_status=decision_status,
                worker_id=worker_id or "",
                gpu_id=gpu_id or "",
                created_at=created_at,
                recorded_at=recorded_at,
                metrics=metrics,
                config=config,
                notes=notes,
                hypothesis_id=hypothesis_id,
                rationale=rationale,
                outcome=outcome,
                decision_markdown_path=display_path(decision_markdown_path),
                decision_markdown=decision_markdown,
                gpu_name=gpu_name,
                diff_stat=diff_stat,
                diff_hash=diff_hash,
            )
        )
    experiments.sort(key=_experiment_sort_key)
    return experiments


def experiments_to_results_rows(experiments: list[AggregateExperiment]) -> list[ResultRow]:
    rows: list[ResultRow] = []
    for item in experiments:
        if item.status not in {"keep", "discard", "crash", "replicate"}:
            continue
        metrics = item.metrics or {}
        peak_vram_mb = float(metrics.get("peak_vram_mb", 0.0) or 0.0)
        rows.append(
            ResultRow(
                commit=item.commit or "unknown",
                val_bpb=float(metrics.get("val_bpb", 0.0) or 0.0),
                memory_gb=peak_vram_mb / 1024.0,
                status=item.status,
                description=item.title,
            )
        )
    return rows


def effective_result_rows(experiments: list[AggregateExperiment]) -> list[ResultRow]:
    return planning_result_rows(experiments)


def build_experiment_records(experiments: list[AggregateExperiment]) -> list[ExperimentRecord]:
    terminal = [
        item for item in experiments if item.status in {"keep", "discard", "crash", "replicate"}
    ]
    terminal.sort(key=_experiment_sort_key)

    best_keep = math.inf
    records: list[ExperimentRecord] = []
    for index, item in enumerate(terminal, start=1):
        metrics = item.metrics or {}
        normalized_config = ExperimentConfig.from_dict(item.config or {}).to_dict()

        val_bpb = _safe_float(metrics.get("val_bpb"))
        previous_best = best_keep if math.isfinite(best_keep) else None
        delta = 0.0 if previous_best is None else val_bpb - previous_best

        status = _dashboard_status(item.status)
        if status in {"keep", "replicate"} and val_bpb > 0:
            best_keep = min(best_keep, val_bpb)

        peak_vram_gb = _safe_float(metrics.get("peak_vram_gb"))
        if peak_vram_gb <= 0.0:
            peak_vram_gb = _safe_float(metrics.get("peak_vram_mb")) / 1024.0

        depth = _safe_int(metrics.get("depth") or normalized_config.get("depth"))
        head_dim = _safe_int(metrics.get("head_dim") or normalized_config.get("head_dim"))
        model_dim = _derive_model_dim(normalized_config, metrics, depth, head_dim)
        n_heads = _derive_n_heads(normalized_config, metrics, model_dim, head_dim)
        checkpoint_values = _float_list(
            metrics.get("bpb_at_checkpoints")
            or metrics.get("val_bpb_checkpoints")
            or metrics.get("checkpoints")
        )

        record = ExperimentRecord(
            id=index,
            commit=item.commit or item.experiment_id,
            parent_commit=item.parent_commit,
            timestamp=item.recorded_at or item.created_at,
            status=status,
            description=item.title.strip() or item.experiment_id,
            execution_status=item.execution_status,
            decision_status=item.decision_status,
            val_bpb=val_bpb,
            delta=delta,
            num_steps=_safe_int(metrics.get("num_steps")),
            training_seconds=_safe_float(metrics.get("training_seconds") or metrics.get("train_seconds")),
            total_seconds=_safe_float(metrics.get("total_seconds")),
            mfu_percent=_safe_float(metrics.get("mfu_percent")),
            total_tokens_M=_safe_float(metrics.get("total_tokens_M") or metrics.get("total_tokens_m")),
            peak_vram_gb=peak_vram_gb,
            num_params_M=_safe_float(metrics.get("num_params_M")),
            depth=depth,
            train_bpb=_safe_float(
                metrics.get("train_bpb") or metrics.get("train_loss") or metrics.get("loss"),
                val_bpb,
            ),
            bpb_at_checkpoints=checkpoint_values,
            still_improving=metrics.get("still_improving"),
            improvement_rate=_safe_float(metrics.get("improvement_rate")),
            tokens_per_second=_safe_int(
                metrics.get("tokens_per_second") or metrics.get("tok_per_sec")
            ),
            diff_stat=item.diff_stat,
            diff_hash=item.diff_hash,
            decision_markdown_path=item.decision_markdown_path,
            decision_markdown=item.decision_markdown,
            gpu_name=item.gpu_name,
            model_dim=model_dim,
            n_heads=n_heads,
            head_dim=head_dim,
            window_pattern=str(
                metrics.get("window_pattern") or normalized_config.get("window_pattern") or ""
            ),
            total_batch_size=_safe_int(
                metrics.get("total_batch_size") or normalized_config.get("total_batch_size")
            ),
            device_batch_size=_safe_int(
                metrics.get("device_batch_size") or normalized_config.get("device_batch_size")
            ),
            matrix_lr=_safe_float(
                metrics.get("matrix_lr") or normalized_config.get("matrix_lr")
            ),
            embedding_lr=_safe_float(
                metrics.get("embedding_lr") or normalized_config.get("embedding_lr")
            ),
            weight_decay=_safe_float(
                metrics.get("weight_decay") or normalized_config.get("weight_decay")
            ),
            warmdown_ratio=_safe_float(
                metrics.get("warmdown_ratio") or normalized_config.get("warmdown_ratio")
            ),
            adam_betas=[_safe_float(item) for item in normalized_config.get("adam_betas", [])],
            worker_id=item.worker_id,
            gpu_id=item.gpu_id,
            hypothesis_id=item.hypothesis_id,
            rationale=item.rationale,
            outcome=item.outcome,
            notes=item.notes,
        )
        records.append(record)
    return records


def render_progress(rows: list[ResultRow], output_path: Path) -> None:
    if not rows:
        return
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    xs = list(range(len(rows)))
    val_bpb = [row.val_bpb for row in rows]
    statuses = [row.status for row in rows]
    descriptions = [row.description for row in rows]

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


def build_leaderboard(
    experiments: list[AggregateExperiment], workers: list[WorkerStatus], rows: list[ResultRow]
) -> dict[str, Any]:
    decided = [item for item in experiments if item.status in {"keep", "discard", "crash", "replicate"}]
    best_row = best_result(rows)
    kept = [row for row in rows if row.status == "keep"]
    return {
        "generated_at": utc_now_iso(),
        "total_runs": len(experiments),
        "decided_runs": len(decided),
        "active_workers": sum(1 for worker in workers if is_worker_active(worker)),
        "best_run": None if best_row is None else asdict(best_row),
        "keep_rate": round(len(kept) / len(rows), 3) if rows else 0.0,
    }


def best_kept_experiment(experiments: list[AggregateExperiment]) -> AggregateExperiment | None:
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
    note_text = f" note={worker.notes}" if worker.notes else ""
    return (
        f"- `{worker.worker_id}` gpu={worker.gpu_id} state={worker.state} "
        f"run={worker.run_id or '-'} age={age} progress={format_progress(worker.progress)} "
        f"title={worker.title or '-'} {metric_text}{note_text}"
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


def hypotheses_for_worker(brief: ResearchBrief, worker_id: str) -> list[Hypothesis]:
    return [
        item
        for item in brief.hypothesis_queue
        if item.assigned_worker == worker_id and item.status == "dispatched"
    ]


def render_fleet_brief(
    experiments: list[AggregateExperiment],
    workers: list[WorkerStatus],
    brief: ResearchBrief,
    registry: ToolRegistry,
) -> str:
    best = best_kept_experiment(experiments)
    recent = sorted(
        [item for item in experiments if item.status in {"keep", "discard", "crash", "replicate"}],
        key=lambda item: item.created_at,
        reverse=True,
    )[:8]
    active_workers = [worker for worker in workers if is_worker_active(worker)]
    next_hypotheses = [
        item for item in brief.hypothesis_queue if item.status in {"pending", "dispatched"}
    ][:6]
    tool_requests = [tool for tool in registry.tools if tool.status == "requested"][:6]

    lines = [
        "# Fleet Brief",
        "",
        f"Generated: {utc_now_iso()}",
        "",
        "## Best Known Result",
    ]
    if best is None:
        best_row = best_result(planning_result_rows(experiments))
        if best_row is None:
            lines.append("- No kept runs yet.")
        else:
            lines.append(
                f"- `{best_row.commit}` {best_row.description}: val_bpb={best_row.val_bpb:.6f}"
            )
    else:
        lines.append(
            f"- `{best.experiment_id}` {best.title}: val_bpb={float(best.metrics.get('val_bpb', math.inf)):.6f}, "
            f"worker={best.worker_id}, gpu={best.gpu_id}"
        )

    lines.extend(["", "## Next Hypotheses"])
    if not next_hypotheses:
        lines.append("- No pending hypotheses. Observer should refresh `research_brief.json`.")
    else:
        for hypothesis in next_hypotheses:
            assignment = hypothesis.assigned_worker or "unassigned"
            lines.append(
                f"- `{hypothesis.hypothesis_id}` [{hypothesis.status}] {hypothesis.title} -> {assignment}"
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

    lines.extend(["", "## Tool Requests"])
    if not tool_requests:
        lines.append("- No requested tools.")
    else:
        for tool in tool_requests:
            lines.append(f"- `{tool.tool_id}` {tool.title}: {tool.problem}")
    return "\n".join(lines) + "\n"


def render_observer_protocol(manifest: FleetManifest) -> str:
    worker_list = "\n".join(
        f"- `{worker.worker_id}` gpu={worker.gpu_id} worktree=`{display_path(Path(worker.worktree_path))}` branch=`{worker.branch}`"
        for worker in manifest.workers
    )
    return (
        "# Observer Protocol\n\n"
        "You are the observer. You control experiment dispatch for the fleet.\n\n"
        "Rules:\n"
        "- Do not edit worker worktrees directly unless you are explicitly taking ownership of that worker.\n"
        "- Choose the experiment queue. Workers do not self-dispatch in fleet mode.\n"
        "- Persist dispatch state in `research/research_brief.json` by editing `hypothesis_queue`.\n"
        "- A dispatched hypothesis must set `status` to `dispatched` and `assigned_worker` to a worker id.\n"
        "- For each dispatched hypothesis, author `research/plans/<experiment_id>.json` and `research/plans/<experiment_id>.md` as the observer-owned dispatch packet.\n"
        "- You own the fleet-level decision after each run: keep, discard, crash, replicate, and whether the branch should advance.\n"
        "- Workers may report metrics and suggested interpretation, but the observer makes the final decision of record and stamps the terminal status that appears in `/history`.\n"
        "- Only modify a worker branch after that worker is idle and its execution artifacts are fully written. Do not race an active worker.\n"
        "- Treat run artifacts as mandatory, not optional. Completed runs are only visible in `/history` after the worker writes the run bundle, the observer stamps `decision_status`, and you run `sync`.\n"
        "- Every dispatched run should also have a scientific decision markdown companion at `research/plans/<experiment_id>.md`.\n"
        "- The minimum lineage fields you should expect in a finished run are `commit`, `parent_commit`, `title`, `execution_status`, `decision_status`, concise `analysis`, and final `metrics.val_bpb`.\n"
        "- After changing the queue, run `uv run python orchestrator.py sync` so worker assignments regenerate.\n"
        "- Keep `research/search_model.md` current. That file is your scratchpad and theory ledger.\n"
        "- Use the tool-builder only when the fleet needs a reusable script or analysis helper.\n\n"
        "Read on every cycle:\n"
        f"- `{display_path(FLEET_BRIEF_PATH)}`\n"
        f"- `{display_path(LIVE_SUMMARY_PATH)}`\n"
        f"- `{display_path(BRIEF_PATH)}`\n"
        f"- `{display_path(KNOWLEDGE_PATH)}`\n"
        f"- `{display_path(SEARCH_MODEL_PATH)}`\n"
        f"- `{display_path(TOOLS_REGISTRY_PATH)}`\n\n"
        "Workers:\n"
        f"{worker_list}\n"
    )


def render_tool_builder_protocol() -> str:
    return (
        "# Tool-Builder Protocol\n\n"
        "You are the tool-builder. Build small reusable helper scripts when the observer or workers request them.\n\n"
        "Rules:\n"
        "- Only create tools that solve a concrete recurring problem.\n"
        "- Prefer zero-dependency Python or shell utilities that run inside this repo.\n"
        "- Publish tools under `research/tools/published/`.\n"
        "- Update `research/tools/registry.json` by changing requested tools to `published` and filling `path`, `summary`, and `usage`.\n"
        "- Treat a valid request as an entry with `tool_id`, `title`, `problem`, `requested_by`, and `status: requested`.\n"
        "- After publishing, set `path` to the tool file, add a one-line `summary`, and provide at least one concrete `usage` command.\n"
        "- Do not rewrite worker code or dispatch experiments. Your scope is tooling only.\n"
    )


def render_gpu_worker_protocol() -> str:
    return (
        "# GPU Worker Protocol\n\n"
        "You are a GPU worker. Execute the observer's assigned hypothesis on your dedicated GPU.\n\n"
        "Rules:\n"
        "- Stay inside your assigned git worktree when editing code.\n"
        "- Edit only `train.py` in your worktree unless the assignment explicitly says otherwise.\n"
        "- Do not self-dispatch new experiments. If the assignment is empty, wait and monitor shared state.\n"
        "- Run exactly one experiment at a time on your assigned GPU.\n"
        "- Use `CUDA_VISIBLE_DEVICES=<gpu> uv run train.py > run.log 2>&1` so your run stays isolated.\n"
        "- Your default job is execution and reporting, not fleet-level decision making.\n"
        "- Always write shared artifacts under the repo-root `research/` tree, never under a worktree-local `research/` directory.\n"
        "- Capture metrics, logs, and run artifacts under `research/runs/` for every completed experiment. This is the visualization contract.\n"
        "- One finished experiment must be associated with `research/plans/<experiment_id>.json` and `research/plans/<experiment_id>.md`, which are authored by the observer before dispatch, plus `research/runs/<experiment_id>/config.json`, `metadata.json`, `result.json`, and `events.jsonl`.\n"
        "- The plan file must include `experiment_id`, `created_at`, `based_on_commit`, `worker_id`, and a `hypothesis` object with `hypothesis_id`, `title`, and `rationale`.\n"
        "- Before editing `train.py`, record `parent_commit` as the current HEAD of your worker branch. Make a dedicated experiment commit before training so `commit` and `parent_commit` are explicit.\n"
        "- The plan markdown is the observer-owned scientific note for the run. It should capture the hypothesis, reference config, planned intervention, and predicted outcome before training starts.\n"
        "- The result file must include a provisional execution `status` (`completed` or `failed`), `recorded_at`, `commit`, `parent_commit`, `title`, concise `analysis`, optional `outcome`, and a `metrics` object containing at least `val_bpb`, `peak_vram_mb`, `num_steps`, `training_seconds`, and `total_seconds` when available. The observer stamps the terminal status before the run is treated as final.\n"
        "- `metadata.json` should capture runtime identity such as `worker_id`, `gpu_id`, `gpu_name`, and any stable metrics you already know before the final decision.\n"
        "- `events.jsonl` should at minimum append `run_started` and then `run_completed` or `run_failed`; add `heartbeat` only if it helps monitoring.\n"
        "- After writing execution artifacts, stop. Do not reset or advance the branch until the observer stamps `decision_status` and the next assignment tells you how to proceed.\n"
        "- Do not hand-edit `results.tsv` in fleet mode; it is derived from the canonical run artifacts.\n"
        "- Read shared state before every run so you avoid duplicating peer work.\n"
    )


def render_observer_start() -> str:
    return (
        "# Observer Start Here\n\n"
        "Role: `observer`\n\n"
        "Read exactly in this order:\n"
        f"1. `{display_path(OBSERVER_ASSIGNMENT_PATH)}`\n"
        f"2. `{display_path(OBSERVER_PROTOCOL_PATH)}`\n"
        f"3. `{display_path(SEARCH_MODEL_PATH)}`\n"
    )


def render_tool_builder_start() -> str:
    return (
        "# Tool-Builder Start Here\n\n"
        "Role: `tool-builder`\n\n"
        "Read exactly in this order:\n"
        f"1. `{display_path(TOOL_BUILDER_ASSIGNMENT_PATH)}`\n"
        f"2. `{display_path(TOOL_BUILDER_PROTOCOL_PATH)}`\n"
        f"3. `{display_path(TOOLS_REGISTRY_PATH)}`\n"
    )


def render_worker_start(worker: FleetWorker) -> str:
    assignment_path = WORKER_ASSIGNMENTS_DIR / f"{worker.worker_id}.md"
    return (
        f"# GPU-Worker Start Here: {worker.worker_id}\n\n"
        "Role: `gpu-worker`\n"
        f"Agent: `{worker.worker_id}`\n\n"
        "Paths:\n"
        f"- `ROOT` = current checkout root\n"
        f"- `WORKTREE` = `{display_path(Path(worker.worktree_path))}`\n"
        f"- `RESEARCH` = `{display_path(RESEARCH_DIR)}`\n"
        f"- `TOOLS` = `{display_path(PUBLISHED_TOOLS_DIR)}`\n"
        f"- `SEARCH_MODEL` = `{display_path(SEARCH_MODEL_PATH)}`\n\n"
        "Read exactly in this order:\n"
        f"1. `{display_path(assignment_path)}`\n"
        f"2. `{display_path(GPU_WORKER_PROTOCOL_PATH)}`\n"
        f"3. `{display_path(SEARCH_MODEL_PATH)}`\n"
    )


def render_legacy_main_prompt() -> str:
    return (
        "# Main Agent Bootstrap\n\n"
        "Use this prompt for the top-level orchestrator before the fleet exists.\n\n"
        "1. Read `program.md` and establish the baseline on this hardware.\n"
        "2. Record the best-known baseline config locally.\n"
        "3. Initialize the fleet once the baseline is established.\n"
        f"4. Hand off to `{display_path(OBSERVER_PROMPT_PATH)}` for N+2 fleet dispatch.\n"
    )


def render_observer_assignment(
    manifest: FleetManifest,
    workers: list[WorkerStatus],
    brief: ResearchBrief,
    registry: ToolRegistry,
) -> str:
    free_workers = [worker for worker in workers if is_worker_dispatchable(worker)]
    pending = [item for item in brief.hypothesis_queue if item.status == "pending"]
    dispatched = [item for item in brief.hypothesis_queue if item.status == "dispatched"]
    requested_tools = [tool for tool in registry.tools if tool.status == "requested"]

    lines = [
        "# Observer Assignment",
        "",
        "Repository: current checkout root",
        "Research dir: `research`",
        f"Git remote: `{get_origin_remote()}`",
        "",
        "## Fleet",
    ]
    if not workers:
        lines.append("- No workers configured.")
    else:
        lines.extend(describe_worker(worker) for worker in workers)

    lines.extend(["", "## Current Reference Config", f"- `{json.dumps(brief.current_config, sort_keys=True)}`"])

    lines.extend(["", "## Dispatch Contract"])
    lines.extend(
        [
            "- Edit `research/research_brief.json` directly when you dispatch.",
            "- Use one `hypothesis_queue` entry per experiment idea.",
            "- Set `status` to `dispatched` and `assigned_worker` to the target worker id.",
            "- After edits, run `uv run python orchestrator.py sync` to regenerate assignments.",
            "- When a run is finished, mark the hypothesis `completed` or `abandoned`, add a short `outcome`, and decide keep/discard/crash/replicate for the fleet record.",
            "- Do not count a run as dashboard-visible until the worker has written `research/plans/<experiment_id>.json`, `research/plans/<experiment_id>.md`, and the full `research/runs/<experiment_id>/` artifact bundle.",
            "- The observer stamps the terminal `decision_status` into `result.json`; worker execution status is not the canonical fleet decision.",
            "- The observer may only reset or advance a worker branch after that worker is idle and has written its execution artifacts for the run.",
            "- Require the finished `result.json` to include `commit`, `parent_commit`, concise `analysis`, and final `metrics.val_bpb`.",
            "- If you need a reusable helper, add a tool request in `research/tools/registry.json` with: `tool_id`, `title`, `problem`, `requested_by`, and `status: requested`.",
        ]
    )

    lines.extend(["", "## Free Workers"])
    if not free_workers:
        lines.append("- No idle workers.")
    else:
        for worker in free_workers:
            lines.append(f"- `{worker.worker_id}` gpu={worker.gpu_id}")

    lines.extend(["", "## Pending Hypotheses"])
    if not pending:
        lines.append("- No pending hypotheses.")
    else:
        for item in pending:
            lines.append(f"- `{item.hypothesis_id}` {item.title}: {item.rationale}")

    lines.extend(["", "## Dispatched Hypotheses"])
    if not dispatched:
        lines.append("- No dispatched hypotheses.")
    else:
        for item in dispatched:
            lines.append(
                f"- `{item.hypothesis_id}` -> `{item.assigned_worker or 'unassigned'}`: {item.title}"
            )

    lines.extend(["", "## Tool Requests"])
    if not requested_tools:
        lines.append("- No tool requests.")
    else:
        for tool in requested_tools:
            lines.append(f"- `{tool.tool_id}` {tool.title}: {tool.problem}")

    lines.extend(["", "## Worker Inventory"])
    for worker in manifest.workers:
        lines.append(
            f"- `{worker.worker_id}` branch=`{worker.branch}` worktree=`{display_path(Path(worker.worktree_path))}`"
        )

    return "\n".join(lines) + "\n"


def render_tool_builder_assignment(registry: ToolRegistry) -> str:
    requested_tools = [tool for tool in registry.tools if tool.status == "requested"]
    published_tools = [tool for tool in registry.tools if tool.status == "published"][:8]
    lines = [
        "# Tool-Builder Assignment",
        "",
        f"Registry: `{display_path(TOOLS_REGISTRY_PATH)}`",
        f"Published dir: `{display_path(PUBLISHED_TOOLS_DIR)}`",
        "",
        "## Request Contract",
        "- Expect requested entries to include: `tool_id`, `title`, `problem`, `requested_by`, `status: requested`.",
        "- On publish, fill `path`, `summary`, and `usage`, then change `status` to `published`.",
        "",
        "## Requested Tools",
    ]
    if not requested_tools:
        lines.append("- No requested tools. Stand by.")
    else:
        for tool in requested_tools:
            lines.append(
                f"- `{tool.tool_id}` {tool.title}: {tool.problem} (requested by {tool.requested_by or 'unknown'})"
            )

    lines.extend(["", "## Recently Published"])
    if not published_tools:
        lines.append("- No published tools yet.")
    else:
        for tool in published_tools:
            lines.append(f"- `{tool.tool_id}` {tool.title}: {tool.path or 'path unset'}")
    return "\n".join(lines) + "\n"


def render_worker_assignment(
    worker: FleetWorker,
    workers: list[WorkerStatus],
    experiments: list[AggregateExperiment],
    brief: ResearchBrief,
) -> str:
    peer_workers = [item for item in workers if item.worker_id != worker.worker_id]
    peer_outcomes = recent_peer_outcomes(experiments, worker.worker_id)
    assigned = hypotheses_for_worker(brief, worker.worker_id)
    worktree_exists = Path(worker.worktree_path).exists()

    lines = [
        f"# Worker Assignment: {worker.worker_id}",
        "",
        f"Worktree: `{display_path(Path(worker.worktree_path))}`",
        f"Branch: `{worker.branch}`",
        f"GPU: `{worker.gpu_id}`",
        f"Shared research root: `{display_path(RESEARCH_DIR)}`",
        "",
        "## Assignment Source",
        "- Observer dispatch is sourced from `research/research_brief.json`.",
        "- If this file says `Await observer dispatch`, do not invent a new experiment.",
        "- The observer owns the final keep/discard/crash decision unless this assignment explicitly says otherwise.",
        "- Treat `research/research_brief.json.current_config` as the active reference config for new work.",
        "",
        "## Current Reference Config",
        f"- `{json.dumps(brief.current_config, sort_keys=True)}`",
        "",
        "## Worktree Status",
        (
            "- Worktree exists and is ready."
            if worktree_exists
            else "- Worktree is missing. Do not start this worker until `uv run python orchestrator.py init-fleet --create-worktrees` has recreated it."
        ),
        "",
        "## Current Assignment",
    ]
    if not assigned:
        lines.append("- Await observer dispatch.")
    else:
        for item in assigned:
            lines.append(f"- Hypothesis: `{item.hypothesis_id}`")
            lines.append(f"- Title: {item.title}")
            lines.append(f"- Rationale: {item.rationale}")
            lines.append(f"- Config overrides: `{json.dumps(item.config_overrides, sort_keys=True)}`")
            lines.append("- Before the run: read `research/plans/<experiment_id>.md` as the observer-owned scientific decision note. Do not edit it unless the observer explicitly asks you to.")
            lines.append("- Before editing `train.py`: record `parent_commit = git rev-parse --short HEAD` in your worktree.")
            lines.append("- Before training: make a dedicated experiment commit so `commit` and `parent_commit` are unambiguous in the run artifacts.")
            lines.append(
                f"- Run command: `CUDA_VISIBLE_DEVICES={worker.gpu_id} uv run train.py > run.log 2>&1`"
            )
            lines.append("- Before the run: confirm the observer has already created the matching `research/plans/<experiment_id>.json` and `research/plans/<experiment_id>.md`; create only `research/runs/<experiment_id>/` for execution artifacts.")
            lines.append("- After the run: write `config.json`, `metadata.json`, `events.jsonl`, and `result.json` with `commit`, `parent_commit`, concise `analysis`, optional `outcome`, execution `status` (`completed` or `failed`), and final metrics. Treat the terminal fleet decision as provisional until the observer stamps `decision_status`.")
            lines.append("- After writing execution artifacts: stop and wait. Do not reset or advance the branch until the observer's next decision is visible in shared state.")
            lines.append("- The `/history` page is derived from these run artifacts after `uv run python orchestrator.py sync`; skipped artifacts mean an invisible run.")
            lines.append("- Report metrics, logs, and your interpretation back to shared state; do not self-dispatch a follow-up family.")
            if item.outcome:
                lines.append(f"- Prior outcome note: {item.outcome}")

    lines.extend(["", "## Peer Workers"])
    if not peer_workers:
        lines.append("- No peer worker status available.")
    else:
        lines.extend(describe_worker(item) for item in peer_workers)

    lines.extend(["", "## Recent Peer Outcomes"])
    if not peer_outcomes:
        lines.append("- No peer outcomes recorded yet.")
    else:
        for item in peer_outcomes:
            val_bpb = item.metrics.get("val_bpb")
            val_text = "n/a" if val_bpb is None else f"{float(val_bpb):.6f}"
            lines.append(f"- `{item.experiment_id}` [{item.status}] {item.title} val_bpb={val_text}")

    return "\n".join(lines) + "\n"


def refresh_manifest_state(
    manifest: FleetManifest,
    live_workers: list[WorkerStatus],
    brief: ResearchBrief,
) -> None:
    live_by_worker = {worker.worker_id: worker for worker in live_workers}
    for manifest_worker in manifest.workers:
        live_worker = live_by_worker.get(manifest_worker.worker_id)
        dispatched = hypotheses_for_worker(brief, manifest_worker.worker_id)
        if live_worker is not None and is_worker_active(live_worker):
            manifest_worker.current_run_id = live_worker.run_id
            manifest_worker.current_hypothesis_id = live_worker.hypothesis_id
            manifest_worker.current_title = live_worker.title
        elif dispatched:
            manifest_worker.current_run_id = None
            manifest_worker.current_hypothesis_id = dispatched[0].hypothesis_id
            manifest_worker.current_title = dispatched[0].title
        else:
            manifest_worker.current_run_id = None
            manifest_worker.current_hypothesis_id = None
            manifest_worker.current_title = None


def write_fleet_docs(
    manifest: FleetManifest,
    experiments: list[AggregateExperiment],
    workers: list[WorkerStatus],
    brief: ResearchBrief,
    registry: ToolRegistry,
) -> None:
    active_worker_ids = {worker.worker_id for worker in manifest.workers}
    for stale_path in WORKER_PROMPTS_DIR.glob("*.md"):
        if stale_path.stem not in active_worker_ids:
            stale_path.unlink(missing_ok=True)
    for stale_path in WORKER_ASSIGNMENTS_DIR.glob("*.md"):
        if stale_path.stem not in active_worker_ids:
            stale_path.unlink(missing_ok=True)

    write_text(FLEET_BRIEF_PATH, render_fleet_brief(experiments, workers, brief, registry))
    write_text(Path(manifest.observer_prompt_path), render_observer_start())
    write_text(Path(manifest.tool_builder_prompt_path), render_tool_builder_start())
    if manifest.main_prompt_path:
        write_text(Path(manifest.main_prompt_path), render_legacy_main_prompt())
    write_text(OBSERVER_PROTOCOL_PATH, render_observer_protocol(manifest))
    write_text(TOOL_BUILDER_PROTOCOL_PATH, render_tool_builder_protocol())
    write_text(GPU_WORKER_PROTOCOL_PATH, render_gpu_worker_protocol())
    write_text(
        OBSERVER_ASSIGNMENT_PATH,
        render_observer_assignment(manifest, workers, brief, registry),
    )
    write_text(TOOL_BUILDER_ASSIGNMENT_PATH, render_tool_builder_assignment(registry))

    for worker in manifest.workers:
        assignment_path = WORKER_ASSIGNMENTS_DIR / f"{worker.worker_id}.md"
        write_text(
            assignment_path,
            render_worker_assignment(worker, workers, experiments, brief),
        )
        write_text(Path(worker.prompt_path), render_worker_start(worker))


def sync_artifacts() -> dict[str, Any]:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    LIVE_WORKERS_DIR.mkdir(parents=True, exist_ok=True)
    AGGREGATE_DIR.mkdir(parents=True, exist_ok=True)
    FLEET_PROTOCOLS_DIR.mkdir(parents=True, exist_ok=True)
    WORKER_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    WORKER_ASSIGNMENTS_DIR.mkdir(parents=True, exist_ok=True)

    ensure_search_model()
    registry = ensure_registry()

    manifest = load_fleet_manifest()
    experiments = collect_experiments()
    live_workers = read_live_workers()
    workers = materialize_fleet_workers(manifest, live_workers)
    rows = planning_result_rows(experiments)
    write_results_tsv(rows)
    experiment_records = build_experiment_records(experiments)
    brief = build_research_brief(experiments)
    brief.save(BRIEF_PATH)

    write_json(EXPERIMENTS_PATH, {"experiments": [item.to_dict() for item in experiments]})
    write_jsonl(EXPERIMENTS_JSONL_PATH, [record.to_dict() for record in experiment_records])
    write_json(LEADERBOARD_PATH, build_leaderboard(experiments, workers, rows))
    render_progress(rows, PROGRESS_PNG_PATH)

    summary = {
        "generated_at": utc_now_iso(),
        "workers": [worker.to_dict() for worker in workers],
        "active_runs": [worker.run_id for worker in workers if is_worker_active(worker) and worker.run_id],
        "free_workers": [worker.worker_id for worker in workers if is_worker_dispatchable(worker)],
        "best_result": None,
        "paths": {
            "results_tsv": str(RESULTS_TSV_PATH),
            "experiments_jsonl": str(EXPERIMENTS_JSONL_PATH),
            "progress_png": str(PROGRESS_PNG_PATH),
            "aggregate_experiments": str(EXPERIMENTS_PATH),
            "research_brief": str(BRIEF_PATH),
            "observer_prompt": str(OBSERVER_PROMPT_PATH),
            "tool_builder_prompt": str(TOOL_BUILDER_PROMPT_PATH),
        },
    }
    best = best_result(rows)
    if best is not None:
        summary["best_result"] = asdict(best)
    write_json(LIVE_SUMMARY_PATH, summary)

    if manifest is not None:
        refresh_manifest_state(manifest, live_workers, brief)
        save_fleet_manifest(manifest)
        write_fleet_docs(manifest, experiments, workers, brief, registry)
    return summary


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
        observer_prompt_path=str(OBSERVER_PROMPT_PATH),
        tool_builder_prompt_path=str(TOOL_BUILDER_PROMPT_PATH),
        workers=workers,
        main_prompt_path=str(LEGACY_MAIN_AGENT_PROMPT_PATH),
    )
    save_fleet_manifest(manifest)
    sync_artifacts()
    return manifest


def print_status() -> None:
    summary = sync_artifacts()
    workers = [WorkerStatus.from_dict(payload) for payload in summary["workers"]]
    manifest = load_fleet_manifest()
    brief = load_existing_brief()
    print(f"Generated at: {summary['generated_at']}")
    if summary["best_result"] is not None:
        best = summary["best_result"]
        print(f"Best keep: {best['val_bpb']:.6f} @ {best['commit']} ({best['description']})")
    else:
        print("Best keep: none yet")
    if manifest is not None:
        print(f"Fleet tag: {manifest.tag} ({len(manifest.workers)} workers + observer + tool-builder)")
    if brief is not None:
        pending = sum(1 for item in brief.hypothesis_queue if item.status == "pending")
        dispatched = sum(1 for item in brief.hypothesis_queue if item.status == "dispatched")
        print(f"Hypotheses: {pending} pending, {dispatched} dispatched")
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
        workers = [WorkerStatus.from_dict(payload) for payload in summary["workers"]]
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


def import_warm_start(source_tsv: Path) -> dict[str, Any]:
    if not source_tsv.exists():
        raise FileNotFoundError(f"Warm-start source not found: {source_tsv}")

    rows = read_results_tsv(source_tsv)
    kept = [row for row in rows if row.status == "keep"]
    if not kept:
        raise ValueError(f"No kept results in {source_tsv}")

    best = min(kept, key=lambda r: r.val_bpb)

    source_dir = source_tsv.parent
    imported_config: dict[str, Any] | None = None
    run_root = source_dir / "research" / "runs"
    if run_root.exists():
        for run_dir in sorted(run_root.glob("exp-*")):
            cfg_path = run_dir / "config.json"
            meta_path = run_dir / "metadata.json"
            if not cfg_path.exists():
                continue
            meta = load_json(meta_path) or {}
            metrics = meta.get("metrics", {})
            if abs(float(metrics.get("val_bpb", 0)) - best.val_bpb) < 1e-4:
                imported_config = json.loads(cfg_path.read_text())
                break

    knowledge = KnowledgeBase.load(KNOWLEDGE_PATH, ROOT.name)
    knowledge.confirmed_findings.append(
        {
            "source": str(source_tsv),
            "imported_at": utc_now_iso(),
            "best_val_bpb": best.val_bpb,
            "best_description": best.description,
            "best_memory_gb": best.memory_gb,
            "total_experiments": len(rows),
            "kept_experiments": len(kept),
            "config": imported_config,
        }
    )

    descriptions = [r.description.lower() for r in kept]
    all_descriptions = " ".join(descriptions)
    proven: list[dict[str, Any]] = []
    if "batch" in all_descriptions and "131072" in all_descriptions:
        proven.append({"finding": "batch=131072 beats default 524288 at depth 9", "confidence": "high"})
    if "depth" in all_descriptions and ("9" in all_descriptions or "10" in all_descriptions):
        proven.append({"finding": "depth 9 substantially beats default depth 8", "confidence": "high"})
    if "embedding_lr" in all_descriptions:
        proven.append({"finding": "embedding_lr=0.8 beats default 0.6", "confidence": "medium"})
    if "warmdown" in all_descriptions:
        proven.append({"finding": "warmdown_ratio=0.85 beats default 0.5", "confidence": "medium"})
    if "weight_decay" in all_descriptions or "weight decay" in all_descriptions:
        proven.append({"finding": "weight_decay=0.1 beats default 0.2", "confidence": "medium"})
    for item in proven:
        item["source"] = str(source_tsv)
        item["imported_at"] = utc_now_iso()
        knowledge.tentative_findings.append(item)

    knowledge.save(KNOWLEDGE_PATH)

    return {
        "source": str(source_tsv),
        "best_val_bpb": best.val_bpb,
        "best_description": best.description,
        "total_imported": len(rows),
        "kept_imported": len(kept),
        "proven_findings": len(proven),
        "config_recovered": imported_config is not None,
    }


def check_data_ready() -> bool:
    data_dir = CACHE_DIR / "data"
    tok_dir = CACHE_DIR / "tokenizer"
    if not data_dir.exists() or not tok_dir.exists():
        return False
    shards = list(data_dir.glob("shard_*.parquet"))
    tok_files = list(tok_dir.glob("*"))
    return len(shards) > 0 and len(tok_files) > 0


def bootstrap(
    tag: str,
    gpus_arg: str | None,
    create_worktrees: bool,
    warm_start_source: Path | None,
) -> None:
    print("=" * 60)
    print("BOOTSTRAP: autoresearch setup")
    print("=" * 60)

    print("\n[1/4] Checking environment...")
    gpu_ids = get_gpu_ids(gpus_arg)
    print(f"  GPUs: {', '.join(gpu_ids)}")
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import torch; print(torch.cuda.is_available(), torch.cuda.device_count())"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        print(f"  CUDA: {result.stdout.strip()}")
    except Exception:
        print("  CUDA: check skipped (no torch or timeout)")

    print("\n[2/4] Checking data...")
    if check_data_ready():
        print("  Data and tokenizer already present.")
    else:
        print("  Running prepare.py (this may take a few minutes on first run)...")
        prep_result = subprocess.run([sys.executable, str(ROOT / "prepare.py")], cwd=ROOT)
        if prep_result.returncode != 0:
            print("  ERROR: prepare.py failed. Fix this before continuing.")
            return
        print("  Data preparation complete.")

    print("\n[3/4] Knowledge base...")
    if warm_start_source is not None:
        print(f"  Importing warm-start from {warm_start_source}...")
        info = import_warm_start(warm_start_source)
        print(f"  Imported {info['total_imported']} experiments ({info['kept_imported']} kept)")
        print(f"  Best known: {info['best_val_bpb']:.6f} ({info['best_description']})")
        print(f"  Proven findings seeded: {info['proven_findings']}")
    else:
        print("  No warm-start source. Starting fresh.")

    print(f"\n[4/4] Initializing fleet (tag={tag}, gpus={','.join(gpu_ids)})...")
    manifest = init_fleet(tag, gpus_arg, create_worktrees)
    sync_artifacts()
    print(f"  Fleet manifest: {FLEET_MANIFEST_PATH.relative_to(ROOT)}")
    print(f"  Observer prompt: {Path(manifest.observer_prompt_path).relative_to(ROOT)}")
    print(f"  Tool-builder prompt: {Path(manifest.tool_builder_prompt_path).relative_to(ROOT)}")
    for worker in manifest.workers:
        wt_status = "worktree ready" if Path(worker.worktree_path).exists() else "no worktree"
        print(f"  {worker.worker_id}: gpu={worker.gpu_id} ({wt_status})")

    print("\n" + "=" * 60)
    print("SETUP COMPLETE")
    print("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scientific orchestrator for CUDA autoresearch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("briefing", help="Generate research brief from repo state")
    subparsers.add_parser("sync", help="Rebuild aggregate artifacts from run logs")
    subparsers.add_parser("status", help="Show current live worker status")

    monitor_parser = subparsers.add_parser(
        "monitor", help="Continuously refresh shared state while workers are training"
    )
    monitor_parser.add_argument("--interval", type=float, default=5.0, help="Seconds between sync cycles")
    monitor_parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Optional number of sync cycles before exiting",
    )

    init_fleet_parser = subparsers.add_parser(
        "init-fleet", help="Create a multi-worker fleet manifest and optional git worktrees"
    )
    init_fleet_parser.add_argument("--tag", type=str, required=True, help="Run tag used to name worker branches")
    init_fleet_parser.add_argument("--gpus", type=str, default=None, help="Optional comma-separated GPU ids override")
    init_fleet_parser.add_argument(
        "--create-worktrees",
        action="store_true",
        help="Create git worktrees for each worker",
    )

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Single-command setup: env check, data prep, fleet init, optional warm-start",
    )
    bootstrap_parser.add_argument("--tag", type=str, required=True, help="Run tag for the fleet")
    bootstrap_parser.add_argument("--gpus", type=str, default=None, help="Comma-separated GPU ids")
    bootstrap_parser.add_argument("--create-worktrees", action="store_true", help="Create git worktrees")
    bootstrap_parser.add_argument(
        "--warm-start",
        type=Path,
        default=None,
        help="Path to a prior results.tsv to seed knowledge base from",
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
        brief = build_research_brief(collect_experiments())
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
        print(f"Observer prompt: {Path(manifest.observer_prompt_path).relative_to(ROOT)}")
        print(f"Tool-builder prompt: {Path(manifest.tool_builder_prompt_path).relative_to(ROOT)}")
        for worker in manifest.workers:
            print(f"{worker.worker_id}: {Path(worker.prompt_path).relative_to(ROOT)}")
        return

    if args.command == "bootstrap":
        bootstrap(
            tag=args.tag,
            gpus_arg=args.gpus,
            create_worktrees=args.create_worktrees,
            warm_start_source=args.warm_start,
        )
        return


if __name__ == "__main__":
    main()
