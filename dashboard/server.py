"""
Dashboard server. Reads experiments.jsonl, serves API + SSE + static files.
Harness-agnostic: any tool that writes ExperimentRecord JSON lines works.
"""

import asyncio
import json
import subprocess
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

REPO_ROOT = Path(__file__).parent.parent
EXPERIMENTS_FILE = REPO_ROOT / "experiments.jsonl"

app = FastAPI(title="autoresearch dashboard")

# In-memory cache
_records: list[dict] = []
_subscribers: list[asyncio.Queue] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short_hash(h: str) -> str:
    """Normalize a git hash to 7 characters for consistent matching."""
    return h[:7] if h else ""


def _load_aggregate_hyperparams() -> dict[str, dict]:
    """Load hyperparameters from aggregate/experiments.json, keyed by experiment_id."""
    agg_path = REPO_ROOT / "research" / "aggregate" / "experiments.json"
    if not agg_path.exists():
        return {}
    try:
        data = json.loads(agg_path.read_text())
        result = {}
        for exp in data.get("experiments", []):
            hp = exp.get("config", {}).get("hyperparameters")
            if hp:
                result[exp["experiment_id"]] = hp
        return result
    except (json.JSONDecodeError, KeyError):
        return {}


def _enrich_record(record: dict, agg_hp: dict[str, dict]) -> None:
    """Enrich a record with data from metadata.json and aggregate hyperparams."""
    exp_id = record.get("id", "")
    run_dir = REPO_ROOT / "research" / "runs" / exp_id

    # Enrich metrics from metadata.json
    meta_path = run_dir / "metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            results = meta.get("results", {})
            # Fill zero metrics from metadata results
            metric_keys = [
                "num_steps", "training_seconds", "total_seconds",
                "mfu_percent", "total_tokens_M", "num_params_M",
            ]
            for key in metric_keys:
                if not record.get(key) and results.get(key):
                    record[key] = results[key]
            # peak_vram: metadata uses MB, record uses GB
            if not record.get("peak_vram_gb") and results.get("peak_vram_mb"):
                record["peak_vram_gb"] = results["peak_vram_mb"] / 1024
            # depth
            if not record.get("depth") and results.get("depth"):
                record["depth"] = results["depth"]
            # Attach hyperparameters
            if meta.get("hyperparameters"):
                record["hyperparameters"] = meta["hyperparameters"]
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback hyperparameters from aggregate
    if not record.get("hyperparameters") and exp_id in agg_hp:
        record["hyperparameters"] = agg_hp[exp_id]

    # Ensure hyperparameters key exists
    if "hyperparameters" not in record:
        record["hyperparameters"] = {}


def _load_records() -> list[dict]:
    """Load all experiment records from the JSONL file."""
    if not EXPERIMENTS_FILE.exists():
        return []
    records = []
    for line in EXPERIMENTS_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Normalize commit hashes to short form for consistent lineage matching
    for r in records:
        if r.get("commit"):
            r["commit"] = _short_hash(r["commit"])
        if r.get("parent_commit"):
            r["parent_commit"] = _short_hash(r["parent_commit"])

    # Enrich records with metadata
    agg_hp = _load_aggregate_hyperparams()
    for record in records:
        _enrich_record(record, agg_hp)

    records.sort(
        key=lambda item: (
            item.get("ordinal", 0),
            item.get("timestamp", ""),
            str(item.get("id", "")),
        )
    )
    return records


