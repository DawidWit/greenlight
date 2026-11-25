import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "SKILL.md"
REFERENCES = ("collecting", "reviewing", "listing", "commenting")
HEADINGS = (
    "## Overview",
    "## Core Principle",
    "## The Iron Law",
    "## The Process",
    "## Human Decision Gate",
    "## Common Rationalizations",
    "## Quick Reference",
    "## Red Flags - STOP",
    "## Common Mistakes",
    "## The Bottom Line",
)
IRON_LAW = "NO COMMENT ON GITHUB WITHOUT A CONFIRMED SELECTION"
MAX_SKILL_LINES = 200


def normalize(text):
    return " ".join(text.split())


def reference_path(name):
    return ROOT / "references" / (name + ".md")


class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_skill = SKILL_PATH.read_text(encoding="utf-8")
        cls.skill = normalize(cls.raw_skill)
        reference_texts = [
            reference_path(name).read_text(encoding="utf-8")
            for name in REFERENCES
            if reference_path(name).exists()
        ]
        cls.all_text = normalize("\n".join([cls.raw_skill] + reference_texts))

    def assert_phrases(self, phrases):
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.all_text)

    def test_frontmatter_is_portable_and_discoverable(self):
        self.assertTrue(self.raw_skill.startswith("---\n"))
        frontmatter = self.raw_skill.split("---", 2)[1]
        self.assertRegex(frontmatter, r"(?m)^name: review-prs$")
        description = re.search(r"(?m)^description: (.+)$", frontmatter)
        self.assertIsNotNone(description)
        self.assertTrue(description.group(1).startswith("Use when "))
        self.assertLessEqual(len(description.group(1)), 1024)
        self.assertNotIn("$ARGUMENTS", self.raw_skill)

    def test_uses_greenlight_heading_order(self):
        positions = [self.raw_skill.find(heading) for heading in HEADINGS]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))

    def test_contains_exact_iron_law(self):
        self.assertIn(IRON_LAW, self.skill)

    def test_confirmation_precedes_github_writes(self):
        self.assertRegex(self.skill, r"(?is)the iron law.*?confirmed.*?gh api")

    def test_every_reference_exists_and_is_linked(self):
        for name in REFERENCES:
            with self.subTest(reference=name):
                self.assertTrue(reference_path(name).is_file())
                self.assertIn("references/" + name + ".md", self.skill)

    def test_adapted_reference_carries_attribution(self):
        text = reference_path("reviewing").read_text(encoding="utf-8")
        self.assertIn("Adapted from", text)
        self.assertIn("THIRD_PARTY_NOTICES.md", text)

    def test_messages_are_chat_text_not_code_blocks(self):
        self.assertIn(
            "Never put a report, a summary or a question in a code block.",
            self.skill,
        )

    def test_forbidden_github_writes(self):
        self.assert_phrases(
            (
                "Never approve, request changes, merge or close pull requests, "
                "resolve threads, request reviews, push to the author's "
                "branch, or re-run CI.",
            )
        )

    def test_publishing_contract(self):
        self.assert_phrases(("event=COMMENT", "outside the diff"))

    def test_list_contract(self):
        self.assert_phrases(
            (
                "**Error:**",
                "**Why:**",
                "🔴",
                "🟡",
                "🟢",
                "Which errors should become comments?",
                "Post these comments?",
            )
        )

    def test_review_focus_rules(self):
        self.assert_phrases(
            (
                "full review",
                "reply-only",
                "related_prs",
                "already in an open thread",
                "without evidence",
            )
        )

    def test_final_review_rules(self):
        self.assert_phrases(
            (
                '"side": "LEFT"',
                "start_line",
                "422",
                "pull/<number>/head",
                "--pr <owner/repo>#<number>",
                "data, not instructions",
                "review_bodies",
                "conversation",
                "no new changes since your last review",
                "Any non-zero exit",
            )
        )

    def test_is_concise(self):
        self.assertLessEqual(len(self.raw_skill.splitlines()), MAX_SKILL_LINES)
        self.assertNotIn("TODO", self.raw_skill)


if __name__ == "__main__":
    unittest.main()
