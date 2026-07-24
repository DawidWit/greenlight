import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "SKILL.md"


class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SKILL_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_frontmatter_is_portable_and_discoverable(self):
        self.assertTrue(self.text.startswith("---\n"))
        frontmatter = self.text.split("---", 2)[1]
        self.assertRegex(frontmatter, r"(?m)^name: apply-pr-reviews$")
        self.assertRegex(frontmatter, r"(?m)^description: Use when .+")
        self.assertNotIn("$ARGUMENTS", self.text)

    def test_uses_full_superpowers_structure(self):
        required_headings = (
            "## Overview",
            "## Core Principle",
            "## The Iron Law",
            "## The Process",
            "## Human Decision Gate",
            "## Local Decision Ledger",
            "## Review Disposition Reference",
            "## Common Rationalizations",
            "## Quick Reference",
            "## Red Flags - STOP",
            "## Common Mistakes",
            "## The Bottom Line",
        )
        positions = [self.text.index(heading) for heading in required_headings]
        self.assertEqual(positions, sorted(positions))

    def test_contains_exact_iron_law(self):
        self.assertIn(
            "NO COMMIT OR PUSH WITHOUT AN APPROVED, CURRENT PACKET",
            self.text,
        )

    def test_human_decision_contract_is_visible_and_scoped(self):
        for phrase in (
            "HUMAN DECISION REQUIRED",
            "Decision:",
            "Why this cannot be decided safely:",
            "Recommendation:",
            "Options:",
            "Paused scope:",
            "continue independent PRs",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), self.text.lower())

    def test_approval_boundary_precedes_git_mutations(self):
        boundary = re.search(
            r"(?is)the iron law.*?approval.*?git add.*?"
            r"git commit.*?git push",
            self.text,
        )
        self.assertIsNotNone(boundary)

    def test_requires_private_takeover_context(self):
        for phrase in (
            "scripts/context_store.py",
            "git rev-parse --git-common-dir",
            "state.json",
            "expected revision",
            "decision history",
            "load existing local context",
            "revalidate",
            "schema_version",
            "review_ledger",
            "pending_decisions",
            "publication",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text.lower())

    def test_forbids_unrequested_github_mutations(self):
        for phrase in (
            "reply to review threads",
            "resolve review threads",
            "merge",
            "close",
            "approve",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text.lower())

    def test_references_collector_and_private_configuration(self):
        self.assertIn("scripts/collect_reviews.py", self.text)
        self.assertIn("repositories.json", self.text)
        self.assertIn("local repository", self.text.lower())

    def test_has_required_approval_packet(self):
        for field in (
            "PR URL",
            "review feedback",
            "changed files",
            "verification",
            "proposed commit",
            "exact push target",
        ):
            with self.subTest(field=field):
                self.assertIn(field, self.text)

    def test_publishing_pressure_cannot_summarize_approval_gate(self):
        normalized = " ".join(self.text.split())
        self.assertIn(
            "Always persist the pending approval decision first and render the "
            "complete gate; never merely summarize either step, even when asked "
            "to commit or push first.",
            normalized,
        )

    def test_publish_approval_persists_decision_record_not_just_packet(self):
        normalized = " ".join(self.text.split())
        self.assertIn(
            "Store the unanswered record in `pending_decisions` with `question` "
            "set to `Approve this exact commit and push for this PR?`, the three "
            "`options` and `recommendation` shown below, `scope` set to `This PR "
            "only.`, and `packet_identity` containing PR head SHA, diff, files, "
            "commit message, and push target. The question must be inside the "
            "stored record, not only in the displayed gate. Persisting only the "
            "approval packet is insufficient.",
            normalized,
        )
        self.assertIn(
            "Do not show the gate unless the stored `pending_decisions` entry "
            "itself contains all five fields: `question`, `options`, "
            "`recommendation`, `scope`, and `packet_identity`. When stating exact "
            "actions, name all five stored fields; saying only that the decision "
            "was persisted or listing only packet identity is insufficient.",
            normalized,
        )

    def test_is_concise_and_has_no_template_placeholders(self):
        self.assertLess(len(self.lines), 500)
        self.assertNotIn("TODO", self.text)


if __name__ == "__main__":
    unittest.main()
