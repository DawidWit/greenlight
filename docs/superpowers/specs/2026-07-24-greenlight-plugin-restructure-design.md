# Greenlight plugin restructure

Convert this single-skill repository into an installable, Superpowers-style
Claude Code plugin named `greenlight`, a collection of human-gated development
workflow skills. `apply-pr-reviews` becomes the first skill in the collection.

## Why

The repo currently holds one skill at its root (`SKILL.md`, `scripts/`,
`tests/`, `agents/`). To grow into a family of related skills and be installable
via `/plugin`, it needs the standard plugin packaging: a `.claude-plugin/`
manifest pair and a per-skill `skills/<name>/` layout.

The unifying theme of the collection is the trait that defines `apply-pr-reviews`:
agents that prepare verified work in isolation and publish only after explicit
human approval - the "green light".

## Target layout

```
.claude-plugin/
  plugin.json          # name: greenlight
  marketplace.json     # name: greenlight-marketplace
skills/
  apply-pr-reviews/
    SKILL.md
    scripts/           # collect_reviews.py, context_store.py
    tests/             # test_collect_reviews.py, test_context_store.py, test_skill_contract.py
    agents/            # openai.yaml (skill-scoped: references $apply-pr-reviews)
README.md              # collection overview + install instructions
LICENSE                # MIT
.gitignore             # unchanged, stays at root
docs/ .superpowers/    # local tooling, untouched
```

## Approach

Pure restructuring. No change to skill behavior, script logic, or test logic.

1. `git mv` `SKILL.md`, `scripts/`, `tests/`, and `agents/` as a unit into
   `skills/apply-pr-reviews/`. Using `git mv` preserves file history.
2. Add `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`,
   `README.md`, and `LICENSE`.
3. Verify from the new location.

### Test path invariance

The test suites locate their targets relatively:

- `test_skill_contract.py`: `ROOT = Path(__file__).resolve().parents[1]`, then
  `ROOT / "SKILL.md"`.
- `test_context_store.py` / `test_collect_reviews.py`:
  `Path(__file__).resolve().parents[1] / "scripts" / "<file>.py"`.

Moving `SKILL.md`, `scripts/`, and `tests/` together into
`skills/apply-pr-reviews/` keeps `parents[1]` pointing at the skill directory,
so all paths resolve unchanged. The contract assertions on the literal strings
`scripts/context_store.py` and `scripts/collect_reviews.py` also remain valid,
because those paths stay relative to the skill directory. No code edits required.

## Metadata

`plugin.json`:

- `name`: `greenlight`
- `description`: collection of human-gated development workflow skills
- `version`: `0.1.0`
- `author`: `DawidWit <135219147+DawidWit@users.noreply.github.com>`
- `license`: `MIT`
- `keywords`: skills, code-review, pull-request, workflow, human-in-the-loop
- `homepage` / `repository`: omitted until a git remote exists, to avoid
  inventing a URL.

`marketplace.json`:

- `name`: `greenlight-marketplace`
- `owner`: `DawidWit`
- `plugins`: one entry - `greenlight`, `source: "./"`, matching version/author.

`LICENSE`: MIT, copyright holder `DawidWit`.

## Verification

Run all three suites from `skills/apply-pr-reviews/` and confirm they stay
green (28 contract + 70 context-store + collector tests), plus `git diff --check`.
Confirm `git mv` recorded the moves as renames (history preserved).

## Out of scope

- No new skills (the collection ships with one).
- No behavior, script, or test-logic changes.
- No `homepage`/`repository` URLs, no CI, no cross-tool packaging
  (`.codex-plugin`, `.pi`, etc.) - can follow later.
