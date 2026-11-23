# Implementing

Do the tasks of the current slice yourself, in order. Do not start one subagent per task.

## Workspace

- From a ticket or description: if the checkout has uncommitted changes that are not part of this task, do not touch them. Run `git fetch origin`, then create a `git worktree` outside the repository: `git worktree add -b <branch> <path outside the repository> origin/<base-branch>`. Work there. The plan file stays in the main checkout; use its absolute path.
- After the PR of a slice is open, remove its worktree with `git worktree remove <path>`. The branch stays on the remote.
- From existing changes: work on the current branch, with the user's changes. If those changes are on the default branch, create the slice branch from it first (`git switch -c <branch>` keeps the changes).

In the "From existing changes" mode, stage 5 means: fix weak code that the diff relies on, and add tests for changed behavior that has none.

## Each task

If the repository has no test command, ask through the Human Decision Gate whether to add a test setup or to continue without tests. Do not decide this yourself.

1. Write the failing test from the plan.
2. Run it. It must fail for the reason the plan gives. If it passes, the test is wrong: fix the test.
3. Write the code.
4. Run the test. It must pass. Run the rest of the suite for the files you touched.

Do not commit. Changes stay uncommitted until the explicit yes.

## Best implementation

Write the best implementation you can, not the first one that passes. When you see a better design than the plan has, use it and update the plan.

## Weak code the task relies on

When the new code calls, extends or copies a fragment that is badly written, fix that fragment in this slice and keep its meaning:

1. Write a test that pins the current behavior of the fragment. Run it. It must pass before you change anything.
2. Rewrite the fragment. The pinning test must still pass.
3. If the current behavior is clearly a bug, do not fix it silently. Ask through the Human Decision Gate.

If this fix alone exceeds the size target, make it its own earlier slice (see [slicing.md](slicing.md)).

## Weak code the task does not rely on

Do not change it. Add one line to the "Later" list in the plan file: the file and what to improve.
