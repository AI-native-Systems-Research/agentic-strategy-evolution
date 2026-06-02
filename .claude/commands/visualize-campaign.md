Visualize a Nous campaign as an interactive knowledge graph.

This skill is a thin wrapper around `visualize_campaign.py`. It does NO processing or understanding — all intelligence lives in `/post-campaign`. This skill only verifies prerequisites and runs the script.

## Steps

1. **Find the campaign path**: If `$ARGUMENTS` is provided, search for a directory matching that name under `.nous/` paths in the project or `~/Downloads/`. Otherwise, search for directories containing both `ledger.json` and `principles.json` under `.nous/` paths, and ask the user which to visualize.

2. **Determine campaign name**: Read `campaign.yaml` from the campaign directory to get the `run_id` value. If `campaign.yaml` doesn't exist, use the directory name.

3. **Verify data files exist**: Check that ALL of the following exist:
   - `~/.nous/wiki/campaigns/<campaign-name>/summaries.json`
   - `~/.nous/wiki/campaigns/<campaign-name>/concepts.json`
   - `~/.nous/wiki/campaigns/<campaign-name>/dead-ends.json`

   If ANY are missing, **STOP** and tell the user:

   > "This campaign hasn't been fully indexed yet. Run `/post-campaign <path>` first, then re-run `/visualize-campaign`."

   Do NOT proceed. Do NOT attempt to generate or fix any data yourself.

4. **Run the visualization script**:
   ```bash
   python scripts/visualize_campaign.py "<campaign_path>" \
     --summaries ~/.nous/wiki/campaigns/<campaign-name>/summaries.json \
     --concepts ~/.nous/wiki/campaigns/<campaign-name>/concepts.json
   ```

5. **Open the HTML**:
   ```bash
   open ~/.nous/wiki/viz/<campaign-name>.html
   ```

6. **Report** the output path.

## Important

- This skill does NOT read ledger.json, principles.json, findings.json, or any campaign data directly.
- This skill does NOT generate or modify any wiki files or JSON data.
- This skill does NOT interpret experimental results or make any decisions about content.
- If prerequisites are missing, the ONLY answer is to tell the user to run `/post-campaign`.
