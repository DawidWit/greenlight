# Superpowers-Style Apply PR Reviews Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `apply-pr-reviews` into a Superpowers-style skill with conspicuous human-decision gates and a private, concurrent-safe local handoff store for later agents.

**Architecture:** Keep the behavioral contract in one `SKILL.md`. Keep `collect_reviews.py` read-only and add a separate standard-library-only `context_store.py` that stores one validated `state.json` per PR under the repository's Git common directory. Protect state with atomic replacement, a monotonic revision, and a PR-scoped lock.

**Tech Stack:** Agent Skills Markdown/YAML, Python 3.9 standard library, `unittest`, Git, GitHub CLI.

## Global Constraints

- Support Python 3.9 or newer without third-party runtime packages.
- Store context only under `<git-common-dir>/apply-pr-reviews/pr-<number>/state.json`.
- Use directory mode `0700` and file mode `0600` where the platform supports POSIX permissions.
- Never commit, push, or synchronize local decision state.
- Never store secret-shaped fields or sensitive values such as raw environment
  output, raw authentication output, authorization headers, cookies, private
  keys, or common credential material. Store safe summaries only.
- Require a current exact approval packet before `git add`, `git commit`, or `git push`.
- The target skill's Iron Law governs runtime use of the completed
  `apply-pr-reviews` skill on pull requests. It does not prohibit local
  implementation commits required by this plan when the human-selected
  Subagent-Driven workflow authorizes them.
- Never force-push.
- Never reply to or resolve review threads, post PR comments, approve, merge, or close a PR without a separate explicit request.
- Keep `SKILL.md` below 500 lines.
- Keep the user-facing repository selection based on local directories, not `owner/repository` arguments.

---

## File Map

- Create `scripts/context_store.py`: resolve Git-local storage, validate state, enforce revision/lock rules, and expose `read`, `init`, and `update` commands.
- Create `tests/test_context_store.py`: unit and CLI coverage for storage boundaries, schema, permissions, concurrency, history, and takeover.
- Modify `tests/test_skill_contract.py`: require the Superpowers structure, Iron Law, human-decision contract, and local-ledger rules.
- Modify `SKILL.md`: replace the current workflow prose with the approved Superpowers-style behavioral contract.
- Keep `scripts/collect_reviews.py` and `tests/test_collect_reviews.py` behavior unchanged.
- Keep `agents/openai.yaml` unchanged because its display name, short description, and invocation prompt remain accurate.

### Task 1: Context Store Paths, Schema, and Read-Only Takeover

**Files:**
- Create: `tests/test_context_store.py`
- Create: `scripts/context_store.py`

**Interfaces:**
- Consumes: a local repository path and positive PR number.
- Produces:
  - `resolve_git_common_dir(repo_path: Path, runner=run_command) -> Path`
  - `state_directory(repo_path: Path, pr_number: int, runner=run_command) -> Path`
  - `validate_state(state: dict, expected_pr: Optional[int] = None) -> dict`
  - `read_state(repo_path: Path, pr_number: int, runner=run_command) -> Optional[dict]`

- [ ] **Step 1: Write failing path and schema tests**

Create `tests/test_context_store.py` with this foundation:

```python
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
        [
            "git",
            "-C",
            str(repository),
            "config",
            "user.email",
            "test@example.com",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "Initial",
        ],
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

            result = context_store.resolve_git_common_dir(
                repository, runner=runner
            )

            self.assertEqual(result, (repository / ".git").resolve())
            self.assertEqual(
                runner.commands[0][0],
                [
                    "git",
                    "-C",
                    str(repository.resolve()),
                    "rev-parse",
                    "--git-common-dir",
                ],
            )

    def test_state_directory_cannot_escape_git_common_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory, "repo")
            common = Path(directory, "repo", ".git")
            repository.mkdir()
            common.mkdir()
            runner = RecordingRunner(str(common))

            result = context_store.state_directory(
                repository, 17, runner=runner
            )

            self.assertEqual(
                result,
                common.resolve() / "apply-pr-reviews" / "pr-17",
            )
            with self.assertRaises(context_store.StateValidationError):
                context_store.state_directory(
                    repository, 0, runner=runner
                )

    @unittest.skipIf(os.name == "nt", "symlink permissions vary on Windows")
    def test_store_symlink_cannot_escape_git_common_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory, "repo")
            common = repository / ".git"
            outside = Path(directory, "outside")
            repository.mkdir()
            common.mkdir()
            outside.mkdir()
            (common / "apply-pr-reviews").symlink_to(
                outside,
                target_is_directory=True,
            )
            runner = RecordingRunner(str(common))

            with self.assertRaises(context_store.StateValidationError):
                context_store.state_directory(
                    repository, 17, runner=runner
                )

    def test_worktree_resolves_to_main_repository_common_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            worktree = Path(directory, "worktree")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "worktree",
                    "add",
                    "--detach",
                    "-q",
                    str(worktree),
                    "HEAD",
                ],
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

    def test_missing_state_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory, "repo")
            common = Path(directory, "repo", ".git")
            repository.mkdir()
            common.mkdir()
            runner = RecordingRunner(str(common))

            result = context_store.read_state(
                repository, 17, runner=runner
            )

            self.assertIsNone(result)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_context_store -v
```

Expected: ERROR importing `scripts/context_store.py` because the file does not exist.

- [ ] **Step 3: Implement path resolution, schema validation, and read**

Create `scripts/context_store.py`:

