"""
Unified schema for autoresearch fleet orchestration.

All dataclasses, JSON/JSONL helpers, and git utilities live here.
The orchestrator imports exclusively from this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _filter_kwargs(cls: type[Any], payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {item.name for item in fields(cls)}
    return {key: value for key, value in payload.items() if key in allowed}


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=False, default=_json_default) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")
    closed = False
    try:
        os.write(fd, content.encode())
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.replace(tmp_path, file_path)
    except BaseException:
        if not closed:
            os.close(fd)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(row, sort_keys=False, default=_json_default) + "\n" for row in rows
    )
    fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")
    closed = False
    try:
        os.write(fd, content.encode())
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.replace(tmp_path, file_path)
    except BaseException:
        if not closed:
            os.close(fd)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def append_jsonl(path: str | Path, payload: dict[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a") as handle:
        handle.write(json.dumps(payload, sort_keys=False, default=_json_default) + "\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    rows = []
    with file_path.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git_short_hash() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()
    except Exception:
        return "nogit"


def git_diff_stat() -> str:
    try:
        r = subprocess.run(
            ["git", "diff", "--stat", "HEAD~1"],
            capture_output=True, text=True, check=True,
        )
        lines = r.stdout.strip().splitlines()
        return lines[-1].strip() if lines else ""
    except Exception:
        return ""


def git_diff_hash() -> str:
    try:
        r = subprocess.run(
            ["git", "diff", "HEAD~1"],
            capture_output=True, text=True, check=True,
        )
        return hashlib.sha1(r.stdout.encode()).hexdigest()[:7]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Experiment config and results
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ExperimentConfig:
    aspect_ratio: int = 64
    head_dim: int = 128
    window_pattern: str = "SSSL"
    total_batch_size: int = 2**19
    embedding_lr: float = 0.6
    unembedding_lr: float = 0.004
    matrix_lr: float = 0.04
    scalar_lr: float = 0.5
    weight_decay: float = 0.2
    adam_betas: tuple[float, float] = (0.8, 0.95)
    warmup_ratio: float = 0.0
    warmdown_ratio: float = 0.5
    final_lr_frac: float = 0.0
    depth: int = 8
    device_batch_size: int = 128
    final_eval_batch_size: int = 128
    startup_exclude_steps: int = 10
    notes: str = "default"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExperimentConfig":
        cleaned = _filter_kwargs(cls, payload)
        if "adam_betas" in cleaned:
            cleaned["adam_betas"] = tuple(cleaned["adam_betas"])
        return cls(**cleaned)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "ExperimentConfig":
        data = json.loads(Path(path).read_text())
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        write_json(path, self.to_dict())


@dataclass(slots=True)
class ResultRow:
    commit: str
    val_bpb: float
    memory_gb: float
    status: str
    description: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResultRow":
        return cls(**_filter_kwargs(cls, payload))


@dataclass(slots=True)
class ExperimentRecord:
    """Full record for one experiment run (JSONL storage)."""
    # Identity
    id: int
    commit: str
    parent_commit: str
    timestamp: str
    status: str
    description: str
    # Result
    val_bpb: float
    delta: float
    # Efficiency
    num_steps: int
    training_seconds: float
    total_seconds: float
    mfu_percent: float
    total_tokens_M: float
    # Resources
    peak_vram_gb: float
    num_params_M: float
    depth: int
    # Decision/source metadata
    execution_status: str = ""
    decision_status: str = ""
    # Convergence (optional)
    train_bpb: float | None = None
    bpb_at_checkpoints: list[float] = field(default_factory=list)
    still_improving: bool | None = None
    improvement_rate: float = 0.0
    tokens_per_second: int | None = None
    # Diff (optional)
    diff_stat: str = ""
    diff_hash: str = ""
    decision_markdown_path: str = ""
    decision_markdown: str = ""
    # Platform and config (optional)
    gpu_name: str = ""
    model_dim: int = 0
    n_heads: int = 0
    head_dim: int = 0
    window_pattern: str = ""
    total_batch_size: int = 0
    device_batch_size: int = 0
    matrix_lr: float = 0.0
    embedding_lr: float = 0.0
    weight_decay: float = 0.0
    warmdown_ratio: float = 0.0
    adam_betas: list[float] = field(default_factory=list)
    # Fleet/context metadata (optional)
    worker_id: str = ""
    gpu_id: str = ""
    hypothesis_id: str = ""
    rationale: str = ""
    outcome: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExperimentRecord":
        cleaned = _filter_kwargs(cls, payload)
        if "adam_betas" in cleaned:
            cleaned["adam_betas"] = list(cleaned["adam_betas"])
        if "bpb_at_checkpoints" in cleaned:
            cleaned["bpb_at_checkpoints"] = list(cleaned["bpb_at_checkpoints"])
        return cls(**cleaned)

    def to_row(self) -> str:
        return "\t".join([
            self.commit,
            f"{self.val_bpb:.6f}",
            f"{self.peak_vram_gb:.1f}",
            self.status,
            self.description,
        ])


def dump_record(record: ExperimentRecord, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(record.to_json() + "\n")


def load_records(path: str | Path) -> list[ExperimentRecord]:
    p = Path(path)
    if not p.exists():
        return []
    records = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            records.append(ExperimentRecord.from_dict(json.loads(line)))
    return records


def next_id(path: str | Path) -> int:
    records = load_records(path)
    return max((r.id for r in records), default=0) + 1


def current_best(path: str | Path) -> float:
    records = load_records(path)
    kept = [r.val_bpb for r in records if r.status == "keep"]
    return min(kept) if kept else float("inf")


# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Hypothesis:
    """One proposed experiment for the observer to dispatch."""
    hypothesis_id: str
    title: str
    rationale: str
    config_overrides: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    status: str = "pending"  # pending | dispatched | completed | abandoned
    assigned_worker: str | None = None
    outcome: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Hypothesis":
        return cls(**_filter_kwargs(cls, payload))


# ---------------------------------------------------------------------------
# Research brief and findings
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class EmpiricalFinding:
    finding_id: str
    title: str
    evidence: str
    confidence: str
    mechanism: str
    implication: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EmpiricalFinding":
        return cls(**_filter_kwargs(cls, payload))


@dataclass(slots=True)
class ResearchBrief:
    generated_at: str
    repository: str
    objective: str
    constraints: list[str]
    current_config: dict[str, Any]
    best_result: dict[str, Any]
    findings: list[EmpiricalFinding]
    open_questions: list[str]
    hypothesis_queue: list[Hypothesis]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        write_json(path, self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchBrief":
        cleaned = _filter_kwargs(cls, payload)
        cleaned["findings"] = [
            EmpiricalFinding.from_dict(item) for item in payload.get("findings", [])
        ]
        cleaned["hypothesis_queue"] = [
            Hypothesis.from_dict(item) for item in payload.get("hypothesis_queue", [])
        ]
        cleaned.setdefault("notes", list(payload.get("notes", [])))
        return cls(**cleaned)


# ---------------------------------------------------------------------------
# Fleet: workers, manifest, status
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class WorkerStatus:
    worker_id: str
    node_id: str
    gpu_id: str
    run_id: str | None
    state: str
    updated_at: str
    pid: int | None = None
    heartbeat_age_seconds: float | None = None
    commit: str | None = None
    hypothesis_id: str | None = None
    title: str | None = None
    notes: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)
    paths: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkerStatus":
        return cls(**_filter_kwargs(cls, payload))


@dataclass(slots=True)
class AggregateExperiment:
    experiment_id: str
    status: str
    title: str
    commit: str
    worker_id: str
    gpu_id: str
    created_at: str
    parent_commit: str = ""
    execution_status: str = ""
    decision_status: str = ""
    recorded_at: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    hypothesis_id: str = ""
    rationale: str = ""
    outcome: str = ""
    decision_markdown_path: str = ""
    decision_markdown: str = ""
    gpu_name: str = ""
    diff_stat: str = ""
    diff_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AggregateExperiment":
        return cls(**_filter_kwargs(cls, payload))


@dataclass(slots=True)
class FleetWorker:
    worker_id: str
    gpu_id: str
    branch: str
    worktree_path: str
    prompt_path: str
    current_run_id: str | None = None
    current_hypothesis_id: str | None = None
    current_title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FleetWorker":
        return cls(**_filter_kwargs(cls, payload))


@dataclass(slots=True)
class FleetManifest:
    tag: str
    created_at: str
    repository_root: str
    shared_research_dir: str
    observer_prompt_path: str
    tool_builder_prompt_path: str
    workers: list[FleetWorker] = field(default_factory=list)
    main_prompt_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "tag": self.tag,
            "created_at": self.created_at,
            "repository_root": self.repository_root,
            "shared_research_dir": self.shared_research_dir,
            "observer_prompt_path": self.observer_prompt_path,
            "tool_builder_prompt_path": self.tool_builder_prompt_path,
            "workers": [worker.to_dict() for worker in self.workers],
        }
        if self.main_prompt_path:
            payload["main_prompt_path"] = self.main_prompt_path
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FleetManifest":
        observer_prompt_path = (
            payload.get("observer_prompt_path") or payload.get("main_prompt_path") or ""
        )
        tool_builder_prompt_path = payload.get("tool_builder_prompt_path") or ""
        main_prompt_path = payload.get("main_prompt_path") or observer_prompt_path
        return cls(
            tag=payload["tag"],
            created_at=payload["created_at"],
            repository_root=payload["repository_root"],
            shared_research_dir=payload["shared_research_dir"],
            observer_prompt_path=observer_prompt_path,
            tool_builder_prompt_path=tool_builder_prompt_path,
            workers=[FleetWorker.from_dict(item) for item in payload.get("workers", [])],
            main_prompt_path=main_prompt_path,
        )


# ---------------------------------------------------------------------------
# Tool registry (minimal)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ToolEntry:
    """One tool in the shared tool registry."""
    tool_id: str
    title: str
    status: str  # requested | published | adopted | discarded
    requested_at: str
    requested_by: str = ""
    problem: str = ""
    path: str | None = None
    summary: str = ""
    usage: str = ""
    decided_at: str | None = None
    decided_by: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ToolEntry":
        return cls(**_filter_kwargs(cls, payload))


@dataclass(slots=True)
class ToolRegistry:
    updated_at: str
    shared_tools_dir: str
    tools: list[ToolEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "updated_at": self.updated_at,
            "shared_tools_dir": self.shared_tools_dir,
            "tools": [tool.to_dict() for tool in self.tools],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ToolRegistry":
        return cls(
            updated_at=payload.get("updated_at") or utc_now_iso(),
            shared_tools_dir=payload.get("shared_tools_dir", ""),
            tools=[ToolEntry.from_dict(item) for item in payload.get("tools", [])],
        )

    @classmethod
    def load(cls, path: str | Path, shared_tools_dir: str | Path) -> "ToolRegistry":
        file_path = Path(path)
        if not file_path.exists():
            return cls(
                updated_at=utc_now_iso(),
                shared_tools_dir=str(shared_tools_dir),
            )
        payload = json.loads(file_path.read_text())
        registry = cls.from_dict(payload)
        if not registry.shared_tools_dir:
            registry.shared_tools_dir = str(shared_tools_dir)
        return registry

    def save(self, path: str | Path) -> None:
        self.updated_at = utc_now_iso()
        write_json(path, self.to_dict())


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class KnowledgeBase:
    updated_at: str
    repository: str
    confirmed_findings: list[dict[str, Any]] = field(default_factory=list)
    tentative_findings: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    invalid_regions: list[dict[str, Any]] = field(default_factory=list)
    experiment_history: list[dict[str, Any]] = field(default_factory=list)
    meta_research: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path, repository: str) -> "KnowledgeBase":
        file_path = Path(path)
        if not file_path.exists():
            return cls(updated_at=utc_now_iso(), repository=repository)
        payload = json.loads(file_path.read_text())
        return cls(**_filter_kwargs(cls, payload))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "KnowledgeBase":
        return cls(**_filter_kwargs(cls, payload))

    def save(self, path: str | Path) -> None:
        self.updated_at = utc_now_iso()
        write_json(path, asdict(self))
