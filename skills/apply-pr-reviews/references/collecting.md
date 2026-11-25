# Collecting

## Configuration

Run `python3 <skill-directory>/scripts/collect_reviews.py show-config`.

If there is no configuration, ask one question through the Human Decision
Gate: which local repository directories to use. Never ask for
`owner/repository`; the script reads it from the `origin` remote. Save the
answer with `collect_reviews.py configure <path> [<path> ...]`.

## Collect

The script only reads. Its output is large, so never print it whole. Save the
output to a file and read it one PR at a time:

```text
python3 <skill-directory>/scripts/collect_reviews.py collect > <output-file>
```

The JSON has:

- `viewer`: the user's GitHub login.
- `repositories[]`: `path`, `repository`, `pull_requests[]`, or `error`.
- Each pull request: `review_threads` (each with `awaiting_reviewer`),
  `reviews`, `issue_comments`, `details` (CI in `statusCheckRollup`,
  `baseRefOid`, `commits`) and `stack` (`parent`, `merged_parent`,
  `shared_head`).
- Pull requests come parents first, so stacks are already bottom up.

A repository with `error` gets one 🔴 line in the report. Continue with the
other repositories.

## Scope

- The user names no PR: take all of them.
- The user names PRs: take those and every PR above them in their stacks.
- Drafts count.
- A PR from a fork (`isCrossRepository: true`): 🔴 `fork, not changed`, no
  work on it.
- A PR with `stack.shared_head: true`: see [rebasing.md](rebasing.md).
- A PR with no open feedback, green CI, no conflict (the local check in
  [rebasing.md](rebasing.md)) and no stack change gets one `nothing to do`
  line and no worktree.

## Repository rules

Read the rules once per repository: `CLAUDE.md`, `AGENTS.md`,
`.claude/rules/`, `.cursor/rules/`, `.github/copilot-instructions.md`,
`CONTRIBUTING.md`, and the files they point to. Use them for every fix, every
skipped comment and every verification command.

## Workspace

Never touch the user's checkout. Do not switch branches, stash, reset, commit
or create worktree branches in it.

Each PR has one fixed worktree path outside the repository:
`<temp-dir>/apply-pr-reviews/<owner>-<repo>/pr-<number>`. A worktree there is
left over from an earlier run. Remove it with `git worktree remove --force`
before you start:

```text
git -C <repository-path> worktree remove --force <worktree-path>
```

For each PR that needs work, create a detached worktree with
`git worktree add --detach` on the fetched PR head:

```text
git -C <repository-path> fetch origin
git -C <repository-path> worktree add --detach <worktree-path> <headRefOid>
```

Record the PR's `headRefOid` as its remote SHA: the push lease uses it
([publishing.md](publishing.md)).
