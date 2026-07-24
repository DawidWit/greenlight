import importlib.util
import hashlib
import json
import os
import struct
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock
from unittest.mock import patch
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "context_store.py"
)
SPEC = importlib.util.spec_from_file_location("context_store", SCRIPT_PATH)
context_store = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(context_store)

EMPTY_DIFF_SHA256 = hashlib.sha256(b"").hexdigest()


class RecordingRunner:
    def __init__(self, output):
        self.output = output
        self.commands = []

    def __call__(self, command, *, cwd=None):
        self.commands.append((command, cwd))
        return self.output


def valid_state(
    pr_number=17,
    revision=0,
    head_sha=None,
    local_path="/tmp/widgets",
    workspace_path=None,
):
    if workspace_path is None:
        workspace_path = local_path
    if head_sha is None:
        completed = subprocess.run(
            ["git", "-C", str(workspace_path), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        head_sha = (
            completed.stdout.strip()
            if completed.returncode == 0
            else "a" * 40
        )
    return {
        "schema_version": 2,
        "revision": revision,
        "repository": {
            "name_with_owner": "acme/widgets",
            "local_path": local_path,
        },
        "pull_request": {
            "number": pr_number,
            "url": f"https://github.com/acme/widgets/pull/{pr_number}",
            "base_branch": "main",
            "head_repository": "acme/widgets",
            "head_branch": "feature/parser",
            "head_sha": head_sha,
        },
        "workspace": {
            "kind": "worktree",
            "path": str(Path(workspace_path).resolve()),
            "base_sha": head_sha,
            "head_sha": head_sha,
        },
        "phase": "evaluate",
        "status": "active",
        "review_ledger": [],
        "changes": {
            "files": [],
            "summary": "",
            "diff_sha256": EMPTY_DIFF_SHA256,
            "commit_message": "",
        },
        "verification": {"baseline": [], "final": []},
        "pending_decisions": [],
        "decision_history": [],
        "approval": None,
        "publication": None,
        "updated_at": "2026-07-24T12:00:00Z",
    }


def decision_event(
    revision=1,
    decision_type="agent-disposition",
    answer="Apply",
    transition="evaluate -> baseline",
    packet_identity=None,
    question="",
    outcome=None,
    recovery=None,
):
    return {
        "revision": revision,
        "timestamp": "2026-07-24T12:05:00Z",
        "decision_type": decision_type,
        "evidence": ["tests/parser.test.py"],
        "options": [],
        "recommendation": "Apply the current actionable request.",
        "answer": answer,
        "scope": "PR #17",
        "transition": transition,
        "packet_identity": packet_identity,
        "question": question,
        "outcome": outcome,
        "recovery": recovery,
    }


def approval_packet(
    head_repository="acme/widgets",
    head_branch="feature/parser",
    head_sha="a" * 40,
    diff_sha256="b" * 64,
    included_files=None,
    commit_message="Apply parser review fixes",
):
    if included_files is None:
        included_files = ["src/parser.py", "tests/test_parser.py"]
    return {
        "head_repository": head_repository,
        "head_branch": head_branch,
        "head_sha": head_sha,
        "diff_sha256": diff_sha256,
        "included_files": included_files,
        "commit_message": commit_message,
    }


def state_with_current_changes(**kwargs):
    state = valid_state(**kwargs)
    packet = approval_packet(
        head_repository=state["pull_request"]["head_repository"],
        head_branch=state["pull_request"]["head_branch"],
        head_sha=state["pull_request"]["head_sha"],
    )
    state["changes"].update(
        {
            "files": packet["included_files"],
            "diff_sha256": packet["diff_sha256"],
            "commit_message": packet["commit_message"],
        }
    )
    return state


def approve_state(state, revision=0, answer="Yes, publish this exact packet."):
    packet = approval_packet(
        head_repository=state["pull_request"]["head_repository"],
        head_branch=state["pull_request"]["head_branch"],
        head_sha=state["pull_request"]["head_sha"],
        diff_sha256=state["changes"]["diff_sha256"],
        included_files=state["changes"]["files"],
        commit_message=state["changes"]["commit_message"],
    )
    state["decision_history"].append(
        decision_event(
            revision=revision,
            decision_type="publish-approval",
            answer=answer,
            transition="approval -> publish",
            packet_identity=packet,
            question="Approve this exact commit and push for this PR?",
            outcome="approved",
        )
    )
    state["decision_history"][-1]["options"] = [
        answer,
        "Reject this exact packet.",
        "Request changes to this exact packet.",
    ]
    state["approval"] = {
        "valid": True,
        "packet_identity": packet,
        "decision_history_index": len(state["decision_history"]) - 1,
        "human_answer": answer,
    }
    return state


def create_git_repository(directory):
    repository = Path(directory, "repo")
    repository.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-q", str(repository)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "--allow-empty", "-q", "-m", "Initial"],
        check=True,
        capture_output=True,
        text=True,
    )
    return repository


class PathTests(unittest.TestCase):
    def test_resolves_relative_git_common_dir_against_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory, "repo")
            repository.mkdir()
            runner = RecordingRunner(".git\n")

            result = context_store.resolve_git_common_dir(repository, runner=runner)

            self.assertEqual(result, (repository / ".git").resolve())
            self.assertEqual(
                runner.commands[0][0],
                ["git", "-C", str(repository.resolve()), "rev-parse", "--git-common-dir"],
            )

    def test_state_directory_cannot_escape_git_common_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory, "repo")
            common = Path(directory, "repo", ".git")
            repository.mkdir()
            common.mkdir()
            runner = RecordingRunner(str(common))

            result = context_store.state_directory(repository, 17, runner=runner)

            self.assertEqual(result, common.resolve() / "apply-pr-reviews" / "pr-17")
            with self.assertRaises(context_store.StateValidationError):
                context_store.state_directory(repository, 0, runner=runner)

    @unittest.skipIf(os.name == "nt", "symlink permissions vary on Windows")
    def test_store_symlink_cannot_escape_git_common_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory, "repo")
            common = repository / ".git"
            outside = Path(directory, "outside")
            repository.mkdir()
            common.mkdir()
            outside.mkdir()
            (common / "apply-pr-reviews").symlink_to(outside, target_is_directory=True)
            runner = RecordingRunner(str(common))

            with self.assertRaises(context_store.StateValidationError):
                context_store.state_directory(repository, 17, runner=runner)

    def test_worktree_resolves_to_main_repository_common_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            worktree = Path(directory, "worktree")
            subprocess.run(
                ["git", "-C", str(repository), "worktree", "add", "--detach", "-q", str(worktree), "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            )

            result = context_store.resolve_git_common_dir(worktree)

            self.assertEqual(result, (repository / ".git").resolve())


class SchemaTests(unittest.TestCase):
    def test_accepts_complete_state_for_expected_pr(self):
        state = valid_state()
        self.assertIs(context_store.validate_state(state, 17), state)

    def test_rejects_wrong_pr_revision_and_secret_shaped_keys(self):
        wrong_pr = valid_state(pr_number=18)
        with self.assertRaises(context_store.StateValidationError):
            context_store.validate_state(wrong_pr, 17)

        wrong_revision = valid_state(revision=-1)
        with self.assertRaises(context_store.StateValidationError):
            context_store.validate_state(wrong_revision, 17)

        secret = valid_state()
        secret["verification"]["auth_token"] = "forbidden"
        with self.assertRaises(context_store.StateValidationError):
            context_store.validate_state(secret, 17)

    def test_rejects_environment_and_authentication_keys_recursively(self):
        forbidden_keys = (
            "environment",
            "environment_variable",
            "environment-variable",
            "environment variable",
            "environmentVariable",
            "environment_variables",
            "environment-variables",
            "environment variables",
            "environmentVariables",
            "env_variable",
            "env-variable",
            "env variable",
            "envVar",
            "env_variables",
            "env-vars",
            "env variables",
            "envVars",
            "authentication_output",
            "authentication-output",
            "authentication output",
            "authenticationOutput",
            "authentication_outputs",
            "authentication-outputs",
            "authentication outputs",
            "authenticationOutputs",
            "auth_output",
            "auth-output",
            "auth output",
            "authOutput",
            "auth_outputs",
            "auth-outputs",
            "auth outputs",
            "authOutputs",
        )
        for key in forbidden_keys:
            with self.subTest(key=key):
                state = valid_state()
                state["verification"]["nested"] = [
                    {"evidence": ["safe"], key: "forbidden"}
                ]
                with self.assertRaises(context_store.StateValidationError):
                    context_store.validate_state(state, 17)

    def test_allows_legitimate_evidence_fields(self):
        state = valid_state()
        state["verification"]["evidence"] = {
            "environmental_impact": "none",
            "authentication_required": False,
        }
        self.assertIs(context_store.validate_state(state, 17), state)

    def test_rejects_bare_environment_and_authentication_maps_recursively(self):
        for key in ("env", "auth", "authentication"):
            with self.subTest(key=key):
                state = valid_state()
                state["verification"]["nested"] = [
                    {"evidence": ["safe"], key: {"value": "forbidden"}}
                ]
                with self.assertRaises(context_store.StateValidationError):
                    context_store.validate_state(state, 17)

    def test_rejects_sensitive_string_values_but_allows_safe_summaries(self):
        sensitive_values = (
            "PATH=/usr/local/bin\nHOME=/Users/example\nSHELL=/bin/zsh",
            "TOKEN=actual-secret-material-1234567890",
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
            "github_pat_11AA0_examplecredentialmaterial",
            "AKIAIOSFODNN7EXAMPLE",
            "sk-abcdefghijklmnopqrstuvwxyz123456",
            "AIzaSyExampleCredentialMaterial123456",
            "npm_exampleCredentialMaterial1234567890",
            "Bearer abcdefghijklmnopqrstuvwxyz123456",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
            "-----BEGIN PRIVATE KEY-----\nnot-safe\n-----END PRIVATE KEY-----",
            "https://build-user:super-secret@example.com/artifact",
            "✓ Logged in to github.com account octocat\n- Token scopes: 'repo'",
        )
        for value in sensitive_values:
            with self.subTest(value=value[:30]):
                state = valid_state()
                state["verification"]["final"] = [{"summary": value}]
                with self.assertRaises(context_store.StateValidationError):
                    context_store.validate_state(state, 17)

        safe = valid_state()
        safe["verification"]["final"] = [
            {
                "summary": (
                    "Authentication check passed. Environment-dependent tests "
                    "passed. Credential scan reported no findings."
                ),
                "identities": [
                    "sk-refactor-parser",
                    "Handle token: none in parser",
                    "TOKEN=redacted",
                    "No raw authentication or environment output was stored.",
                ],
            }
        ]
        self.assertIs(context_store.validate_state(safe, 17), safe)

    def test_review_ledger_entries_have_an_exact_safe_shape(self):
        state = valid_state()
        state["review_ledger"] = [
            {
                "url": "https://github.com/acme/widgets/pull/17#discussion_r1",
                "author": "reviewer",
                "requested_behavior": "Reject empty parser input.",
                "evidence": ["src/parser.py:42 currently accepts it."],
                "disposition": "current-and-actionable",
            }
        ]
        self.assertIs(context_store.validate_state(state, 17), state)

        malformed_entries = (
            {"url": "https://example.test/review"},
            {
                **state["review_ledger"][0],
                "unexpected": "unsafe takeover ambiguity",
            },
            {**state["review_ledger"][0], "evidence": "not a list"},
            {**state["review_ledger"][0], "disposition": "invented"},
        )
        for entry in malformed_entries:
            with self.subTest(entry=entry):
                malformed = valid_state()
                malformed["review_ledger"] = [entry]
                with self.assertRaises(context_store.StateValidationError):
                    context_store.validate_state(malformed, 17)

    def test_changes_and_pending_decisions_have_exact_shapes(self):
        state = state_with_current_changes()
        packet = approval_packet()
        pending = {
            "question": "Approve this exact commit and push for this PR?",
            "options": [
                "Approve the exact displayed commit and push.",
                "Reject it and keep the verified diff local.",
                "Request changes to the proposed work.",
            ],
            "recommendation": "Approve only if the packet is correct.",
            "scope": "This PR only.",
            "packet_identity": packet,
        }
        state["pending_decisions"] = [pending]
        self.assertIs(context_store.validate_state(state, 17), state)

        for field in pending:
            with self.subTest(missing=field):
                malformed = state_with_current_changes()
                malformed["pending_decisions"] = [
                    {key: value for key, value in pending.items() if key != field}
                ]
                with self.assertRaises(context_store.StateValidationError):
                    context_store.validate_state(malformed, 17)

        malformed = state_with_current_changes()
        malformed["changes"]["extra"] = "ambiguous"
        with self.assertRaises(context_store.StateValidationError):
            context_store.validate_state(malformed, 17)

        stale = state_with_current_changes()
        stale_pending = json.loads(json.dumps(pending))
        stale_pending["packet_identity"]["diff_sha256"] = "c" * 64
        stale["pending_decisions"] = [stale_pending]
        with self.assertRaises(context_store.StateValidationError):
            context_store.validate_state(stale, 17)

    def test_valid_approval_requires_exact_packet_and_human_decision_linkage(self):
        state = approve_state(state_with_current_changes())
        self.assertIs(context_store.validate_state(state, 17), state)

        malformed_approvals = []
        missing_field = json.loads(json.dumps(state))
        del missing_field["approval"]["human_answer"]
        malformed_approvals.append(missing_field)

        wrong_kind = json.loads(json.dumps(state))
        wrong_kind["decision_history"][0]["decision_type"] = "agent-disposition"
        malformed_approvals.append(wrong_kind)

        wrong_index = json.loads(json.dumps(state))
        wrong_index["approval"]["decision_history_index"] = 42
        malformed_approvals.append(wrong_index)

        wrong_answer = json.loads(json.dumps(state))
        wrong_answer["approval"]["human_answer"] = "fabricated answer"
        malformed_approvals.append(wrong_answer)

        wrong_packet = json.loads(json.dumps(state))
        wrong_packet["approval"]["packet_identity"]["diff_sha256"] = "c" * 64
        malformed_approvals.append(wrong_packet)

        for malformed in malformed_approvals:
            with self.subTest(approval=malformed["approval"]):
                with self.assertRaises(context_store.StateValidationError):
                    context_store.validate_state(malformed, 17)

    def test_publish_outcome_controls_approval_authority(self):
        affirmative = approve_state(state_with_current_changes())
        self.assertIs(
            context_store.validate_state(affirmative, 17),
            affirmative,
        )

        for outcome, answer in (
            ("rejected", "Reject this exact packet."),
            ("changes-requested", "Request changes to this exact packet."),
        ):
            with self.subTest(outcome=outcome):
                state = approve_state(state_with_current_changes())
                decision = state["decision_history"][0]
                decision["outcome"] = outcome
                decision["answer"] = answer
                state["approval"]["human_answer"] = answer
                with self.assertRaises(context_store.StateValidationError):
                    context_store.validate_state(state, 17)

                state["approval"]["valid"] = False
                self.assertIs(context_store.validate_state(state, 17), state)

    def test_publish_decision_requires_options_and_exact_displayed_answer(self):
        empty_options = approve_state(state_with_current_changes())
        empty_options["decision_history"][0]["options"] = []
        with self.assertRaises(context_store.StateValidationError):
            context_store.validate_state(empty_options, 17)

        undisplayed_answer = approve_state(state_with_current_changes())
        undisplayed_answer["decision_history"][0]["answer"] = "Sure, do it."
        undisplayed_answer["approval"]["human_answer"] = "Sure, do it."
        with self.assertRaises(context_store.StateValidationError):
            context_store.validate_state(undisplayed_answer, 17)

        wrong_question = approve_state(state_with_current_changes())
        wrong_question["decision_history"][0]["question"] = (
            "Can I publish something?"
        )
        with self.assertRaises(context_store.StateValidationError):
            context_store.validate_state(wrong_question, 17)

    def test_recovery_metadata_is_reserved_for_state_recovery_events(self):
        state = valid_state()
        state["decision_history"].append(
            decision_event(
                revision=0,
                recovery={
                    "backup_name": "state-corrupt.json",
                    "backup_path": "/tmp/state-corrupt.json",
                }
            )
        )

        with self.assertRaises(context_store.StateValidationError):
            context_store.validate_state(state, 17)

    def test_valid_approval_cannot_leave_its_publish_decision_pending(self):
        state = approve_state(state_with_current_changes())
        state["pending_decisions"] = [
            {
                "question": "Approve this exact commit and push for this PR?",
                "options": [
                    "Approve the exact displayed commit and push.",
                    "Reject it and keep the verified diff local.",
                ],
                "recommendation": "Approve only if the packet is correct.",
                "scope": "This PR only.",
                "packet_identity": state["approval"]["packet_identity"],
            }
        ]

        with self.assertRaises(context_store.StateValidationError):
            context_store.validate_state(state, 17)

    def test_valid_approval_must_match_every_current_packet_field(self):
        for field, replacement in (
            ("head_repository", "fork/widgets"),
            ("head_branch", "feature/rebased"),
            ("head_sha", "c" * 40),
            ("diff_sha256", "c" * 64),
            ("included_files", ["src/other.py"]),
            ("commit_message", "Different exact message"),
        ):
            with self.subTest(field=field):
                state = approve_state(state_with_current_changes())
                if field in state["pull_request"]:
                    state["pull_request"][field] = replacement
                elif field == "included_files":
                    state["changes"]["files"] = replacement
                else:
                    state["changes"][field] = replacement
                with self.assertRaises(context_store.StateValidationError):
                    context_store.validate_state(state, 17)

    def test_publication_has_exact_shape_and_approval_linkage(self):
        state = approve_state(state_with_current_changes())
        packet = state["approval"]["packet_identity"]
        state["publication"] = {
            "commit_sha": "c" * 40,
            "pushed_sha": "c" * 40,
            "packet_identity": packet,
            "approval_decision_history_index": 0,
            "checks": ["python3 -m unittest: 52 tests passed"],
            "published_at": "2026-07-24T12:10:00Z",
        }
        self.assertIs(context_store.validate_state(state, 17), state)

        malformed_publications = []
        missing = json.loads(json.dumps(state))
        del missing["publication"]["published_at"]
        malformed_publications.append(missing)
        wrong_link = json.loads(json.dumps(state))
        wrong_link["publication"]["approval_decision_history_index"] = 7
        malformed_publications.append(wrong_link)
        wrong_packet = json.loads(json.dumps(state))
        wrong_packet["publication"]["packet_identity"]["commit_message"] = "Other"
        malformed_publications.append(wrong_packet)
        wrong_checks = json.loads(json.dumps(state))
        wrong_checks["publication"]["checks"] = "passed"
        malformed_publications.append(wrong_checks)

        for malformed in malformed_publications:
            with self.subTest(publication=malformed["publication"]):
                with self.assertRaises(context_store.StateValidationError):
                    context_store.validate_state(malformed, 17)

        missing_approval = json.loads(json.dumps(state))
        missing_approval["approval"] = None
        with self.assertRaises(context_store.StateValidationError):
            context_store.validate_state(missing_approval, 17)

        invalid_approval = json.loads(json.dumps(state))
        invalid_approval["approval"]["valid"] = False
        with self.assertRaises(context_store.StateValidationError):
            context_store.validate_state(invalid_approval, 17)

    def test_missing_state_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory, "repo")
            common = Path(directory, "repo", ".git")
            repository.mkdir()
            common.mkdir()
            runner = RecordingRunner(str(common))

            result = context_store.read_state(repository, 17, runner=runner)

            self.assertIsNone(result)

    @unittest.skipIf(os.name == "nt", "symlink permissions vary on Windows")
    def test_rejects_state_file_symlink_outside_pr_state_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory, "repo")
            common = repository / ".git"
            outside = Path(directory, "outside.json")
            repository.mkdir()
            common.mkdir()
            outside.write_text(json.dumps(valid_state()), encoding="utf-8")
            state = common / "apply-pr-reviews" / "pr-17"
            state.mkdir(parents=True)
            (state / "state.json").symlink_to(outside)
            runner = RecordingRunner(str(common))

            with self.assertRaises(context_store.StateValidationError):
                context_store.read_state(repository, 17, runner=runner)

    def test_read_rejects_copied_ledger_with_mismatched_local_path(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            state = valid_state(
                local_path=str(Path(directory, "other-repository")),
                workspace_path=str(repository),
            )
            state_dir = context_store.state_directory(repository, 17)
            state_dir.mkdir(parents=True)
            (state_dir / "state.json").write_text(
                json.dumps(state),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                context_store.StateValidationError,
                "local_path",
            ):
                context_store.read_state(repository, 17)

    @unittest.skipIf(os.name == "nt", "symlink behavior varies on Windows")
    def test_read_rejects_dangling_state_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            state_dir = context_store.state_directory(repository, 17)
            state_dir.mkdir(parents=True)
            (state_dir / "state.json").symlink_to(
                state_dir / "missing-state.json"
            )

            with self.assertRaises(context_store.StateValidationError):
                context_store.read_state(repository, 17)


class MutationTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "symlink behavior varies on Windows")
    def test_initialize_never_replaces_dangling_state_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            state_dir = context_store.state_directory(repository, 17)
            state_dir.mkdir(parents=True)
            state_path = state_dir / "state.json"
            target = state_dir / "missing-state.json"
            state_path.symlink_to(target)

            with self.assertRaises(context_store.ContextStoreError):
                context_store.initialize_state(
                    repository,
                    17,
                    valid_state(local_path=str(repository)),
                )

            self.assertTrue(state_path.is_symlink())
            self.assertEqual(os.readlink(state_path), str(target))

    def test_initialize_and_update_are_private_atomic_and_revision_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            initial = valid_state(local_path=str(repository.resolve()))

            written = context_store.initialize_state(
                repository, 17, initial
            )
            state_dir = context_store.state_directory(repository, 17)
            state_path = state_dir / "state.json"

            self.assertEqual(written["revision"], 0)
            if os.name != "nt":
                self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)
                self.assertEqual(
                    state_dir.parent.stat().st_mode & 0o777,
                    0o700,
                )

            updated = json.loads(json.dumps(written))
            updated["revision"] = 1
            updated["phase"] = "baseline"
            updated["decision_history"].append(decision_event())

            result = context_store.update_state(
                repository, 17, 0, updated
            )

            self.assertEqual(result["revision"], 1)
            self.assertEqual(
                context_store.read_state(repository, 17)["phase"],
                "baseline",
            )
            with self.assertRaises(context_store.RevisionConflict):
                context_store.update_state(repository, 17, 0, updated)

    def test_update_preserves_identity_and_history_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            initial = valid_state(local_path=str(repository.resolve()))
            context_store.initialize_state(repository, 17, initial)

            changed_identity = valid_state(
                revision=1,
                local_path=str(repository.resolve()),
            )
            changed_identity["repository"]["name_with_owner"] = "other/repo"
            with self.assertRaises(context_store.StateValidationError):
                context_store.update_state(
                    repository, 17, 0, changed_identity
                )

            other_repository = create_git_repository(
                Path(directory, "second")
            )
            initial_with_history = valid_state(
                local_path=str(other_repository.resolve())
            )
            initial_with_history["decision_history"] = [
                decision_event(revision=0)
            ]
            context_store.initialize_state(
                other_repository, 17, initial_with_history
            )
            removed_history = valid_state(
                revision=1,
                local_path=str(other_repository.resolve()),
            )
            with self.assertRaises(context_store.StateValidationError):
                context_store.update_state(
                    other_repository, 17, 0, removed_history
                )

    def test_existing_lock_blocks_update_and_exposes_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            initial = valid_state(local_path=str(repository.resolve()))
            context_store.initialize_state(repository, 17, initial)
            state_dir = context_store.state_directory(repository, 17)
            lock_dir = state_dir / ".lock"
            lock_dir.mkdir()
            (lock_dir / "owner.json").write_text(
                json.dumps(
                    {
                        "pid": 4242,
                        "created_at": "2026-07-24T12:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            updated = valid_state(
                revision=1,
                local_path=str(repository.resolve()),
            )
            with self.assertRaisesRegex(
                context_store.StateLockError, "4242"
            ):
                context_store.update_state(
                    repository, 17, 0, updated
                )

    def test_initialize_rejects_forged_valid_approval_without_human_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            forged = state_with_current_changes(
                local_path=str(repository.resolve())
            )
            forged["approval"] = {
                "valid": True,
                "packet_identity": approval_packet(),
                "decision_history_index": 0,
                "human_answer": "Approve it.",
            }

            with self.assertRaises(context_store.StateValidationError):
                context_store.initialize_state(repository, 17, forged)

            state_path = (
                context_store.state_directory(repository, 17) / "state.json"
            )
            self.assertFalse(state_path.exists())

    def test_initialize_accepts_valid_approval_with_exact_human_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            state = approve_state(
                state_with_current_changes(
                    local_path=str(repository.resolve())
                )
            )

            result = context_store.initialize_state(repository, 17, state)

            self.assertTrue(result["approval"]["valid"])

    def test_every_approved_packet_change_requires_explicit_invalidation(self):
        mutations = (
            ("head_repository", "fork/widgets"),
            ("head_branch", "feature/rebased"),
            ("head_sha", "c" * 40),
            ("diff_sha256", "c" * 64),
            ("files", ["src/other.py"]),
            ("commit_message", "Different exact message"),
        )
        for field, replacement in mutations:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    repository = create_git_repository(directory)
                    initial = approve_state(
                        state_with_current_changes(
                            local_path=str(repository.resolve())
                        )
                    )
                    context_store.initialize_state(repository, 17, initial)

                    unsafe = json.loads(json.dumps(initial))
                    unsafe["revision"] = 1
                    if field == "head_sha":
                        second_root = Path(directory, "second-workspace")
                        second_workspace = create_git_repository(second_root)
                        subprocess.run(
                            [
                                "git",
                                "-C",
                                str(second_workspace),
                                "commit",
                                "--allow-empty",
                                "-q",
                                "-m",
                                "Moved head",
                            ],
                            check=True,
                            capture_output=True,
                            text=True,
                        )
                        replacement = subprocess.run(
                            [
                                "git",
                                "-C",
                                str(second_workspace),
                                "rev-parse",
                                "HEAD",
                            ],
                            check=True,
                            capture_output=True,
                            text=True,
                        ).stdout.strip()
                        unsafe["workspace"] = {
                            "kind": "worktree",
                            "path": str(second_workspace.resolve()),
                            "base_sha": replacement,
                            "head_sha": replacement,
                        }
                    if field in unsafe["pull_request"]:
                        unsafe["pull_request"][field] = replacement
                    else:
                        unsafe["changes"][field] = replacement
                    with self.assertRaises(context_store.StateValidationError):
                        context_store.update_state(repository, 17, 0, unsafe)

                    safe = json.loads(json.dumps(unsafe))
                    safe["approval"]["valid"] = False
                    safe["decision_history"].append(
                        decision_event(
                            revision=1,
                            decision_type="approval-invalidated",
                            answer=(
                                f"Approval invalidated because {field} changed."
                            ),
                            transition="approval -> evaluate",
                            packet_identity=initial["approval"][
                                "packet_identity"
                            ],
                        )
                    )

                    result = context_store.update_state(
                        repository, 17, 0, safe
                    )

                    self.assertFalse(result["approval"]["valid"])

    def test_approved_packet_change_cannot_reuse_old_invalidation_history(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            initial = state_with_current_changes(
                local_path=str(repository.resolve())
            )
            initial["decision_history"].append(
                decision_event(
                    revision=0,
                    decision_type="approval-invalidated",
                    answer="Old event.",
                    transition="approval -> evaluate",
                    packet_identity=approval_packet(),
                )
            )
            initial = approve_state(initial)
            context_store.initialize_state(repository, 17, initial)

            changed = json.loads(json.dumps(initial))
            changed["revision"] = 1
            changed["changes"]["diff_sha256"] = "c" * 64
            changed["approval"]["valid"] = False

            with self.assertRaises(context_store.StateValidationError):
                context_store.update_state(repository, 17, 0, changed)

    @unittest.skipIf(os.name == "nt", "Windows does not use POSIX modes")
    def test_initialize_fails_closed_when_private_mode_cannot_be_set(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            initial = valid_state(local_path=str(repository.resolve()))
            state_path = (
                context_store.state_directory(repository, 17) / "state.json"
            )

            with mock.patch.object(
                context_store.os,
                "chmod",
                side_effect=PermissionError("chmod denied"),
            ):
                with self.assertRaises(PermissionError):
                    context_store.initialize_state(repository, 17, initial)

            self.assertFalse(state_path.exists())


class FingerprintTests(unittest.TestCase):
    def create_changed_workspace(self, directory):
        repository = create_git_repository(directory)
        (repository / "tracked.txt").write_text("before\n", encoding="utf-8")
        (repository / "deleted.txt").write_text("delete me\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repository), "add", "tracked.txt", "deleted.txt"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repository), "commit", "-q", "-m", "Add files"],
            check=True,
        )
        base_sha = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        (repository / "tracked.txt").write_text("after\n", encoding="utf-8")
        (repository / "deleted.txt").unlink()
        (repository / "untracked.txt").write_bytes(b"\x00new\xff\n")
        return repository, base_sha

    def compute(self, repository, base_sha, files):
        return context_store.compute_packet_identity(
            workspace_path=repository,
            workspace_kind="worktree",
            base_sha=base_sha,
            head_repository="acme/widgets",
            head_branch="feature/parser",
            head_sha=base_sha,
            commit_message="Apply exact review fixes",
            included_files=files,
        )

    def test_fingerprint_is_stable_and_covers_tracked_deleted_and_untracked(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, base_sha = self.create_changed_workspace(directory)
            files = ["untracked.txt", "tracked.txt", "deleted.txt"]

            first = self.compute(repository, base_sha, files)
            second = self.compute(repository, base_sha, list(reversed(files)))

            self.assertEqual(first, second)
            self.assertEqual(
                first["packet_identity"]["included_files"],
                sorted(files),
            )
            self.assertRegex(
                first["packet_identity"]["diff_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertEqual(first["workspace"]["base_sha"], base_sha)
            self.assertEqual(first["workspace"]["head_sha"], base_sha)

            def framed(tag, payload):
                return tag + struct.pack(">Q", len(payload)) + payload

            canonical = bytearray(b"apply-pr-reviews-change-v1\0")
            for path, base_mode, base_content, work_mode, work_content in (
                (
                    b"deleted.txt",
                    b"100644",
                    b"delete me\n",
                    b"missing",
                    b"",
                ),
                (
                    b"tracked.txt",
                    b"100644",
                    b"before\n",
                    b"100644",
                    b"after\n",
                ),
                (
                    b"untracked.txt",
                    b"missing",
                    b"",
                    b"100644",
                    b"\x00new\xff\n",
                ),
            ):
                canonical.extend(framed(b"P", path))
                canonical.extend(framed(b"M", base_mode))
                canonical.extend(framed(b"B", base_content))
                canonical.extend(framed(b"m", work_mode))
                canonical.extend(framed(b"W", work_content))
            self.assertEqual(
                first["packet_identity"]["diff_sha256"],
                hashlib.sha256(canonical).hexdigest(),
            )

            old_hash = first["packet_identity"]["diff_sha256"]
            if os.name != "nt":
                os.chmod(repository / "tracked.txt", 0o755)
                mode_changed = self.compute(repository, base_sha, files)
                self.assertNotEqual(
                    mode_changed["packet_identity"]["diff_sha256"],
                    old_hash,
                )
                os.chmod(repository / "tracked.txt", 0o644)
            (repository / "tracked.txt").write_text(
                "different after\n",
                encoding="utf-8",
            )
            changed = self.compute(repository, base_sha, files)
            self.assertNotEqual(
                changed["packet_identity"]["diff_sha256"],
                old_hash,
            )

    def test_fingerprint_rejects_unchanged_missing_outside_and_wrong_base(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, base_sha = self.create_changed_workspace(directory)
            for files in (
                ["missing.txt"],
                ["../outside.txt"],
            ):
                with self.subTest(files=files), self.assertRaises(
                    context_store.StateValidationError
                ):
                    self.compute(repository, base_sha, files)

            if os.name != "nt":
                outside = Path(directory, "outside")
                outside.mkdir()
                (outside / "external.txt").write_text(
                    "outside\n",
                    encoding="utf-8",
                )
                (repository / "linked-directory").symlink_to(
                    outside,
                    target_is_directory=True,
                )
                with self.assertRaises(context_store.StateValidationError):
                    self.compute(
                        repository,
                        base_sha,
                        ["linked-directory/external.txt"],
                    )

            nested = repository / "nested"
            nested.mkdir()
            (nested / "new.txt").write_text("nested\n", encoding="utf-8")
            with self.assertRaises(context_store.StateValidationError):
                self.compute(nested, base_sha, ["new.txt"])

            (repository / "unchanged.txt").write_text(
                "same\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "-C", str(repository), "add", "unchanged.txt"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "commit", "-q", "-m", "Same"],
                check=True,
            )
            new_head = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            with self.assertRaises(context_store.StateValidationError):
                self.compute(repository, new_head, ["unchanged.txt"])
            with self.assertRaises(context_store.StateValidationError):
                self.compute(repository, base_sha, ["tracked.txt"])

    def test_read_fails_closed_for_missing_or_mismatched_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            state = valid_state(local_path=str(repository))
            state_dir = context_store.state_directory(repository, 17)
            state_dir.mkdir(parents=True)
            state["workspace"]["path"] = str(
                Path(directory, "missing-workspace").resolve()
            )
            (state_dir / "state.json").write_text(
                json.dumps(state),
                encoding="utf-8",
            )
            with self.assertRaises(context_store.StateValidationError):
                context_store.read_state(repository, 17)


class RecoveryTests(unittest.TestCase):
    QUESTION = "How should the preserved invalid local state be handled?"
    ANSWER = (
        "Authorize moving the invalid state to a named private backup, then "
        "initialize fresh state."
    )

    def create_corrupt_state(self, repository, content="{broken"):
        state_dir = context_store.state_directory(repository, 17)
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / "state.json"
        state_path.write_text(content, encoding="utf-8")
        return state_dir, state_path

    def recover(self, repository, backup_name="state-corrupt.json"):
        return context_store.recover_state(
            repository,
            17,
            backup_name=backup_name,
            recovery_question=self.QUESTION,
            human_answer=self.ANSWER,
        )

    def test_recover_moves_regular_corrupt_state_and_prints_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            state_dir, state_path = self.create_corrupt_state(repository)

            result = self.recover(repository)

            backup = state_dir / "state-corrupt.json"
            self.assertFalse(os.path.lexists(state_path))
            self.assertEqual(backup.read_text(encoding="utf-8"), "{broken")
            self.assertEqual(
                result,
                {
                    "backup_name": "state-corrupt.json",
                    "backup_path": str(backup.resolve()),
                    "recovery_question": self.QUESTION,
                    "human_answer": self.ANSWER,
                },
            )
            if os.name != "nt":
                self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
                self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)

    @unittest.skipIf(os.name == "nt", "symlink behavior varies on Windows")
    def test_recover_moves_dangling_symlink_without_following_it(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            state_dir = context_store.state_directory(repository, 17)
            state_dir.mkdir(parents=True)
            state_path = state_dir / "state.json"
            target = state_dir / "missing-target.json"
            state_path.symlink_to(target)

            self.recover(repository, "dangling-state")

            backup = state_dir / "dangling-state"
            self.assertFalse(os.path.lexists(state_path))
            self.assertTrue(backup.is_symlink())
            self.assertEqual(os.readlink(backup), str(target))

    def test_recover_rejects_unsafe_or_existing_backup_names(self):
        for backup_name in (
            "",
            "../escape",
            "nested/name",
            "state.json",
            ".lock",
            "recovery.json",
        ):
            with self.subTest(backup_name=backup_name):
                with tempfile.TemporaryDirectory() as directory:
                    repository = create_git_repository(directory)
                    _, state_path = self.create_corrupt_state(repository)
                    with self.assertRaises(
                        context_store.StateValidationError
                    ):
                        self.recover(repository, backup_name)
                    self.assertTrue(os.path.lexists(state_path))

        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            state_dir, state_path = self.create_corrupt_state(repository)
            (state_dir / "existing-backup").write_text(
                "preserve",
                encoding="utf-8",
            )
            with self.assertRaises(context_store.StateValidationError):
                self.recover(repository, "existing-backup")
            self.assertTrue(os.path.lexists(state_path))

    def test_recover_respects_existing_pr_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            state_dir, state_path = self.create_corrupt_state(repository)
            lock_dir = state_dir / ".lock"
            lock_dir.mkdir()
            (lock_dir / "owner.json").write_text(
                '{"pid": 9}',
                encoding="utf-8",
            )

            with self.assertRaises(context_store.StateLockError):
                self.recover(repository)

            self.assertTrue(os.path.lexists(state_path))

    def test_fresh_init_after_recovery_requires_exact_first_history_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            self.create_corrupt_state(repository)
            recovery = self.recover(repository)
            state = valid_state(local_path=str(repository))

            with self.assertRaises(context_store.StateValidationError):
                context_store.initialize_state(repository, 17, state)

            state["decision_history"].append(
                decision_event(
                    revision=0,
                    decision_type="state-recovery",
                    answer=self.ANSWER,
                    transition="blocked -> evaluate",
                    question=self.QUESTION,
                    recovery={
                        "backup_name": recovery["backup_name"],
                        "backup_path": recovery["backup_path"],
                    },
                )
            )
            result = context_store.initialize_state(repository, 17, state)
            self.assertEqual(
                result["decision_history"][0]["decision_type"],
                "state-recovery",
            )


class CliTests(unittest.TestCase):
    def test_read_missing_state_prints_null(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = context_store.main(
                    ["read", "--repo", str(repository), "--pr", "17"]
                )
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), None)

    def test_init_read_and_update_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            initial = valid_state(
                local_path=str(repository.resolve())
            )
            updated = valid_state(
                revision=1,
                local_path=str(repository.resolve()),
            )
            updated["phase"] = "baseline"

            with patch.object(
                context_store.sys,
                "stdin",
                StringIO(json.dumps(initial)),
            ), redirect_stdout(StringIO()):
                self.assertEqual(
                    context_store.main(
                        [
                            "init",
                            "--repo",
                            str(repository),
                            "--pr",
                            "17",
                        ]
                    ),
                    0,
                )
            with patch.object(
                context_store.sys,
                "stdin",
                StringIO(json.dumps(updated)),
            ), redirect_stdout(StringIO()):
                self.assertEqual(
                    context_store.main(
                        [
                            "update",
                            "--repo",
                            str(repository),
                            "--pr",
                            "17",
                            "--expected-revision",
                            "0",
                        ]
                    ),
                    0,
                )
            state = context_store.read_state(repository, 17)
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["phase"], "baseline")

    def test_cli_reports_revision_conflict_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            context_store.initialize_state(
                repository,
                17,
                valid_state(local_path=str(repository.resolve())),
            )
            updated = valid_state(
                revision=1,
                local_path=str(repository.resolve()),
            )
            stderr = StringIO()
            with patch.object(
                context_store.sys,
                "stdin",
                StringIO(json.dumps(updated)),
            ), redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                context_store.main(
                    [
                        "update",
                        "--repo",
                        str(repository),
                        "--pr",
                        "17",
                        "--expected-revision",
                        "5",
                    ]
                )
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("revision", stderr.getvalue().lower())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_fingerprint_cli_prints_packet_and_workspace_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            (repository / "new.txt").write_text("new\n", encoding="utf-8")
            head_sha = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = context_store.main(
                    [
                        "fingerprint",
                        "--workspace",
                        str(repository),
                        "--workspace-kind",
                        "worktree",
                        "--base-sha",
                        head_sha,
                        "--head-repository",
                        "acme/widgets",
                        "--head-branch",
                        "feature/parser",
                        "--head-sha",
                        head_sha,
                        "--commit-message",
                        "Add new file",
                        "--file",
                        "new.txt",
                    ]
                )
            result = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(
                result["packet_identity"]["included_files"],
                ["new.txt"],
            )

    def test_recover_cli_moves_corrupt_state(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            state_dir = context_store.state_directory(repository, 17)
            state_dir.mkdir(parents=True)
            (state_dir / "state.json").write_text("{broken", encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = context_store.main(
                    [
                        "recover",
                        "--repo",
                        str(repository),
                        "--pr",
                        "17",
                        "--backup-name",
                        "state-corrupt.json",
                        "--recovery-question",
                        RecoveryTests.QUESTION,
                        "--human-answer",
                        RecoveryTests.ANSWER,
                    ]
                )
            result = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(result["backup_name"], "state-corrupt.json")
