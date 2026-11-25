import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "SKILL.md"
REFERENCES = (
    "collecting",
    "evaluating",
    "fixing",
    "rebasing",
    "reporting",
    "publishing",
)
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
IRON_LAW = "NO PUSH AND NO GITHUB WRITE WITHOUT A YES TO THE CURRENT REPORT"
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
        self.assertRegex(frontmatter, r"(?m)^name: apply-pr-reviews$")
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

    def test_approval_boundary_precedes_push(self):
        self.assertRegex(self.skill, r"(?is)the iron law.*?current report.*?git push")

    def test_every_reference_exists_and_is_linked(self):
        for name in REFERENCES:
            with self.subTest(reference=name):
                self.assertTrue(reference_path(name).is_file())
                self.assertIn("references/" + name + ".md", self.skill)

    def test_old_state_machine_is_gone(self):
        self.assertFalse((ROOT / "scripts" / "context_store.py").exists())
        self.assertFalse((ROOT / "tests" / "test_context_store.py").exists())
        for phrase in ("context_store", "HUMAN DECISION REQUIRED", "Approve the exact"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, self.all_text)

    def test_report_contract(self):
        self.assert_phrases(
            ("🟢", "🟡", "🔴", "one line per item", "nothing to do", "QUESTION:")
        )

    def test_push_contract(self):
        self.assert_phrases(
            (
                "--force-with-lease=refs/heads/<branch>:<remote-sha>",
                "git worktree add --detach",
                "Never touch the user's checkout.",
            )
        )

    def test_rebase_contract(self):
        self.assert_phrases(
            (
                "Never merge the base branch into the PR branch.",
                "rebase --onto",
                "gh pr edit --base",
                "bottom up",
            )
        )

    def test_reply_contract(self):
        self.assert_phrases(
            ("Fixed in <sha>", "Not applied: <reason>", "one plain sentence")
        )

    def test_forbidden_github_writes(self):
        self.assert_phrases(
            (
                "Never resolve threads, approve, merge or close pull requests, "
                "request reviews, edit a title or description, or re-run CI.",
            )
        )

    def test_review_focus_rules(self):
        self.assert_phrases(
            (
                "waits for the reviewer",
                "every PR above it in the stack",
                "comes back on the next run",
                "Do not retry",
                "If anything changed after the report, show a new report and ask again.",
            )
        )

    def test_final_review_rules(self):
        self.assert_phrases(
            (
                "shared_head",
                "git merge-tree --write-tree",
                "Do not rely on `mergeable`",
                "Conflict with its base",
                "rebase every PR above it in the stack again",
                "A moved remote is handled like a rejected push.",
                "links to it",
                "git worktree remove --force",
                "Save the output to a file",
                "isCrossRepository",
            )
        )

    def test_is_concise(self):
        self.assertLessEqual(len(self.raw_skill.splitlines()), MAX_SKILL_LINES)
        for placeholder in ("TODO", "<placeholder>"):
            with self.subTest(placeholder=placeholder):
                self.assertNotIn(placeholder, self.raw_skill)


if __name__ == "__main__":
    unittest.main()
