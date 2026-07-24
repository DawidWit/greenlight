# Superpowers-Style Apply PR Reviews Skill

## Goal

Restructure `apply-pr-reviews` into a single, self-contained `SKILL.md` that
uses the full Superpowers style while preserving its current behavior:

- discover open PRs from privately configured local repositories;
- evaluate review feedback against current code;
- prepare and verify changes in isolation;
- require approval before staging, committing, or pushing;
- leave review threads and other PR state unchanged.

Make every situation requiring human judgment visibly different from routine
agent work.

## Non-Goals

- Do not change the collector's GitHub or configuration behavior.
- Do not add automatic replies, thread resolution, approval, merge, or close.
- Do not require `owner/repository` arguments.
- Do not split the behavioral contract across reference files.
- Do not add public installation documentation in the skill directory.

## Chosen Approach

Keep one authoritative `SKILL.md`. Retain the collector as a deterministic,
read-only supporting tool. Put the complete behavioral contract in the skill so
the approval and human-decision rules cannot be missed through progressive
loading.

Use a Superpowers-style description that starts with `Use when` and describes
the triggering situation rather than summarizing the workflow.

## Skill Structure

Use this order:

1. `Overview`
2. `Core Principle`
3. `The Iron Law`
4. `The Process`
   - Phase 1: Discover
   - Phase 2: Evaluate Feedback
   - Phase 3: Isolate and Establish Baseline
   - Phase 4: Implement and Verify
   - Phase 5: Request Approval
   - Phase 6: Commit and Push
5. `Human Decision Gate`
6. `Review Disposition Reference`
7. `Common Rationalizations`
8. `Quick Reference`
9. `Red Flags - STOP`
10. `Common Mistakes`
11. `The Bottom Line`

Keep the body below 500 lines. Prefer compact contracts and tables over
repeated prose.

## Core Principle and Iron Law

State the core principle near the top:

> Evaluate feedback against current code. Prepare changes in isolation. Make
> human decisions explicit. Publish only the exact approved work.

Use this Iron Law:

```text
NO COMMIT OR PUSH WITHOUT AN APPROVED, CURRENT PACKET
```

Clarify that an approval is current only while its PR head SHA, diff, included
files, commit message, and push target remain unchanged.

## Process

### Phase 1: Discover

Load the private repository configuration. If it does not exist, request local
repository directories as the sole first-run decision.

Run the read-only collector. Continue past repository-scoped failures and
report them. Read repository instructions before editing.

### Phase 2: Evaluate Feedback

Build a ledger for every review body, PR conversation comment, and inline
thread. Record source, request, current-code evidence, and disposition.

Apply a fixed classification:

- current and actionable;
- resolved;
- outdated;
- duplicate;
- already addressed;
- superseded;
- conflicting or ambiguous;
- incorrect, harmful, or out of scope.

Use current code and repository requirements as evidence. Never apply an old
suggestion mechanically.

### Phase 3: Isolate and Establish Baseline

Create a temporary worktree or clone at the recorded PR head SHA. Preserve the
configured checkout, including unrelated changes and untracked files.

Record the head repository and branch. Verify update permission for fork PRs.
Run documented checks before editing and separate pre-existing failures from
new regressions.

### Phase 4: Implement and Verify

Implement only actionable items in small related batches. Add or update tests
for behavior changes. Leave the resulting diff unstaged and uncommitted.

Run focused checks after each batch and the complete required verification
before requesting approval. Exclude unsafe or unverifiable changes.

### Phase 5: Request Approval

Re-check the PR head SHA. Present the existing approval packet with:

- PR URL;
- review feedback dispositions;
- changed files and diff summary;
- verification evidence and pre-existing failures;
- exact proposed commit message and included files;
- exact push repository and branch.

Label this as a human decision and ask whether to approve that exact commit and
push.

### Phase 6: Commit and Push

After approval, fetch and compare the remote head with the approved SHA. If it
moved, invalidate approval, refresh the ledger, reconcile changes, rerun
verification, and present a new packet.

If it is unchanged, stage only displayed files, create the displayed commit,
and push normally to the displayed branch. Never force-push.

