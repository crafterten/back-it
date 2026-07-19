from pathlib import Path

import pytest

from backit.ledger import (
    evaluate_predictions,
    invalidate_prediction,
    record_outcome,
    record_prediction,
    record_target,
)


def test_multiple_predictions_are_evaluated_against_one_outcome(
    tmp_path: Path,
) -> None:
    project = tmp_path / "scores"
    (project / "ledger").mkdir(parents=True)
    (project / "audit").mkdir()

    record_target(
        project,
        {
            "target_event_id": "biology-exam-3",
            "target_at": "2026-07-20T10:00:00-04:00",
            "features": {"study_hours": 4.0},
            "feature_available_at": {
                "study_hours": "2026-07-15T20:00:00-04:00"
            },
        },
        idempotency_key="target-exam-3",
    )
    record_prediction(
        project,
        {
            "prediction_id": "prediction-1",
            "target_event_id": "biology-exam-3",
            "predicted_at": "2026-07-15T20:01:00-04:00",
            "data_cutoff": "2026-07-15T20:00:00-04:00",
            "method": "prior_median",
            "prediction": 84.0,
        },
        idempotency_key="prediction-1",
    )
    record_prediction(
        project,
        {
            "prediction_id": "prediction-2",
            "target_event_id": "biology-exam-3",
            "predicted_at": "2026-07-19T20:01:00-04:00",
            "data_cutoff": "2026-07-19T20:00:00-04:00",
            "method": "ols",
            "prediction": 90.0,
        },
        idempotency_key="prediction-2",
    )
    record_outcome(
        project,
        {
            "outcome_id": "outcome-1",
            "target_event_id": "biology-exam-3",
            "recorded_at": "2026-07-22T15:00:00-04:00",
            "actual": 93.0,
            "unit": "points",
        },
        idempotency_key="outcome-1",
    )

    report = evaluate_predictions(project)

    assert report["prediction_count"] == 2
    assert report["mae"] == 6.0
    assert report["rmse"] == pytest.approx(6.7082039325)
    assert report["bias"] == -6.0
    assert [item["absolute_error"] for item in report["predictions"]] == [
        9.0,
        3.0,
    ]


def test_outcome_correction_replaces_active_leaf_without_mutation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "scores"
    (project / "ledger").mkdir(parents=True)
    (project / "audit").mkdir()
    record_target(
        project,
        {
            "target_event_id": "exam-1",
            "target_at": "2026-07-20T10:00:00Z",
            "features": {"study_hours": 4.0},
            "feature_available_at": {
                "study_hours": "2026-07-19T10:00:00Z"
            },
        },
        idempotency_key="target",
    )
    record_prediction(
        project,
        {
            "prediction_id": "prediction-1",
            "target_event_id": "exam-1",
            "predicted_at": "2026-07-19T10:01:00Z",
            "data_cutoff": "2026-07-19T10:00:00Z",
            "method": "prior_median",
            "prediction": 88,
        },
        idempotency_key="prediction",
    )
    record_outcome(
        project,
        {
            "outcome_id": "outcome-1",
            "target_event_id": "exam-1",
            "recorded_at": "2026-07-22T15:00:00Z",
            "actual": 90,
            "unit": "points",
        },
        idempotency_key="outcome-1",
    )
    record_outcome(
        project,
        {
            "outcome_id": "outcome-2",
            "target_event_id": "exam-1",
            "recorded_at": "2026-07-22T15:05:00Z",
            "actual": 92,
            "unit": "points",
            "supersedes_outcome_id": "outcome-1",
        },
        idempotency_key="outcome-2",
    )

    assert evaluate_predictions(project)["mae"] == 4.0

    with pytest.raises(ValueError, match="current active outcome"):
        record_outcome(
            project,
            {
                "outcome_id": "outcome-fork",
                "target_event_id": "exam-1",
                "recorded_at": "2026-07-22T15:10:00Z",
                "actual": 91,
                "unit": "points",
                "supersedes_outcome_id": "outcome-1",
            },
            idempotency_key="outcome-fork",
        )


def test_invalidated_prediction_is_excluded_from_evaluation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "scores"
    (project / "ledger").mkdir(parents=True)
    (project / "audit").mkdir()
    record_target(
        project,
        {
            "target_event_id": "exam-1",
            "target_at": "2026-07-20T10:00:00Z",
            "features": {"study_hours": 4.0},
            "feature_available_at": {
                "study_hours": "2026-07-19T10:00:00Z"
            },
        },
        idempotency_key="target",
    )
    record_prediction(
        project,
        {
            "prediction_id": "prediction-1",
            "target_event_id": "exam-1",
            "predicted_at": "2026-07-19T10:01:00Z",
            "data_cutoff": "2026-07-19T10:00:00Z",
            "method": "prior_median",
            "prediction": 88,
        },
        idempotency_key="prediction",
    )
    record_outcome(
        project,
        {
            "outcome_id": "outcome-1",
            "target_event_id": "exam-1",
            "recorded_at": "2026-07-22T15:00:00Z",
            "actual": 90,
            "unit": "points",
        },
        idempotency_key="outcome",
    )

    invalidate_prediction(
        project,
        "prediction-1",
        reason="Entered target features incorrectly.",
        idempotency_key="invalidate-prediction-1",
    )

    assert evaluate_predictions(project)["prediction_count"] == 0
