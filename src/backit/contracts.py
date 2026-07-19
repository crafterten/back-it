from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AvailabilityRule(StrictModel):
    same_as: str | None = None
    column: str | None = None

    @model_validator(mode="after")
    def require_one_source(self) -> "AvailabilityRule":
        if (self.same_as is None) == (self.column is None):
            raise ValueError("availability must define exactly one of same_as or column")
        return self


SemanticType = Literal[
    "number",
    "integer",
    "score",
    "datetime",
    "identifier",
    "note",
    "duration",
    "distance",
    "pace",
    "percentage",
    "boolean",
]


class ColumnConfig(StrictModel):
    name: str
    semantic_type: SemanticType
    unit: str | None = None
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    available_at: AvailabilityRule


class OutcomeConfig(StrictModel):
    column: str
    semantic_type: Literal["number", "integer", "score", "duration", "pace"]
    unit: str
    better: Literal["higher", "lower"]
    minimum: float | None = None
    maximum: float | None = None
    available_at: AvailabilityRule


class AdapterConfig(StrictModel):
    name: str
    version: str


class ProjectConfig(StrictModel):
    schema_name: Literal["backit.project"]
    schema_version: int = Field(ge=1)
    project_id: str
    name: str
    goal: str
    state: Literal["unconfigured", "inspected", "configured", "ingested"]
    canonical_workbook: str
    sheet: str
    timezone: str
    columns: list[ColumnConfig]
    outcome: OutcomeConfig
    adapter: AdapterConfig

    @model_validator(mode="after")
    def validate_column_references(self) -> "ProjectConfig":
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("Project column names must be unique")
        if self.outcome.column in names:
            raise ValueError("Outcome column must not be duplicated in columns")
        available_names = {*names, self.outcome.column}
        for column in self.columns:
            source = column.available_at.same_as or column.available_at.column
            if source not in available_names:
                raise ValueError(
                    f"Availability source {source!r} for {column.name!r} is not configured"
                )
        outcome_source = (
            self.outcome.available_at.same_as or self.outcome.available_at.column
        )
        if outcome_source not in available_names:
            raise ValueError(
                f"Availability source {outcome_source!r} for "
                f"{self.outcome.column!r} is not configured"
            )
        return self


class AnalysisPlan(StrictModel):
    schema_name: Literal["backit.analysis-plan"]
    schema_version: int = Field(ge=1)
    plan_id: str
    question: str
    operation: Literal["descriptive", "spearman", "combinations"]
    predictors: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    outcome: str | None = None
    bins: dict[str, list[float]] = Field(default_factory=dict)
    better: Literal["higher", "lower"] = "higher"
    minimum_group_size: int = Field(default=3, ge=1)


class PredictionPlan(StrictModel):
    schema_name: Literal["backit.prediction-plan"]
    schema_version: int = Field(ge=1)
    plan_id: str
    predictors: list[str] = Field(min_length=1)
    outcome: str
    predicted_at: str
    data_cutoff: str
    feature_available_columns: dict[str, str]
    outcome_available_column: str
    historical_cutoff_column: str
