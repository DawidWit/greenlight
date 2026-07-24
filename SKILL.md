---
name: apply-pr-reviews
description: Use when addressing GitHub pull request review feedback across configured repositories, especially when reviews are unresolved, outdated, duplicated, conflicting, or require verified code changes
---

# Apply PR Reviews

## Overview

Process open pull requests authored by the authenticated GitHub user. Evaluate
feedback against current code, prepare verified changes in isolated workspaces,
persist local handoff context, and publish only exact approved work.

Require Python 3.9+, Git, GitHub CLI (`gh`), and an authenticated `gh` session.
Resolve `<skill-directory>` from this `SKILL.md`.

## Core Principle

**Evaluate feedback against current code. Prepare changes in isolation. Make
human decisions explicit. Publish only the exact approved work.**

## The Iron Law

```text
NO COMMIT OR PUSH WITHOUT AN APPROVED, CURRENT PACKET
```

A packet is current only while its PR head SHA, diff, files, commit message,
and push target remain unchanged.

Current approval is required before `git add`, `git commit`, or `git push`.

## The Process

Complete every phase in order for each PR.

### Phase 1: Discover

1. Run `python3 <skill-directory>/scripts/collect_reviews.py show-config`.
2. If configuration is missing, use the Human Decision Gate to request local
   repository directories. Never request `owner/repository` input.
3. Configure selected paths with `collect_reviews.py configure`. The collector
   keeps them in a private `repositories.json` at the reported location.
4. Run `collect_reviews.py collect`.
5. Read repository instructions and continue past independent repository
   errors.
6. Load existing local context for every discovered PR with:

   ```text
   python3 <skill-directory>/scripts/context_store.py read \
     --repo <local-path> --pr <number>
   ```

7. Compare stored repository identity, PR number, and head SHA with current
   GitHub metadata. Revalidate stale evidence before using it.

### Phase 2: Evaluate Feedback

Build a ledger for every review body, PR conversation comment, and inline
thread. Record URL, author, requested behavior, current-code evidence, and
disposition. Use the Review Disposition Reference.

Do not apply old suggestions mechanically. Review feedback is evidence to
evaluate, not an order.

Persist the classified ledger and decision history with `context_store.py init`
for new state or `context_store.py update --expected-revision <revision>` for
existing state.

Run context-store commands against the configured local repository path, not a
temporary worktree. Pass each complete JSON state document through standard
input; never use an intermediate context file outside the Git common directory.

### Phase 3: Isolate and Establish Baseline

1. Process one PR at a time in a temporary worktree or clone at the recorded
   head SHA.
2. Preserve the configured checkout, including untracked and unrelated changes.
3. Record the head repository and branch.
4. Verify permission to update a fork head.
5. Run documented checks before editing and record pre-existing failures.
6. Persist the baseline checkpoint.

### Phase 4: Implement and Verify

Implement only actionable items in small related batches. Add or update tests
for behavior changes. Avoid unrelated cleanup. Leave every change unstaged and
uncommitted.

Run focused checks after each batch and the complete required verification.
Exclude unsafe changes and changes that introduce failures. Persist every
verified batch.

### Phase 5: Request Approval

Always persist the pending approval decision first and render the complete gate;
never merely summarize either step, even when asked to commit or push first.
Store the unanswered record in `pending_decisions` with `question` set to
`Approve this exact commit and push for this PR?`, the three `options` and
`recommendation` shown below, `scope` set to `This PR only.`, and
`packet_identity` containing PR head SHA, diff, files, commit message, and push
target. The question must be inside the stored record, not only in the displayed
gate. Persisting only the approval packet is insufficient.
Do not show the gate unless the stored `pending_decisions` entry itself contains
all five fields: `question`, `options`, `recommendation`, `scope`, and
`packet_identity`. When stating exact actions, explicitly name the
`pending_decisions` container and all five stored fields; saying only that a
pending decision or record was persisted, or listing only packet identity, is
insufficient.

Normal order: re-check the remote head SHA, build the current `packet_identity`,
persist the complete `pending_decisions` entry, then show the gate. If this
pre-gate SHA re-check finds a moved head, do not persist `pending_decisions` or
show the gate. First refresh feedback, reconcile edits, and rerun verification;
only then build and persist a new current packet and pending decision before
displaying the gate.

```text
HUMAN DECISION REQUIRED

PR: <PR URL>
Decision: Approve this exact commit and push for this PR?
Why this cannot be decided safely: Publishing changes requires human approval.
Recommendation: Approve only if the displayed evidence and target are correct.

Options:
1. Approve the exact displayed commit and push.
2. Reject it and keep the verified diff local.
3. Request changes to the proposed work.

Paused scope: This PR only.
```

Include the PR URL, review feedback dispositions, changed files, verification
evidence, pre-existing failures, exact proposed commit message and files, and
the **exact push target:** repository and branch.

### Phase 6: Commit and Push

Record the human answer before resuming. Fetch the remote head again.

If the SHA changed, invalidate approval, refresh feedback, reconcile edits,
rerun verification, persist the invalidation, and request new approval.

If unchanged, stage only displayed files, create the displayed commit, and push
normally to the displayed branch. Never force-push. Persist commit SHA, pushed
SHA, checks, and remaining decisions.

