from dataclasses import asdict
import json
from pathlib import Path
from collections.abc import Callable
from typing import Any

import pandas as pd
import typer
import yaml

from backit.ledger import (
    evaluate_predictions,
    record_outcome,
    record_prediction,
    record_target,
)
from backit.projects import (
    check_project,
    configure_project,
    ingest_project,
    init_project,
    inspect_project,
)
from backit.predictions import predict_project
from backit.reports import execute_analysis_plan
from backit.serialization import canonical_json


app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
project_app = typer.Typer(no_args_is_help=True)
target_app = typer.Typer(no_args_is_help=True)
prediction_app = typer.Typer(no_args_is_help=True)
outcome_app = typer.Typer(no_args_is_help=True)
app.add_typer(project_app, name="project")
app.add_typer(target_app, name="target")
app.add_typer(prediction_app, name="prediction")
app.add_typer(outcome_app, name="outcome")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _emit(command: str, result: Any, json_output: bool) -> None:
    value = _jsonable(result)
    if json_output:
        envelope = {
            "contract": "backit.command-result",
            "version": 1,
            "ok": True,
            "command": command,
            "result": value,
            "diagnostics": [],
        }
        typer.echo(canonical_json(envelope).decode("utf-8"))
    else:
        typer.echo(f"{command}: {value}")


def _execute(
    command: str,
    json_output: bool,
    operation: Callable[[], Any],
    *,
    error_exit: int,
) -> None:
    try:
        result = operation()
    except FileNotFoundError as error:
        diagnostic = {
            "code": "PROJECT_NOT_FOUND",
            "message": str(error),
        }
        if json_output:
            typer.echo(
                canonical_json(
                    {
                        "contract": "backit.command-result",
                        "version": 1,
                        "ok": False,
                        "command": command,
                        "result": None,
                        "diagnostics": [diagnostic],
                    }
                ).decode("utf-8")
            )
        else:
            typer.echo(diagnostic["message"], err=True)
        raise typer.Exit(3) from error
    except (TypeError, ValueError) as error:
        diagnostic = {
            "code": "VALIDATION_ERROR",
            "message": str(error),
        }
        if json_output:
            typer.echo(
                canonical_json(
                    {
                        "contract": "backit.command-result",
                        "version": 1,
                        "ok": False,
                        "command": command,
                        "result": None,
                        "diagnostics": [diagnostic],
                    }
                ).decode("utf-8")
            )
        else:
            typer.echo(diagnostic["message"], err=True)
        raise typer.Exit(error_exit) from error
    _emit(command, result, json_output)


