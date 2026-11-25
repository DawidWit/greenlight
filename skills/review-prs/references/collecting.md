# Collecting

## Configuration

Run `python3 <skill-directory>/scripts/collect_review_requests.py show-config`.

If there is no configuration, run `collect_review_requests.py suggest-config`.
It prints the repository paths already configured for `apply-pr-reviews`, if
any. Ask one question through the Human Decision Gate: which local repository
directories to use, with those paths as the recommendation. Never ask for
`owner/repository`. Save the answer with
`collect_review_requests.py configure <path> [<path> ...]`.

## Collect

The script only reads from GitHub. Its output can be large: save it to a file
and read it one PR at a time.

```text
python3 <skill-directory>/scripts/collect_review_requests.py collect > <output-file>
```

Without options it collects open, non-draft PRs that request the user's
review, directly or through a team. When the user names PRs, collect only
those, requested or not, with `collect --pr <owner/repo>#<number>` (repeat
`--pr` for each). GitHub drops the review request after a review, so a named
PR is the usual way to review a PR again.

The JSON has:

- `viewer`: the user's GitHub login.
- `repositories[]`: `path`, `repository`, `pull_requests[]`, or `error`.
- Each pull request: `number`, `title`, `url`, `author`, `headRefName`,
  `baseRefName`, `details` (`headRefOid`, `baseRefOid`, `body`,
  `isCrossRepository`, `commits`, `statusCheckRollup`), `ticket_keys`,
  `related_prs` (open and merged PRs with the same ticket key),
  `last_review` (or `null`), `threads.mine`, `threads.open_others`,
  `review_bodies` and `conversation`. A PR that could not be collected has
  `error` instead: show it in the list header and skip it.

## Workspace

Never touch the user's checkout. Each PR gets one fixed, read-only worktree
outside the repository: `<temp-dir>/review-prs/<owner>-<repo>/pr-<number>`.
Fetch the head through `pull/<number>/head`, which also works for PRs from
forks:

```text
git -C <repository-path> worktree remove --force <worktree-path>
git -C <repository-path> fetch origin <baseRefName> pull/<number>/head
git -C <repository-path> worktree add --detach <worktree-path> <headRefOid>
```

The first command removes a worktree left by an earlier run, if there is one.
Only read code in the worktree. Do not install dependencies, build, or run
tests. Remove the worktrees when the run ends.

## What to review

- `last_review` is `null`: full review of the PR's own changes,
  `git diff origin/<baseRefName>...<headRefOid>`.
- `last_review.commit` equals `headRefOid`: there are no new changes since
  your last review. The PR header says so, and the PR gets no list items.
- Otherwise check:

  ```text
  git merge-base --is-ancestor <last_review.commit> <headRefOid>
  git rev-list --merges <last_review.commit>..<headRefOid>
  ```

  If the first command succeeds and the second prints nothing, review
  `git diff <last_review.commit>..<headRefOid>`. Any non-zero exit (including
  128 when the commit no longer exists) or any merge commit means a full
  review, and the PR header says `full review (rebased since your last
review)`.

The script skips reply-only reviews, so a reply in a thread never moves
`last_review`. A review that approves or requests changes counts even with an
empty body.
