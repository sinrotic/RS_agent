from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResourceEstimateContract:
    job_type: str
    estimated_memory_gb: float = 0.0
    max_local_memory_gb: float = 14.0
    heavy_job: bool = False
    recommendation: str = "local_smoke"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrainingJobContract:
    job_id: str
    config_path: str = ""
    model_family: str = ""
    status: str = "dry_run"
    execution_mode: str = "dry_run"
    resource_estimate: ResourceEstimateContract | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resource_estimate"] = self.resource_estimate.to_dict() if self.resource_estimate else None
        return payload


@dataclass(frozen=True)
class ModelArtifactContract:
    artifact_id: str
    uri: str
    model_family: str = ""
    metrics_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MetricReportContract:
    report_id: str
    metrics: dict[str, float] = field(default_factory=dict)
    path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvaluationJobContract:
    eval_id: str
    dataset_ref: str = ""
    model_artifact_id: str = ""
    execution_mode: str = "smoke"
    resource_estimate: ResourceEstimateContract | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resource_estimate"] = self.resource_estimate.to_dict() if self.resource_estimate else None
        return payload


@dataclass(frozen=True)
class EvaluationResultContract:
    eval_id: str
    status: str = "unknown"
    report: MetricReportContract | None = None
    job: EvaluationJobContract | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["report"] = self.report.to_dict() if self.report else None
        payload["job"] = self.job.to_dict() if self.job else None
        return payload


@dataclass(frozen=True)
class ExperimentRunContract:
    experiment_id: str
    route: str = "offline"
    status: str = "smoke_planned"
    resource_estimate: ResourceEstimateContract | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resource_estimate"] = self.resource_estimate.to_dict() if self.resource_estimate else None
        return payload


@dataclass(frozen=True)
class PromotionContract:
    route_name: str
    candidate_artifact_id: str
    decision: str = "hold"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OfflineSimulationResultContract:
    simulation_id: str
    sample_count: int = 0
    metrics: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ResourceEstimateContract",
    "TrainingJobContract",
    "ModelArtifactContract",
    "MetricReportContract",
    "EvaluationJobContract",
    "EvaluationResultContract",
    "ExperimentRunContract",
    "PromotionContract",
    "OfflineSimulationResultContract",
]
