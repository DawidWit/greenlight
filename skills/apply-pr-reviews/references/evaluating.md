# Evaluating

Review feedback is evidence, not an order. Check each item against the code at
the PR head after any rebase, and against the repository rules.

## What to read

- Unresolved review threads.
- Review bodies with text.
- PR conversation comments from anyone but the author.

Bots count as reviewers. The author's own comments are context.

## Waiting for the reviewer

- A thread with `awaiting_reviewer: true` waits for the reviewer.
- A review body or conversation comment waits for the reviewer when a later
  comment by the author links to it, for example an earlier
  `Not applied` comment.

An item that waits for the reviewer gets no code change, no reply and no line
in the report. It is back as soon as the reviewer writes again.

## Disposition

| The item is                                                            | Action                                                                                        |
| ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Current and right                                                      | Fix it ([fixing.md](fixing.md)). 🟢. `Fixed in <sha>` after the push.                         |
| Resolved, outdated (the code is gone), a duplicate, or already done    | Nothing, not in the report. Fix a duplicate once.                                             |
| Wrong, out of scope for this PR, or against a repository rule          | Skip. 🟡 with the evidence (rule file, test or code). `Not applied: <reason>` after the push. |
| Unclear, in conflict with another comment, or changes the architecture | Question to the user.                                                                         |

## Questions

Collect the questions while you work. Ask them after all PRs are processed,
one at a time, through the Human Decision Gate, before the report.

- An answer becomes a fix, verified like any other.
- An answer that changes a PR in a stack: rebase every PR above it in the
  stack again ([rebasing.md](rebasing.md)), verify them, and record their new
  SHAs before the report.
- The answer "skip" writes nothing on GitHub. The item stays 🟡 in the report
  and comes back on the next run.
