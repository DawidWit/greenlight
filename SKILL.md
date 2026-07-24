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

A `packet_identity` has exactly `head_repository`, `head_branch`, `head_sha`,
`diff_sha256`, `included_files`, and `commit_message`. Build it only with
`context_store.py fingerprint` in the recorded isolated workspace. A packet is
current before commit only while every field and the pre-commit workspace
identity remain unchanged. After the approved commit, the retained pre-commit
packet remains publication authority only through the validated `committed`
and `pushed` lifecycle described in Phase 6.

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
6. Record `workspace` with exactly `kind`, absolute `path`, `base_sha`, and
   `head_sha`. Both SHAs must equal the PR head used to create the isolated
   workspace.
7. Persist the baseline checkpoint.

### Phase 4: Implement and Verify

Implement only actionable items in small related batches. Add or update tests
for behavior changes. Avoid unrelated cleanup. Leave every change unstaged and
uncommitted.

Run focused checks after each batch and the complete required verification.
Exclude unsafe changes and changes that introduce failures. Persist every
verified batch.

Persist only summarized command results and evidence. Never store raw
environment output, raw authentication output, authorization headers, cookies,
credentials, or credential material in any key or value.
Sensitive assignment and header checks apply only to true assignment/header
lines. A safe sentinel such as `redacted` or `not available` must occupy the
entire value after optional matching quotes; a safe word followed by any other
content remains unsafe. Descriptive prose that merely mentions a token or
password is allowed when it contains no credential-shaped value.

### Phase 5: Request Approval

Compute the proposed packet with:

```text
python3 <skill-directory>/scripts/context_store.py fingerprint \
  --workspace <isolated-path> --workspace-kind <worktree-or-clone> \
  --base-sha <recorded-pr-head-sha> \
  --head-repository <owner/repository> --head-branch <branch> \
  --head-sha <recorded-pr-head-sha> --commit-message <exact-message> \
  --source working \
  --file <included-file> [--file <included-file> ...]
```

The command returns the exact `workspace` and `packet_identity` to persist.
It rejects a missing or moved workspace, an incorrect base, unchanged or
missing files, paths outside the workspace, and unsupported file types.
Before the approval fingerprint, require the real Git index to be empty. The
working mode builds an immutable tree through a temporary Git index and never
stages the real index.

The canonical fingerprint begins with `apply-pr-reviews-change-v1` followed by
a NUL byte. For each lexically sorted included path, append five records in
order: path (`P`), base file mode (`M`), base content (`B`), working file mode
(`m`), and working content (`W`). Each record is its one-byte tag, an
8-byte unsigned big-endian payload length, and the exact payload bytes. Use
`missing` as the mode and empty content when one side is absent. It covers
tracked changes, deletions, untracked files, and file mode changes, including
executable bits and symlink target bytes. `diff_sha256` is the lowercase
SHA-256 of those complete canonical bytes, not a prose summary or raw command
output.

Recompute the fingerprint from the recorded isolated workspace before trusting
takeover evidence, showing approval, and publishing; any missing or mismatched
workspace fails closed.

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

The three canonical publish choices, in order, are:

1. `approved` → `Approve the exact displayed commit and push.`
2. `rejected` → `Reject it and keep the verified diff local.`
3. `changes-requested` → `Request changes to the proposed work.`

Persist each displayed choice as exactly `{outcome, label}` in this order; the
selected label and stored outcome must come from the same canonical choice.

Normal order: re-check the remote head SHA, build the current `packet_identity`,
persist the complete `pending_decisions` entry, then show the gate. If this
pre-gate SHA re-check finds a moved head, do not persist `pending_decisions` or
show the gate. First refresh feedback, reconcile edits, and rerun verification;
only then build and persist a new current packet and pending decision before
displaying the gate.

