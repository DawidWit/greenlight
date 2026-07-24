import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "context_store.py"
)
SPEC = importlib.util.spec_from_file_location("context_store", SCRIPT_PATH)
context_store = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(context_store)


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
        "changes": {"files": [], "summary": ""},
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
    }


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
