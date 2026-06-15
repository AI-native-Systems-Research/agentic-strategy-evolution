# Style-Customized Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to specify a style intent (e.g., "explain like I'm a novice") with `/visualize-campaign` that ephemerally restyles all visible text in the visualization HTML without modifying canonical wiki data.

**Architecture:** The `/visualize-campaign` skill parses a `::` delimiter from arguments. When a style is present, it extracts text fields from canonical JSON files, makes 5 parallel LLM calls with structured output schemas to restyle them, merges results into temp files, and passes those to `visualize_campaign.py` via existing flags. When no style is present, behavior is unchanged.

**Tech Stack:** Python (visualize_campaign.py), Claude Code skill markdown, LLM structured output (tool use within skill execution)

**Spec:** `docs/superpowers/specs/2026-06-15-style-customized-visualization-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `scripts/visualize_campaign.py` | Modify (lines 2360-2465) | Add `--summary-md` flag for summary.md override |
| `.claude/commands/visualize-campaign.md` | Rewrite | Add `::` parsing, style detection, LLM rewrite pipeline, temp file creation |
| `.claude/commands/post-campaign.md` | Modify (step 11) | Pass style through to visualize-campaign invocation |

---

### Task 1: Add `--summary-md` flag to `visualize_campaign.py`

**Files:**
- Modify: `scripts/visualize_campaign.py:2361-2439`

The script already has `--concepts`, `--summaries`, and `--insights` flags. The only missing override is for `summary.md`. Add it.

- [ ] **Step 1: Add the argument to the parser**

In `scripts/visualize_campaign.py`, after line 2369 (`--no-open`), add:

```python
    parser.add_argument("--summary-md", help="Markdown file for the Summary tab (overrides wiki lookup)")
```

- [ ] **Step 2: Use the flag in the loading logic**

Replace lines 2434-2439:

```python
    # Load summary.md for the Summary tab
    summary_md = ""
    wiki_campaigns_dir = Path.home() / ".nous" / "wiki" / "campaigns" / campaign_name
    summary_md_path = wiki_campaigns_dir / "summary.md"
    if summary_md_path.exists():
        summary_md = summary_md_path.read_text()
```

With:

```python
    # Load summary.md for the Summary tab
    if args.summary_md:
        summary_md = Path(args.summary_md).read_text()
    else:
        summary_md = ""
        wiki_campaigns_dir = Path.home() / ".nous" / "wiki" / "campaigns" / campaign_name
        summary_md_path = wiki_campaigns_dir / "summary.md"
        if summary_md_path.exists():
            summary_md = summary_md_path.read_text()
```

- [ ] **Step 3: Verify the script still runs without the flag**

Run:
```bash
python scripts/visualize_campaign.py --help
```

Expected: help output includes `--summary-md` with description. No errors.

- [ ] **Step 4: Commit**

```bash
git add scripts/visualize_campaign.py
git commit -m "feat(viz): add --summary-md flag for summary override"
```

---

### Task 2: Update `/visualize-campaign` skill with style parsing and rewrite pipeline

**Files:**
- Rewrite: `.claude/commands/visualize-campaign.md`

This is the core change. The skill needs to:
1. Always require a campaign name
2. Parse `::` for optional style intent
3. When style is absent: current behavior
4. When style is present: read canonical files → 5 parallel LLM calls → merge → write temp → pass temp paths to script

- [ ] **Step 1: Rewrite the skill**

Replace `.claude/commands/visualize-campaign.md` with:

```markdown
Visualize a Nous campaign as an interactive knowledge graph.

## Arguments

`$ARGUMENTS` format: `<campaign-name>` or `<campaign-name> :: <style intent>`

- **Campaign name** (required): The name of an indexed campaign (must exist under `~/.nous/wiki/campaigns/`)
- **Style intent** (optional): Everything after `::`. When present, all visible text in the visualization is restyled to match this tone/style. The canonical wiki data is NOT modified.

Examples:
- `/visualize-campaign epp-ttft-slope-detector`
- `/visualize-campaign epp-ttft-slope-detector :: explain like I'm a novice`
- `/visualize-campaign blis-search-algo2 :: brief and technical, no jargon expansion`

## Steps

1. **Parse arguments**: Split `$ARGUMENTS` on `::`.
   - Left side (trimmed) = campaign name. If empty, STOP and tell the user: "Please provide a campaign name. Usage: `/visualize-campaign <name>` or `/visualize-campaign <name> :: <style>`"
   - Right side (trimmed, if present) = style intent. If no `::` in arguments, style = None.

2. **Resolve paths**:
   - `wiki_dir` = `~/.nous/wiki`
   - `campaign_dir` = `~/.nous/wiki/campaigns/<campaign-name>`

