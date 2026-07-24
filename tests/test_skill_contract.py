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
        self.assertRegex(
            frontmatter,
            r"(?m)^description: .+Use when .+",
        )
        self.assertNotIn("$ARGUMENTS", self.text)

    def test_contains_mutation_boundary_before_commit_and_push(self):
        boundary = re.search(
            r"(?is)mutation boundary.*?approval.*?git add.*?"
            r"git commit.*?git push",
            self.text,
        )
        self.assertIsNotNone(boundary)

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

    def test_is_concise_and_has_no_template_placeholders(self):
        self.assertLess(len(self.lines), 500)
        self.assertNotIn("TODO", self.text)


if __name__ == "__main__":
    unittest.main()
