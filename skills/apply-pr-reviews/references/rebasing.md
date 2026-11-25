# Rebasing

Never merge the base branch into the PR branch. Conflicts are resolved by
rebase only, and the push then uses the lease with the remote SHA
([publishing.md](publishing.md)).

## Shared branches

A PR with `stack.shared_head: true` has a head branch that other PRs merge
into, for example a promotion PR from `test` to `beta`. Never rebase it and
never push to it. Report `🟡 shared branch <head>, not changed` and do no other
work on it.

## Conflict check

Do not rely on `mergeable`: GitHub can show `UNKNOWN` for a long time. After
`git fetch origin`, check every PR locally with `git merge-tree --write-tree`:

```text
git -C <repository-path> merge-tree --write-tree origin/<baseRefName> <headRefOid>
```

Exit code 1 means a conflict. Exit code 0 means none.

## When to rebase

Use the first row that matches:

| Situation                                                  | Command in the worktree                                                         |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `stack.merged_parent` is set                               | `git rebase --onto origin/<merged_parent.base_branch> <merged_parent.head_oid>` |
| `stack.parent` got new commits in this run, or was rebased | `git rebase --onto <parent-local-sha> <parent-remote-sha>`                      |
| Conflict with its base (the check above)                   | `git rebase origin/<baseRefName>`                                               |

In every other case, do not rebase. A base that only moved ahead is fine.

`<parent-local-sha>` and `<parent-remote-sha>` are the parent PR's local SHA
from this run and its `headRefOid` from the collection. For a child whose
parent did not change, the base is the parent's branch, so the last row
rebases it onto the parent.

For a merged parent, the PR's base on GitHub must change too. After the yes,
change it with `gh pr edit --base`:

```text
gh pr edit <number> --repo <owner/repo> --base <merged_parent.base_branch>
```

## Order

Work bottom up. Rebase a PR only after the PR below it is final. Then rebase
every PR above it in the stack, one after another.

## Conflicts

- Resolve a conflict when both sides can be combined without guessing what
  the code must do, for example a rename on one side and a body change on the
  other.
- Otherwise run `git rebase --abort`. That PR and every PR above it in the
  stack get 🟡 and a question.
- After a rebase, run the verification again ([fixing.md](fixing.md)).

## Report lines

- `🔴 Conflict with <base>, rebased #<n>-#<m>; push with --force-with-lease`
- `🔴 Parent #<n> merged, rebased onto <base>; push with --force-with-lease, base changes to <base>`
