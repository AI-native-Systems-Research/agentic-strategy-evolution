## Required final output

Before you finish, write the file `final/answer.json` in the repository root, with exactly these keys:

```json
{
  "answer": "short prose answer to the research question",
  "deliverable": "path to the delivered artifact (patch, script, or null)",
  "repro": "one shell command, run from the repository root, that regenerates your headline numbers",
  "claims": [
    {"id": "c1", "metric": "name of the measured quantity", "value": 0.0,
     "condition": "the exact configuration it was measured under", "evidence": "path to the file holding this number"}
  ]
}
```

List every quantitative conclusion you rely on as a claim. Each `evidence` path must exist and contain the value.
Overwrite `final/answer.json` whenever your conclusions change, so it always reflects your current best answer.
