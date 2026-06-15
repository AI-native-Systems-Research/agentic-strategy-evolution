# Style-Customized Visualization

Ephemeral restyling of campaign visualization text to match a user-specified tone, without modifying indexed wiki data.

## Problem

Users want visualization text (definitions, summaries, insights) adapted to their audience — e.g., "explain like I'm a novice" or "keep it brief and technical." Currently, all text is baked into the wiki at index time and rendered as-is.

## Constraint

The canonical data in `~/.nous/wiki/` and the registry must remain unchanged. Restyling is ephemeral and applies only to the generated HTML output.

## Entry Points

### `/visualize-campaign`

```
/visualize-campaign <campaign-name>
→ canonical visualization, no LLM call

/visualize-campaign <campaign-name> :: <style intent>
→ restyled visualization
```

Campaign name is always required. Everything after `::` is the style intent. No `::` = no restyling, current behavior unchanged.

### `/post-campaign`

```
/post-campaign <campaign-path>
→ indexes + canonical visualization

/post-campaign <campaign-path> :: <style intent>
→ indexes normally (steps 4-10 unaffected), passes style to visualization step (step 11)
```

## Architecture

```
User provides style intent
         │
         ▼
┌────────────────────────────────────────────────┐
│ Read canonical files from                      │
│ ~/.nous/wiki/campaigns/<name>/                 │
│   concepts.json, summaries.json, dead-ends.json│
│   frontiers.json, interactions.json, summary.md│
└────────────────────┬───────────────────────────┘
                     │
   ┌─────────────────┼─────────────────┐
   │                 │                 │
   ▼                 ▼                 ▼
 Call 1           Call 2          Call 3        Call 4           Call 5
 concepts.json    summaries.json  dead-ends     frontiers+       summary.md
 (definitions)    (narratives)    (insights)    interactions
   │                 │                 │
   └─────────────────┼─────────────────┘
                     │  (5 parallel LLM calls)
                     ▼
┌────────────────────────────────────────────────┐
│ Merge rewritten text into deep copies of       │
│ canonical files (non-text fields untouched)    │
└────────────────────┬───────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────┐
│ Write styled files to /tmp/nous-viz-styled-*/  │
│ Pass temp paths to visualize_campaign.py       │
└────────────────────────────────────────────────┘
```

## LLM Rewrite Approach

Each file gets a single LLM call with **structured output** (tool use / response schema) that enforces the exact shape of the response.

### Concepts.json call

**Input to LLM:**

The original definitions as context, plus the style instruction.

**Response schema (enforced):**

```json
{
  "entities": [
    {"name": "FlowControlFilter", "definition": "string"},
    {"name": "Scheduler", "definition": "string"}
  ],
  "concepts": [
    {"name": "Slope Detection", "definition": "string"}
  ],
  "parameters": [
    {"name": "slopeThreshold", "definition": "string"}
  ]
}
```

The `name` fields are pre-filled and locked (provided as context, not rewritten). The LLM only produces the `definition` string values. Array lengths are fixed by the schema.

After the call returns, the skill injects the rewritten definitions into a deep copy of the full canonical `concepts.json` (preserving `principles`, `operates_on`, `parent_concept`, `evolution`, `source`, and all other structural fields).

### Summaries.json call

**Response schema:**

```json
{
  "iter-0": {"what_was_tried": "string", "what_was_found": "string", "why_it_matters": "string"},
  "iter-1": {"what_was_tried": "string", "what_was_found": "string", "why_it_matters": "string"}
}
```

Keys are pre-determined from the canonical file. LLM fills the three narrative strings per iteration.

### Dead-ends.json call

**Response schema:**

```json
[
  {"id": "DE-1", "title": "string", "what_was_tried": "string", "why_it_failed": "string", "avoid_when": "string"}
]
```

`id` and `iteration` are locked. LLM fills `title`, `what_was_tried`, `why_it_failed`, `avoid_when`.

### Frontiers + Interactions call (Call 4)

