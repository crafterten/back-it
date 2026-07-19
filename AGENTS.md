# Back It operating rules for Codex

Back It is the calculator. Codex is the interface and interpreter.

When the user gives a spreadsheet path and a natural-language goal:

1. Run `project init` and `project inspect` with `--json`.
2. Read headers, sample structure, warnings, and errors.
3. Ask only about meanings, units, ranges, outcome direction, and dates that
   cannot be inferred safely.
4. Create a strict project configuration. Show the proposed mapping before
   running `project configure --approve-import-plan`.
5. Tell the user to continue editing only the generated
   `source/project_data.xlsx`.
6. When the user says data was added, run `check --json` first. Run `ingest`
   only when check passes.
7. Translate natural-language questions into constrained JSON analysis or
   prediction plans. Never add arbitrary Python to a plan.
8. Treat Back It's JSON as authoritative. Do not redo arithmetic in prose,
   modify calculated numbers, import general population claims, or state that an
   association is causal.
9. Quote the relevant result field, sample count, missingness, method, cutoff,
   and measured prediction error when interpreting results.
10. Keep projects isolated unless the user explicitly requests a cross-project
    comparison.

Use `.\.venv\Scripts\backit.exe` from this repository.
