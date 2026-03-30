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


def _load_records() -> list[dict]:
    """Load all experiment records from the JSONL file."""
    if not EXPERIMENTS_FILE.exists():
        return []
    records = []
    for line in EXPERIMENTS_FILE.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


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
async def get_experiment(exp_id: int):
    for r in _records:
        if r.get("id") == exp_id:
            return r
    return JSONResponse(status_code=404, content={"error": "not found"})


@app.get("/api/experiments/{exp_id}/diff")
async def get_diff(exp_id: int):
    """Return unified diff between parent_commit and commit for an experiment."""
    for r in _records:
        if r.get("id") == exp_id:
            commit = r.get("commit", "")
            parent = r.get("parent_commit", "")
            if commit and parent:
                try:
                    result = subprocess.run(
                        ["git", "diff", parent, commit, "--", "train.py"],
                        capture_output=True, text=True, timeout=5,
                        cwd=REPO_ROOT,
                    )
                    return {"diff": result.stdout or ""}
                except Exception:
                    return {"diff": ""}
            return {"diff": ""}
    return JSONResponse(status_code=404, content={"error": "not found"})


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
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
