import json
from pathlib import Path
from typing import Any

import pandas as pd

from backit.analytics import forecast_numeric
from backit.contracts import PredictionPlan
from backit.ledger import get_target, record_prediction
from backit.serialization import sha256_json


def _latest_snapshot(project: Path) -> tuple[str, Path]:
    manifests: list[tuple[str, dict[str, Any]]] = []
    for path in (project / "snapshots").glob("*-manifest.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        manifests.append((value["created_at"], value))
    if not manifests:
        raise ValueError("Project has no ingested snapshot")
    _, manifest = max(manifests, key=lambda item: item[0])
    return (
        manifest["snapshot_id"],
        project / "snapshots" / manifest["files"]["data"],
    )


def predict_project(
    project: Path,
    raw_plan: dict[str, Any],
    *,
    event_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    plan = PredictionPlan.model_validate(raw_plan)
    if set(plan.predictors) != set(plan.feature_available_columns):
        raise ValueError("Every predictor needs an availability column")
    target = get_target(project, event_id)
    if not set(plan.predictors).issubset(target["features"]):
        raise ValueError("Target event is missing required predictor values")

    snapshot_id, snapshot_path = _latest_snapshot(project)
    frame = pd.read_parquet(snapshot_path)
    forecast = forecast_numeric(
        frame,
        predictors=plan.predictors,
        outcome=plan.outcome,
        target_features={
            predictor: float(target["features"][predictor])
            for predictor in plan.predictors
        },
        target_feature_available_at={
            predictor: pd.Timestamp(target["feature_available_at"][predictor])
            for predictor in plan.predictors
        },
        data_cutoff=pd.Timestamp(plan.data_cutoff),
        feature_available_columns=plan.feature_available_columns,
        outcome_available_column=plan.outcome_available_column,
        historical_cutoff_column=plan.historical_cutoff_column,
    )
    prediction_id = sha256_json(
        {
            "target_event_id": event_id,
            "snapshot_id": snapshot_id,
            "plan": plan.model_dump(mode="json"),
        }
    )
    record = {
        "prediction_id": prediction_id,
        "target_event_id": event_id,
        "predicted_at": plan.predicted_at,
        "data_cutoff": plan.data_cutoff,
        "snapshot_id": snapshot_id,
        "plan_id": plan.plan_id,
        "method": forecast["method"],
        "prediction": forecast["prediction"],
        "baseline": forecast["baseline"],
        "candidate_metrics": forecast["candidate_metrics"],
        "training_count": forecast["training_count"],
        "training_row_ids": forecast["training_row_ids"],
        "interval_status": forecast["interval_status"],
    }
    return record_prediction(
        project,
        record,
        idempotency_key=idempotency_key,
    )