@project_app.command("init")
def project_init_command(
    project: Path = typer.Argument(...),
    workbook: Path = typer.Option(..., "--workbook"),
    name: str = typer.Option(..., "--name"),
    goal: str = typer.Option(..., "--goal"),
    idempotency_key: str = typer.Option(..., "--idempotency-key"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _execute(
        "project init",
        json_output,
        lambda: init_project(
            project,
            workbook,
            name=name,
            goal=goal,
            idempotency_key=idempotency_key,
        ),
        error_exit=3,
    )


@project_app.command("inspect")
def project_inspect_command(
    project: Path = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _execute(
        "project inspect",
        json_output,
        lambda: inspect_project(project),
        error_exit=3,
    )


@project_app.command("configure")
def project_configure_command(
    project: Path = typer.Argument(...),
    config: Path = typer.Option(..., "--config"),
    approve_import_plan: bool = typer.Option(False, "--approve-import-plan"),
    idempotency_key: str = typer.Option(..., "--idempotency-key"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    if not approve_import_plan:
        raise typer.BadParameter("--approve-import-plan is required")
    with config.open("r", encoding="utf-8") as stream:
        raw_config = yaml.safe_load(stream)
    _execute(
        "project configure",
        json_output,
        lambda: configure_project(
            project,
            raw_config,
            idempotency_key=idempotency_key,
        ),
        error_exit=3,
    )


@app.command("ingest")
def ingest_command(
    project: Path = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _execute(
        "ingest",
        json_output,
        lambda: ingest_project(project),
        error_exit=4,
    )


@app.command("check")
def check_command(
    project: Path = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _execute(
        "check",
        json_output,
        lambda: check_project(project),
        error_exit=4,
    )


def _latest_snapshot(project: Path) -> tuple[str, Path]:
    manifests: list[tuple[str, dict[str, Any], Path]] = []
    for path in (project / "snapshots").glob("*-manifest.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        manifests.append((value["created_at"], value, path))
    if not manifests:
        raise ValueError("Project has no ingested snapshot")
    _, manifest, _ = max(manifests, key=lambda item: item[0])
    return manifest["snapshot_id"], project / "snapshots" / manifest["files"]["data"]


@app.command("analyze")
def analyze_command(
    project: Path = typer.Argument(...),
    plan: Path = typer.Option(..., "--plan"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    def operation() -> dict[str, Any]:
        snapshot_id, snapshot_path = _latest_snapshot(project)
        frame = pd.read_parquet(snapshot_path)
        raw_plan = json.loads(plan.read_text(encoding="utf-8"))
        return execute_analysis_plan(
            frame,
            raw_plan,
            project_id=project.name,
            snapshot_id=snapshot_id,
        )

    _execute("analyze", json_output, operation, error_exit=5)


@target_app.command("record")
def target_record_command(
    project: Path = typer.Argument(...),
    target: Path = typer.Option(..., "--target"),
    idempotency_key: str = typer.Option(..., "--idempotency-key"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    record = json.loads(target.read_text(encoding="utf-8"))
    _execute(
        "target record",
        json_output,
        lambda: record_target(
            project,
            record,
            idempotency_key=idempotency_key,
        ),
        error_exit=4,
    )


@prediction_app.command("record")
def prediction_record_command(
    project: Path = typer.Argument(...),
    prediction: Path = typer.Option(..., "--prediction"),
    idempotency_key: str = typer.Option(..., "--idempotency-key"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    record = json.loads(prediction.read_text(encoding="utf-8"))
    _execute(
        "prediction record",
        json_output,
        lambda: record_prediction(
            project,
            record,
            idempotency_key=idempotency_key,
        ),
        error_exit=4,
    )


@outcome_app.command("record")
def outcome_record_command(
    project: Path = typer.Argument(...),
    event: str = typer.Option(..., "--event"),
    outcome_id: str = typer.Option(..., "--outcome-id"),
    value: float = typer.Option(..., "--value"),
    unit: str = typer.Option(..., "--unit"),
    recorded_at: str = typer.Option(..., "--recorded-at"),
    idempotency_key: str = typer.Option(..., "--idempotency-key"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _execute(
        "outcome record",
        json_output,
        lambda: record_outcome(
            project,
            {
                "outcome_id": outcome_id,
                "target_event_id": event,
                "recorded_at": recorded_at,
                "actual": value,
                "unit": unit,
            },
            idempotency_key=idempotency_key,
        ),
        error_exit=4,
    )


@app.command("evaluate")
def evaluate_command(
    project: Path = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _execute(
        "evaluate",
        json_output,
        lambda: evaluate_predictions(project),
        error_exit=5,
    )


@app.command("predict")
def predict_command(
    project: Path = typer.Argument(...),
    plan: Path = typer.Option(..., "--plan"),
    event: str = typer.Option(..., "--event"),
    idempotency_key: str = typer.Option(..., "--idempotency-key"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    raw_plan = json.loads(plan.read_text(encoding="utf-8"))
    _execute(
        "predict",
        json_output,
        lambda: predict_project(
            project,
            raw_plan,
            event_id=event,
            idempotency_key=idempotency_key,
        ),
        error_exit=5,
    )
