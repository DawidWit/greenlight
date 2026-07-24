---
name: apply-pr-reviews
description: Collects and applies actionable feedback from GitHub pull request reviews across user-configured local repositories. Use when the user asks to process, address, implement, or fix review comments on all or selected open PRs, including unresolved, outdated, duplicate, or conflicting feedback.
---

# Apply PR Reviews

## Overview

Process open pull requests authored by the authenticated GitHub user. Discover
repositories from private local configuration, evaluate every review item
against the current PR head, prepare and verify edits in isolation, then obtain
explicit approval before committing or pushing.

Require Python 3.9 or newer, Git, GitHub CLI (`gh`), and an authenticated GitHub
CLI session. Resolve `<skill-directory>` from the location of this `SKILL.md`.

## Configure Repositories

Use local repository directories as the user-facing identifiers. Do not ask the
user to type `owner/repository` names.

1. Check for `repositories.json` at the default path reported by:

   ```text
   python3 <skill-directory>/scripts/collect_reviews.py show-config
   ```

2. When configuration is missing, ask the user to choose one or more local
   repository directories. This is the only required first-run question.
3. After the user chooses, configure them:

   ```text
   python3 <skill-directory>/scripts/collect_reviews.py configure <local-path>...
   ```

4. Explain that configuration is private, stored outside the skill, and derived
   from each repository's `origin` remote.
5. Reconfigure only when the user asks to change the selected repositories.

## Workflow

### 1. Collect Read-Only Context

Run:

```text
python3 <skill-directory>/scripts/collect_reviews.py collect
```

The collector only reads local Git configuration and GitHub data. It returns
open PRs authored by `@me`, current head metadata, submitted reviews, PR
conversation comments, and paginated review threads with resolved and outdated
state.

For every configured local repository:

- Read applicable repository instructions before editing.
- Preserve its current branch, index, working tree, and untracked files.
- Report a missing directory, invalid remote, authentication error, or
  inaccessible repository; continue with independent repositories.
- Stop with a concise report when there are no matching open PRs.

### 2. Build a Review Ledger

Evaluate every review body, PR conversation comment, and inline thread against
the current PR head. Record the review URL, author, requested behavior, current
location, disposition, and evidence.

| State | Action |
|---|---|
| Current and actionable | Implement the underlying request. |
| Resolved | Verify the concern remains addressed; do not redo it. |
| Outdated | Map the concern to current code; apply only if still relevant. |
| Duplicate | Implement once and associate all duplicates with that change. |
| Already addressed | Make no edit; record the current code or commit as evidence. |
| Superseded | Follow the latest explicit reviewer or author decision. |
| Conflicting or ambiguous | Do not guess; include it as a decision needed. |
| Incorrect, harmful, or out of scope | Skip it and give a technical reason. |

Never apply a suggestion mechanically from its old line number or patch. Follow
the repository's current architecture, instructions, and tests.

### 3. Isolate Each PR

Process one PR at a time in a separate temporary worktree or temporary clone
created from its exact recorded head SHA.

- Never switch branches, stash, reset, clean, or edit the configured checkout.
- Record the initial head SHA, head repository, and head branch.
- For a fork PR, verify the authenticated user owns or can update the head
  branch. Otherwise prepare a patch and report that push is unavailable.
- If the remote head moves before editing, refresh the review ledger and start
  from the new head.

### 4. Establish a Baseline and Edit

Run the repository's documented focused and required checks before editing.
Record pre-existing failures separately.

Implement only actionable ledger items in small related batches:

- Add or update tests when feedback changes behavior.
- Keep generated files consistent with repository instructions.
- Avoid unrelated cleanup and formatting churn.
- Inspect the diff and run focused checks after each batch.
- Leave changes unstaged and uncommitted.

Run the complete required verification. If an edit introduces a failure,
diagnose and revise it. If the request cannot be implemented safely, exclude
that edit and report the exact blocker. Never publish failing changes.

### 5. Present the Approval Packet

Before requesting approval, re-check that the PR head still matches the initial
SHA. Present one packet per PR containing:

- **PR URL**
- **review feedback:** applied, already addressed, skipped, and decisions needed
- **changed files:** diff summary and any generated files
- **verification:** commands, results, and pre-existing failures
- **proposed commit:** exact message and included files
- **exact push target:** head repository and branch

Ask: `Approve this exact commit and push for this PR?`

Approval applies only to the displayed PR, diff, commit message, and push
target. A clear approval for a displayed batch may cover that exact batch.

## Mutation Boundary

Until approval is received, do not run `git add`, `git commit`, or `git push`.
Do not reply to review threads, resolve review threads, post PR comments,
approve, merge, close, or otherwise mutate GitHub.

After approval:

1. Fetch and compare the remote head to the approved SHA.
2. If it changed, invalidate the approval, refresh the ledger, reconcile the
   edits, rerun verification, and present a new packet.
3. Stage only the displayed files.
4. Create the displayed commit.
5. Push normally to the exact displayed head branch. Never force-push.
6. Confirm the pushed SHA and report updated checks.

Even after approval, do not reply to review threads, resolve review threads,
post comments, approve, merge, or close the PR. Those actions require a
separate explicit request.

## Example

User: `Process the reviews on my open PRs.`

On first use, ask for local repository directories and save them with the
collector. On later uses, load the saved selection, prepare each PR in
isolation, and stop at an approval packet. Do not require repository arguments
in the invocation.

## Common Mistakes

| Mistake | Correction |
|---|---|
| Treating every comment as current | Re-evaluate the underlying concern against the current head. |
| Committing before approval | Keep the verified diff unstaged until the packet is approved. |
| Treating approval as reusable | Bind it to the exact SHA, diff, message, and push target. |
| Editing a user's checkout | Use a temporary worktree or clone. |
| Pushing after the head moved | Refresh, verify again, and request new approval. |
| Resolving threads after pushing | Report outcomes only; leave GitHub discussions unchanged. |
