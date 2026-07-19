from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import statsmodels.api as sm


def descriptive_statistics(
    frame: pd.DataFrame,
    columns: list[str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        present = values.dropna()
        result[column] = {
            "count": int(present.count()),
            "missing": int(values.isna().sum()),
            "mean": float(present.mean()) if not present.empty else None,
            "median": float(present.median()) if not present.empty else None,
            "minimum": float(present.min()) if not present.empty else None,
            "maximum": float(present.max()) if not present.empty else None,
        }
    return result


def spearman_associations(
    frame: pd.DataFrame,
    *,
    predictors: list[str],
    outcome: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for predictor in predictors:
        complete = frame[[predictor, outcome]].dropna()
        if len(complete) < 3:
            results.append(
                {
                    "predictor": predictor,
                    "n": int(len(complete)),
                    "rho": None,
                    "p_value": None,
                    "status": "insufficient_data",
                }
            )
            continue
        statistic = spearmanr(
            complete[predictor].astype(float),
            complete[outcome].astype(float),
        )
        rho = float(statistic.statistic)
        p_value = float(statistic.pvalue)
        results.append(
            {
                "predictor": predictor,
                "n": int(len(complete)),
                "rho": rho if np.isfinite(rho) else None,
                "p_value": p_value if np.isfinite(p_value) else None,
                "status": "ok" if np.isfinite(rho) else "constant_input",
            }
        )
    return sorted(
        results,
        key=lambda item: (
            -abs(item["rho"]) if item["rho"] is not None else float("inf"),
            item["predictor"],
        ),
    )


def rank_observed_combinations(
    frame: pd.DataFrame,
    *,
    predictors: list[str],
    bins: dict[str, list[float]],
    outcome: str,
    better: str,
    minimum_group_size: int = 3,
) -> list[dict[str, Any]]:
    working = frame[[*predictors, outcome]].dropna().copy()
    bin_columns: list[str] = []
    for predictor in predictors:
        bin_column = f"__bin_{predictor}"
        working[bin_column] = pd.cut(
            working[predictor],
            bins=bins[predictor],
            include_lowest=True,
            ordered=True,
        )
        bin_columns.append(bin_column)
    working = working.dropna(subset=bin_columns)

    groups: list[dict[str, Any]] = []
    for keys, group in working.groupby(bin_columns, observed=True, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        values = group[outcome].astype(float)
        median = float(values.median())
        mad = float((values - median).abs().median())
        groups.append(
            {
                "combination": {
                    predictor: str(key)
                    for predictor, key in zip(predictors, keys, strict=True)
                },
                "count": int(len(group)),
                "median": median,
                "median_absolute_deviation": mad,
                "minimum": float(values.min()),
                "maximum": float(values.max()),
                "sparse": len(group) < minimum_group_size,
                "rank": None,
            }
        )

    eligible = [group for group in groups if not group["sparse"]]
    direction = -1 if better == "higher" else 1
    eligible.sort(
        key=lambda group: (
            direction * group["median"],
            group["median_absolute_deviation"],
            -group["count"],
            tuple(group["combination"].values()),
        )
    )
    for rank, group in enumerate(eligible, start=1):
        group["rank"] = rank
    sparse = sorted(
        (group for group in groups if group["sparse"]),
        key=lambda group: tuple(group["combination"].values()),
    )
    return [*eligible, *sparse]


def forecast_numeric(
    frame: pd.DataFrame,
    *,
    predictors: list[str],
    outcome: str,
    target_features: dict[str, float],
    target_feature_available_at: dict[str, pd.Timestamp],
    data_cutoff: pd.Timestamp,
    feature_available_columns: dict[str, str],
    outcome_available_column: str,
    historical_cutoff_column: str,
) -> dict[str, Any]:
    cutoff = pd.Timestamp(data_cutoff)
    if cutoff.tzinfo is None:
        raise ValueError("data_cutoff must be timezone-aware")
    for predictor in predictors:
        available_at = pd.Timestamp(target_feature_available_at[predictor])
        if available_at.tzinfo is None or available_at > cutoff:
            raise ValueError(f"{predictor} was not available by data_cutoff")

    working = frame.copy()
    working[outcome_available_column] = pd.to_datetime(
        working[outcome_available_column],
        utc=True,
    )
    working[historical_cutoff_column] = pd.to_datetime(
        working[historical_cutoff_column],
        utc=True,
    )
    for predictor, available_column in feature_available_columns.items():
        working[available_column] = pd.to_datetime(
            working[available_column],
            utc=True,
        )
        working[predictor] = pd.to_numeric(working[predictor], errors="coerce")
    working[outcome] = pd.to_numeric(working[outcome], errors="coerce")
    working = working.dropna(
        subset=[
            "_backit_row_id",
            outcome,
            outcome_available_column,
            historical_cutoff_column,
            *predictors,
            *feature_available_columns.values(),
        ]
    ).sort_values(
        [outcome_available_column, "_backit_row_id"],
        kind="stable",
    )

    def eligible_before(fold_cutoff: pd.Timestamp) -> pd.DataFrame:
        mask = working[outcome_available_column] <= fold_cutoff
        for predictor in predictors:
            mask &= working[feature_available_columns[predictor]] <= fold_cutoff
        return working.loc[mask].copy()

    fold_rows: list[tuple[pd.Series, pd.DataFrame]] = []
    for _, test_row in working.sort_values(
        [historical_cutoff_column, "_backit_row_id"],
        kind="stable",
    ).iterrows():
        fold_cutoff = test_row[historical_cutoff_column]
        if test_row[outcome_available_column] > cutoff:
            continue
        if any(
            test_row[feature_available_columns[predictor]] > fold_cutoff
            for predictor in predictors
        ):
            continue
        training = eligible_before(fold_cutoff)
        training = training[
            training["_backit_row_id"] != test_row["_backit_row_id"]
        ]
        if len(training) >= 5:
            fold_rows.append((test_row, training))

    baseline_predictions: dict[str, list[tuple[float, float]]] = {
        "prior_median": [],
        "last_outcome": [],
    }
    for test_row, training in fold_rows:
        actual = float(test_row[outcome])
        baseline_predictions["prior_median"].append(
            (float(training[outcome].median()), actual)
        )
        last = training.sort_values(
            [outcome_available_column, "_backit_row_id"],
            kind="stable",
        ).iloc[-1]
        baseline_predictions["last_outcome"].append((float(last[outcome]), actual))

    baseline_mae = {
        name: float(np.mean([abs(predicted - actual) for predicted, actual in pairs]))
        if pairs
        else float("inf")
        for name, pairs in baseline_predictions.items()
    }
    selected_baseline = min(
        baseline_mae,
        key=lambda name: (baseline_mae[name], 0 if name == "prior_median" else 1),
    )

    minimum_rows = max(12, 5 * (len(predictors) + 1))
    ols_predictions: list[tuple[float, float]] = []
    common_baseline_predictions: list[tuple[float, float]] = []
    for fold_index, (test_row, training) in enumerate(fold_rows):
        if len(training) < minimum_rows:
            continue
        x_train = sm.add_constant(
            training[predictors].astype(float),
            has_constant="add",
        )
        if np.linalg.matrix_rank(x_train.to_numpy()) != x_train.shape[1]:
            continue
        fitted = sm.OLS(training[outcome].astype(float), x_train).fit()
        target_row = pd.DataFrame(
            [[float(test_row[predictor]) for predictor in predictors]],
            columns=predictors,
        )
        x_test = sm.add_constant(target_row, has_constant="add")
        predicted = float(fitted.predict(x_test).iloc[0])
        actual = float(test_row[outcome])
        ols_predictions.append((predicted, actual))
        baseline_pairs = baseline_predictions[selected_baseline]
        common_baseline_predictions.append(baseline_pairs[fold_index])

    ols_mae = (
        float(np.mean([abs(predicted - actual) for predicted, actual in ols_predictions]))
        if len(ols_predictions) >= 5
        else float("inf")
    )
    common_baseline_mae = (
        float(
            np.mean(
                [
                    abs(predicted - actual)
                    for predicted, actual in common_baseline_predictions
                ]
            )
        )
        if common_baseline_predictions
        else float("inf")
    )

    final_training = eligible_before(cutoff)
    method = selected_baseline
    if (
        len(ols_predictions) >= 5
        and np.isfinite(ols_mae)
        and ols_mae <= 0.95 * common_baseline_mae
        and len(final_training) >= minimum_rows
    ):
        method = "ols"

    if selected_baseline == "prior_median":
        baseline_prediction = float(final_training[outcome].median())
    else:
        baseline_prediction = float(
            final_training.sort_values(
                [outcome_available_column, "_backit_row_id"],
                kind="stable",
            ).iloc[-1][outcome]
        )

    prediction = baseline_prediction
    if method == "ols":
        x_train = sm.add_constant(
            final_training[predictors].astype(float),
            has_constant="add",
        )
        fitted = sm.OLS(final_training[outcome].astype(float), x_train).fit()
        target_row = pd.DataFrame(
            [[float(target_features[predictor]) for predictor in predictors]],
            columns=predictors,
        )
        prediction = float(
            fitted.predict(sm.add_constant(target_row, has_constant="add")).iloc[0]
        )

    return {
        "method": method,
        "prediction": prediction,
        "baseline": {
            "method": selected_baseline,
            "prediction": baseline_prediction,
        },
        "candidate_metrics": {
            "baseline_mae": {
                name: value if np.isfinite(value) else None
                for name, value in baseline_mae.items()
            },
            "common_baseline_mae": common_baseline_mae
            if np.isfinite(common_baseline_mae)
            else None,
            "ols_mae": ols_mae if np.isfinite(ols_mae) else None,
            "common_folds": len(ols_predictions),
        },
        "training_count": int(len(final_training)),
        "training_row_ids": sorted(final_training["_backit_row_id"].astype(str)),
        "data_cutoff": cutoff.isoformat(),
        "interval_status": "not_implemented",
    }
