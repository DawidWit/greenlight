#!/usr/bin/env python3
"""Persist private per-PR handoff context inside a repository's Git data."""

import json
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


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
            if FORBIDDEN_KEY.search(key):
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
    for key in ("url", "base_branch", "head_repository", "head_branch"):
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
    directory = state_directory(repo_path, pr_number, runner=runner)
    path = directory / STATE_FILENAME
    if not path.exists():
        return None
    path = path.resolve()
    if path.parent != directory:
        raise StateValidationError("State file escaped the PR state directory.")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StateValidationError(f"Cannot read valid state: {path}") from error
    return validate_state(state, pr_number)


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
    try:
        os.chmod(path, mode)
    except (NotImplementedError, PermissionError):
        pass


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
        old_sha = current["pull_request"]["head_sha"]
        new_sha = state["pull_request"]["head_sha"]
        current_approval = current["approval"]
        if (
            old_sha != new_sha
            and isinstance(current_approval, dict)
            and current_approval.get("valid") is True
        ):
            approval = state["approval"]
            if (
                not isinstance(approval, dict)
                or approval.get("valid") is not False
                or not new_history
                or new_history[-1]["decision_type"]
                != "head-sha-invalidated"
            ):
                raise StateValidationError(
                    "A head SHA change must invalidate approval and append "
                    "a head-sha-invalidated decision."
                )
        _atomic_write(state_dir / STATE_FILENAME, state)
    return state