def _load_record(exp_id: str) -> dict | None:
    for record in _load_records():
        if str(record.get("id")) == exp_id:
            return record
    return None


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _relative_or_absolute(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _find_run_dir_for_commit(commit: str) -> tuple[Path, dict, dict] | None:
    if not commit:
        return None
    short = _short_hash(commit)
    runs_dir = REPO_ROOT / "research" / "runs"
    if not runs_dir.exists():
        return None
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        result = _read_json(run_dir / "result.json")
        metadata = _read_json(run_dir / "metadata.json")
        result_commit = result.get("commit") or metadata.get("runtime", {}).get("commit")
        if _short_hash(result_commit or "") == short:
            return run_dir, result, metadata
    return None


def _decision_markdown_for_record(record: dict) -> dict:
    inline_content = record.get("decision_markdown") or ""
    inline_path = record.get("decision_markdown_path") or ""
    if inline_content or inline_path:
        resolved_path = ""
        if inline_path:
            candidate = Path(inline_path)
            if not candidate.is_absolute():
                candidate = REPO_ROOT / candidate
            resolved_path = _relative_or_absolute(candidate)
            if not inline_content and candidate.exists():
                inline_content = candidate.read_text()
        return {
            "exists": bool(inline_content),
            "path": resolved_path,
            "content": inline_content,
            "commit": record.get("commit", ""),
        }

    commit = record.get("commit", "")
    match = _find_run_dir_for_commit(commit)
    if match is None:
        return {
            "exists": False,
            "path": "",
            "content": "",
            "commit": commit,
        }

    run_dir, result, metadata = match
    candidate_paths: list[Path] = []

    for payload in (result, metadata):
        for key in ("decision_md_path", "decision_markdown_path"):
            raw_path = payload.get(key)
            if not raw_path:
                continue
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = REPO_ROOT / candidate
            candidate_paths.append(candidate)

    candidate_paths.extend(
        [
            run_dir / "decision.md",
            run_dir / "scientific-decision.md",
            run_dir / "decision-note.md",
            REPO_ROOT / "research" / "plans" / f"{run_dir.name}.md",
        ]
    )

    seen: set[str] = set()
    for path in candidate_paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            return {
                "exists": True,
                "path": _relative_or_absolute(path),
                "content": path.read_text(),
                "commit": commit,
                "run_id": run_dir.name,
            }

    fallback = candidate_paths[0] if candidate_paths else run_dir / "decision.md"
    return {
        "exists": False,
        "path": _relative_or_absolute(fallback),
        "content": "",
        "commit": commit,
        "run_id": run_dir.name,
    }


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    global _records
    _records = _load_records()
    asyncio.create_task(_tail_experiments())


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------

@app.get("/stream")
async def stream(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _subscribers.append(q)

    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield {"data": json.dumps(event)}
                except asyncio.TimeoutError:
                    yield {"comment": "keepalive"}
        finally:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass

    return EventSourceResponse(generator())


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------

@app.get("/api/experiments")
async def list_experiments():
    return _records


@app.get("/api/experiments/{exp_id}")
async def get_experiment(exp_id: str):
    for r in _records:
        if str(r.get("id")) == exp_id:
            return r
    return JSONResponse(status_code=404, content={"error": "not found"})


@app.get("/api/experiments/{exp_id}/diff")
async def get_diff(exp_id: str):
    """Return unified diff between parent_commit and commit for an experiment."""
    for r in _records:
        if str(r.get("id")) != exp_id:
            continue
        commit = r.get("commit", "")
        parent = r.get("parent_commit", "")
        if not commit or not parent:
            return {"diff": ""}
        try:
            result = subprocess.run(
                ["git", "diff", parent, commit, "--", "train.py"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=REPO_ROOT,
            )
        except Exception:
            return {"diff": ""}
        return {"diff": result.stdout or ""}
    return JSONResponse(status_code=404, content={"error": "not found"})


@app.get("/api/experiments/{exp_id}/decision-md")
async def get_decision_markdown(exp_id: str):
    record = _load_record(exp_id)
    if record is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return _decision_markdown_for_record(record)


# ---------------------------------------------------------------------------
# Karpathy comparison endpoints
# ---------------------------------------------------------------------------

@app.get("/api/karpathy-comparison")
def get_karpathy_comparison():
    csv_path = REPO_ROOT / "research" / "karpathy_comparison.csv"
    if not csv_path.exists():
        return []
    rows = []
    for line in csv_path.read_text().splitlines()[1:]:  # skip header
        parts = line.strip().split(",")
        if len(parts) < 4:
            continue
        rows.append({
            "experiment": parts[0],
            "karpathy_bpb": float(parts[1]),
            "our_bpb": float(parts[2]),
            "delta": parts[3],
        })
    return rows


@app.get("/api/karpathy-original")
def get_karpathy_original():
    tsv_path = REPO_ROOT / "research" / "karpathy_original_results.tsv"
    if not tsv_path.exists():
        return []
    rows = []
    best = float("inf")
    for line in tsv_path.read_text().splitlines()[1:]:  # skip header
        parts = line.strip().split("\t")
        if len(parts) < 5:
            continue
        try:
            bpb = float(parts[1])
        except ValueError:
            continue
        if bpb <= 0:
            continue
        status = parts[3]
        if status == "keep" and bpb < best:
            best = bpb
        rows.append({
            "commit": parts[0],
            "val_bpb": bpb,
            "memory_gb": float(parts[2]) if parts[2] else 0,
            "status": status,
            "description": parts[4] if len(parts) > 4 else "",
            "best_so_far": min(best, bpb) if best < float("inf") else bpb,
        })
    return rows


# ---------------------------------------------------------------------------
# Research data API
# ---------------------------------------------------------------------------

RESEARCH_DIR = REPO_ROOT / "research"


@app.get("/api/research/brief")
async def research_brief():
    return _read_json(RESEARCH_DIR / "research_brief.json") or {}


@app.get("/api/research/leaderboard")
async def research_leaderboard():
    return _read_json(RESEARCH_DIR / "aggregate" / "leaderboard.json") or {}


@app.get("/api/research/run/{exp_id}")
async def research_run(exp_id: str):
    """Return merged run data: result.json + config.json + plan JSON + plan markdown."""
    run_dir = RESEARCH_DIR / "runs" / exp_id
    plans_dir = RESEARCH_DIR / "plans"
    out: dict = {"experiment_id": exp_id}

    if run_dir.is_dir():
        out["result"] = _read_json(run_dir / "result.json")
        out["config"] = _read_json(run_dir / "config.json")
        out["metadata"] = _read_json(run_dir / "metadata.json")

    plan_json = plans_dir / f"{exp_id}.json"
    if plan_json.exists():
        out["plan"] = _read_json(plan_json)

    plan_md = plans_dir / f"{exp_id}.md"
    if plan_md.exists():
        out["plan_markdown"] = plan_md.read_text()

    return out


@app.get("/api/research/top")
async def research_top():
    """Return the top 10 experiments by val_bpb with their hypotheses."""
    records = _load_records()
    kept = [r for r in records if r.get("status") == "keep"]
    kept.sort(key=lambda r: r.get("val_bpb", float("inf")))
    top = kept[:10]

    results = []
    plans_dir = RESEARCH_DIR / "plans"
    for r in top:
        exp_id = str(r.get("id", ""))
        plan = _read_json(plans_dir / f"{exp_id}.json")
        hypothesis = plan.get("hypothesis", {})
        run_result = _read_json(RESEARCH_DIR / "runs" / exp_id / "result.json")
        results.append({
            "id": exp_id,
            "val_bpb": r.get("val_bpb"),
            "delta": r.get("delta"),
            "description": r.get("description", ""),
            "status": r.get("status"),
            "commit": r.get("commit", ""),
            "hypothesis_title": hypothesis.get("title", ""),
            "hypothesis_rationale": hypothesis.get("rationale", ""),
            "prediction": hypothesis.get("prediction", ""),
            "changes_from_baseline": run_result.get("changes_from_baseline", {}),
            "num_steps": r.get("num_steps", 0),
            "training_seconds": r.get("training_seconds", 0),
            "mfu_percent": r.get("mfu_percent", 0),
            "peak_vram_gb": r.get("peak_vram_gb", 0),
        })
    return results


@app.get("/api/research/lineage")
async def research_lineage():
    """Infer experiment-to-experiment lineage.

    Strategy:
    1. Parse description/title for explicit 'exp-NNN' references.
    2. For experiments without an explicit parent, assign the most recent
       'keep' experiment with a lower ordinal as the parent (representing
       the best-known config they branched from).
    """
    import re

    records = _load_records()
    runs_dir = RESEARCH_DIR / "runs"
    ids = {str(r.get("id", "")) for r in records}
    id_list = [str(r.get("id", "")) for r in records]

    edges: list[dict] = []
    assigned: set[str] = set()

    # Pass 1: explicit references from descriptions/titles
    for r in records:
        exp_id = str(r.get("id", ""))
        desc = r.get("description", "") or ""

        # Also check result.json title
        result = _read_json(runs_dir / exp_id / "result.json")
        title = result.get("title", "") or result.get("description", "") or ""
        text = title or desc

        own_match = re.match(r"exp-(\d+)", exp_id)
        own_prefix = own_match.group(0) if own_match else ""

        refs = re.findall(r"exp-(\d+)", text)
        parent_id = None
        for ref_num in refs:
            ref_prefix = f"exp-{ref_num}"
            if ref_prefix == own_prefix:
                continue
            for eid in ids:
                if eid.startswith(ref_prefix + "-") or eid == ref_prefix:
                    parent_id = eid
                    break
            if parent_id:
                break

        if parent_id:
            edges.append({"from": parent_id, "to": exp_id, "type": "explicit"})
            assigned.add(exp_id)

    # Pass 2: for unassigned experiments, link to the most recent prior 'keep'
    # Only link within the same experiment family (exp-* to exp-*, karpathy-* to karpathy-*)
    # Skip benchmark/comparison experiments — they aren't part of the research lineage
    def _family(eid: str) -> str:
        return eid.split("-")[0] if "-" in eid else eid

    benchmark_ids: set[str] = set()
    for r in records:
        desc = (r.get("description", "") or "").lower()
        if "benchmark" in desc or "upstream" in desc:
            benchmark_ids.add(str(r.get("id", "")))

    keep_ids = [
        str(r.get("id", ""))
        for r in records
        if r.get("status") == "keep" and str(r.get("id", "")) not in benchmark_ids
    ]
    for i, exp_id in enumerate(id_list):
        if exp_id in assigned or exp_id in benchmark_ids:
            continue
        fam = _family(exp_id)
        prior_keep = None
        for kid in keep_ids:
            if _family(kid) == fam and id_list.index(kid) < i:
                prior_keep = kid
        if prior_keep and prior_keep != exp_id:
            edges.append({"from": prior_keep, "to": exp_id, "type": "inferred"})

    return edges


@app.get("/api/research/config-diff/{exp_id}")
async def research_config_diff(exp_id: str):
    """Diff the config of exp_id against its lineage parent's config."""
    runs_dir = RESEARCH_DIR / "runs"

    child_cfg = _read_json(runs_dir / exp_id / "config.json")
    child_hp = child_cfg.get("hyperparameters", {})
    if not child_hp:
        return {"has_diff": False, "reason": "no config for this experiment"}

    # Find parent from lineage (same logic as lineage endpoint)
    import re
    records = _load_records()
    id_list = [str(r.get("id", "")) for r in records]
    ids = set(id_list)

    # Try explicit parent from description
    record = None
    for r in records:
        if str(r.get("id", "")) == exp_id:
            record = r
            break
    if not record:
        return {"has_diff": False, "reason": "experiment not found"}

    result = _read_json(runs_dir / exp_id / "result.json")
    text = result.get("title", "") or result.get("description", "") or record.get("description", "")
    own_match = re.match(r"exp-(\d+)", exp_id)
    own_prefix = own_match.group(0) if own_match else ""

    parent_id = None
    for ref_num in re.findall(r"exp-(\d+)", text):
        ref_prefix = f"exp-{ref_num}"
        if ref_prefix == own_prefix:
            continue
        for eid in ids:
            if eid.startswith(ref_prefix + "-") or eid == ref_prefix:
                parent_id = eid
                break
        if parent_id:
            break

    # Fallback to most recent prior keep
    if not parent_id:
        def _family(eid: str) -> str:
            return eid.split("-")[0] if "-" in eid else eid
        fam = _family(exp_id)
        keep_ids = [str(r.get("id", "")) for r in records if r.get("status") == "keep"]
        idx = id_list.index(exp_id) if exp_id in id_list else -1
        for kid in keep_ids:
            if _family(kid) == fam and id_list.index(kid) < idx:
                parent_id = kid

    if not parent_id:
        return {"has_diff": False, "reason": "no parent found"}

    parent_cfg = _read_json(runs_dir / parent_id / "config.json")
    parent_hp = parent_cfg.get("hyperparameters", {})

    if not parent_hp:
        # Use baseline config
        baseline_cfg = _read_json(runs_dir / "exp-000-baseline" / "config.json")
        parent_hp = baseline_cfg.get("hyperparameters", {})
        parent_id = "exp-000-baseline"

    if not parent_hp:
        return {"has_diff": False, "reason": "no parent config"}

    all_keys = sorted(set(list(child_hp.keys()) + list(parent_hp.keys())))
    diff = []
    for k in all_keys:
        if k == "base_experiment":
            continue
        old = parent_hp.get(k)
        new = child_hp.get(k)
        if str(old) != str(new):
            diff.append({"key": k, "old": old, "new": new})

    return {
        "has_diff": len(diff) > 0,
        "parent_id": parent_id,
        "child_id": exp_id,
        "changes": diff,
        "parent_config": parent_hp,
        "child_config": child_hp,
    }


@app.get("/api/research/strategies")
async def research_strategies():
    """Analyze which hyperparameter changes led to keeps vs discards."""
    records = _load_records()
    plans_dir = RESEARCH_DIR / "plans"
    runs_dir = RESEARCH_DIR / "runs"

    categories: dict[str, dict] = {}

    for r in records:
        exp_id = str(r.get("id", ""))
        status = r.get("status", "")
        run_result = _read_json(runs_dir / exp_id / "result.json")
        changes = run_result.get("changes_from_baseline", {})
        if not changes:
            continue

        changed_params = {
            k for k in changes
            if k != "base_experiment" and not k.startswith("_")
        }

        for param in changed_params:
            if param not in categories:
                categories[param] = {"kept": 0, "discarded": 0, "crashed": 0, "total": 0}
            categories[param]["total"] += 1
            if status == "keep":
                categories[param]["kept"] += 1
            elif status == "crash":
                categories[param]["crashed"] += 1
            else:
                categories[param]["discarded"] += 1

    result = [
        {"param": k, **v, "keep_rate": round(v["kept"] / v["total"], 3) if v["total"] > 0 else 0}
        for k, v in sorted(categories.items(), key=lambda x: -x[1]["total"])
    ]
    return result


# ---------------------------------------------------------------------------
# File tailer — watches experiments.jsonl for new records
# ---------------------------------------------------------------------------

async def _tail_experiments():
    """Tail experiments.jsonl for new records, push to SSE subscribers."""
    pos = EXPERIMENTS_FILE.stat().st_size if EXPERIMENTS_FILE.exists() else 0

    while True:
        await asyncio.sleep(1.0)
        if not EXPERIMENTS_FILE.exists():
            continue

        size = EXPERIMENTS_FILE.stat().st_size
        if size <= pos:
            if size < pos:
                pos = 0  # file was truncated
            continue

        try:
            with open(EXPERIMENTS_FILE) as f:
                f.seek(pos)
                new_data = f.read()
                pos = f.tell()

            for line in new_data.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                _records.append(record)
                event = {"type": "new_experiment", **record}
                for q in list(_subscribers):
                    try:
                        q.put_nowait(event)
                    except asyncio.QueueFull:
                        pass

        except Exception as e:
            print(f"[server] error tailing experiments.jsonl: {e}")


# ---------------------------------------------------------------------------
# Static files (Svelte build) — must be last so it doesn't shadow API routes
# ---------------------------------------------------------------------------

_dist = Path(__file__).parent / "frontend" / "build"
if _dist.exists():
    from fastapi.responses import FileResponse

    app.mount("/_app", StaticFiles(directory=str(_dist / "_app")), name="static-app")

    _fallback = _dist / "index.html"

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """Serve static files if they exist, otherwise fall back to index.html for SPA routing."""
        candidate = _dist / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_fallback)
