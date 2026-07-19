from typing import Any

import pandas as pd

from backit.analytics import (
    descriptive_statistics,
    rank_observed_combinations,
    spearman_associations,
)
from backit.contracts import AnalysisPlan
from backit.serialization import sha256_json


def execute_analysis_plan(
    frame: pd.DataFrame,
    plan: dict[str, Any],
    *,
    project_id: str,
    snapshot_id: str,
) -> dict[str, Any]:
    validated = AnalysisPlan.model_validate(plan)
    required_columns = {
        *validated.columns,
        *validated.predictors,
        *([validated.outcome] if validated.outcome else []),
    }
    missing = sorted(required_columns - set(frame.columns))
    if missing:
        raise ValueError(f"Plan references missing columns: {missing}")

    results: dict[str, Any]
    supported_claims: list[dict[str, Any]]
    unsupported_claims = [
        "These observational results do not show that any predictor caused the outcome."
    ]
    if validated.operation == "descriptive":
        results = {
            "descriptive": descriptive_statistics(frame, validated.columns)
        }
        supported_claims = [
            {
                "kind": "description",
                "text": "The report may describe the observed personal data.",
            }
        ]
    elif validated.operation == "spearman":
        if validated.outcome is None:
            raise ValueError("Spearman analysis requires an outcome")
        results = {
            "associations": spearman_associations(
                frame,
                predictors=validated.predictors,
                outcome=validated.outcome,
            )
        }
        supported_claims = [
            {
                "kind": "association",
                "text": "The report may describe rank associations in this dataset.",
            }
        ]
    else:
        if validated.outcome is None:
            raise ValueError("Combination analysis requires an outcome")
        results = {
            "combinations": rank_observed_combinations(
                frame,
                predictors=validated.predictors,
                bins=validated.bins,
                outcome=validated.outcome,
                better=validated.better,
                minimum_group_size=validated.minimum_group_size,
            )
        }
        supported_claims = [
            {
                "kind": "observed_combination",
                "text": "The report may rank sufficiently populated observed groups.",
            }
        ]

    report_body = {
        "schema_name": "backit.report",
        "schema_version": 1,
        "project_id": project_id,
        "question": validated.question,
        "plan": validated.model_dump(mode="json"),
        "snapshot_id": snapshot_id,
        "results": results,
        "diagnostics": {
            "row_count": int(len(frame)),
            "missing_by_column": {
                column: int(frame[column].isna().sum())
                for column in sorted(required_columns)
            },
        },
        "supported_claims": supported_claims,
        "unsupported_claims": unsupported_claims,
        "provenance": {
            "row_ids": sorted(frame["_backit_row_id"].astype(str).tolist())
            if "_backit_row_id" in frame
            else [],
        },
    }
    return {
        "report_id": sha256_json(report_body),
        **report_body,
    }