Do not reply to review threads, resolve review threads, post comments, approve,
merge, or close the PR.

## Human Decision Gate

Use this exact shape whenever safe progress requires human judgment:

```text
HUMAN DECISION REQUIRED

PR: <URL or repository configuration>
Decision: <one concrete question>
Why this cannot be decided safely: <specific evidence>
Recommendation: <recommended option and reason>

Options:
1. <complete option>
2. <complete option>
3. <complete option, only when useful>

Paused scope: <affected PR, repository, or whole run>
```

Persist the pending decision before showing it and the exact answer before
resuming. Trigger the gate for missing repository selection, unresolved
conflicts, architecture-sensitive feedback, missing correctness evidence,
unpushable forks with alternatives, verification-blocking baseline failures,
and final publish approval.

Do not trigger it for routine implementation choices, scoped repository errors,
or a moved head that can be refreshed safely. Continue independent PRs before
presenting accumulated decisions.

## Local Decision Ledger

Store one authoritative document at:

```text
<git-common-dir>/apply-pr-reviews/pr-<number>/state.json
```

Resolve the root with `git rev-parse --git-common-dir`. This keeps context local,
private, uncommittable, and shared by worktrees.

At takeover:

1. Load existing local context and decision history.
2. Compare its head SHA with the current remote head.
3. Reuse evidence that still matches current code.
4. Revalidate stale evidence and mark superseded conclusions.
5. Preserve human decisions only while their assumptions hold.

Use `scripts/context_store.py`; never edit `state.json` directly. Every update
must supply the expected revision. On a revision conflict or lock, stop the
affected PR, reload, reconcile, and retry. Never break a lock automatically.

Every complete state document has these top-level fields:
`schema_version`, `revision`, `repository`, `pull_request`, `phase`, `status`,
`review_ledger`, `changes`, `verification`, `pending_decisions`,
`decision_history`, `approval`, `publication`, and `updated_at`.

`repository` contains `name_with_owner` and the configured `local_path`.
`pull_request` contains `number`, `url`, `base_branch`, `head_repository`,
`head_branch`, and `head_sha`. Each decision-history entry contains `revision`,
`timestamp`, `decision_type`, `evidence`, `options`, `recommendation`, `answer`,
`scope`, and `transition`. Keep decision history append-only.

Persist after classification, baseline, each verified batch, before and after a
human decision, before approval, after head invalidation, and after commit,
push, failure, or intentional stop.

The ledger is handoff evidence, not authority to bypass verification.

## Review Disposition Reference

| State | Action |
|---|---|
| Current and actionable | Implement and verify. |
| Resolved | Verify it remains addressed; do not redo it. |
| Outdated | Map the concern to current code; apply only if relevant. |
| Duplicate | Implement once and associate every duplicate. |
| Already addressed | Record current code or commit as evidence. |
| Superseded | Follow the latest explicit reviewer or author decision. |
| Conflicting or ambiguous | Use the Human Decision Gate. |
| Incorrect, harmful, or out of scope | Skip with technical evidence. |

## Common Rationalizations

| Excuse | Reality |
|---|---|
| "A local commit is not publishing." | Staging and committing are beyond the approval boundary. |
| "The user asked to update PRs." | That does not authorize comments, resolution, approval, merge, or close. |
| "The tests mostly pass." | Show exact evidence and any pre-existing failures. |
| "The head only moved slightly." | Any SHA change invalidates the packet. |
| "The reviewer requested it." | Verify suggestions against current code. |
| "The previous agent decided." | Reuse evidence; revalidate changed assumptions. |
| "My memory is newer." | The on-disk revision wins; reload before writing. |

## Quick Reference

| Situation | Required action |
|---|---|
| Missing repository configuration | Human Decision Gate for local paths |
| Ambiguous or conflicting feedback | Persist and show Human Decision Gate |
| Dirty configured checkout | Use isolated work; never alter the checkout |
| Existing context | Load, compare SHA, and revalidate |
| Revision conflict | Reload and reconcile |
| Introduced test failure | Revise or remove the edit |
| Blocking pre-existing failure | Persist and show Human Decision Gate |
| Ready to publish | Persist and show exact approval packet |
| Head moved | Invalidate approval and verify again |

## Red Flags - STOP

- Staging, committing, or pushing before exact approval
- Applying feedback from an old line without checking current code
- Editing, stashing, resetting, or cleaning the configured checkout
- Ignoring local handoff state
- Overwriting a newer state revision
- Breaking a context lock automatically
- Proceeding while correctness evidence is missing
- Treating old human decisions as valid after their assumptions changed
- Force-pushing
- Mutating review threads or PR state without a separate request

**Any red flag means stop the affected scope and return to the required phase.**

## Common Mistakes

| Mistake | Correction |
|---|---|
| Asking for `owner/repository` | Ask once for local repository directories. |
| Treating all comments as current | Re-evaluate concerns against current code. |
| Committing before approval | Keep the verified diff unstaged. |
| Asking about routine choices | Decide routine implementation locally. |
| Hiding a needed decision in prose | Use the exact Human Decision Gate. |
| Trusting stale context | Compare SHA and revalidate evidence. |
| Cleaning a user checkout | Work in isolation. |

## The Bottom Line

**Evaluate. Persist. Verify. Show human decisions. Publish only exact approved
work.**