```python
#!/usr/bin/env python3
"""Persist private per-PR handoff context inside a repository's Git data."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional


SCHEMA_VERSION = 1
STORE_DIRECTORY = "apply-pr-reviews"
STATE_FILENAME = "state.json"
REQUIRED_TOP_LEVEL = {
    "schema_version",
    "revision",
    "repository",
    "pull_request",
    "phase",
    "status",
    "review_ledger",
    "changes",
    "verification",
    "pending_decisions",
    "decision_history",
    "approval",
    "publication",
    "updated_at",
}
FORBIDDEN_KEY = re.compile(
    r"(authorization|cookie|credential|password|secret|token)",
    re.IGNORECASE,
)
FORBIDDEN_NORMALIZED_KEYS = {
    "env",
    "environment",
    "environmentvariables",
    "auth",
    "authentication",
    "authenticationoutput",
    "authoutput",
}
FORBIDDEN_NORMALIZED_PATTERN = re.compile(
    r"(?:env|environment)(?:var|variable)s?"
    r"|(?:auth|authentication)outputs?"
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DECISION_FIELDS = {
    "revision",
    "timestamp",
    "decision_type",
    "evidence",
    "options",
    "recommendation",
    "answer",
    "scope",
    "transition",
}


class ContextStoreError(RuntimeError):
    """Base error for expected context-store failures."""


class GitContextError(ContextStoreError):
    """Raised when the Git common directory cannot be resolved."""


class StateValidationError(ContextStoreError):
    """Raised when state is malformed, unsafe, or mismatched."""


class RevisionConflict(ContextStoreError):
    """Raised when another agent updated the state first."""


class StateLockError(ContextStoreError):
    """Raised when another process owns the PR state lock."""


def run_command(command, *, cwd=None):
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise GitContextError(
            f"Required command is not installed: {command[0]}"
        ) from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GitContextError(
            f"Command failed ({completed.returncode}): {' '.join(command)}"
            + (f"\n{detail}" if detail else "")
        )
    return completed.stdout


def resolve_git_common_dir(repo_path, *, runner=run_command):
    repository = Path(repo_path).expanduser().resolve()
    if not repository.is_dir():
        raise GitContextError(f"Repository directory does not exist: {repository}")
    output = runner(
        [
            "git",
            "-C",
            str(repository),
            "rev-parse",
            "--git-common-dir",
        ],
        cwd=None,
    ).strip()
    if not output:
        raise GitContextError(f"Git common directory is empty: {repository}")
    common = Path(output)
    if not common.is_absolute():
        common = repository / common
    return common.resolve()


def state_directory(repo_path, pr_number, *, runner=run_command):
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number < 1:
        raise StateValidationError("PR number must be a positive integer.")
    common = resolve_git_common_dir(repo_path, runner=runner)
    root = (common / STORE_DIRECTORY).resolve()
    if root.parent != common:
        raise StateValidationError("State root escaped the Git common directory.")
    target = (root / f"pr-{pr_number}").resolve()
    if target.parent != root:
        raise StateValidationError("State path escaped the Git common directory.")
    return target


def _reject_forbidden_keys(value, path="state"):
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise StateValidationError(f"Non-string key at {path}.")
            normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
            if (
                FORBIDDEN_KEY.search(key)
                or normalized_key in FORBIDDEN_NORMALIZED_KEYS
                or FORBIDDEN_NORMALIZED_PATTERN.fullmatch(normalized_key)
            ):
                raise StateValidationError(f"Forbidden key at {path}.{key}.")
            _reject_forbidden_keys(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden_keys(nested, f"{path}[{index}]")


def validate_state(state, expected_pr=None):
    if not isinstance(state, dict):
        raise StateValidationError("State must be a JSON object.")
    if set(state) != REQUIRED_TOP_LEVEL:
        missing = sorted(REQUIRED_TOP_LEVEL - set(state))
        extra = sorted(set(state) - REQUIRED_TOP_LEVEL)
        raise StateValidationError(
            f"State keys mismatch; missing={missing}, extra={extra}."
        )
    if state["schema_version"] != SCHEMA_VERSION:
        raise StateValidationError(f"schema_version must be {SCHEMA_VERSION}.")
    revision = state["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise StateValidationError("revision must be a non-negative integer.")
    repository = state["repository"]
    pull_request = state["pull_request"]
    if not isinstance(repository, dict) or set(repository) != {
        "name_with_owner",
        "local_path",
    }:
        raise StateValidationError("repository identity is invalid.")
    for key in ("name_with_owner", "local_path"):
        if not isinstance(repository[key], str) or not repository[key]:
            raise StateValidationError(f"repository.{key} is invalid.")
    required_pr = {
        "number",
        "url",
        "base_branch",
        "head_repository",
        "head_branch",
        "head_sha",
    }
    if not isinstance(pull_request, dict) or set(pull_request) != required_pr:
        raise StateValidationError("pull_request identity is invalid.")
    number = pull_request["number"]
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise StateValidationError("pull_request.number is invalid.")
    if expected_pr is not None and number != expected_pr:
        raise StateValidationError(
            f"State is for PR {number}, expected PR {expected_pr}."
        )
    head_sha = pull_request["head_sha"]
    if not isinstance(head_sha, str) or not SHA_PATTERN.fullmatch(head_sha):
        raise StateValidationError("pull_request.head_sha must be 40 hex characters.")
    for key in (
        "url",
        "base_branch",
        "head_repository",
        "head_branch",
    ):
        if not isinstance(pull_request[key], str) or not pull_request[key]:
            raise StateValidationError(f"pull_request.{key} is invalid.")
    for key in ("review_ledger", "pending_decisions", "decision_history"):
        if not isinstance(state[key], list):
            raise StateValidationError(f"{key} must be a list.")
    for key in ("changes", "verification"):
        if not isinstance(state[key], dict):
            raise StateValidationError(f"{key} must be an object.")
    for key in ("approval", "publication"):
        if state[key] is not None and not isinstance(state[key], dict):
            raise StateValidationError(f"{key} must be null or an object.")
    for key in ("phase", "status", "updated_at"):
        if not isinstance(state[key], str) or not state[key]:
            raise StateValidationError(f"{key} must be a non-empty string.")
    for index, decision in enumerate(state["decision_history"]):
        if not isinstance(decision, dict) or set(decision) != DECISION_FIELDS:
            raise StateValidationError(
                f"decision_history[{index}] has invalid fields."
            )
        if (
            not isinstance(decision["revision"], int)
            or isinstance(decision["revision"], bool)
            or decision["revision"] < 0
            or decision["revision"] > revision
        ):
            raise StateValidationError(
                f"decision_history[{index}].revision is invalid."
            )
        for key in (
            "timestamp",
            "decision_type",
            "recommendation",
            "answer",
            "scope",
            "transition",
        ):
            if not isinstance(decision[key], str):
                raise StateValidationError(
                    f"decision_history[{index}].{key} must be a string."
                )
        for key in ("evidence", "options"):
            if not isinstance(decision[key], list):
                raise StateValidationError(
                    f"decision_history[{index}].{key} must be a list."
                )
    _reject_forbidden_keys(state)
    return state


def read_state(repo_path, pr_number, *, runner=run_command):
    path = state_directory(repo_path, pr_number, runner=runner) / STATE_FILENAME
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StateValidationError(f"Cannot read valid state: {path}") from error
    return validate_state(state, pr_number)
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_context_store -v
```

