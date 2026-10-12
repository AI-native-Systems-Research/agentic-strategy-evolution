# Leaked-run backups (kept for reference, NOT valid results)

These Nous research preds were produced while the local research judge ran solutions on the host
without a sandbox. Each run's own transcript shows the agent reading engine/data copies from /tmp
that judged "solutions" had dumped there (see README §0 "Judge side channel").

| pred | score | evidence |
|---|---|---|
| gf_seed_sql.nous.research.json (opus-4-6) | 86.9 | 9 dump-writes, 23 reads (e.g. Read /tmp/sql_engine_dump/parser.py) |
| gf_seed_sql.nous.s45.json (Sonnet-4.5) | 59.56 | 1 dump-write (explore_parser.py), 6 reads of /tmp/gf_s45_parser_source |
| gf_seed_sql.nous.o5.json (Opus-5) | 87.14 | 23 reads of older dumps (/tmp/sql_engine_dump, /tmp/gf_harness) |
| llm_router.nous.research.json (opus-4-6) | 59.66 | dump_routing.py -> /tmp/routing_dump.json; filename obfuscated chr(114)+"eference_data.csv" |

All four are being re-run with the sandboxed judge (gen/judge_sandbox.py). The /tmp dumps were moved
to ~/frontier/_quarantine_tmp_20261012/.

## cloudcast (added 2026-10-12)

| result | value | evidence |
|---|---|---|
| Nous cloudcast.nous.json (Oct 1, before any sandbox) | $626 | 82 /tmp probe/eval-dump uses (probe_costs*.py, cloudcast_eval.json, milp_*.json) |
| Claude runs/cloudcast/claude (pred.json kept in place) | $659 | judged solution wrote per-scenario test configs to /tmp/cloudcast_debug.txt; agent read it 11x |

Both queued for re-run on the sandboxed judge (gen/nous_research_cap.py / gen/claude_code_research_runner.py,
task `cloudcast`; total_cost reproduces under the sandbox: attempt_26 = $659.15).
