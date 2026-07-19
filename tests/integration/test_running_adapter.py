from pathlib import Path

from openpyxl import Workbook
import pandas as pd

from backit.projects import (
    configure_project,
    ingest_project,
    init_project,
    inspect_project,
)
from backit.reports import execute_analysis_plan


def test_running_project_normalizes_pace_and_duration(tmp_path: Path) -> None:
    source = tmp_path / "runs.xlsx"
    project = tmp_path / "running-5k"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Runs"
    sheet.append(
        [
            "observed_at",
            "sleep_hours",
            "weekly_mileage",
            "pace",
            "five_k_time",
        ]
    )
    for row in [
        ["2026-06-01T09:00:00-04:00", 7.0, 20, "7:30", "23:15"],
        ["2026-06-08T09:00:00-04:00", 8.0, 24, "7:15", "22:40"],
        ["2026-06-15T09:00:00-04:00", 8.2, 25, "7:10", "22:25"],
    ]:
        sheet.append(row)
    workbook.save(source)

    init_project(
        project,
        source,
        name="Running 5K",
        goal="Find combinations associated with my fastest 5K.",
        idempotency_key="running-init",
    )
    inspect_project(project)
    configure_project(
        project,
        {
            "schema_name": "backit.project",
            "schema_version": 1,
            "project_id": "running-5k",
            "name": "Running 5K",
            "goal": "Find combinations associated with my fastest 5K.",
            "state": "configured",
            "canonical_workbook": "source/project_data.xlsx",
            "sheet": "Runs",
            "timezone": "America/New_York",
            "columns": [
                {
                    "name": "observed_at",
                    "semantic_type": "datetime",
                    "required": True,
                    "available_at": {"same_as": "observed_at"},
                },
                {
                    "name": "sleep_hours",
                    "semantic_type": "number",
                    "unit": "hours",
                    "required": True,
                    "minimum": 0,
                    "maximum": 24,
                    "available_at": {"same_as": "observed_at"},
                },
                {
                    "name": "weekly_mileage",
                    "semantic_type": "distance",
                    "unit": "miles",
                    "required": True,
                    "minimum": 0,
                    "available_at": {"same_as": "observed_at"},
                },
                {
                    "name": "pace",
                    "semantic_type": "pace",
                    "unit": "seconds_per_mile",
                    "required": True,
                    "minimum": 0,
                    "available_at": {"same_as": "observed_at"},
                },
            ],
            "outcome": {
                "column": "five_k_time",
                "semantic_type": "duration",
                "unit": "seconds",
                "better": "lower",
                "minimum": 0,
                "available_at": {"column": "observed_at"},
            },
            "adapter": {"name": "running_5k", "version": "1"},
        },
        idempotency_key="running-config",
    )

    ingested = ingest_project(project)
    frame = pd.read_parquet(ingested.snapshot_path)

    assert frame["pace"].tolist() == [450.0, 435.0, 430.0]
    assert frame["five_k_time"].tolist() == [1395.0, 1360.0, 1345.0]

    report = execute_analysis_plan(
        frame,
        {
            "schema_name": "backit.analysis-plan",
            "schema_version": 1,
            "plan_id": "running-combinations",
            "question": "Which observed combinations had my fastest times?",
            "operation": "combinations",
            "predictors": ["sleep_hours", "weekly_mileage"],
            "outcome": "five_k_time",
            "bins": {
                "sleep_hours": [0, 7.5, 24],
                "weekly_mileage": [0, 22, 100],
            },
            "better": "lower",
            "minimum_group_size": 2,
        },
        project_id="running-5k",
        snapshot_id=ingested.snapshot_id,
    )
    assert report["results"]["combinations"][0]["median"] == 1352.5