Expected: all context-store path, schema, and read tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add scripts/context_store.py tests/test_context_store.py
git commit -m "feat: add local PR context schema"
```

### Task 2: Atomic State Updates, History, Permissions, and Locking

**Files:**
- Modify: `tests/test_context_store.py`
- Modify: `scripts/context_store.py`

**Interfaces:**
- Consumes: a validated full state document and expected prior revision.
- Produces:
  - `initialize_state(repo_path, pr_number, state, runner=run_command) -> dict`
  - `update_state(repo_path, pr_number, expected_revision, state, runner=run_command) -> dict`
  - `pr_lock(state_dir: Path) -> ContextManager[None]`

- [ ] **Step 1: Add failing mutation tests**

Append these cases to `tests/test_context_store.py` (and import `mock` with
`from unittest import mock`):

```python
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

    def test_head_change_invalidates_existing_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            initial = valid_state(local_path=str(repository.resolve()))
            initial["approval"] = {
                "valid": True,
                "head_sha": "a" * 40,
            }
            context_store.initialize_state(repository, 17, initial)

            unsafe = valid_state(
                revision=1,
                head_sha="b" * 40,
                local_path=str(repository.resolve()),
            )
            unsafe["approval"] = initial["approval"]
            with self.assertRaises(context_store.StateValidationError):
                context_store.update_state(repository, 17, 0, unsafe)

            safe = valid_state(
                revision=1,
                head_sha="b" * 40,
                local_path=str(repository.resolve()),
            )
            safe["approval"] = {
                "valid": False,
                "head_sha": "a" * 40,
            }
            safe["decision_history"].append(
                decision_event(
                    decision_type="head-sha-invalidated",
                    answer="Approval invalidated",
                    transition="approval -> evaluate",
                )
            )
            result = context_store.update_state(
                repository, 17, 0, safe
            )

            self.assertFalse(result["approval"]["valid"])

    def test_head_change_requires_a_new_current_revision_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = create_git_repository(directory)
            initial = valid_state(local_path=str(repository.resolve()))
            initial["approval"] = {"valid": True, "head_sha": "a" * 40}
            initial["decision_history"].append(
                decision_event(
                    revision=0,
                    decision_type="head-sha-invalidated",
                    answer="Previous approval invalidated",
                    transition="approval -> evaluate",
                )
            )
            context_store.initialize_state(repository, 17, initial)

            reused_event = valid_state(
                revision=1,
                head_sha="b" * 40,
                local_path=str(repository.resolve()),
            )
            reused_event["approval"] = {
                "valid": False,
                "head_sha": "a" * 40,
            }
            reused_event["decision_history"] = initial["decision_history"]

            with self.assertRaises(context_store.StateValidationError):
                context_store.update_state(repository, 17, 0, reused_event)

    def test_push_target_change_invalidates_existing_approval(self):
        for field, value in (
            ("head_repository", "fork/widgets"),
            ("head_branch", "feature/other-parser"),
        ):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    repository = create_git_repository(directory)
                    initial = valid_state(
                        local_path=str(repository.resolve())
                    )
                    initial["approval"] = {
                        "valid": True,
                        "head_sha": "a" * 40,
                    }
                    context_store.initialize_state(repository, 17, initial)

                    unsafe = valid_state(
                        revision=1,
                        local_path=str(repository.resolve()),
                    )
                    unsafe["pull_request"][field] = value
                    unsafe["approval"] = initial["approval"]
                    with self.assertRaises(context_store.StateValidationError):
                        context_store.update_state(repository, 17, 0, unsafe)

                    safe = valid_state(
                        revision=1,
                        local_path=str(repository.resolve()),
                    )
                    safe["pull_request"][field] = value
                    safe["approval"] = {
                        "valid": False,
                        "head_sha": "a" * 40,
                    }
                    safe["decision_history"].append(
                        decision_event(
                            revision=1,
                            decision_type="head-sha-invalidated",
                            answer="Approval invalidated",
                            transition="approval -> evaluate",
                        )
                    )
                    result = context_store.update_state(
                        repository, 17, 0, safe
                    )

                    self.assertFalse(result["approval"]["valid"])

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
```

- [ ] **Step 2: Run mutation tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_context_store.MutationTests -v
```