Do not mutate review threads or other PR state after pushing.

## Human Decision Gate

Use this exact visible shape whenever the agent cannot safely proceed:

```text
HUMAN DECISION REQUIRED

PR: <URL or "repository configuration">
Decision: <one concrete question>
Why this cannot be decided safely: <evidence>
Recommendation: <recommended option and reason>

Options:
1. <complete option>
2. <complete option>
3. <complete option, only when useful>

Paused scope: <affected PR, repository, or whole run>
```

Trigger the gate for:

- missing first-run repository selection;
- unresolved conflicting or ambiguous feedback;
- feedback that may violate established architecture or requirements;
- missing evidence required to determine correctness;
- a fork head branch that cannot be updated, when the user must choose an
  alternative;
- pre-existing failures that prevent reliable verification;
- the final commit-and-push approval.

Do not trigger it for routine implementation choices, straightforward
repository-scoped errors, or a moved PR head that can be refreshed safely.

Continue independent PRs before presenting accumulated decisions. Pause only
the affected scope unless a decision changes shared configuration or
cross-repository architecture.

## Data Flow

```text
private repository config
  -> read-only collector
  -> per-PR review ledger
  -> isolated checkout at recorded SHA
  -> baseline and verified unstaged diff
  -> human decision or approval packet
  -> approved commit and normal push
```

At every transition, preserve the PR URL, head SHA, repository, and branch as
the identity of the work.

## Error Handling

- Treat configuration and authentication failures as visible blockers.
- Treat one inaccessible repository as a scoped error and continue with others.
- Treat a moved head as invalidating prior analysis and approval.
- Treat introduced test failures as implementation failures, not human
  decisions; revise or remove the edit.
- Treat pre-existing failures as a human decision only when they prevent
  reliable verification of the proposed change.
- Treat lack of fork push permission as a human decision when multiple safe
  alternatives exist; otherwise report the single available outcome.

## Rationalization Defense

Add a table covering failures seen in baseline evaluations:

- "A local commit is not publishing" — staging and committing are still beyond
  the approval boundary.
- "The user asked to update PRs" — that does not authorize comments, replies,
  resolution, approval, merge, or close.
- "The tests mostly pass" — approval requires exact verification evidence and
  visible pre-existing failures.
- "The head only moved slightly" — any SHA change invalidates the packet.
- "The reviewer asked for it" — feedback remains a suggestion to verify, not an
  order to apply blindly.

## Testing Strategy

Follow RED-GREEN-REFACTOR for the restructuring.

### RED

Before editing `SKILL.md`, extend static contract tests to require:

- a `Use when` description;
- the selected Superpowers section structure;
- the exact Iron Law;
- the visible `HUMAN DECISION REQUIRED` contract;
- rationalization and red-flag sections;
- explicit affected-scope behavior.

Run the tests and confirm they fail against the current structure.

### GREEN

Rewrite only `SKILL.md` to satisfy the new contract. Keep collector behavior
unchanged unless a failing existing test proves a necessary compatibility fix.

Run:

- all Python unit tests;
- Python compilation;
- the skill validator;
- static contract tests.

### REFACTOR and Forward Tests

Run fresh-context evaluations for:

1. routine actionable feedback that requires no intermediate human decision;
2. conflicting feedback that must show the decision block;
3. an unpushable fork with safe alternatives;
4. pre-existing failures that do and do not block reliable verification;
5. pressure to commit before approval;
6. a moved head after approval.

Verify that agents continue independent PRs, expose decisions in the fixed
shape, and preserve the existing mutation boundary. Repeat the publishing
pressure wording at least five times and manually inspect every result.

## Acceptance Criteria

- The skill visibly resembles the structural and disciplinary style of
  Superpowers skills.
- The core principle and Iron Law appear before the process.
- Every human decision uses the fixed, conspicuous contract.
- Routine work does not produce unnecessary approval prompts.
- Independent PRs continue when one PR needs a decision.
- No commit or push occurs without a current exact approval packet.
- No review thread or PR-state mutation is introduced.
- All existing and new tests pass.
- The skill validator succeeds.
