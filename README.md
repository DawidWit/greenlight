# greenlight

A collection of human-gated development workflow skills for Claude Code and
other Superpowers-compatible agents.

The theme is in the name: these skills let an agent do real work - read
feedback, prepare changes, verify them in isolation - but hold anything
outward-facing behind an explicit human **green light**. Nothing is published,
pushed, or made irreversible without approval bound to the exact change.

## Skills

| Skill                                                  | What it does                                                                                                                                                                                                                                                                                                       |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [`apply-pr-reviews`](skills/apply-pr-reviews/SKILL.md) | Processes open pull requests authored by the authenticated GitHub user: evaluates review feedback against current code, prepares verified changes in isolated workspaces, persists local handoff context, and publishes only exact approved work.                                                                  |
| [`prepare-pr`](skills/prepare-pr/SKILL.md)             | Takes a ticket, a description or existing changes to a pull request: asks one short question at a time, routes behavior questions to the PO, slices work into small stacked PRs, checks the plan against the repository rules, implements test-first, verifies, reviews, and publishes only after an explicit yes. |

## Install

Add this repository as a plugin marketplace, then install the plugin:

```
/plugin marketplace add DawidWit/greenlight
/plugin install greenlight@greenlight-marketplace
```

## Layout

```
.claude-plugin/    plugin + marketplace manifests
skills/<name>/     one directory per skill (SKILL.md plus its scripts and tests)
```

Each skill is self-contained: its `scripts/` and `tests/` live alongside its
`SKILL.md`, so the skill can be understood, tested, and moved as a unit.

## Development

Run a skill's tests from its own directory:

```
cd skills/apply-pr-reviews
python3 -m unittest discover tests
```

Run the tests of every skill:

```
for dir in skills/*/; do (cd "$dir" && python3 -m unittest discover tests) || exit 1; done
```

## Third-party notices

Some skills adapt text from other MIT-licensed projects. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

MIT - see [LICENSE](LICENSE).