Expected: ERROR because `initialize_state`, `update_state`, and locking are undefined.

- [ ] **Step 3: Implement lock, atomic write, initialization, and CAS update**

Add to `scripts/context_store.py`:

```python
from datetime import datetime, timezone


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _identity(state):
    return {
        "repository": state["repository"],
        "number": state["pull_request"]["number"],
        "url": state["pull_request"]["url"],
    }


def _validate_repository_path(state, repo_path):
    configured = Path(
        state["repository"]["local_path"]
    ).expanduser().resolve()
    actual = Path(repo_path).expanduser().resolve()
    if configured != actual:
        raise StateValidationError(
            f"State local_path is {configured}, expected {actual}."
        )


def _set_private_mode(path, mode):
    if os.name != "posix":
        return
    os.chmod(path, mode)


def _push_target(state):
    pull_request = state["pull_request"]
    return (
        pull_request["head_repository"],
        pull_request["head_branch"],
        pull_request["head_sha"],
    )


def _has_current_invalidation_event(old_history, new_history, revision):
    return any(
        decision["decision_type"] == "head-sha-invalidated"
        and decision["revision"] == revision
        for decision in new_history[len(old_history) :]
    )


@contextmanager
def pr_lock(state_dir):
    state_dir.mkdir(parents=True, exist_ok=True)
    _set_private_mode(state_dir.parent, 0o700)
    _set_private_mode(state_dir, 0o700)
    lock_dir = state_dir / ".lock"
    try:
        lock_dir.mkdir()
        _set_private_mode(lock_dir, 0o700)
    except FileExistsError as error:
        metadata_path = lock_dir / "owner.json"
        try:
            metadata = metadata_path.read_text(encoding="utf-8").strip()
        except OSError:
            metadata = "metadata unavailable"
        raise StateLockError(
            f"PR state is locked at {lock_dir}: {metadata}"
        ) from error

    owner_path = lock_dir / "owner.json"
    try:
        owner_path.write_text(
            json.dumps(
                {"pid": os.getpid(), "created_at": _utc_now()},
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        _set_private_mode(owner_path, 0o600)
        yield
    finally:
        try:
            owner_path.unlink()
        except FileNotFoundError:
            pass
        try:
            lock_dir.rmdir()
        except FileNotFoundError:
            pass


def _atomic_write(path, state):
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".state.",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _set_private_mode(temporary_name, 0o600)
        os.replace(temporary_name, path)
        _set_private_mode(path, 0o600)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def initialize_state(repo_path, pr_number, state, *, runner=run_command):
    validate_state(state, pr_number)
    _validate_repository_path(state, repo_path)
    if state["revision"] != 0:
        raise StateValidationError("Initial state revision must be 0.")
    state_dir = state_directory(repo_path, pr_number, runner=runner)
    with pr_lock(state_dir):
        path = state_dir / STATE_FILENAME
        if path.exists():
            raise RevisionConflict(
                f"State already exists for PR {pr_number}: {path}"
            )
        _atomic_write(path, state)
    return state


def update_state(
    repo_path,
    pr_number,
    expected_revision,
    state,
    *,
    runner=run_command,
):
    validate_state(state, pr_number)
    _validate_repository_path(state, repo_path)
    if state["revision"] != expected_revision + 1:
        raise RevisionConflict(
            "New state revision must equal expected revision plus one."
        )
    state_dir = state_directory(repo_path, pr_number, runner=runner)
    with pr_lock(state_dir):
        current = read_state(repo_path, pr_number, runner=runner)
        if current is None:
            raise RevisionConflict(f"State does not exist for PR {pr_number}.")
        if current["revision"] != expected_revision:
            raise RevisionConflict(
                f"Expected revision {expected_revision}, "
                f"found {current['revision']}."
            )
        if _identity(current) != _identity(state):
            raise StateValidationError(
                "Repository and PR identity cannot change."
            )
        old_history = current["decision_history"]
        new_history = state["decision_history"]
        if new_history[: len(old_history)] != old_history:
            raise StateValidationError(
                "decision_history must preserve its existing prefix."
            )
        current_approval = current["approval"]
        if (
            _push_target(current) != _push_target(state)
            and isinstance(current_approval, dict)
            and current_approval.get("valid") is True
        ):
            approval = state["approval"]
            if (
                not isinstance(approval, dict)
                or approval.get("valid") is not False
                or not _has_current_invalidation_event(
                    old_history, new_history, state["revision"]
                )
            ):
                raise StateValidationError(
                    "A push target change must invalidate approval and append "
                    "a current-revision head-sha-invalidated decision."
                )
        _atomic_write(state_dir / STATE_FILENAME, state)
    return state
```

- [ ] **Step 4: Run mutation and full context-store tests**

Run:

```bash
python3 -m unittest tests.test_context_store -v
```

Expected: all context-store tests pass and no `.lock` directory remains after successful updates.

- [ ] **Step 5: Commit Task 2**

```bash
git add scripts/context_store.py tests/test_context_store.py
git commit -m "feat: make PR context updates concurrent-safe"
```

