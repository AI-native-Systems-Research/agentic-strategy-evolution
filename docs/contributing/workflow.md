# Claude-Based PR Creation Workflow

This document defines the standard workflow for contributors using Claude Code to address issues and create pull requests in this repository.

---

## Overview

Any contributor with Claude Code should follow this workflow when working on an issue. It combines AI-assisted planning and review with explicit human approval gates to produce consistent, high-quality contributions.

---

## Step 1: Create a Worktree

**Before any work**, isolate your changes in a dedicated git worktree. The main worktree is never touched during development.

```
/superpowers:using-git-worktrees
```

This creates an isolated copy of the repo in a separate directory. All subsequent steps happen inside this worktree.

---

## Step 2: Analyze the Issue and Source Code

Inside the worktree, before writing any plan or code:

- Read the issue carefully and identify the exact problem or feature requested.
- Explore the relevant source files and understand the existing structure.
- Note affected files, dependencies, edge cases, and risks.

```bash
# Example: search for relevant patterns
grep -r "keyword" src/
```

---

## Step 3: Plan with `/superpowers:writing-plans`

Invoke the planning skill to produce a structured implementation plan saved to `docs/plans/`:

```
/superpowers:writing-plans
```

- Plans are saved to `docs/plans/YYYY-MM-DD-<feature-name>-plan.md`.
- The plan must include: goal, architecture, exact file paths, step-by-step tasks with code, and a commit message per task.
- `docs/plans/` is listed in `.gitignore` — plan files never appear in PRs.

---

## Step 4: Review the Plan with an Agent

Have an agent critique the plan before presenting it to the human:

```
/research-ideas:_review-plan
```

The agent should check for:
- Missing steps or ambiguities
- Edge cases not covered
- Consistency with existing repo patterns

Incorporate feedback into the plan before proceeding.

---

## Step 5: Human Gate

**Do not write any implementation code before this step is complete.**

Summarize the finalized plan for the human contributor:

1. State the issue being addressed.
2. List the files that will be created or modified.
3. Describe the approach in 2–3 sentences.
4. Show the task breakdown at a high level.

**Wait for explicit human approval** (e.g., "looks good", "proceed") before moving to Step 6.

---

## Step 6: Implement Step by Step

Follow the approved plan, one task at a time:

- Mark each task complete before starting the next.
- Keep changes focused — no scope creep.
- Commit after each task using the message from the plan.
- Run tests after each task if applicable.

```
/superpowers:subagent-driven-development
```

---

## Step 7: Review the Implementation

Once all tasks are complete, run a full review before opening the PR:

```
/pr-review-toolkit:review-pr
```

This checks adherence to the plan, code quality, test coverage, and comment accuracy. Address all issues found before proceeding.

---

## Step 8: Create the PR

Push changes to a branch in your fork and open a PR to the upstream repository.

```bash
# Branch naming convention
git checkout -b feat/issue-<number>-<short-description>
git push -u origin feat/issue-<number>-<short-description>

# Open PR to upstream
gh pr create \
  --repo AI-native-Systems-Research/agentic-strategy-evolution \
  --title "<concise title>" \
  --body "$(cat <<'EOF'
## Summary
- <what this does>
- <why>

## Related Issue
Closes #<issue-number>

## Test Plan
- [ ] <verification step>

🤖 Generated with [Claude Code](https://claude.ai/claude-code)
EOF
)"
```

**PR checklist before submitting:**
- [ ] Worktree was used — main worktree untouched
- [ ] Plan was reviewed by agent and approved by human gate
- [ ] All plan tasks completed and committed
- [ ] `/pr-review-toolkit:review-pr` passed

---

## Quick Reference

| Step | Action | Skill / Command |
|------|--------|-----------------|
| 1 | Create worktree | `/superpowers:using-git-worktrees` |
| 2 | Analyze issue + code | Read files, grep, explore |
| 3 | Write plan | `/superpowers:writing-plans` |
| 4 | Review plan | `/research-ideas:_review-plan` |
| 5 | Human approval | Summarize + wait |
| 6 | Implement | `/superpowers:subagent-driven-development` |
| 7 | Review implementation | `/pr-review-toolkit:review-pr` |
| 8 | Create PR | `gh pr create` to upstream |
