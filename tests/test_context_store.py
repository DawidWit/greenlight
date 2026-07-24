import importlib.util
import hashlib
import json
import os
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
    head_sha="a" * 40,
    local_path="/tmp/widgets",
):
    return {
        "schema_version": 1,
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
        )
    )
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
                )
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


class MutationTests(unittest.TestCase):
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