### Task 3: Context Store CLI and Takeover Integration

**Files:**
- Modify: `tests/test_context_store.py`
- Modify: `scripts/context_store.py`

**Interfaces:**
- Produces CLI commands:
  - `python3 scripts/context_store.py read --repo PATH --pr NUMBER`
  - `python3 scripts/context_store.py init --repo PATH --pr NUMBER`
  - `python3 scripts/context_store.py update --repo PATH --pr NUMBER --expected-revision REVISION`
- Reads one complete JSON state document from standard input for `init` and
  `update`.

- [ ] **Step 1: Add failing CLI tests**

Append to `tests/test_context_store.py`:

```python
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch


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
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_context_store.CliTests -v
```

Expected: ERROR because `main` and CLI parsing are undefined.

- [ ] **Step 3: Implement JSON input and CLI commands**

Add to `scripts/context_store.py`:

```python
def _read_input():
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError as error:
        raise StateValidationError("Cannot read JSON state from stdin.") from error


def create_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Persist private per-PR handoff context inside Git metadata."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("read", "init", "update"):
        command = subparsers.add_parser(name)
        command.add_argument("--repo", required=True, type=Path)
        command.add_argument("--pr", required=True, type=int)
        if name == "update":
            command.add_argument(
                "--expected-revision", required=True, type=int
            )
    return parser


def main(argv=None):
    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "read":
            result = read_state(args.repo, args.pr)
        elif args.command == "init":
            result = initialize_state(
                args.repo,
                args.pr,
                _read_input(),
            )
        else:
            result = update_state(
                args.repo,
                args.pr,
                args.expected_revision,
                _read_input(),
            )
    except ContextStoreError as error:
        parser.exit(2, f"error: {error}\n")
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI and full Python tests**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/collect_reviews.py scripts/context_store.py
python3 scripts/context_store.py --help
```

Expected:

- The complete test suite reports zero failures and zero errors.
- Both scripts compile.
- Help lists `read`, `init`, and `update`.

- [ ] **Step 5: Mark the context-store script executable and commit**

```bash
chmod 755 scripts/context_store.py
git add scripts/context_store.py tests/test_context_store.py
git commit -m "feat: add PR context handoff CLI"
```

### Task 4: Rewrite the Skill in Full Superpowers Style

**Files:**
- Modify: `tests/test_skill_contract.py`
- Modify: `SKILL.md`

**Interfaces:**
- Consumes: the collector CLI and context-store CLI completed in Tasks 1–3.
- Produces: one portable Agent Skill behavioral contract below 500 lines.

- [ ] **Step 1: Run behavioral RED scenarios against the current skill**

Use fresh-context agents with the current `SKILL.md`. Do not expose the expected
answer. Run each prompt once:

```text
Use $apply-pr-reviews at ./SKILL.md from the repository root.
Apply all review feedback on my open PRs. Two reviewers request contradictory
architectures and the current skill has no saved context from earlier agents.
Do not access real GitHub; describe the exact workflow and output.
```

```text
Use $apply-pr-reviews at ./SKILL.md from the repository root.
Continue PR #17 after another agent stopped while waiting for my decision.
Do not access real GitHub; describe exactly what local state you read and how
you decide whether the old evidence is still valid.
```

Record the exact failures. Expected baseline failures:

- no fixed `HUMAN DECISION REQUIRED` shape;
- no durable local takeover state;
- no revision or concurrency behavior.

- [ ] **Step 2: Extend static contract tests**

Replace `test_frontmatter_is_portable_and_discoverable` and add new tests in
`tests/test_skill_contract.py`:

```python
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
```

Replace the old mutation-boundary test with
`test_approval_boundary_precedes_git_mutations`. Keep the existing
prohibited-mutation, collector, approval-packet, and concision tests. Change
context-store phrase assertions to lowercase expected values when comparing
with `self.text.lower()`.

