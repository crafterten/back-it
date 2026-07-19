import pytest
from pydantic import ValidationError

from backit.contracts import ProjectConfig
from backit.serialization import canonical_json, sha256_json


def test_project_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(
            {
                "schema_name": "backit.project",
                "schema_version": 1,
                "project_id": "tests",
                "name": "Test Scores",
                "goal": "Predict my next test score.",
                "state": "configured",
                "canonical_workbook": "source/project_data.xlsx",
                "sheet": "Scores",
                "timezone": "America/New_York",
                "columns": [],
                "outcome": {
                    "column": "score",
                    "semantic_type": "score",
                    "unit": "points",
                    "better": "higher",
                },
                "adapter": {"name": "test_scores", "version": "1"},
                "unexpected": "must not be ignored",
            }
        )


def test_project_config_preserves_typed_schema_fields() -> None:
    config = ProjectConfig.model_validate(
        {
            "schema_name": "backit.project",
            "schema_version": 1,
            "project_id": "tests",
            "name": "Test Scores",
            "goal": "Predict my next test score.",
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
                    "name": "score_received_at",
                    "semantic_type": "datetime",
                    "required": True,
                    "available_at": {"same_as": "score_received_at"},
                },
                {
                    "name": "study_hours",
                    "semantic_type": "number",
                    "unit": "hours",
                    "required": True,
                    "available_at": {"same_as": "observed_at"},
                }
            ],
            "outcome": {
                "column": "score",
                "semantic_type": "score",
                "unit": "points",
                "better": "higher",
                "minimum": 0,
                "maximum": 100,
                "available_at": {"column": "score_received_at"},
            },
            "adapter": {"name": "test_scores", "version": "1"},
        }
    )

    assert config.project_id == "tests"
    assert config.columns[0].available_at.same_as == "observed_at"
    assert config.outcome.maximum == 100
    assert ProjectConfig.model_json_schema()["additionalProperties"] is False


def test_canonical_json_is_order_independent() -> None:
    left = {"z": 2, "a": {"b": 1, "a": 3}}
    right = {"a": {"a": 3, "b": 1}, "z": 2}

    assert canonical_json(left) == canonical_json(right)
    assert sha256_json(left) == sha256_json(right)
    assert canonical_json(left) == b'{"a":{"a":3,"b":1},"z":2}'


def test_project_config_rejects_unknown_availability_columns() -> None:
    payload = {
        "schema_name": "backit.project",
        "schema_version": 1,
        "project_id": "tests",
        "name": "Test Scores",
        "goal": "Predict my next test score.",
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
            }
        ],
        "outcome": {
            "column": "score",
            "semantic_type": "score",
            "unit": "points",
            "better": "higher",
            "available_at": {"column": "missing_received_at"},
        },
        "adapter": {"name": "test_scores", "version": "1"},
    }

    with pytest.raises(ValidationError, match="missing_received_at"):
        ProjectConfig.model_validate(payload)
