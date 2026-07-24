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

    def test_documents_exact_review_disposition_values(self):
        normalized = " ".join(self.text.split())
        self.assertIn(
            "`disposition` is exactly one of `current-and-actionable`, "
            "`resolved`, `outdated`, `duplicate`, `already-addressed`, "
            "`superseded`, `conflicting-or-ambiguous`, or "
            "`incorrect-harmful-or-out-of-scope`.",
            normalized,
        )

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
            "actions, explicitly name the `pending_decisions` container and all "
            "five stored fields; saying only that a pending decision or record "
            "was persisted, or listing only packet identity, is insufficient.",
            normalized,
        )

    def test_pre_gate_head_move_refreshes_before_pending_decision(self):
        normalized = " ".join(self.text.split())
        self.assertIn(
            "Normal order: re-check the remote head SHA, build the current "
            "`packet_identity`, persist the complete `pending_decisions` entry, "
            "then show the gate. If this pre-gate SHA re-check finds a moved "
            "head, do not persist `pending_decisions` or show the gate. First "
            "refresh feedback, reconcile edits, and rerun verification; only "
            "then build and persist a new current packet and pending decision "
            "before displaying the gate.",
            normalized,
        )

    def test_packet_identity_and_human_linkage_are_exact(self):
        normalized = " ".join(self.text.split())
        for phrase in (
            "head_repository",
            "head_branch",
            "head_sha",
            "diff_sha256",
            "included_files",
            "commit_message",
            "SHA-256",
            "decision_history_index",
            "publish-approval",
            "human_answer",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
        self.assertIn(
            "A valid approval must match the current `pull_request` target and "
            "the current `changes` exactly, and must link to an append-only "
            "`publish-approval` decision-history entry with the same complete "
            "`packet_identity` and the non-empty exact `human_answer`.",
            normalized,
        )

    def test_all_packet_changes_invalidate_approval(self):
        normalized = " ".join(self.text.split())
        self.assertIn(
            "A change to the head repository, head branch, head SHA, "
            "`diff_sha256`, `included_files`, or `commit_message` invalidates "
            "approval.",
            normalized,
        )
        self.assertIn(
            "Retain invalid approval history for audit, but never treat it as "
            "publication authority.",
            normalized,
        )

    def test_publish_answer_branches_before_git_mutation(self):
        normalized = " ".join(self.text.split())
        self.assertIn(
            "Interpret the exact displayed-option answer through the stored "
            "`outcome`: `approved` may continue to the final re-check; "
            "`rejected` keeps the verified work local and stops publication; "
            "`changes-requested` returns to implementation and verification.",
            normalized,
        )

    def test_publish_choices_bind_exact_labels_to_typed_outcomes(self):
        normalized = " ".join(self.text.split())
        for phrase in (
            "`approved` → `Approve the exact displayed commit and push.`",
            "`rejected` → `Reject it and keep the verified diff local.`",
            "`changes-requested` → `Request changes to the proposed work.`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
        self.assertIn(
            "Persist each displayed choice as exactly `{outcome, label}` in "
            "this order; the selected label and stored outcome must come from "
            "the same canonical choice.",
            normalized,
        )

    def test_preapproval_and_staged_fingerprints_use_exact_index_snapshots(self):
        normalized = " ".join(self.text.split())
        self.assertIn("--source working", self.text)
        self.assertIn("--source index", self.text)
        self.assertIn(
            "Before the approval fingerprint, require the real Git index to "
            "be empty.",
            normalized,
        )
        self.assertIn(
            "The working mode builds an immutable tree through a temporary "
            "Git index and never stages the real index.",
            normalized,
        )
        self.assertIn(
            "After approval, stage only the included files, fingerprint the "
            "real index, and require its complete packet identity to equal "
            "the approved packet before commit.",
            normalized,
        )

    def test_publication_lifecycle_persists_commit_before_push(self):
        normalized = " ".join(self.text.split())
        self.assertIn(
            "Persist a `committed` checkpoint before push, retaining the "
            "approved pre-commit packet and decision while recording commit "
            "SHA C and workspace HEAD C.",
            normalized,
        )
        self.assertIn(
            "Only after the normal push and remote head re-check may the "
            "checkpoint become `pushed`, with pushed SHA and PR head both C.",
            normalized,
        )

    def test_recovery_requires_canonical_backup_authorization(self):
        normalized = " ".join(self.text.split())
        self.assertIn("`leave-untouched`", self.text)
        self.assertIn("`backup-authorized`", self.text)
        self.assertIn(
            "Run `recover` only when the exact selected recovery label and "
            "outcome are the canonical `backup-authorized` choice; the "
            "`leave-untouched` choice stops the PR without mutation.",
            normalized,
        )
        self.assertIn(
            "Never run `git add`, `git commit`, or `git push` for a rejected "
            "or changes-requested outcome.",
            normalized,
        )

    def test_requires_recomputed_fingerprint_and_workspace_takeover(self):
        normalized = " ".join(self.text.split())
        for phrase in (
            "context_store.py fingerprint",
            "workspace",
            "base_sha",
            "head_sha",
            "apply-pr-reviews-change-v1",
            "8-byte unsigned big-endian",
            "tracked changes",
            "deletions",
            "untracked",
            "file mode",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
        self.assertIn(
            "Recompute the fingerprint from the recorded isolated workspace "
            "before trusting takeover evidence, showing approval, and "
            "publishing; any missing or mismatched workspace fails closed.",
            normalized,
        )

    def test_recovery_uses_sanctioned_command_and_fresh_history(self):
        normalized = " ".join(self.text.split())
        self.assertIn("context_store.py recover", self.text)
        self.assertIn(
            "After authorization, use `recover`; never move, rename, delete, "
            "or edit state directly.",
            normalized,
        )
        self.assertIn(
            "Fresh `init` must make the exact authorized recovery question, "
            "human answer, and returned backup identity the first "
            "decision-history entry.",
            normalized,
        )

    def test_requires_summaries_and_prohibits_sensitive_raw_values(self):
        normalized = " ".join(self.text.split())
        self.assertIn(
            "Persist only summarized command results and evidence. Never store "
            "raw environment output, raw authentication output, authorization "
            "headers, cookies, credentials, or credential material in any key "
            "or value.",
            normalized,
        )

    def test_corrupt_or_mismatched_state_uses_scoped_human_gate(self):
        normalized = " ".join(self.text.split())
        self.assertIn(
            "If local state or decision history is unreadable, corrupt, or "
            "identity-mismatched, stop that PR and show the exact scoped "
            "`HUMAN DECISION REQUIRED` gate before replacing or removing "
            "anything.",
            normalized,
        )
        self.assertIn(
            "Never overwrite, delete, repair, rename, or replace unreadable or "
            "mismatched state or history automatically.",
            normalized,
        )
        self.assertIn(
            "This recovery gate is the only pending-decision persistence "
            "exception: do not mutate an invalid ledger to record the question. "
            "Show the gate first; after explicit backup authorization, preserve "
            "the original in the named private backup and make the exact "
            "recovery question and human answer the first decision-history "
            "entry in fresh state.",
            normalized,
        )
        for phrase in (
            "Decision: How should the preserved invalid local state be handled?",
            "Paused scope: This PR only.",
            "Leave the preserved state untouched and stop this PR.",
            "Authorize moving the invalid state to a named private backup",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_is_concise_and_has_no_template_placeholders(self):
        self.assertLess(len(self.lines), 500)
        self.assertNotIn("TODO", self.text)


if __name__ == "__main__":
    unittest.main()