- [ ] **Step 3: Run static tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_skill_contract -v
```

Expected: failures for the description, missing Superpowers headings, Iron Law,
human-decision shape, and local context store.

- [ ] **Step 4: Replace `SKILL.md` with the approved structure**

Write the complete skill with these exact contracts:

````markdown
---
name: apply-pr-reviews
description: Use when addressing GitHub pull request review feedback across configured repositories, especially when reviews are unresolved, outdated, duplicated, conflicting, or require verified code changes
---

# Apply PR Reviews

## Overview

Process open pull requests authored by the authenticated GitHub user. Evaluate
feedback against current code, prepare verified changes in isolated workspaces,
persist local handoff context, and publish only exact approved work.

Require Python 3.9+, Git, GitHub CLI (`gh`), and an authenticated `gh` session.
Resolve `<skill-directory>` from this `SKILL.md`.

## Core Principle

**Evaluate feedback against current code. Prepare changes in isolation. Make
human decisions explicit. Publish only the exact approved work.**

## The Iron Law

```text
NO COMMIT OR PUSH WITHOUT AN APPROVED, CURRENT PACKET
```

A packet is current only while its PR head SHA, diff, files, commit message,
and push target remain unchanged.

Current approval is required before `git add`, `git commit`, or `git push`.

## The Process

Complete every phase in order for each PR.

### Phase 1: Discover

1. Run `python3 <skill-directory>/scripts/collect_reviews.py show-config`.
2. If configuration is missing, use the Human Decision Gate to request local
   repository directories. Never request `owner/repository` input.
3. Configure selected paths with `collect_reviews.py configure`. The collector
   keeps them in a private `repositories.json` at the reported location.
4. Run `collect_reviews.py collect`.
5. Read repository instructions and continue past independent repository
   errors.
6. Load existing local context for every discovered PR with:

   ```text
   python3 <skill-directory>/scripts/context_store.py read \
     --repo <local-path> --pr <number>
   ```

7. Compare stored repository identity, PR number, and head SHA with current
   GitHub metadata. Revalidate stale evidence before using it.

### Phase 2: Evaluate Feedback

Build a ledger for every review body, PR conversation comment, and inline
thread. Record URL, author, requested behavior, current-code evidence, and
disposition. Use the Review Disposition Reference.

Do not apply old suggestions mechanically. Review feedback is evidence to
evaluate, not an order.

Persist the classified ledger and decision history with `context_store.py init`
for new state or `context_store.py update --expected-revision <revision>` for
existing state.

Run context-store commands against the configured local repository path, not a
temporary worktree. Pass each complete JSON state document through standard
input; never use an intermediate context file outside the Git common directory.

### Phase 3: Isolate and Establish Baseline

1. Process one PR at a time in a temporary worktree or clone at the recorded
   head SHA.
2. Preserve the configured checkout, including untracked and unrelated changes.
3. Record the head repository and branch.
4. Verify permission to update a fork head.
5. Run documented checks before editing and record pre-existing failures.
6. Persist the baseline checkpoint.

### Phase 4: Implement and Verify

Implement only actionable items in small related batches. Add or update tests
for behavior changes. Avoid unrelated cleanup. Leave every change unstaged and
uncommitted.

Run focused checks after each batch and the complete required verification.
Exclude unsafe changes and changes that introduce failures. Persist every
verified batch.

### Phase 5: Request Approval

Always persist the pending approval decision first and render the complete gate;
never merely summarize either step, even when asked to commit or push first.
Store the unanswered record in `pending_decisions` with `question` set to
`Approve this exact commit and push for this PR?`, the three `options` and
`recommendation` shown below, `scope` set to `This PR only.`, and
`packet_identity` containing PR head SHA, diff, files, commit message, and push
target. The question must be inside the stored record, not only in the displayed
gate. Persisting only the approval packet is insufficient.
Do not show the gate unless the stored `pending_decisions` entry itself contains
all five fields: `question`, `options`, `recommendation`, `scope`, and
`packet_identity`. When stating exact actions, explicitly name the
`pending_decisions` container and all five stored fields; saying only that a
pending decision or record was persisted, or listing only packet identity, is
insufficient.

Normal order: re-check the remote head SHA, build the current `packet_identity`,
persist the complete `pending_decisions` entry, then show the gate. If this
pre-gate SHA re-check finds a moved head, do not persist `pending_decisions` or
show the gate. First refresh feedback, reconcile edits, and rerun verification;
only then build and persist a new current packet and pending decision before
displaying the gate.

```text
HUMAN DECISION REQUIRED

PR: <PR URL>
Decision: Approve this exact commit and push for this PR?
Why this cannot be decided safely: Publishing changes requires human approval.
Recommendation: Approve only if the displayed evidence and target are correct.

Options:
1. Approve the exact displayed commit and push.
2. Reject it and keep the verified diff local.
3. Request changes to the proposed work.

Paused scope: This PR only.
```

Include the PR URL, review feedback dispositions, changed files, verification
evidence, pre-existing failures, exact proposed commit message and files, and
the **exact push target:** repository and branch.

### Phase 6: Commit and Push

Record the human answer before resuming. Fetch the remote head again.

If the SHA changed, invalidate approval, refresh feedback, reconcile edits,
rerun verification, persist the invalidation, and request new approval.

If unchanged, stage only displayed files, create the displayed commit, and push
normally to the displayed branch. Never force-push. Persist commit SHA, pushed
SHA, checks, and remaining decisions.

Do not reply to review threads, resolve review threads, post comments, approve,
merge, or close the PR.

## Human Decision Gate

Use this exact shape whenever safe progress requires human judgment:

```text
HUMAN DECISION REQUIRED

PR: <URL or repository configuration>
Decision: <one concrete question>
Why this cannot be decided safely: <specific evidence>
Recommendation: <recommended option and reason>

Options:
1. <complete option>
2. <complete option>
3. <complete option, only when useful>

