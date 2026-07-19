import pandas as pd
import pytest

from backit.analytics import (
    descriptive_statistics,
    forecast_numeric,
    rank_observed_combinations,
    spearman_associations,
)
from backit.serialization import canonical_json


def test_descriptive_and_spearman_results_are_numeric_evidence() -> None:
    frame = pd.DataFrame(
        {
            "study_hours": [1, 2, 3, 4, 5, 6],
            "screen_time": [6, 5, 4, 3, 2, 1],
            "score": [60, 68, 74, 83, 90, 96],
        }
    )

    summary = descriptive_statistics(frame, ["study_hours", "score"])
    associations = spearman_associations(
        frame,
        predictors=["study_hours", "screen_time"],
        outcome="score",
    )

    assert summary["score"]["count"] == 6
    assert summary["score"]["median"] == 78.5
    assert associations[0]["predictor"] == "screen_time"
    assert associations[0]["rho"] == -1.0
    assert associations[1]["predictor"] == "study_hours"
    assert associations[1]["rho"] == 1.0
    assert all(result["n"] == 6 for result in associations)


def test_combination_ranking_uses_configured_bins_and_observed_groups() -> None:
    frame = pd.DataFrame(
        {
            "sleep_hours": [6.5, 6.8, 6.9, 7.5, 7.7, 7.9, 8.2, 8.4],
            "study_hours": [1.2, 1.5, 1.8, 3.1, 3.3, 3.5, 4.0, 4.2],
            "score": [70, 72, 71, 88, 90, 89, 92, 93],
        }
    )

    result = rank_observed_combinations(
        frame,
        predictors=["sleep_hours", "study_hours"],
        bins={
            "sleep_hours": [0, 7, 8, 24],
            "study_hours": [0, 2, 4, 10],
        },
        outcome="score",
        better="higher",
        minimum_group_size=3,
    )

    assert result[0]["rank"] == 1
    assert result[0]["median"] == 89.0
    assert result[0]["count"] == 3
    assert result[-1]["rank"] is None
    assert result[-1]["sparse"] is True


def test_forecast_uses_only_values_available_by_each_cutoff() -> None:
    observed = pd.date_range("2026-01-01", periods=30, tz="UTC")
    frame = pd.DataFrame(
        {
            "_backit_row_id": [f"row-{index}" for index in range(30)],
            "study_hours": [float(index + 1) for index in range(30)],
            "study_hours_available_at": observed,
            "historical_prediction_cutoff": observed,
            "outcome_available_at": observed + pd.Timedelta(days=1),
            "score": [55.0 + 4.0 * index for index in range(30)],
        }
    )
    frame.loc[29, "score"] = 9999.0
    frame.loc[29, "outcome_available_at"] = pd.Timestamp(
        "2026-03-01",
        tz="UTC",
    )

    result = forecast_numeric(
        frame,
        predictors=["study_hours"],
        outcome="score",
        target_features={"study_hours": 31.0},
        target_feature_available_at={
            "study_hours": pd.Timestamp("2026-01-31", tz="UTC")
        },
        data_cutoff=pd.Timestamp("2026-01-31", tz="UTC"),
        feature_available_columns={
            "study_hours": "study_hours_available_at"
        },
        outcome_available_column="outcome_available_at",
        historical_cutoff_column="historical_prediction_cutoff",
    )

    assert result["method"] == "ols"
    assert result["prediction"] == pytest.approx(175.0)
    assert result["training_count"] == 29
    assert "row-29" not in result["training_row_ids"]
    assert result["interval_status"] == "not_implemented"


def test_small_forecast_report_contains_no_non_finite_json_values() -> None:
    dates = pd.date_range("2026-01-01", periods=3, tz="UTC")
    frame = pd.DataFrame(
        {
            "_backit_row_id": ["a", "b", "c"],
            "study_hours": [1.0, 2.0, 3.0],
            "study_hours_available_at": dates,
            "historical_prediction_cutoff": dates,
            "outcome_available_at": dates,
            "score": [70.0, 80.0, 90.0],
        }
    )

    result = forecast_numeric(
        frame,
        predictors=["study_hours"],
        outcome="score",
        target_features={"study_hours": 4.0},
        target_feature_available_at={"study_hours": dates[-1]},
        data_cutoff=dates[-1],
        feature_available_columns={
            "study_hours": "study_hours_available_at"
        },
        outcome_available_column="outcome_available_at",
        historical_cutoff_column="historical_prediction_cutoff",
    )

    assert result["method"] == "prior_median"
    assert result["candidate_metrics"]["ols_mae"] is None
    canonical_json(result)
