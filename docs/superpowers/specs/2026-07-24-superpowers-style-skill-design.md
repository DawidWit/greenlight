# Superpowers-Style Apply PR Reviews Skill

## Goal

Restructure `apply-pr-reviews` into a single, self-contained `SKILL.md` that
uses the full Superpowers style while preserving its current behavior:

- discover open PRs from privately configured local repositories;
- evaluate review feedback against current code;
- prepare and verify changes in isolation;
- require approval before staging, committing, or pushing;
- preserve decisions and handoff context locally for later agents;
- leave review threads and other PR state unchanged.

Make every situation requiring human judgment visibly different from routine
agent work.

## Non-Goals

- Do not change the collector's GitHub or configuration behavior.
- Do not add automatic replies, thread resolution, approval, merge, or close.
- Do not require `owner/repository` arguments.
- Do not split the behavioral contract across reference files.
- Do not add public installation documentation in the skill directory.
- Do not commit, push, or otherwise synchronize the decision ledger.

## Chosen Approach

Keep one authoritative `SKILL.md`. Retain the collector as a deterministic,
read-only supporting tool. Add a deterministic local context-store script for
validated, atomic state updates. Put the complete behavioral contract in the
skill so the approval and human-decision rules cannot be missed through
progressive loading.

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
6. `Local Decision Ledger`
7. `Review Disposition Reference`
8. `Common Rationalizations`
9. `Quick Reference`
10. `Red Flags - STOP`
11. `Common Mistakes`
12. `The Bottom Line`

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

Define `packet_identity` as exactly `head_repository`, `head_branch`,
`head_sha`, `diff_sha256`, `included_files`, and `commit_message`.
`diff_sha256` is a lowercase deterministic SHA-256 of canonical patch bytes,
including untracked-file patches. Approval is current only while every field
matches the current PR target and changes before commit, or while an authorized
commit/push lifecycle retains and validates that exact pre-commit packet.

## Process

### Phase 1: Discover

Load the private repository configuration. If it does not exist, request local
repository directories as the sole first-run decision.

Run the read-only collector. Continue past repository-scoped failures and
report them. Read repository instructions before editing.

For each discovered PR, load existing local context from the repository's Git
common directory. Validate its repository identity, PR number, and recorded
head SHA before using it.

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
new regressions. Persist the isolated workspace identity as exactly `kind`,
absolute `path`, `base_sha`, and `head_sha`; both SHAs equal the PR head at
which the workspace was created.

### Phase 4: Implement and Verify

Implement only actionable items in small related batches. Add or update tests
for behavior changes. Leave the resulting diff unstaged and uncommitted.

Run focused checks after each batch and the complete required verification
before requesting approval. Exclude unsafe or unverifiable changes.

### Phase 5: Request Approval

Re-check the PR head SHA and require the real index to be empty. Run
`context_store.py fingerprint --source working` against the recorded isolated
workspace and the exact included files. The command requires
the workspace HEAD, `base_sha`, and packet `head_sha` to agree. It
deterministically covers tracked changes, deletions, untracked files, file
contents, and file modes, and rejects unchanged, missing, escaping, or
unsupported paths. Working mode uses a temporary Git index to write an
immutable tree and does not mutate the real index or read included paths
directly after snapshot creation.

The canonical byte stream begins `apply-pr-reviews-change-v1\0`. For each
sorted path, append path, base mode, base content, working mode, and working
content records. Every record is a one-byte tag, an 8-byte unsigned big-endian
payload length, and payload bytes. SHA-256 of this stream is `diff_sha256`.

Present the resulting approval packet with:

- PR URL;
- review feedback dispositions;
- changed files and diff summary;
- verification evidence and pre-existing failures;
- exact proposed commit message and included files;
- exact push repository and branch.

Label this as a human decision and ask whether to approve that exact commit and
push.

Persist the decision request before showing it so a later agent can resume from
the same evidence and paused scope.

A valid approval is not a free-standing boolean. It has exactly `valid`,
`packet_identity`, `decision_history_index`, `human_answer`, and `outcome`; it
must link to an append-only `publish-approval` history entry containing the
same complete packet and exact selected choice. The canonical ordered choice
objects are `{approved, "Approve the exact displayed commit and push."}`,
`{rejected, "Reject it and keep the verified diff local."}`, and
`{changes-requested, "Request changes to the proposed work."}`. Initialization
and takeover reject missing, reordered, duplicated, unknown, or unselected
choices and any label/outcome mismatch.

### Phase 6: Commit and Push

