You are writing the final report for a Nous research campaign.

## Research Question

{{research_question}}

## Campaign Results (Ledger)

{{ledger_summary}}

## Final Principles

{{final_principles}}

## Result files on disk (per-iteration)

{{results_summary}}

## Dispatcher retry/silence summary

{{retry_log_summary}}

## Bundle amendments (executed parameters vs prescribed)

{{bundle_amendments_summary}}

## Brief amendments (campaign-spec friction surfaced; cross-run propagation)

{{brief_amendments_summary}}

## Instructions

Write a concise research report in markdown answering the research question. Structure:

### Answer
1-3 sentences directly answering the research question with specific numbers.

### Evidence
Key findings from each iteration that support the answer. Reference specific
metrics. **If "Result files on disk" lists ANY files, you MUST acknowledge
them in this section** — even if the iteration failed mid-flight, partial
data is meaningful (search-orientation discipline, #214). Read the files
to extract actual values when relevant; do not dismiss them as "no data".
If the apparatus failed before producing data, say so explicitly and cite
the dispatcher retry/silence summary above.

### Principles Discovered
List the active principles with confidence levels and applicability regimes.

### Limitations & Open Questions
What wasn't answered. What would the next campaign investigate.
Distinguish *scientific* gaps (the experiment's design limits) from
*infrastructure* gaps (the run was interrupted by a dispatcher failure —
see retry_log summary above). Use this to inform the next iteration's
bundle.

Output ONLY the markdown. No preamble.
