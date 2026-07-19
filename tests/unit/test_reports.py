import pandas as pd
import pytest

from backit.reports import execute_analysis_plan


def test_report_separates_supported_and_unsupported_claims() -> None:
    frame = pd.DataFrame(
        {
            "_backit_row_id": ["a", "b", "c", "d", "e"],
            "sleep_hours": [6, 7, 7.5, 8, 9],
            "score": [70, 75, 82, 88, 90],
        }
    )
    plan = {
        "schema_name": "backit.analysis-plan",
        "schema_version": 1,
        "plan_id": "sleep-score",
        "question": "How is sleep associated with my score?",
        "operation": "spearman",
        "predictors": ["sleep_hours"],
        "outcome": "score",
    }

    report = execute_analysis_plan(
        frame,
        plan,
        project_id="test-scores",
        snapshot_id="snapshot-1",
    )

    assert report["results"]["associations"][0]["rho"] == pytest.approx(1.0)
    assert report["supported_claims"][0]["kind"] == "association"
    assert "caused" in report["unsupported_claims"][0].lower()
    assert report["provenance"]["row_ids"] == ["a", "b", "c", "d", "e"]