A valid approval must match the current `pull_request` target and the current
`changes` exactly, and must link to an append-only `publish-approval`
decision-history entry with the same complete `packet_identity` and the
non-empty exact `human_answer`. The entry must store the exact question, two or
three non-empty unique displayed options for a non-publish decision; a publish
decision must store exactly the three canonical choices, with the answer equal
to exactly one choice label and its matching typed `outcome`.
Store that linkage as
`decision_history_index`. Approval objects have exactly `valid`,
`packet_identity`, `decision_history_index`, `human_answer`, and `outcome`.
This current-target comparison is the pre-commit rule; the authorized H-to-C
lifecycle retains the H packet under the stricter Phase 6 commit and remote
checks.

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

Record the exact human answer and complete packet in a `publish-approval`
decision-history entry before resuming. Interpret the exact displayed-option
answer through the stored `outcome`: `approved` may continue to the final
re-check; `rejected` keeps the verified work local and stops publication;
`changes-requested` returns to implementation and verification. Never run
`git add`, `git commit`, or `git push` for a rejected or changes-requested
outcome. Reject a missing, unknown, reordered, duplicate, or unselected
canonical choice and any label/outcome mismatch. Fetch the remote head again
only for an approved outcome.

A change to the head repository, head branch, head SHA, `diff_sha256`,
`included_files`, or `commit_message` invalidates approval. Persist an
`approval-invalidated` history entry for the old packet, refresh feedback when
the head changed, reconcile edits, rerun verification, and request new
approval. Retain invalid approval history for audit, but never treat it as
publication authority. This ordinary invalidation comparison applies before
creating C; the validated lifecycle's recorded workspace and PR head transition
from H to C does not alter or invalidate the retained H packet.

If unchanged, stage only the included files and recompute with the same
fingerprint arguments except:

```text
python3 <skill-directory>/scripts/context_store.py fingerprint \
  <same packet arguments> --source index \
  --file <included-file> [--file <included-file> ...]
```

After approval, stage only the included files, fingerprint the real index, and
require its complete packet identity to equal the approved packet before
commit. The index mode rejects any extra staged path. Unstaged working-tree
drift cannot silently change the staged snapshot, and the commit tree must be
the immutable tree returned by the approved index fingerprint.

Create the exact displayed commit C. Persist a `committed` checkpoint before
push, retaining the approved pre-commit packet and decision while recording
commit SHA C and workspace HEAD C. At this checkpoint, workspace base remains
the approved head H, the PR head remains H, and `pushed_sha` and `published_at`
remain null. The checkpoint is valid only when C directly descends from H, has
the exact message and included paths, and its tree reproduces the approved
canonical fingerprint.

Push normally to the displayed branch; never force-push. Re-check that the
remote branch head is C. Only after the normal push and remote head re-check
may the checkpoint become `pushed`, with pushed SHA and PR head both C. Retain
the approved pre-commit H packet and exact decision in both lifecycle states;
record checks and remaining decisions without replacing that audit evidence.

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
3. Verify the configured `repository.local_path` and recorded `workspace`
   identity; a missing directory, mismatched Git HEAD, or state symlink fails
   closed.
4. Before commit, recompute the working fingerprint with an empty real index.
   At a `committed` or `pushed` checkpoint, instead validate the exact commit
   parent, message, changed paths, commit tree, retained pre-commit packet, and
   recorded remote lifecycle state.
5. Reuse evidence that still matches current code.
6. Revalidate stale evidence and mark superseded conclusions.
7. Preserve human decisions only while their assumptions hold.

If local state or decision history is unreadable, corrupt, or
identity-mismatched, stop that PR and show the exact scoped
`HUMAN DECISION REQUIRED` gate before replacing or removing anything. Never
overwrite, delete, repair, rename, or replace unreadable or mismatched state or
history automatically.

This recovery gate is the only pending-decision persistence exception: do not
mutate an invalid ledger to record the question. Show the gate first; after
explicit backup authorization, preserve the original in the named private
backup and make the exact recovery question and human answer the first
decision-history entry in fresh state.

