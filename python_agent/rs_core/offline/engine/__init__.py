from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rs_core.data.clients import ArtifactClient, DatasetClient
from rs_core.offline.contracts import (
    EvaluationJobContract,
    EvaluationResultContract,
    ExperimentRunContract,
    MetricReportContract,
    ModelArtifactContract,
    OfflineSimulationResultContract,
    ResourceEstimateContract,
    TrainingJobContract,
)

LOCAL_MEMORY_LIMIT_GB = 14.0
DEFAULT_SMOKE_MEMORY_GB = 1.0


@dataclass
class OfflineModelEngine:
    """Offline model boundary for training, evaluation, experiments and offline simulation."""

    dataset_client: DatasetClient = field(default_factory=DatasetClient)
    artifact_client: ArtifactClient = field(default_factory=ArtifactClient)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "engine": "OfflineModelEngine",
            "default_execution_mode": "dry_run_or_smoke",
            "heavy_jobs_default": "disabled",
        }

    def resource_estimate(
        self,
        job_type: str,
        *,
        estimated_memory_gb: float = DEFAULT_SMOKE_MEMORY_GB,
        heavy_job: bool = False,
    ) -> dict[str, Any]:
        return self._resource_estimate(job_type, estimated_memory_gb=estimated_memory_gb, heavy_job=heavy_job).to_dict()

    def start_training_job(
        self,
        job_id: str,
        config_path: str = "",
        model_family: str = "",
        *,
        execution_mode: str = "dry_run",
        estimated_memory_gb: float = DEFAULT_SMOKE_MEMORY_GB,
    ) -> dict[str, Any]:
        resource = self._resource_estimate(
            "training",
            estimated_memory_gb=estimated_memory_gb,
            heavy_job=execution_mode not in {"dry_run", "smoke"} or estimated_memory_gb > LOCAL_MEMORY_LIMIT_GB,
        )
        return TrainingJobContract(
            job_id=job_id,
            config_path=config_path,
            model_family=model_family,
            status="blocked_heavy_job" if resource.heavy_job else "dry_run_ready",
            execution_mode=execution_mode,
            resource_estimate=resource,
            metadata={"no_training_started": True},
        ).to_dict()

    def register_model_artifact(
        self,
        artifact_id: str,
        uri: str,
        model_family: str = "",
        *,
        metrics_ref: str = "",
    ) -> dict[str, Any]:
        artifact = ModelArtifactContract(
            artifact_id=artifact_id,
            uri=uri,
            model_family=model_family,
            metrics_ref=metrics_ref,
            metadata={"registered_by": "OfflineModelEngine"},
        )
        self.artifact_client.artifact(
            artifact.artifact_id,
            artifact.uri,
            kind="model",
            metadata={"model_family": model_family, "metrics_ref": metrics_ref},
        )
        return artifact.to_dict()

    def evaluation_job(
        self,
        eval_id: str,
        *,
        dataset_ref: str = "",
        model_artifact_id: str = "",
        execution_mode: str = "smoke",
        estimated_memory_gb: float = DEFAULT_SMOKE_MEMORY_GB,
    ) -> dict[str, Any]:
        return self._evaluation_job(
            eval_id,
            dataset_ref=dataset_ref,
            model_artifact_id=model_artifact_id,
            execution_mode=execution_mode,
            estimated_memory_gb=estimated_memory_gb,
        ).to_dict()

    def run_evaluation_smoke(
        self,
        eval_id: str = "offline-smoke",
        *,
        dataset_ref: str = "",
        model_artifact_id: str = "",
    ) -> dict[str, Any]:
        job = self._evaluation_job(eval_id, dataset_ref=dataset_ref, model_artifact_id=model_artifact_id)
        report = MetricReportContract(
            report_id=f"{eval_id}-report",
            metrics={"smoke_passed": 1.0},
            metadata={"public_safe": True, "no_full_eval": True},
        )
        return EvaluationResultContract(eval_id=eval_id, status="ok", report=report, job=job).to_dict()

    def experiment_smoke(self, experiment_id: str, *, route: str = "offline") -> dict[str, Any]:
        return ExperimentRunContract(
            experiment_id=experiment_id,
            route=route,
            status="smoke_planned",
            resource_estimate=self._resource_estimate("experiment"),
            metadata={"no_full_run": True},
        ).to_dict()

    def simulation_smoke(self, simulation_id: str, *, sample_count: int = 0) -> dict[str, Any]:
        return OfflineSimulationResultContract(
            simulation_id=simulation_id,
            sample_count=sample_count,
            metrics={"smoke_passed": 1.0},
            metadata={"offline_only": True, "public_serving_excluded": True},
        ).to_dict()

    def _evaluation_job(
        self,
        eval_id: str,
        *,
        dataset_ref: str = "",
        model_artifact_id: str = "",
        execution_mode: str = "smoke",
        estimated_memory_gb: float = DEFAULT_SMOKE_MEMORY_GB,
    ) -> EvaluationJobContract:
        resource = self._resource_estimate(
            "evaluation",
            estimated_memory_gb=estimated_memory_gb,
            heavy_job=execution_mode not in {"dry_run", "smoke"} or estimated_memory_gb > LOCAL_MEMORY_LIMIT_GB,
        )
        return EvaluationJobContract(
            eval_id=eval_id,
            dataset_ref=dataset_ref,
            model_artifact_id=model_artifact_id,
            execution_mode=execution_mode,
            resource_estimate=resource,
            metadata={"no_full_eval": True},
        )

    def _resource_estimate(
        self,
        job_type: str,
        *,
        estimated_memory_gb: float = DEFAULT_SMOKE_MEMORY_GB,
        heavy_job: bool = False,
    ) -> ResourceEstimateContract:
        is_heavy = heavy_job or estimated_memory_gb > LOCAL_MEMORY_LIMIT_GB
        return ResourceEstimateContract(
            job_type=job_type,
            estimated_memory_gb=estimated_memory_gb,
            max_local_memory_gb=LOCAL_MEMORY_LIMIT_GB,
            heavy_job=is_heavy,
            recommendation="remote_or_limited_smoke" if is_heavy else "local_smoke",
        )


__all__ = ["OfflineModelEngine"]
