from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _filter_kwargs(cls: type[Any], payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {item.name for item in fields(cls)}
    return {key: value for key, value in payload.items() if key in allowed}


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


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


@dataclass(slots=True)
class EmpiricalFinding:
    finding_id: str
    title: str
    evidence: str
    confidence: str
    mechanism: str
    implication: str


@dataclass(slots=True)
class Hypothesis:
    hypothesis_id: str
    title: str
    question: str
    why_now: str
    rationale: str
    intervention: dict[str, Any]
    expected_effect: dict[str, str]
    success_criteria: str
    alternative_explanations: list[str]
    follow_if_supported: list[str]
    follow_if_not_supported: list[str]
    confidence: str
    scientific_value: str
    family: str
    score: float = 0.0


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


@dataclass(slots=True)
class ExperimentPlan:
    experiment_id: str
    created_at: str
    phase: str
    based_on_commit: str
    hypothesis: Hypothesis
    config_path: str
    output_metadata_path: str
    run_command: str
    decision_rules: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        write_json(path, self.to_dict())


@dataclass(slots=True)
class ExperimentResult:
    experiment_id: str
    recorded_at: str
    status: str
    hypothesis_id: str
    metrics: dict[str, Any]
    matched_prediction: str
    analysis: str
    candidate_mechanisms: list[str]
    next_steps: list[str]
    contradiction_flags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        write_json(path, self.to_dict())


@dataclass(slots=True)
class RunIdentity:
    run_id: str
    worker_id: str
    node_id: str
    gpu_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunEvent:
    event_type: str
    recorded_at: str
    run_id: str
    worker_id: str
    node_id: str
    gpu_id: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


@dataclass(slots=True)
class AggregateExperiment:
    experiment_id: str
    status: str
    title: str
    commit: str
    worker_id: str
    gpu_id: str
    created_at: str
    recorded_at: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


@dataclass(slots=True)
class FleetManifest:
    tag: str
    created_at: str
    repository_root: str
    shared_research_dir: str
    main_prompt_path: str
    workers: list[FleetWorker] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "created_at": self.created_at,
            "repository_root": self.repository_root,
            "shared_research_dir": self.shared_research_dir,
            "main_prompt_path": self.main_prompt_path,
            "workers": [worker.to_dict() for worker in self.workers],
        }


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

    def save(self, path: str | Path) -> None:
        self.updated_at = utc_now_iso()
        write_json(path, asdict(self))


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(payload, indent=2, sort_keys=False, default=_json_default) + "\n"
    )


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