Branch on the stored outcome before any Git mutation. Only `approved` may
continue. `rejected` keeps the verified work local and stops publication;
`changes-requested` returns to implementation and verification. Then recompute
the fingerprint from the recorded workspace, fetch and compare the remote
target, and compare all change-identity fields. A changed head repository,
head branch, head SHA, diff SHA-256,
included-file list, or commit message requires a current-revision
`approval-invalidated` event for the old packet. Preserve invalid approval
history for audit, but never use it as publication authority. Reconcile,
reverify, and obtain a newly linked human decision for the new packet.

If unchanged, stage only included files. Run the same fingerprint operation
with `--source index`; require the entire packet identity and immutable tree to
equal the approved working snapshot, and reject extra staged paths. Create the
displayed commit C whose direct parent is approved head H and whose changed
paths, message, and tree match that snapshot.

Persist a `committed` checkpoint before push. It retains the approved H packet
and decision, records workspace base H/head C and commit C, keeps the PR head
at H, and leaves pushed SHA and publication time null. Then push normally and
re-check the remote branch head; never force-push. Only after it is C may the
checkpoint transition to `pushed`, with workspace and PR head C, commit and
pushed SHA C, and a publication timestamp. Direct-to-pushed transitions,
regressions, and incoherent fields fail closed.

Do not mutate review threads or other PR state after pushing.

Persist the final commit SHA, pushed SHA, verification result, and remaining
decisions. Keep the completed ledger for future sessions.

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

Record the user's exact answer before resuming. Treat a recorded human decision
as a constraint only while its PR identity and relevant evidence remain
current.

## Local Decision Ledger

Store context exclusively in the configured repository's Git common directory:

```text
<git-common-dir>/apply-pr-reviews/pr-<number>/
└── state.json
```

Resolve `<git-common-dir>` with `git rev-parse --git-common-dir` and normalize
relative results. This makes the ledger shared by local worktrees while keeping
it outside the tracked working tree.

Use `state.json` as the single authoritative handoff document. Include:

- schema version and monotonic revision;
- repository identity, local repository path, PR number, and PR URL;
- base branch, head repository, head branch, and recorded head SHA;
- isolated workspace kind, absolute path, base SHA, and current HEAD SHA;
- current phase and status;
- review-ledger dispositions with evidence;
- changed files, deterministic diff SHA-256, diff summary, and commit message;
- baseline and verification commands with results;
- pending human decisions and paused scope;
- append-only decision history within the document;
- approved packet identity and its validity state;
- commit and push results when completed;
- update timestamp.

Use exact nested shapes. Review entries contain `url`, `author`,
`requested_behavior`, `evidence`, and a fixed disposition. `changes` contains
`files`, `summary`, `diff_sha256`, and `commit_message`. Pending decisions
contain all five fields `question`, `options`, `recommendation`, `scope`, and
`packet_identity`; only non-publish decisions may use a null packet. Decision
history has exact `question`, `outcome`, and `recovery` fields in addition to
the existing evidence and `packet_identity`. Publish and recovery options are
canonical ordered objects with exactly `outcome` and `label`. Publication
contains `status`, `commit_sha`, `pushed_sha`, `packet_identity`,
`approval_decision_history_index`, `checks`, and `published_at`, and must link
to retained approval and its exact publish decision.

The machine disposition values are `current-and-actionable`, `resolved`,
`outdated`, `duplicate`, `already-addressed`, `superseded`,
`conflicting-or-ambiguous`, and `incorrect-harmful-or-out-of-scope`.

For every decision-history entry, record:

- timestamp and revision;
- decision type;
- evidence available at the time;
- options shown;
- recommendation;
- exact human answer, or the agent's technical disposition;
- affected scope and resulting state transition.

Add a deterministic `scripts/context_store.py` tool. Require agents to use the
tool rather than editing ledger files directly. The tool must:

- validate schema version 3, configured repository path, PR identity, and
  isolated workspace identity;
- acquire a PR-scoped lock with atomic directory creation;
- re-check the expected revision after acquiring the lock;
- append decision history and write `state.json` through one atomic replace;
- set directory permissions to `0700` and files to `0600` where supported;
- reject stale writes through an expected-revision check;
- print the current snapshot for agent takeover;
- accept state-update payloads only through standard input;
- never store or modify context outside the resolved Git common directory;
- never store secret-shaped keys or sensitive values, including raw
  environment/authentication output, authorization headers, cookies,
  credential assignments, private keys, or common credential formats;
- allow descriptive prose and safe summaries such as authentication success
  and check results, while recognizing assignments and headers only as complete
  lines and safe sentinels only as the entire optionally quoted value;
- compute canonical change fingerprints only from a matching isolated
  workspace;
