import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "SKILL.md"
REFERENCES = (
    "asking",
    "slicing",
    "planning",
    "rules-check",
    "implementing",
    "reviewing",
    "publishing",
)
ADAPTED_REFERENCES = ("planning", "slicing", "reviewing")
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

    def test_frontmatter_is_portable_and_discoverable(self):
        self.assertTrue(self.raw_skill.startswith("---\n"))
        frontmatter = self.raw_skill.split("---", 2)[1]
        self.assertRegex(frontmatter, r"(?m)^name: prepare-pr$")
        description = re.search(r"(?m)^description: (.+)$", frontmatter)
        self.assertIsNotNone(description)
        self.assertTrue(description.group(1).startswith("Use when "))
        self.assertLessEqual(len(description.group(1)), 1024)
        self.assertNotIn("$ARGUMENTS", self.raw_skill)

    def test_uses_greenlight_heading_order(self):
        positions = [self.raw_skill.index(heading) for heading in HEADINGS]
        self.assertEqual(positions, sorted(positions))

    def test_contains_exact_iron_law(self):
        self.assertIn("NO COMMIT, PUSH OR PR WITHOUT AN EXPLICIT YES", self.skill)

    def test_approval_boundary_precedes_git_mutations(self):
        iron_law = self.raw_skill.split("## The Iron Law", 1)[1]
        iron_law = normalize(iron_law.split("## The Process", 1)[0])
        boundary = re.search(r"(?is)explicit yes.*?git commit.*?git push", iron_law)
        self.assertIsNotNone(boundary)

    def test_existing_changes_mode_has_a_plan_file(self):
        for phrase in (
            "In this mode, create the plan file",
            "In the \"From existing changes\" mode, stage 5 means",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.all_text)

    def test_worktree_keeps_one_plan_file(self):
        for phrase in (
            "git rev-parse --git-path info/exclude",
            "outside the repository",
            "absolute path",
            "git worktree remove",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.all_text)

    def test_yes_is_bound_to_the_listed_files(self):
        for phrase in (
            "one line per file",
            "Before `git add`, compare",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.all_text)

    def test_review_focus_prohibitions_are_pinned(self):
        for phrase in (
            "Do not invent rules.",
            "Never overwrite it.",
            "Never report a check as passed without its output.",
            "do not touch them",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.all_text)

    def test_missing_test_command_goes_to_the_gate(self):
        self.assertIn(
            "If the repository has no test command, ask through the Human "
            "Decision Gate",
            self.all_text,
        )

    def test_repository_conventions_override_default_names(self):
        self.assertIn("repository rules or the recent `git log`", self.all_text)

    def test_every_reference_exists_and_is_linked(self):
        for name in REFERENCES:
            with self.subTest(reference=name):
                self.assertTrue(reference_path(name).exists())
                self.assertIn("references/" + name + ".md", self.skill)

    def test_adapted_references_carry_attribution(self):
        for name in ADAPTED_REFERENCES:
            with self.subTest(reference=name):
                text = reference_path(name).read_text(encoding="utf-8")
                self.assertIn("Adapted from", text)
                self.assertIn("THIRD_PARTY_NOTICES.md", text)

    def test_both_entry_modes_are_documented(self):
        self.assertIn("From a ticket or description", self.skill)
        self.assertIn("From existing changes", self.skill)

    def test_asking_contract(self):
        for phrase in (
            "one question at a time",
            "MESSAGE FOR THE PO",
            "in the user's language",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.all_text)

    def test_plan_file_stays_local(self):
        self.assertIn(".claude/plans/", self.all_text)
        self.assertIn(".git/info/exclude", self.all_text)
        self.assertNotIn("commit the plan", self.all_text.lower())

    def test_naming_contract(self):
        for phrase in (
            "`<type>(<TICKET>): <summary>`",
            "`<type>: <summary>`",
            "`<type>/<TICKET>/<slug>`",
            "`<type>/<slug>`",
            "about 300 changed lines",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.all_text)

    def test_messages_are_chat_text_not_code_blocks(self):
        self.assertIn(
            "Never put a report, a summary or a question in a code block.",
            self.skill,
        )

    def test_review_focus_rules(self):
        for phrase in (
            "git worktree",
            "no rules found",
            "say which check is missing",
            "read the plan file and continue",
            "If the diff changes after the yes, ask again.",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.all_text)


if __name__ == "__main__":
    unittest.main()
