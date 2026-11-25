# Publishing

Only after a yes to the current report.

## Before the push

- An excluded PR also excludes every PR above it in the stack. Those PRs
  carry its unpushed commits.
- For each PR to push, check that the worktree HEAD equals the local SHA from
  the report. If it does not, show a new report and ask again.
- For each PR to push, check that `git ls-remote origin refs/heads/<branch>`
  equals the remote SHA from the report. A moved remote is handled like a
  rejected push.

## Push

Push stacks bottom up. Use this form for every push, rebased or not:

```text
git -C <worktree-path> push --force-with-lease=refs/heads/<branch>:<remote-sha> origin <local-sha>:refs/heads/<branch>
```

Never use `--force`, and never `--force-with-lease` without the remote SHA.

A rejected push (`stale info` or any other error): 🔴 for that PR and every PR
above it in the stack. Do not retry. Continue with the other PRs: the yes
still covers them.

## After each successful push

1. Merged parent: change the base (`gh pr edit --base`, see
   [rebasing.md](rebasing.md)).
2. Fixed item in a thread: reply `Fixed in <sha>`, with the short SHA of the
   commit that holds the fix:

   ```text
   gh api -X POST repos/<owner>/<repo>/pulls/<number>/comments/<comment-id>/replies -f body='Fixed in <sha>'
   ```

   `<comment-id>` is the `databaseId` of the first comment in the thread.

3. Skipped item: reply `Not applied: <reason>`. It is one plain sentence in
   plain human language, without jargon. Example:
   `Not applied: lib code can't import from app, see CLAUDE.md.` In a thread,
   use the replies call above. An item without a thread gets a PR comment that
   links to it:

   ```text
   gh pr comment <number> --repo <owner/repo> --body '<item-url> Not applied: <reason>'
   ```

## Never

Never resolve threads, approve, merge or close pull requests, request reviews,
edit a title or description, or re-run CI. The only base change is the one for
a merged parent.

## After the push

- One line per PR, for example `#3001 pushed, 2 replies`, plus every error.
- Remove the worktree of each pushed PR with
  `git -C <repository-path> worktree remove <worktree-path>`.
- List the paths of the worktrees you keep. The next run removes them before
  it starts ([collecting.md](collecting.md)).
