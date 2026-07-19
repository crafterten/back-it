import json
from pathlib import Path

from openpyxl import Workbook
from typer.testing import CliRunner
import yaml

from backit.cli import app


def _workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Scores"
    sheet.append(["observed_at", "study_hours", "score"])
    sheet.append(["2026-07-01T09:00:00-04:00", 2.0, 75])
    sheet.append(["2026-07-08T09:00:00-04:00", 3.0, 82])
    sheet.append(["2026-07-15T09:00:00-04:00", 4.0, 91])
    workbook.save(path)


def test_cli_project_init_and_inspect_emit_json_envelopes(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    workbook = tmp_path / "scores.xlsx"
    project = tmp_path / "project"
    _workbook(workbook)

    initialized = runner.invoke(
        app,
        [
            "project",
            "init",
            str(project),
            "--workbook",
            str(workbook),
            "--name",
            "Test Scores",
            "--goal",
            "Predict my next score",
            "--idempotency-key",
            "cli-init",
            "--json",
        ],
    )
    assert initialized.exit_code == 0, initialized.output
    init_payload = json.loads(initialized.stdout)
    assert init_payload["ok"] is True
    assert init_payload["command"] == "project init"
    assert init_payload["result"]["state"] == "unconfigured"

    inspected = runner.invoke(
        app,
        ["project", "inspect", str(project), "--json"],
    )
    assert inspected.exit_code == 0, inspected.output
    inspect_payload = json.loads(inspected.stdout)
    assert inspect_payload["result"]["headers"] == [
        "observed_at",
        "study_hours",
        "score",
    ]


def test_cli_configure_ingest_and_analyze(tmp_path: Path) -> None:
    runner = CliRunner()
    workbook = tmp_path / "scores.xlsx"
    project = tmp_path / "project"
    config_path = tmp_path / "project-config.yaml"
    plan_path = tmp_path / "plan.json"
    _workbook(workbook)
    init_args = [
        "project",
        "init",
        str(project),
        "--workbook",
        str(workbook),
        "--name",
        "Test Scores",
        "--goal",
        "Predict my next score",
        "--idempotency-key",
        "full-init",
        "--json",
    ]
    assert runner.invoke(app, init_args).exit_code == 0
    assert runner.invoke(
        app,
        ["project", "inspect", str(project), "--json"],
    ).exit_code == 0

    config = {
        "schema_name": "backit.project",
        "schema_version": 1,
        "project_id": "test-scores",
        "name": "Test Scores",
        "goal": "Predict my next score.",
        "state": "configured",
        "canonical_workbook": "source/project_data.xlsx",
        "sheet": "Scores",
        "timezone": "America/New_York",
        "columns": [
            {
                "name": "observed_at",
                "semantic_type": "datetime",
                "required": True,
                "available_at": {"same_as": "observed_at"},
            },
            {
                "name": "study_hours",
                "semantic_type": "number",
                "unit": "hours",
                "required": True,
                "minimum": 0,
                "available_at": {"same_as": "observed_at"},
            },
        ],
        "outcome": {
            "column": "score",
            "semantic_type": "score",
            "unit": "points",
            "better": "higher",
            "minimum": 0,
            "maximum": 100,
            "available_at": {"column": "observed_at"},
        },
        "adapter": {"name": "test_scores", "version": "1"},
    }
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    configured = runner.invoke(
        app,
        [
            "project",
            "configure",
            str(project),
            "--config",
            str(config_path),
            "--approve-import-plan",
            "--idempotency-key",
            "full-configure",
            "--json",
        ],
    )
    assert configured.exit_code == 0, configured.output

    ingested = runner.invoke(app, ["ingest", str(project), "--json"])
    assert ingested.exit_code == 0, ingested.output
    snapshot_id = json.loads(ingested.stdout)["result"]["snapshot_id"]

    checked = runner.invoke(app, ["check", str(project), "--json"])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.stdout)["result"]["ok"] is True

    plan_path.write_text(
        json.dumps(
            {
                "schema_name": "backit.analysis-plan",
                "schema_version": 1,
                "plan_id": "study-score",
                "question": "How are study hours associated with score?",
                "operation": "spearman",
                "predictors": ["study_hours"],
                "outcome": "score",
            }
        ),
        encoding="utf-8",
    )
    analyzed = runner.invoke(
        app,
        [
            "analyze",
            str(project),
            "--plan",
            str(plan_path),
            "--json",
        ],
    )
    assert analyzed.exit_code == 0, analyzed.output
    report = json.loads(analyzed.stdout)["result"]
    assert report["snapshot_id"] == snapshot_id
    assert report["results"]["associations"][0]["rho"] == 1.0


def test_cli_records_prediction_and_actual_outcome(tmp_path: Path) -> None:
    runner = CliRunner()
    project = tmp_path / "project"
    (project / "ledger").mkdir(parents=True)
    (project / "audit").mkdir()
    target_path = tmp_path / "target.json"
    target_path.write_text(
        json.dumps(
            {
                "target_event_id": "exam-1",
                "target_at": "2026-07-20T10:00:00-04:00",
                "features": {"study_hours": 5.0},
                "feature_available_at": {
                    "study_hours": "2026-07-19T20:00:00-04:00"
                },
            }
        ),
        encoding="utf-8",
    )

    target = runner.invoke(
        app,
        [
            "target",
            "record",
            str(project),
            "--target",
            str(target_path),
            "--idempotency-key",
            "target-exam-1",
            "--json",
        ],
    )
    assert target.exit_code == 0, target.output

    prediction_path = tmp_path / "prediction.json"
    prediction_path.write_text(
        json.dumps(
            {
                "prediction_id": "prediction-exam-1",
                "target_event_id": "exam-1",
                "predicted_at": "2026-07-19T20:01:00-04:00",
                "data_cutoff": "2026-07-19T20:00:00-04:00",
                "method": "prior_median",
                "prediction": 88.0,
            }
        ),
        encoding="utf-8",
    )
    predicted = runner.invoke(
        app,
        [
            "prediction",
            "record",
            str(project),
            "--prediction",
            str(prediction_path),
            "--idempotency-key",
            "prediction-exam-1",
            "--json",
        ],
    )
    assert predicted.exit_code == 0, predicted.output

    outcome = runner.invoke(
        app,
        [
            "outcome",
            "record",
            str(project),
            "--event",
            "exam-1",
            "--outcome-id",
            "outcome-exam-1",
            "--value",
            "92",
            "--unit",
            "points",
            "--recorded-at",
            "2026-07-22T15:00:00-04:00",
            "--idempotency-key",
            "outcome-exam-1",
            "--json",
        ],
    )
    assert outcome.exit_code == 0, outcome.output

    evaluated = runner.invoke(
        app,
        ["evaluate", str(project), "--json"],
    )
    assert evaluated.exit_code == 0, evaluated.output
    report = json.loads(evaluated.stdout)["result"]
    assert report["prediction_count"] == 1
    assert report["mae"] == 4.0


def test_cli_json_errors_are_machine_readable(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["check", str(tmp_path / "missing"), "--json"],
    )

    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["diagnostics"][0]["code"] == "PROJECT_NOT_FOUND"