3. **Verify data files exist**: Check that ALL of the following exist:
   - `<campaign_dir>/summaries.json`
   - `<campaign_dir>/concepts.json`
   - `<campaign_dir>/dead-ends.json`

   If ANY are missing, **STOP** and tell the user:
   > "This campaign hasn't been fully indexed yet. Run `/post-campaign <path>` first, then re-run `/visualize-campaign`."

   Do NOT proceed. Do NOT attempt to generate or fix any data yourself.

4. **Find the campaign source path**: Look for a directory containing `ledger.json` and `principles.json` that matches the campaign name. Search in:
   - `.nous/<campaign-name>/` relative to the current project
   - `~/Downloads/**/.nous/<campaign-name>/`
   - If not found, ask the user for the campaign source path.

5. **If no style intent** → go directly to step 7.

6. **Restyle text fields** (only when style intent is present):

   Read the canonical files:
   - `<campaign_dir>/concepts.json`
   - `<campaign_dir>/summaries.json`
   - `<campaign_dir>/dead-ends.json`
   - `<campaign_dir>/frontiers.json` (if exists)
   - `<campaign_dir>/interactions.json` (if exists)
   - `<campaign_dir>/summary.md` (if exists)

   Make **5 parallel LLM calls** to restyle text. For each call, use structured output (provide a response schema) so the LLM can ONLY fill in text strings — the structure is locked.

   **Call 1 — Concepts/Entities/Parameters definitions:**

   Prompt:
   ```
   Rewrite each "definition" field to match this style: "<style intent>"

   Keep the name fields exactly as-is. Only rewrite the definition strings.
   Preserve technical accuracy — change tone/vocabulary/depth, not meaning.
   ```

   Response schema (construct from the canonical concepts.json):
   ```json
   {
     "entities": [{"name": "<exact name>", "definition": "string"}],
     "concepts": [{"name": "<exact name>", "definition": "string"}],
     "parameters": [{"name": "<exact name>", "definition": "string"}]
   }
   ```

   Provide the original definitions as context so the LLM knows what to restyle.

   **Call 2 — Iteration summaries:**

   Prompt:
   ```
   Rewrite each narrative field to match this style: "<style intent>"

   Keep iter keys exactly as-is. Only rewrite the three text fields per iteration.
   Preserve technical accuracy.
   ```

   Response schema (construct from canonical summaries.json):
   ```json
   {
     "<iter-key>": {"what_was_tried": "string", "what_was_found": "string", "why_it_matters": "string"}
   }
   ```

   **Call 3 — Dead-ends:**

   Prompt:
   ```
   Rewrite the text fields to match this style: "<style intent>"

   Keep id and iteration fields exactly as-is. Only rewrite title, what_was_tried, why_it_failed, avoid_when.
   ```

   Response schema:
   ```json
   [{"id": "<exact>", "title": "string", "what_was_tried": "string", "why_it_failed": "string", "avoid_when": "string"}]
   ```

   **Call 4 — Frontiers + Interactions:**

   Prompt:
   ```
   Rewrite the text fields to match this style: "<style intent>"

   Keep id and related_principles fields exactly as-is.
   ```

   Response schema for frontiers:
   ```json
   [{"id": "<exact>", "title": "string", "what_was_tried": "string", "what_was_left_untried": "string", "what_to_try_next": "string"}]
   ```

   Response schema for interactions:
   ```json
   [{"id": "<exact>", "title": "string", "approach_a": "string", "approach_b": "string", "why_combine": "string", "experiment_to_run": "string"}]
   ```

   (If either file doesn't exist, skip that part of the call.)

   **Call 5 — Summary.md:**

   Prompt:
   ```
   Rewrite this campaign summary markdown to match this style: "<style intent>"

   Preserve the heading structure (# headings). Change the prose tone/vocabulary/depth.
   ```

   Response: a single markdown string.

   **Merge and write temp files:**

   For each successful call:
   - Deep copy the canonical file
   - Replace only the text fields with the restyled versions (matched by `name` for concepts, by `id` for insights, by key for summaries)
   - All structural fields (`principles`, `operates_on`, `parent_concept`, `parameters`, `evolution`, `source`, `related_principles`, `iteration`) remain unchanged
   - Write to `/tmp/nous-viz-styled-<campaign-name>/`

   If a call fails or returns unexpected structure, use the canonical file for that component and emit a warning.

7. **Run the visualization script**:

   If style was applied (step 6 completed):
   ```bash
   python scripts/visualize_campaign.py "<campaign_source_path>" \
     --concepts /tmp/nous-viz-styled-<campaign-name>/concepts.json \
     --summaries /tmp/nous-viz-styled-<campaign-name>/summaries.json \
     --insights /tmp/nous-viz-styled-<campaign-name>/insights.json \
     --summary-md /tmp/nous-viz-styled-<campaign-name>/summary.md
   ```

   If no style (canonical):
   ```bash
   python scripts/visualize_campaign.py "<campaign_source_path>" \
     --summaries ~/.nous/wiki/campaigns/<campaign-name>/summaries.json \
     --concepts ~/.nous/wiki/campaigns/<campaign-name>/concepts.json
   ```

8. **Open the HTML**:
   ```bash
   open ~/.nous/wiki/viz/<campaign-name>.html
   ```

9. **Report** the output path.

## Important

- This skill does NOT modify any wiki files or registry data.
- Style restyling is ephemeral — it only affects the generated HTML, not the stored JSON.
- If style is present, the 5 LLM calls happen in parallel for speed.
- If any restyle call fails, that file falls back to canonical text with a warning.
```

- [ ] **Step 2: Verify the skill file is valid markdown**

Read back the file and check for formatting issues.

- [ ] **Step 3: Commit**

```bash
git add .claude/commands/visualize-campaign.md
git commit -m "feat(viz): add style customization to /visualize-campaign skill"
```

---

### Task 3: Update `/post-campaign` to pass style through

**Files:**
- Modify: `.claude/commands/post-campaign.md` (step 11, around line 282-288)

- [ ] **Step 1: Update step 11 to forward the style argument**

In `.claude/commands/post-campaign.md`, replace step 11:

```markdown
11. **Generate visualization and open**: Only after ALL indexing steps (4-10) are complete, run the visualization script. The script reads insights from per-campaign JSON files.
    ```bash
    python scripts/visualize_campaign.py "<campaign_path>" \
      --summaries ~/.nous/wiki/campaigns/<campaign-name>/summaries.json \
      --concepts ~/.nous/wiki/campaigns/<campaign-name>/concepts.json
    ```
    The script generates `~/.nous/wiki/viz/<campaign-name>.html` and opens it in the browser.
```

With:

```markdown
11. **Generate visualization and open**: Only after ALL indexing steps (4-10) are complete, invoke `/visualize-campaign` to generate and open the HTML.

    If `$ARGUMENTS` contained a `::` delimiter (style intent), pass it through:
    - Without style: invoke `/visualize-campaign <campaign-name>`
    - With style: invoke `/visualize-campaign <campaign-name> :: <style intent>`

    The visualization skill handles running the script, applying any style, and opening the browser.
```

- [ ] **Step 2: Add style parsing note at the top of the skill**

After step 1 ("Find the campaign"), add a note about `::` parsing. Before the existing step 1 content, add:

```markdown
   **Style passthrough**: If `$ARGUMENTS` contains `::`, split on it. The left side is the campaign path. The right side is the style intent — it is ignored during indexing (steps 2-10) and only forwarded to `/visualize-campaign` in step 11.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/commands/post-campaign.md
git commit -m "feat(viz): pass style intent through /post-campaign to visualization"
```

---

### Task 4: Manual integration test

**Files:** None (verification only)

- [ ] **Step 1: Test canonical mode (no style)**

Run:
```bash
python scripts/visualize_campaign.py .nous/<some-campaign>/ \
  --summaries ~/.nous/wiki/campaigns/<name>/summaries.json \
  --concepts ~/.nous/wiki/campaigns/<name>/concepts.json
```

Expected: HTML generated and opens in browser. Same as before.

- [ ] **Step 2: Test --summary-md flag**

Create a test file:
```bash
echo "# Test Summary\n\nThis is a test." > /tmp/test-summary.md
python scripts/visualize_campaign.py .nous/<some-campaign>/ \
  --summaries ~/.nous/wiki/campaigns/<name>/summaries.json \
  --concepts ~/.nous/wiki/campaigns/<name>/concepts.json \
  --summary-md /tmp/test-summary.md
```

Expected: HTML generated. Summary tab shows "Test Summary / This is a test." instead of the real summary.

- [ ] **Step 3: Test the full style flow via skill**

Invoke: `/visualize-campaign <campaign-name> :: explain like I'm a novice`

Expected:
- Skill reads canonical files
- Makes parallel LLM calls
- Writes temp files
- Runs script with temp paths
- HTML opens with restyled text
- Wiki files remain unchanged

- [ ] **Step 4: Test failure fallback**

Invoke with an edge case where a file is missing (e.g., no `frontiers.json`):
`/visualize-campaign <campaign-name> :: simplify for a manager`

Expected: Skill warns about missing frontiers, uses canonical for that section, rest is restyled.