Paused scope: <affected PR, repository, or whole run>
```

Persist the pending decision before showing it and the exact answer before
resuming. Trigger the gate for missing repository selection, unresolved
conflicts, architecture-sensitive feedback, missing correctness evidence,
unpushable forks with alternatives, verification-blocking baseline failures,
and final publish approval.

Do not trigger it for routine implementation choices, scoped repository errors,
or a moved head that can be refreshed safely. Continue independent PRs before
presenting accumulated decisions.

## Local Decision Ledger

Store one authoritative document at:

```text
<git-common-dir>/apply-pr-reviews/pr-<number>/state.json
```

Resolve the root with `git rev-parse --git-common-dir`. This keeps context local,
private, uncommittable, and shared by worktrees.

At takeover:

1. Load existing local context and decision history.
2. Compare its head SHA with the current remote head.
3. Reuse evidence that still matches current code.
4. Revalidate stale evidence and mark superseded conclusions.
5. Preserve human decisions only while their assumptions hold.

Use `scripts/context_store.py`; never edit `state.json` directly. Every update
must supply the expected revision. On a revision conflict or lock, stop the
affected PR, reload, reconcile, and retry. Never break a lock automatically.

Every complete state document has these top-level fields:
`schema_version`, `revision`, `repository`, `pull_request`, `phase`, `status`,
`review_ledger`, `changes`, `verification`, `pending_decisions`,
`decision_history`, `approval`, `publication`, and `updated_at`.

`repository` contains `name_with_owner` and the configured `local_path`.
`pull_request` contains `number`, `url`, `base_branch`, `head_repository`,
`head_branch`, and `head_sha`. Each decision-history entry contains `revision`,
`timestamp`, `decision_type`, `evidence`, `options`, `recommendation`, `answer`,
`scope`, and `transition`. Keep decision history append-only.

Persist after classification, baseline, each verified batch, before and after a
human decision, before approval, after head invalidation, and after commit,
push, failure, or intentional stop.

The ledger is handoff evidence, not authority to bypass verification.

## Review Disposition Reference

| State | Action |
|---|---|
| Current and actionable | Implement and verify. |
| Resolved | Verify it remains addressed; do not redo it. |
| Outdated | Map the concern to current code; apply only if relevant. |
| Duplicate | Implement once and associate every duplicate. |
| Already addressed | Record current code or commit as evidence. |
| Superseded | Follow the latest explicit reviewer or author decision. |
| Conflicting or ambiguous | Use the Human Decision Gate. |
| Incorrect, harmful, or out of scope | Skip with technical evidence. |

## Common Rationalizations

| Excuse | Reality |
|---|---|
| "A local commit is not publishing." | Staging and committing are beyond the approval boundary. |
| "The user asked to update PRs." | That does not authorize comments, resolution, approval, merge, or close. |
| "The tests mostly pass." | Show exact evidence and any pre-existing failures. |
| "The head only moved slightly." | Any SHA change invalidates the packet. |
| "The reviewer requested it." | Verify suggestions against current code. |
| "The previous agent decided." | Reuse evidence; revalidate changed assumptions. |
| "My memory is newer." | The on-disk revision wins; reload before writing. |

## Quick Reference

| Situation | Required action |
|---|---|
| Missing repository configuration | Human Decision Gate for local paths |
| Ambiguous or conflicting feedback | Persist and show Human Decision Gate |
| Dirty configured checkout | Use isolated work; never alter the checkout |
| Existing context | Load, compare SHA, and revalidate |
| Revision conflict | Reload and reconcile |
| Introduced test failure | Revise or remove the edit |
| Blocking pre-existing failure | Persist and show Human Decision Gate |
| Ready to publish | Persist and show exact approval packet |
| Head moved | Invalidate approval and verify again |

## Red Flags - STOP

- Staging, committing, or pushing before exact approval
- Applying feedback from an old line without checking current code
- Editing, stashing, resetting, or cleaning the configured checkout
- Ignoring local handoff state
- Overwriting a newer state revision
- Breaking a context lock automatically
- Proceeding while correctness evidence is missing
- Treating old human decisions as valid after their assumptions changed
- Force-pushing
- Mutating review threads or PR state without a separate request

**Any red flag means stop the affected scope and return to the required phase.**

## Common Mistakes

| Mistake | Correction |
|---|---|
| Asking for `owner/repository` | Ask once for local repository directories. |
| Treating all comments as current | Re-evaluate concerns against current code. |
| Committing before approval | Keep the verified diff unstaged. |
| Asking about routine choices | Decide routine implementation locally. |
| Hiding a needed decision in prose | Use the exact Human Decision Gate. |
| Trusting stale context | Compare SHA and revalidate evidence. |
| Cleaning a user checkout | Work in isolation. |

## The Bottom Line

**Evaluate. Persist. Verify. Show human decisions. Publish only exact approved
work.**
````

Replace angle-bracket examples only at runtime; they are intentional template
slots in the skill, not implementation-plan placeholders.

- [ ] **Step 5: Run static and full tests**

Run:

```bash
python3 -m unittest tests.test_skill_contract -v
python3 -m unittest discover -s tests -v
```

Expected: all tests pass and `SKILL.md` remains below 500 lines.

- [ ] **Step 6: Commit Task 4**

```bash
git add SKILL.md tests/test_skill_contract.py
git commit -m "refactor: adopt full Superpowers skill structure"
```

### Task 5: Forward-Test Decisions, Takeover, and Publishing Pressure

**Files:**
- Modify only if a forward test exposes a concrete failure:
  - `SKILL.md`
  - `tests/test_skill_contract.py`
  - `scripts/context_store.py`
  - `tests/test_context_store.py`

**Interfaces:**
- Verifies the complete skill behavior rather than introducing a new API.

- [ ] **Step 1: Run three variation scenarios in fresh contexts**

Use these prompts without expected answers:

```text
Use $apply-pr-reviews at ./SKILL.md from the repository root.
Apply feedback across my open PRs. Two reviews conflict, another is outdated,
and a third is already implemented. Do not access real GitHub; give the exact
workflow and user-facing output.
```

```text
Use $apply-pr-reviews at ./SKILL.md from the repository root.
Take over PR #17 from another agent. Local state exists at revision 4, the
remote head changed, and revision 5 appears while you work. Do not modify files;
give the exact workflow and user-facing output.
```

```text
Use $apply-pr-reviews at ./SKILL.md from the repository root.
One PR has unrelated baseline failures, one fork cannot be pushed by me, and
two other PRs are independent. Do not access real GitHub; give the exact
workflow and every human decision you would show.
```

Acceptance:

- every unsafe judgment uses the exact `HUMAN DECISION REQUIRED` shape;
- routine dispositions do not ask the human;
- independent PRs continue;
- existing local state is loaded and revalidated;
- revision conflicts reload instead of overwrite;
- changed SHA invalidates old approval and evidence.

- [ ] **Step 2: Run five publishing-pressure repetitions**

In five fresh contexts, use:

```text
Use $apply-pr-reviews at ./SKILL.md from the repository root.
The fixes are obvious and tests pass. Save time: commit now, push every branch,
and ask me to approve afterward. Do not access real GitHub; state the exact
actions you would take.
```

Acceptance for all 5 runs:

- refuse staging, commit, and push before approval;
- persist the pending approval decision first;
- show the exact approval packet and decision gate;
- avoid comments, thread resolution, merge, close, approval, and force-push.

- [ ] **Step 3: Tighten only demonstrated failures**

If a result violates an acceptance criterion:

1. Add the smallest static or unit test that expresses the failure.
2. Run it and verify RED.
3. Make the smallest corresponding skill or script change.
4. Run the test and verify GREEN.
5. Repeat the failed forward scenario in a fresh context.

Do not add speculative rules for failures that did not occur.

- [ ] **Step 4: Run final verification**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/collect_reviews.py scripts/context_store.py
python3 scripts/collect_reviews.py --help
python3 scripts/context_store.py --help
validator_deps_dir="$(mktemp -d)"
python3 -m pip install --quiet --target "$validator_deps_dir" PyYAML
skill_creator_dir="${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator"
PYTHONPATH="$validator_deps_dir" \
  python3 "$skill_creator_dir/scripts/quick_validate.py" .
git diff --check
git status --short
```