Combined into a single LLM call. If neither file exists, skip this call entirely.

**Response schema for frontiers:**

```json
[
  {"id": "F-1", "title": "string", "what_was_tried": "string", "what_was_left_untried": "string", "what_to_try_next": "string"}
]
```

**Response schema for interactions:**

```json
[
  {"id": "I-1", "title": "string", "approach_a": "string", "approach_b": "string", "why_combine": "string", "experiment_to_run": "string"}
]
```

`id` and `related_principles` are locked. LLM fills the text fields.

### Summary.md call

Single string — the LLM receives the full markdown and returns a restyled version. No schema needed beyond "return a string."

## Merge Logic

For each file:

1. Deep copy the canonical data
2. Walk the LLM response and inject rewritten strings at the corresponding positions (matched by `name` for concepts.json items, by `id` for insights, by key for summaries). If a returned `name`/`id` doesn't match any canonical entry, skip it.
3. All non-text fields (`principles`, `operates_on`, `parent_concept`, `parameters`, `evolution`, `source`, `related_principles`, `iteration`) remain from the canonical copy
4. Assemble `insights.json`: combine restyled dead-ends, frontiers, and interactions arrays into a single `{"dead_ends": [...], "frontiers": [...], "interactions": [...]}` object matching the `--insights` flag's expected format

## Failure Handling

- If an LLM call fails, returns invalid schema, or array length doesn't match → use canonical text for that file
- Print a visible warning: "WARNING: Could not restyle <component> (<reason>). Showing original text for this section."
- Never partial-restyle within a file: either fully restyled or fully canonical
- If ALL 5 calls fail → STOP and ask the user: "All style calls failed. Would you like to open the canonical (unstyled) visualization instead, or retry?"
- Delete and recreate `/tmp/nous-viz-styled-<campaign>/` before each run to prevent stale data from prior runs

## Changes to `visualize_campaign.py`

The script already accepts `--concepts`, `--summaries`, and `--insights` flags. The `--insights` flag accepts a single JSON file containing `dead_ends`, `frontiers`, and `interactions` arrays (the same structure produced by the script's internal `build_insights_data()` function). Add:

- `--summary-md <path>` — optional, overrides wiki directory lookup for the Summary tab markdown

When this flag is present, the script reads summary markdown from the provided path. When absent, current behavior (auto-discover from `~/.nous/wiki/campaigns/<name>/summary.md`) is unchanged.

The styled workflow assembles restyled dead-ends, frontiers, and interactions into a single `insights.json` matching the `--insights` expected format, so no additional per-file flags are needed.

## Changes to `/visualize-campaign` Skill

1. Parse `$ARGUMENTS` for `::` delimiter
2. Left side = campaign name (required)
3. Right side = style intent (optional)
4. If no style: current behavior (verify prerequisites, run script with canonical paths)
5. If style present:
   a. Read canonical files
   b. Fire 5 parallel LLM calls with structured output schemas
   c. Merge responses into deep copies
   d. Write to `/tmp/nous-viz-styled-<campaign>/`
   e. Run `visualize_campaign.py` with all temp paths via flags
   f. Open the HTML

## Changes to `/post-campaign` Skill

1. Parse `$ARGUMENTS` for `::` delimiter
2. Left side = campaign path (used for all indexing steps)
3. Right side = style intent (ignored during steps 4-10)
4. In step 11 (visualization): invoke `/visualize-campaign <campaign-name> :: <style>` if style was provided, otherwise invoke without style as today

## LLM Execution Context

The rewrite calls are made by the LLM executing the `/visualize-campaign` skill itself. No external API client or separate model configuration is needed — the skill simply asks the executing LLM to produce the restyled text as part of its tool-use flow. This means the style quality depends on whichever model the user is running Claude Code with.

## Non-Goals

- Caching restyled output
- Persisting style preferences
- Modifying the canonical wiki data
- Supporting multiple simultaneous styles
- Client-side (in-browser) restyling
