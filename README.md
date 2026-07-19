# Back It

Back It is a local, deterministic personal analytics engine operated through
Codex. You keep adding observations to Excel. Back It validates, snapshots,
calculates, predicts, and evaluates. Codex explains the resulting JSON without
inventing or changing the numbers.

There is no GUI and no shared population model. Each project uses only its own
workbook, schema, analysis plans, predictions, and actual outcomes.

## What is implemented

- Untouched archival copy of the first `.xlsx` workbook.
- Canonical project workbook with stable `_backit_row_id` values.
- Read-only `check` workflow for rows added or edited in Excel.
- Typed, content-addressed Parquet snapshots.
- Strict versioned project, analysis, and prediction plans.
- Descriptive statistics and Spearman associations.
- Rankings of sufficiently populated observed combinations using explicit bins.
- Time-aware baseline and eligible OLS forecasts.
- Multiple dated predictions for one target event.
- Append-only target, prediction, outcome, correction, and invalidation records.
- MAE, RMSE, median absolute error, and signed bias against actual outcomes.
- Machine-readable JSON envelopes and validation errors.
- Test-score and running/5K proof workflows.

Association is never labeled as causation. Predictions only use outcomes and
features that were available by the saved cutoff.

## Environment

The repository already contains a local virtual environment at `.venv`.

To recreate it:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e .
```

Run the CLI with:

```powershell
.\.venv\Scripts\backit.exe --help
```

## Codex workflow

### 1. Start a project from a loose workbook

```powershell
.\.venv\Scripts\backit.exe project init "C:\data\backit-projects\test-scores" `
  --workbook "C:\data\loose-test-scores.xlsx" `
  --name "Test Scores" `
  --goal "Predict my next score from my own preparation history" `
  --idempotency-key "init-test-scores-1" `
  --json

.\.venv\Scripts\backit.exe project inspect "C:\data\backit-projects\test-scores" --json
```

Codex reads the inspection, asks about ambiguous meanings or units, and creates a
`project.yaml` modeled after `examples/test_scores/project.yaml`.

### 2. Approve the mapping and create the canonical workbook

```powershell
.\.venv\Scripts\backit.exe project configure "C:\data\backit-projects\test-scores" `
  --config "C:\data\test-scores-project.yaml" `
  --approve-import-plan `
  --idempotency-key "configure-test-scores-v1" `
  --json
```

The original import remains untouched. From this point forward, edit only:

```text
<project>\source\project_data.xlsx
```

### 3. After adding data in Excel

First ask Codex: “I entered new data. Check whether everything is good.”

Codex runs:

```powershell
.\.venv\Scripts\backit.exe check "<project>" --json
```

`check` never edits the workbook. If validation passes, Codex runs:

```powershell
.\.venv\Scripts\backit.exe ingest "<project>" --json
```

Ingest assigns IDs only to newly appended rows and creates an immutable snapshot.
The outcome may be empty when it has not happened yet.

### 4. Ask an analytical question

Codex converts the question into a constrained plan like
`examples/running_5k/combination-plan.json`, then runs:

```powershell
.\.venv\Scripts\backit.exe analyze "<project>" `
  --plan "<analysis-plan.json>" `
  --json
```

The JSON report is authoritative. Codex should quote its numeric fields, explain
sample sizes and missingness, and preserve its supported/unsupported claim
boundary.

### 5. Make a dated prediction

Record the event and feature values available at that date:

```powershell
.\.venv\Scripts\backit.exe target record "<project>" `
  --target "<target.json>" `
  --idempotency-key "target-biology-exam-3-20260719" `
  --json
```

Then run a saved prediction plan:

```powershell
.\.venv\Scripts\backit.exe predict "<project>" `
  --plan "<prediction-plan.json>" `
  --event "biology-exam-3" `
  --idempotency-key "prediction-biology-exam-3-20260719" `
  --json
```

A later prediction for the same exam is a new dated prediction, not a revision.

### 6. Record the actual result and evaluate

```powershell
.\.venv\Scripts\backit.exe outcome record "<project>" `
  --event "biology-exam-3" `
  --outcome-id "biology-exam-3-actual-v1" `
  --value 93 `
  --unit "points" `
  --recorded-at "2026-07-22T15:00:00-04:00" `
  --idempotency-key "biology-exam-3-actual-v1" `
  --json

.\.venv\Scripts\backit.exe evaluate "<project>" --json
```

## Spreadsheet rules

- MVP input is a literal-value `.xlsx` table with one header row.
- Formulas, merged cells in the data range, ambiguous dates, and duplicate
  headers are rejected.
- Durations and paces accept numeric seconds or `MM:SS` / `HH:MM:SS`.
- Sort rows freely. `_backit_row_id` preserves identity.
- Do not copy or edit `_backit_row_id` values.
- Leave an outcome blank until it is known.
- Dates used for predictions must include a timezone.

## Development verification

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=backit --cov-report=term-missing -q
```
