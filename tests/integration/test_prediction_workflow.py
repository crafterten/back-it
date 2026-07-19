import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from backit.cli import app
from backit.ledger import record_target
from backit.predictions import predict_project


def test_predict_project_uses_snapshot_and_records_provenance(
    tmp_path: Path,
) -> None:
    project = tmp_path / "scores"
    for directory in ("snapshots", "ledger", "audit"):
        (project / directory).mkdir(parents=True)
    dates = pd.date_range("2026-01-01", periods=3, tz="UTC")
    frame = pd.DataFrame(
        {
            "_backit_row_id": ["a", "b", "c"],
            "study_hours": [1.0, 2.0, 3.0],
            "observed_at": dates,
            "score_received_at": dates,
            "score": [70.0, 80.0, 90.0],
        }
    )
    snapshot = project / "snapshots" / "snapshot-1.parquet"
    frame.to_parquet(snapshot, index=False)
    (project / "snapshots" / "snapshot-1-manifest.json").write_text(
        json.dumps(
            {
                "snapshot_id": "snapshot-1",
                "created_at": "2026-01-03T12:00:00Z",
                "files": {"data": snapshot.name},
            }
        ),
        encoding="utf-8",
    )
    record_target(
        project,
        {
            "target_event_id": "exam-1",
            "target_at": "2026-01-10T10:00:00Z",
            "features": {"study_hours": 4.0},
            "feature_available_at": {
                "study_hours": "2026-01-03T12:00:00Z"
            },
        },
        idempotency_key="target-exam-1",
    )

    prediction = predict_project(
        project,
        {
            "schema_name": "backit.prediction-plan",
            "schema_version": 1,
            "plan_id": "score-v1",
            "predictors": ["study_hours"],
            "outcome": "score",
            "predicted_at": "2026-01-03T12:01:00Z",
            "data_cutoff": "2026-01-03T12:00:00Z",
            "feature_available_columns": {
                "study_hours": "observed_at"
            },
            "outcome_available_column": "score_received_at",
            "historical_cutoff_column": "observed_at",
        },
        event_id="exam-1",
        idempotency_key="predict-exam-1",
    )

    assert prediction["method"] == "prior_median"
    assert prediction["prediction"] == 80.0
    assert prediction["snapshot_id"] == "snapshot-1"
    assert prediction["training_row_ids"] == ["a", "b", "c"]

    plan_path = tmp_path / "prediction-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_name": "backit.prediction-plan",
                "schema_version": 1,
                "plan_id": "score-v1",
                "predictors": ["study_hours"],
                "outcome": "score",
                "predicted_at": "2026-01-03T12:01:00Z",
                "data_cutoff": "2026-01-03T12:00:00Z",
                "feature_available_columns": {
                    "study_hours": "observed_at"
                },
                "outcome_available_column": "score_received_at",
                "historical_cutoff_column": "observed_at",
            }
        ),
        encoding="utf-8",
    )
    invoked = CliRunner().invoke(
        app,
        [
            "predict",
            str(project),
            "--plan",
            str(plan_path),
            "--event",
            "exam-1",
            "--idempotency-key",
            "predict-exam-1",
            "--json",
        ],
    )
    assert invoked.exit_code == 0, invoked.output
    assert json.loads(invoked.stdout)["result"]["prediction"] == 80.0
