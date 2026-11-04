# Nous: keep a notebook, finish with a checkable answer

Work on the task the way you normally would. Nous records your commands. Two extra things:

**Notebook.** Append one JSON line to `$NOUS_WORK_DIR/notebook.jsonl` (with a shell command) when you:
- form a hypothesis, before testing it: `{"kind": "hypothesis", "id": "H1", "claim": "...", "predict": "what you expect to measure"}`;
- get its result: `{"kind": "result", "id": "H1", "status": "confirmed|refuted|inconclusive", "evidence": [{"path", "key", "value"}]}`.
A confirmed or refuted result cites the file holding the measured number. Write each entry once; Nous checks them all when you finish, so you need not re-read the notebook.

**Answer.** Finish by writing `$NOUS_WORK_DIR/answer.json`: `{answer, deliverable, repro, claims}`.
- `answer`: prose answering every part of the question.
- `deliverable`: a path or short description.
- `repro`: one command run from the repository root, relative paths only, no `cd`, that regenerates the
  headline numbers.
- `claims: [{id, metric, value, condition, evidence: {path, key, value}}]`, values copied from the files.

Evidence keys: `.json` a JSON pointer (`/a/0/b`); `.jsonl` `line@pointer`; `.csv` `column@row`; other text a
regex whose group 1 is the value (write `\d`, not `\\d`). Paths are relative to the work dir or the repository.

After you finish, an independent reviewer may ask for one more check; run it and update the answer.
