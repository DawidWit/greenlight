# Slicing

Adapted from `to-issues` in [mattpocock/skills](https://github.com/mattpocock/skills) (MIT). See THIRD_PARTY_NOTICES.md.

Split the work into slices before you write a plan. One slice is one branch and one PR.

## What a slice is

- A thin vertical slice: it goes through every layer the change needs (data, logic, UI, tests) and can be verified on its own.
- Many thin slices are better than a few thick ones.
- Size target: about 300 changed lines per slice, tests included. This is a soft limit. Go above it only when a smaller slice could not be verified on its own, and say so in the slice list.

## Special slices

- **Waiting for the PO.** A part that depends on an open PO question becomes its own later slice with status `waiting for PO`. The slices before it do not include it and do not prepare for it.
- **Refactor first.** When weak code that the task relies on needs a fix that alone exceeds the size target, that fix becomes its own earlier slice. See [implementing.md](implementing.md).

## Branches

- Use the branch naming from the repository rules or the recent `git log`. If there is none, use the default below.
- Default name: `<type>/<TICKET>/<slug>` with a ticket, `<type>/<slug>` without one. `<type>` is one of `feat`, `fix`, `refactor`, `test`, `docs`, `chore`. `<slug>` is 2-5 lowercase words joined with hyphens.
- Slice 1 starts from `origin/<default-branch>` after `git fetch origin`. Do not pull into the user's checkout.
- Slice N+1 starts from the branch of slice N, and its PR targets that branch (stacked PRs).

## Slice list

Write the list at the top of the plan file (see [planning.md](planning.md)):

| #   | Slice   | Delivers                               | Branch     | Status                                                      |
| --- | ------- | -------------------------------------- | ---------- | ----------------------------------------------------------- |
| 1   | <title> | <what can be verified when it is done> | `<branch>` | `todo` / `in progress` / `waiting for PO` / `PR open <url>` |

With one slice, continue to planning. With two or more, show the list and ask one question through the Human Decision Gate: does this split work?
