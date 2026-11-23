# Planning

Adapted from `writing-plans` in [obra/superpowers](https://github.com/obra/superpowers) (MIT). See THIRD_PARTY_NOTICES.md.

## The plan file

- Path: `.claude/plans/<ticket-or-name>.md` in the target repository. `<ticket-or-name>` is the ticket key, or a 2-5 word slug of the task.
- The plan file lives in the main checkout, never in a worktree. From a worktree, read and write it by its absolute path.
- Before you write it, make sure the repository's exclude file contains the line `.claude/plans/`. The file is `.git/info/exclude`; get its exact path with `git rev-parse --git-path info/exclude`, which also works inside a worktree. Add the line if it is missing. Do not edit `.gitignore`.
- The plan file never goes into `git add`. It is local working state.
- One plan file holds the whole task, in this order:
  1. Source: ticket key or link, or the user's description.
  2. Slice list with status (see [slicing.md](slicing.md)).
  3. Waiting for PO: each open PO question and the slice it blocks.
  4. Later: improvements found outside the task, one line each.
  5. Rules check: each rule that changed the plan, and the change (see [rules-check.md](rules-check.md)).
  6. Plan for the current slice.

If the plan file already exists when you start, read the plan file and continue from the first slice that is not done. Never overwrite it.

## The plan for a slice

Write it for an engineer who has not seen this code. Record the decisions they cannot make alone. Leave out code they can write from a signature and a test.

Start with:

- **Goal:** one sentence.
- **Files:** each file to create or change, and what it is responsible for. Follow the patterns the repository already uses.
- **Constraints:** the repository rules that apply to this slice, one line each.

Then tasks. One task is the smallest change with its own test cycle:

```markdown
### Task N: <name>

Files: create `path`, modify `path`, test `path`
Uses: <names and signatures from earlier tasks>
Gives: <names and signatures later tasks rely on>

- [ ] Write the failing test `<test name>`: <assertions with exact values>
- [ ] Run `<command>`. Expected: FAIL because <reason>.
- [ ] Implement `<signature>` in `<path>`.
- [ ] Run `<command>`. Expected: PASS.
```

The plan has no commit steps. Commits happen only after the explicit yes (see [publishing.md](publishing.md)).

## Self-check

Before the rules check, read the plan once against the requirements:

1. Every requirement of this slice has a task.
2. Every step lets the engineer write exactly one reasonable thing. Replace "handle edge cases" or "add tests" with the exact case or test.
3. Names and signatures match between tasks.
4. The plan is shorter than the code it describes. Replace code bodies with signatures and test assertions.

Fix what you find, then go to [rules-check.md](rules-check.md).