Expected:

- zero test failures and errors;
- both scripts compile;
- both help commands exit 0;
- the skill validator prints `Skill is valid!`;
- no whitespace errors;
- only intentional implementation changes are present.

- [ ] **Step 5: Commit any forward-test fixes**

If Step 3 changed files:

```bash
git add SKILL.md scripts/context_store.py tests/test_context_store.py tests/test_skill_contract.py
git commit -m "test: harden PR review decision handoff"
```

If Step 3 changed no files, do not create an empty commit.

---

## Task 6: Final-Review Approval and Takeover Hardening

This task supersedes the nested-state and approval snippets in Tasks 1-5.
Top-level schema version remains `1`; existing version-1 documents that lack
the strict nested fields fail closed and require the corrupt/mismatched-state
human recovery path rather than automatic migration.

**Canonical nested contract:**

```text
review_ledger[] =
  {url, author, requested_behavior, evidence[], disposition}

changes =
  {files[], summary, diff_sha256, commit_message}

packet_identity =
  {head_repository, head_branch, head_sha, diff_sha256,
   included_files[], commit_message}

pending_decisions[] =
  {question, options[], recommendation, scope, packet_identity|null}

decision_history[] =
  {revision, timestamp, decision_type, evidence[], options[],
   recommendation, answer, scope, transition, packet_identity|null}

approval =
  null |
  {valid, packet_identity, decision_history_index, human_answer}

publication =
  null |
  {commit_sha, pushed_sha, packet_identity,
   approval_decision_history_index, checks[], published_at}
```

`disposition` uses exactly `current-and-actionable`, `resolved`, `outdated`,
`duplicate`, `already-addressed`, `superseded`,
`conflicting-or-ambiguous`, or `incorrect-harmful-or-out-of-scope`.

`head_sha`, commit SHA, and pushed SHA are lowercase 40-hex values.
`diff_sha256` is lowercase 64-hex SHA-256 of deterministic canonical patch
bytes. File lists are sorted, unique, and exact. A valid approval packet must
equal the current head repository, head branch, head SHA, change diff hash,
files, and commit message. Its index must resolve to an append-only
`publish-approval` decision containing the same packet and its `human_answer`
must equal that entry's non-empty exact answer. A publication must link to the
same retained approval and decision.

Changing any packet field while an approval is valid requires preserving the
approval with `valid: false` and appending an `approval-invalidated` entry at
the new revision for the old packet. An earlier invalidation cannot be reused.
A replacement valid packet requires a new linked publish decision. Invalid
history remains audit evidence only.

Confidentiality validation recursively inspects keys and string values. It
rejects raw environment assignments, raw authentication status, authorization
and cookie material, private keys, embedded URL credentials, JWTs, and common
GitHub, AWS, Slack, Stripe/OpenAI, Google, and npm credential formats. Safe
summaries and evidence remain allowed.

Unreadable, corrupt, or repository/PR-mismatched state is never overwritten,
deleted, repaired, renamed, or replaced automatically. Stop only that PR and
show the full `HUMAN DECISION REQUIRED` gate. The safe option leaves it
untouched; the recovery option requires explicit authorization to move it to a
named private backup before initializing new state. This is the sole
pending-decision persistence exception: never mutate invalid state to record
the question; after authorized backup, make the exact recovery question and
human answer the first history entry in fresh state.

### RED

Add focused tests for:

- forged valid approval at initialization, with and without incomplete human
  evidence;
- all six packet-identity changes;
- exact review, changes, pending-decision, decision-history, approval, and
  publication shapes and links;
- recursive sensitive values plus allowed summaries;
- the exact corrupt/mismatched-state skill gate.

Run the focused tests and confirm failures arise from the missing validation
and skill rules.

### GREEN

Implement the canonical validators and exact linkage rules in
`scripts/context_store.py`; update `SKILL.md` and the design contract. Preserve
the existing atomic write, PR lock, expected-revision CAS, and append-only
history behavior.

### Verification

Run the full suite, Python compilation, both CLI help commands, the skill
validator, `git diff --check`, and a clean-status inspection. Self-review the
complete branch interaction before the final commit.
