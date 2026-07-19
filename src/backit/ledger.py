from datetime import datetime
import math
import os
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

import portalocker

from backit.serialization import canonical_json, sha256_json


def _aware_datetime(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.isoformat()


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                import json

                record = json.loads(line)
            except Exception as error:
                raise ValueError(f"Corrupt ledger line {line_number}: {path}") from error
            records.append(record)
    return records


def _replace_ledger(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"".join(canonical_json(record) + b"\n" for record in records)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-",
        dir=path.parent,
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _append(
    project: Path,
    ledger_name: str,
    record: dict[str, Any],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    if not idempotency_key:
        raise ValueError("idempotency_key is required")
    path = project / "ledger" / ledger_name
    lock_path = project / ".backit.lock"
    with portalocker.Lock(lock_path, timeout=0):
        records = _read_ledger(path)
        for existing in records:
            if existing["idempotency_key"] == idempotency_key:
                return existing
        stored = {
            **record,
            "transaction_id": str(uuid4()),
            "idempotency_key": idempotency_key,
        }
        stored["record_hash"] = sha256_json(stored)
        _replace_ledger(path, [*records, stored])
        return stored


def record_target(
    project: Path,
    record: dict[str, Any],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    required = {
        "target_event_id",
        "target_at",
        "features",
        "feature_available_at",
    }
    missing = required - record.keys()
    if missing:
        raise ValueError(f"Missing target fields: {sorted(missing)}")
    if set(record["features"]) != set(record["feature_available_at"]):
        raise ValueError("Every target feature needs an available_at value")
    normalized = {
        **record,
        "target_at": _aware_datetime(record["target_at"], "target_at"),
        "feature_available_at": {
            key: _aware_datetime(value, f"feature_available_at.{key}")
            for key, value in record["feature_available_at"].items()
        },
    }
    existing = _read_ledger(project / "ledger" / "targets.jsonl")
    for target in existing:
        if (
            target["target_event_id"] == record["target_event_id"]
            and target["idempotency_key"] != idempotency_key
        ):
            raise ValueError("target_event_id already exists")
    return _append(
        project,
        "targets.jsonl",
        normalized,
        idempotency_key=idempotency_key,
    )


def record_prediction(
    project: Path,
    record: dict[str, Any],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    target_ids = {
        target["target_event_id"]
        for target in _read_ledger(project / "ledger" / "targets.jsonl")
    }
    if record.get("target_event_id") not in target_ids:
        raise ValueError("Prediction references an unknown target event")
    normalized = {
        **record,
        "predicted_at": _aware_datetime(record["predicted_at"], "predicted_at"),
        "data_cutoff": _aware_datetime(record["data_cutoff"], "data_cutoff"),
        "prediction": float(record["prediction"]),
    }
    return _append(
        project,
        "predictions.jsonl",
        normalized,
        idempotency_key=idempotency_key,
    )


def record_outcome(
    project: Path,
    record: dict[str, Any],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    target_ids = {
        target["target_event_id"]
        for target in _read_ledger(project / "ledger" / "targets.jsonl")
    }
    if record.get("target_event_id") not in target_ids:
        raise ValueError("Outcome references an unknown target event")
    existing_outcomes = _read_ledger(project / "ledger" / "outcomes.jsonl")
    for existing in existing_outcomes:
        if existing["idempotency_key"] == idempotency_key:
            return existing
        if existing["outcome_id"] == record.get("outcome_id"):
            raise ValueError("outcome_id already exists")
    event_outcomes = [
        outcome
        for outcome in existing_outcomes
        if outcome["target_event_id"] == record["target_event_id"]
    ]
    supersedes = record.get("supersedes_outcome_id")
    if event_outcomes:
        superseded_ids = {
            outcome.get("supersedes_outcome_id")
            for outcome in event_outcomes
            if outcome.get("supersedes_outcome_id")
        }
        active = [
            outcome
            for outcome in event_outcomes
            if outcome["outcome_id"] not in superseded_ids
        ]
        if len(active) != 1:
            raise ValueError("Outcome correction chain is ambiguous")
        if supersedes != active[0]["outcome_id"]:
            raise ValueError("Correction must supersede the current active outcome")
    elif supersedes is not None:
        raise ValueError("First outcome cannot supersede another outcome")
    normalized = {
        **record,
        "recorded_at": _aware_datetime(record["recorded_at"], "recorded_at"),
        "actual": float(record["actual"]),
    }
    return _append(
        project,
        "outcomes.jsonl",
        normalized,
        idempotency_key=idempotency_key,
    )


def invalidate_prediction(
    project: Path,
    prediction_id: str,
    *,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    prediction_ids = {
        prediction["prediction_id"]
        for prediction in _read_ledger(project / "ledger" / "predictions.jsonl")
    }
    if prediction_id not in prediction_ids:
        raise ValueError("Cannot invalidate an unknown prediction")
    invalidations = _read_ledger(project / "ledger" / "invalidations.jsonl")
    if any(
        invalidation["prediction_id"] == prediction_id
        and invalidation["idempotency_key"] != idempotency_key
        for invalidation in invalidations
    ):
        raise ValueError("Prediction is already invalidated")
    return _append(
        project,
        "invalidations.jsonl",
        {
            "event_type": "prediction_invalidated",
            "prediction_id": prediction_id,
            "reason": reason,
        },
        idempotency_key=idempotency_key,
    )


def evaluate_predictions(project: Path) -> dict[str, Any]:
    predictions = _read_ledger(project / "ledger" / "predictions.jsonl")
    invalidated_ids = {
        invalidation["prediction_id"]
        for invalidation in _read_ledger(
            project / "ledger" / "invalidations.jsonl"
        )
    }
    outcomes = _read_ledger(project / "ledger" / "outcomes.jsonl")
    active_outcomes: dict[str, dict[str, Any]] = {}
    for event_id in {outcome["target_event_id"] for outcome in outcomes}:
        event_outcomes = [
            outcome
            for outcome in outcomes
            if outcome["target_event_id"] == event_id
        ]
        superseded_ids = {
            outcome.get("supersedes_outcome_id")
            for outcome in event_outcomes
            if outcome.get("supersedes_outcome_id")
        }
        leaves = [
            outcome
            for outcome in event_outcomes
            if outcome["outcome_id"] not in superseded_ids
        ]
        if len(leaves) != 1:
            raise ValueError(f"Ambiguous outcome correction chain for {event_id}")
        active_outcomes[event_id] = leaves[0]

    evaluated: list[dict[str, Any]] = []
    for prediction in sorted(predictions, key=lambda item: item["predicted_at"]):
        if prediction["prediction_id"] in invalidated_ids:
            continue
        outcome = active_outcomes.get(prediction["target_event_id"])
        if outcome is None:
            continue
        error = float(prediction["prediction"]) - float(outcome["actual"])
        evaluated.append(
            {
                "prediction_id": prediction["prediction_id"],
                "target_event_id": prediction["target_event_id"],
                "predicted_at": prediction["predicted_at"],
                "predicted": float(prediction["prediction"]),
                "actual": float(outcome["actual"]),
                "error": error,
                "absolute_error": abs(error),
                "squared_error": error * error,
                "method": prediction["method"],
            }
        )
    if not evaluated:
        return {
            "prediction_count": 0,
            "mae": None,
            "rmse": None,
            "median_absolute_error": None,
            "bias": None,
            "predictions": [],
        }
    absolute = sorted(item["absolute_error"] for item in evaluated)
    middle = len(absolute) // 2
    if len(absolute) % 2:
        median_absolute_error = absolute[middle]
    else:
        median_absolute_error = (absolute[middle - 1] + absolute[middle]) / 2
    return {
        "prediction_count": len(evaluated),
        "mae": sum(absolute) / len(absolute),
        "rmse": math.sqrt(
            sum(item["squared_error"] for item in evaluated) / len(evaluated)
        ),
        "median_absolute_error": median_absolute_error,
        "bias": sum(item["error"] for item in evaluated) / len(evaluated),
        "predictions": evaluated,
    }


def get_target(project: Path, event_id: str) -> dict[str, Any]:
    matches = [
        target
        for target in _read_ledger(project / "ledger" / "targets.jsonl")
        if target["target_event_id"] == event_id
    ]
    if len(matches) != 1:
        raise ValueError(f"Unknown or ambiguous target event: {event_id}")
    return matches[0]