```text
HUMAN DECISION REQUIRED

PR: <PR URL>
Decision: How should the preserved invalid local state be handled?
Why this cannot be decided safely: Replacing it could destroy handoff history.
Recommendation: Leave it untouched until its provenance is understood.

Options:
1. Leave the preserved state untouched and stop this PR.
2. Authorize moving the invalid state to a named private backup, then initialize fresh state.

Paused scope: This PR only.
```

The canonical recovery choices, in order, are:

1. `leave-untouched` → `Leave the preserved state untouched and stop this PR.`
2. `backup-authorized` → `Authorize moving the invalid state to a named private backup, then initialize fresh state.`

Run `recover` only when the exact selected recovery label and outcome are the
canonical `backup-authorized` choice; the `leave-untouched` choice stops the PR
without mutation. After authorization, use `recover`; never move, rename,
delete, or edit state directly.

```text
python3 <skill-directory>/scripts/context_store.py recover \
  --repo <local-path> --pr <number> --backup-name <safe-name> \
  --recovery-question <exact-displayed-question> \
  --human-answer <exact-human-answer> --outcome backup-authorized
```

The locked command moves the lexical `state.json` entry without following a
symlink, first refuses state that still validates normally, rejects any
noncanonical question, choices, recommendation, scope, label, or outcome,
refuses an existing or escaping backup name, applies private modes where
possible, and returns the exact backup identity. The recovery marker records
the exact canonical question, ordered choices, recommendation, selected label,
outcome, scope, and backup identity. Fresh `init` must make the exact authorized
recovery question, human answer, and returned backup identity the first
decision-history entry.

Use `scripts/context_store.py`; never edit `state.json` directly. Every update
must supply the expected revision. On a revision conflict or lock, stop the
affected PR, reload, reconcile, and retry. Never break a lock automatically.

Every complete state document has these top-level fields:
`schema_version` (currently `3`), `revision`, `repository`, `pull_request`,
`workspace`, `phase`, `status`, `review_ledger`, `changes`, `verification`,
`pending_decisions`, `decision_history`, `approval`, `publication`, and
`updated_at`.

`repository` contains `name_with_owner` and the configured `local_path`.
`pull_request` contains `number`, `url`, `base_branch`, `head_repository`,
`head_branch`, and `head_sha`. `workspace` contains exactly `kind`, absolute
`path`, `base_sha`, and `head_sha`. Each review-ledger entry has exactly `url`,
`author`, `requested_behavior`, `evidence`, and `disposition`. `changes` has
exactly `files`, `summary`, `diff_sha256`, and `commit_message`. `disposition`
is exactly one of `current-and-actionable`, `resolved`, `outdated`, `duplicate`,
`already-addressed`, `superseded`, `conflicting-or-ambiguous`, or
`incorrect-harmful-or-out-of-scope`. Every pending
decision has exactly `question`, `options`, `recommendation`, `scope`, and
`packet_identity`; use `null` packet identity only for non-publish decisions.
Publish and recovery `options` are the canonical ordered choice objects with
exactly `outcome` and `label`; other decisions retain their exact displayed
string options.
Each decision-history entry contains `revision`, `timestamp`, `decision_type`,
`evidence`, `options`, `recommendation`, `answer`, `scope`, `transition`,
`packet_identity`, `question`, `outcome`, and `recovery`. A publish decision
requires the exact packet, question, canonical options, answer, and matching
typed outcome. Publication has exactly `status`, `commit_sha`, `pushed_sha`,
`packet_identity`,
`approval_decision_history_index`, `checks`, and `published_at`, and links to
the same publish decision. `status` is `committed` or `pushed`; its nullable
fields and workspace/PR SHA relationships follow Phase 6. Keep decision
history append-only.

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
- Replacing corrupt or mismatched state without the scoped human decision
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