- recover authorized invalid state with a locked lexical move to a contained,
  non-overwriting private backup, including when `state.json` is a dangling
  symlink;
- require the exact recovery question, human answer, and returned backup
  identity as the first history entry of fresh state.

Always release the lock in a `finally` path. Never break an existing or stale
lock automatically; report it as a scoped blocker with lock metadata so the
human can decide whether the owning process still exists.

### Takeover Rule

At the beginning of each PR:

1. Read the local snapshot and decision history.
2. Compare the recorded head SHA with the current remote head.
3. Verify `repository.local_path` and the recorded workspace path and Git HEAD.
4. Before commit, recompute the working fingerprint with an empty real index.
   For committed or pushed state, validate the commit parent, message, paths,
   tree, retained packet, and remote lifecycle checkpoint instead.
5. Reuse verified evidence that still matches current code.
6. Revalidate stale evidence and mark superseded conclusions explicitly.
7. Preserve current human decisions when their assumptions still hold.
8. Surface a new human decision when changed evidence invalidates a prior
   choice.

The ledger is a handoff and evidence store, not authority to bypass
verification.

### Write Checkpoints

Update the ledger:

- after collecting and classifying reviews;
- after establishing the baseline;
- after every implemented and verified batch;
- before showing `HUMAN DECISION REQUIRED`;
- immediately after recording the human answer;
- before requesting final publish approval;
- after a head-SHA change invalidates work or approval;
- after commit, push, failure, or intentional stop.

If another agent updated the ledger revision, stop the affected PR, reload the
new state, reconcile differences, and only then continue.

## Data Flow

```text
private repository config
  -> read-only collector
  -> existing local handoff context
  -> per-PR review ledger
  -> isolated checkout at recorded SHA
  -> baseline and verified unstaged diff
  -> human decision or approval packet
  -> atomic local context update
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
- Treat a context revision conflict as concurrent work: reload and reconcile
  instead of overwriting another agent's decisions.
- Treat corrupt or mismatched local context as a scoped blocker. Preserve the
  unreadable file and history exactly, report it with the complete
  `HUMAN DECISION REQUIRED` shape, and require explicit authorization before
  moving it to a named private backup and initializing fresh state. Never
  overwrite, delete, repair, rename, or replace it automatically.
- Because invalid state cannot safely persist its own pending record, treat
  this as the sole persistence-order exception: show the recovery gate first,
  then call `context_store.py recover` only for the exact canonical
  `backup-authorized` label/outcome choice. The canonical `leave-untouched`
  choice stops without mutation. Recovery refuses state that validates
  normally and any mismatch in the canonical question, ordered choices,
  recommendation, scope, label, or outcome. Fresh initialization must record
  all canonical recovery evidence and the returned backup identity as its
  first decision. Never move or edit invalid state directly.

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
- "The previous agent already decided" — reuse evidence, but revalidate every
  decision whose assumptions may have changed.
- "My state is newer in memory" — the on-disk revision wins; reload before
  writing.

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

Before implementing the context store, add unit tests for:

- resolving the Git common directory from normal repos and worktrees;
- keeping every state path inside that directory;
- schema and identity validation;
- atomic snapshot writes and private permissions;
- append-only decision history within the snapshot;
- expected-revision conflicts;
- active and stale lock handling;
- takeover of current context;
- invalidation when the PR head SHA changes;
- rejection of secrets and forbidden fields.

### GREEN

Rewrite `SKILL.md` and implement `scripts/context_store.py` to satisfy the new
contract. Keep collector behavior unchanged unless a failing existing test
proves a necessary compatibility fix.

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
7. a later agent taking over current context;
8. concurrent agents attempting to update the same PR revision;
9. stale context whose assumptions no longer match current code.

Verify that agents continue independent PRs, expose decisions in the fixed
shape, and preserve the existing mutation boundary. Repeat the publishing
pressure wording at least five times and manually inspect every result.

## Acceptance Criteria

- The skill visibly resembles the structural and disciplinary style of
  Superpowers skills.
- The core principle and Iron Law appear before the process.
- Every human decision uses the fixed, conspicuous contract.
- Every decision request is persisted before it is shown.
- Routine work does not produce unnecessary approval prompts.
- Independent PRs continue when one PR needs a decision.
- Later agents load and revalidate local context before acting.
- Context remains only under the Git common directory and cannot be committed.
- Concurrent agents cannot silently overwrite each other's decisions.
- No commit or push occurs without a current exact approval packet.
- No review thread or PR-state mutation is introduced.
- All existing and new tests pass.
- The skill validator succeeds.
