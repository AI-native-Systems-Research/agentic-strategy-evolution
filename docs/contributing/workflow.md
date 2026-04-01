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

This creates an isolated working directory linked to the same git repository. All subsequent steps happen inside this worktree. The worktree skill creates and checks out a branch — this is the branch you will push in Step 8.

---

## Step 2: Analyze the Issue and Source Code

Inside the worktree, before writing any plan or code:

- Read the issue carefully and identify the exact problem or feature requested.
- Explore the relevant source files and understand the existing structure.
- Note affected files, dependencies, edge cases, and risks.

When using Claude Code, use the built-in Grep tool to search rather than shell `grep`.

---

## Step 3: Plan with `/superpowers:writing-plans`

Invoke the planning skill to structure your implementation plan:

```
/superpowers:writing-plans
```

The skill guides the planning process. Save the resulting plan to `docs/plans/` using the naming convention `YYYY-MM-DD-<feature-name>-plan.md`. The plan must include: goal, architecture, exact file paths, step-by-step tasks with code, and a commit message per task.

`docs/plans/` is listed in `.gitignore` — plan files never appear in PRs.

---

## Step 4: Review the Plan with an Agent

Have an agent critique the plan before presenting it to the human. Pass the plan file path to a review agent:

```
/research-ideas:_review-plan
```

> Note: `_review-plan` is an internal sub-skill. If unavailable, ask a general-purpose agent to review the plan file directly by providing its path.

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

Invoke the subagent-driven development skill to execute the approved plan. This drives each task in sequence within the current session, using a fresh subagent per task with a review checkpoint between tasks:

```
/superpowers:subagent-driven-development
```

- Mark each task complete before starting the next.
- Keep changes focused — no scope creep.
- Commit after each task using the message from the plan.
- Run tests after each task if applicable.

---

## Step 7: Review the Implementation

Once all tasks are complete, run a comprehensive PR review using specialized agents before opening the PR:

```
/pr-review-toolkit:review-pr
```

Address all issues found before proceeding.

---

## Step 8: Create the PR

Confirm your current branch name (set by the worktree in Step 1), then push and open a PR to the upstream repository.

```bash
# Confirm branch name
git branch --show-current

# Push to your fork
git push -u origin <your-branch-name>

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
| 2 | Analyze issue + code | Read files, explore |
| 3 | Write plan | `/superpowers:writing-plans` |
| 4 | Review plan | `/research-ideas:_review-plan` |
| 5 | Human approval | Summarize + wait |
| 6 | Implement | `/superpowers:subagent-driven-development` |
| 7 | Review implementation | `/pr-review-toolkit:review-pr` |
| 8 | Create PR | `gh pr create` to upstream |
