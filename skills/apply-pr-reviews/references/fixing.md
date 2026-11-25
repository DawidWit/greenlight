# Fixing

Do only what review or CI requires. Do not add improvements, and do not offer
extra work in the report.

## Review items

- Every fix obeys the repository rules. A rule beats a comment: skip the
  comment and cite the rule ([evaluating.md](evaluating.md)).
- A fix that changes behavior starts with a test: write it, run it, see it
  fail for the expected reason, fix the code, run it again.
- A rename or a style fix needs no new test. Run the existing tests.

## Failing CI

For each failed check in `statusCheckRollup`, read the log:

```text
gh run view <run-id> --repo <owner/repo> --log-failed
```

Take `<run-id>` from the check's `detailsUrl`. A check that is not a GitHub
Actions run (a status with a `targetUrl`) has no log here: report
`🔴 CI failed: <check name>, see <targetUrl>` and do not guess the cause.

- **Caused by the code** (a test, type, lint or build error the PR code
  produces): fix it like a review item. Report line:
  `🔴 CI failed: <cause>, fixed <what>`.
- **Caused by the environment or a flaky test** (registry, network, runner,
  timeout): change nothing. Report line:
  `🔴 CI failed: <cause>, not caused by the code`. Never re-run CI.

## Verification

- Take the commands from the repository rules, then from the project scripts
  (`package.json`, `Makefile`, `pyproject.toml` and similar). Do not guess the
  package manager.
- Run the tests, the type check and the lint in the worktree after the fixes
  and after any rebase.
- No command for a check: say which check is missing in the PR's report line.
- A fix that breaks verification and that you cannot repair: revert it and
  report 🔴 with the failing check.

## Commits

- Commit only in the detached worktree. Nothing leaves the machine before the
  yes.
- Per PR and run: one commit for review fixes, one for CI fixes.
- Title: the convention from the repository rules or the recent `git log`.
  Default: `fix(<TICKET>): apply review feedback` and
  `fix(<TICKET>): fix failing CI`, with the ticket from the branch name or
  the PR title; without a ticket, `fix: apply review feedback`.
- After the last commit, record the worktree HEAD as the PR's local SHA. The
  push sends exactly it.
