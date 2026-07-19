import json
from pathlib import Path

from backit.contracts import AnalysisPlan, PredictionPlan, ProjectConfig


def main() -> None:
    output = Path("schemas")
    output.mkdir(parents=True, exist_ok=True)
    models = {
        "project.schema.json": ProjectConfig,
        "analysis-plan.schema.json": AnalysisPlan,
        "prediction-plan.schema.json": PredictionPlan,
    }
    for filename, model in models.items():
        path = output / filename
        path.write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
