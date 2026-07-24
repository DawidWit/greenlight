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
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CHANGES_FIELDS = {
    "files",
    "summary",
    "diff_sha256",
    "commit_message",
}
REVIEW_FIELDS = {
    "url",
    "author",
    "requested_behavior",
    "evidence",
    "disposition",
}
REVIEW_DISPOSITIONS = {
    "current-and-actionable",
    "resolved",
    "outdated",
    "duplicate",
    "already-addressed",
    "superseded",
    "conflicting-or-ambiguous",
    "incorrect-harmful-or-out-of-scope",
}
PACKET_FIELDS = {
    "head_repository",
    "head_branch",
    "head_sha",
    "diff_sha256",
    "included_files",
    "commit_message",
}
PENDING_DECISION_FIELDS = {
    "question",
    "options",
    "recommendation",
    "scope",
    "packet_identity",
}
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
    "packet_identity",
}
APPROVAL_FIELDS = {
    "valid",
    "packet_identity",
    "decision_history_index",
    "human_answer",
}
PUBLICATION_FIELDS = {
    "commit_sha",
    "pushed_sha",
    "packet_identity",
    "approval_decision_history_index",
    "checks",
    "published_at",
}
PUBLISH_APPROVAL_QUESTION = "Approve this exact commit and push for this PR?"
RAW_ENV_ASSIGNMENT = re.compile(
    r"(?m)^[A-Z_][A-Z0-9_]{1,}\s*=\s*\S.*$"
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(
        r"(?i)\b(?:authorization|api[_ -]?key|client[_ -]?secret|"
        r"password|secret|token|cookie)\b\s*[:=]\s*\S+"
    ),
    re.compile(r"(?i)\bauthorization\s*:\s*(?:bearer|basic)\s+\S+"),
    re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{10,}|gh[pousr]_[A-Za-z0-9]{10,})\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(
        r"\b(?:sk-|sk_live_|sk_test_|sk-proj-)[A-Za-z0-9_-]{10,}\b"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}\b"),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\."
        r"[A-Za-z0-9_-]{5,}\b"
    ),
    re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(r"(?i)https?://[^/\s:@]+:[^/\s@]+@"),
    re.compile(r"(?im)^\s*[✓*]?\s*logged in to .+ account .+$"),
    re.compile(r"(?im)^\s*[-*]?\s*token scopes?\s*:"),
)


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


def _reject_sensitive_content(value, path="state"):
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
            _reject_sensitive_content(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_content(nested, f"{path}[{index}]")
    elif isinstance(value, str):
        if RAW_ENV_ASSIGNMENT.search(value) or any(
            pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS
        ):
            raise StateValidationError(f"Sensitive value at {path}.")


def _require_exact_object(value, fields, path):
    if not isinstance(value, dict) or set(value) != fields:
        raise StateValidationError(f"{path} has invalid fields.")
    return value


def _require_nonempty_string(value, path):
    if not isinstance(value, str) or not value.strip():
        raise StateValidationError(f"{path} must be a non-empty string.")
    return value


def _validate_string_list(
    value,
    path,
    *,
    minimum=0,
    maximum=None,
    unique=False,
    sorted_values=False,
):
    if not isinstance(value, list):
        raise StateValidationError(f"{path} must be a list.")
    if len(value) < minimum or (
        maximum is not None and len(value) > maximum
    ):
        raise StateValidationError(f"{path} has an invalid item count.")
    for index, item in enumerate(value):
        _require_nonempty_string(item, f"{path}[{index}]")
    if unique and len(value) != len(set(value)):
        raise StateValidationError(f"{path} must not contain duplicates.")
    if sorted_values and value != sorted(value):
        raise StateValidationError(f"{path} must be sorted.")
    return value


def _validate_packet_identity(packet, path):
    _require_exact_object(packet, PACKET_FIELDS, path)
    for field in ("head_repository", "head_branch", "commit_message"):
        _require_nonempty_string(packet[field], f"{path}.{field}")
    if (
        not isinstance(packet["head_sha"], str)
        or not SHA_PATTERN.fullmatch(packet["head_sha"])
    ):
        raise StateValidationError(f"{path}.head_sha is invalid.")
    if (
        not isinstance(packet["diff_sha256"], str)
        or not SHA256_PATTERN.fullmatch(packet["diff_sha256"])
    ):
        raise StateValidationError(f"{path}.diff_sha256 is invalid.")
    _validate_string_list(
        packet["included_files"],
        f"{path}.included_files",
        minimum=1,
        unique=True,
        sorted_values=True,
    )
    return packet


def _current_packet_identity(state):
    return {
        "head_repository": state["pull_request"]["head_repository"],
        "head_branch": state["pull_request"]["head_branch"],
        "head_sha": state["pull_request"]["head_sha"],
        "diff_sha256": state["changes"]["diff_sha256"],
        "included_files": state["changes"]["files"],
        "commit_message": state["changes"]["commit_message"],
    }


def _validate_review_ledger(review_ledger):
    if not isinstance(review_ledger, list):
        raise StateValidationError("review_ledger must be a list.")
    for index, entry in enumerate(review_ledger):
        path = f"review_ledger[{index}]"
        _require_exact_object(entry, REVIEW_FIELDS, path)
        for field in ("url", "author", "requested_behavior"):
            _require_nonempty_string(entry[field], f"{path}.{field}")
        _validate_string_list(entry["evidence"], f"{path}.evidence")
        if entry["disposition"] not in REVIEW_DISPOSITIONS:
            raise StateValidationError(f"{path}.disposition is invalid.")


def _validate_changes(changes):
    _require_exact_object(changes, CHANGES_FIELDS, "changes")
    _validate_string_list(
        changes["files"],
        "changes.files",
        unique=True,
        sorted_values=True,
    )
    if not isinstance(changes["summary"], str):
        raise StateValidationError("changes.summary must be a string.")
    if (
        not isinstance(changes["diff_sha256"], str)
        or not SHA256_PATTERN.fullmatch(changes["diff_sha256"])
    ):
        raise StateValidationError("changes.diff_sha256 is invalid.")
    if not isinstance(changes["commit_message"], str):
        raise StateValidationError("changes.commit_message must be a string.")


def _validate_pending_decisions(state):
    pending_decisions = state["pending_decisions"]
    if not isinstance(pending_decisions, list):
        raise StateValidationError("pending_decisions must be a list.")
    current_packet = _current_packet_identity(state)
    for index, decision in enumerate(pending_decisions):
        path = f"pending_decisions[{index}]"
        _require_exact_object(decision, PENDING_DECISION_FIELDS, path)
        for field in ("question", "recommendation", "scope"):
            _require_nonempty_string(decision[field], f"{path}.{field}")
        _validate_string_list(
            decision["options"],
            f"{path}.options",
            minimum=2,
            maximum=3,
            unique=True,
        )
        packet = decision["packet_identity"]
        if packet is not None:
            _validate_packet_identity(packet, f"{path}.packet_identity")
            if packet != current_packet:
                raise StateValidationError(
                    f"{path}.packet_identity is not current."
                )
        if decision["question"] == PUBLISH_APPROVAL_QUESTION and packet is None:
            raise StateValidationError(
                f"{path}.packet_identity is required for publish approval."
            )


def _validate_decision_history(state):
    revision = state["revision"]
    previous_revision = -1
    for index, decision in enumerate(state["decision_history"]):
        path = f"decision_history[{index}]"
        _require_exact_object(decision, DECISION_FIELDS, path)
        decision_revision = decision["revision"]
        if (
            not isinstance(decision_revision, int)
            or isinstance(decision_revision, bool)
            or decision_revision < previous_revision
            or decision_revision > revision
        ):
            raise StateValidationError(f"{path}.revision is invalid.")
        previous_revision = decision_revision
        for field in (
            "timestamp",
            "decision_type",
            "recommendation",
            "answer",
            "scope",
            "transition",
        ):
            _require_nonempty_string(decision[field], f"{path}.{field}")
        for field in ("evidence", "options"):
            _validate_string_list(decision[field], f"{path}.{field}")
        packet = decision["packet_identity"]
        if packet is not None:
            _validate_packet_identity(packet, f"{path}.packet_identity")
        if decision["decision_type"] == "publish-approval" and packet is None:
            raise StateValidationError(
                f"{path}.packet_identity is required for publish approval."
            )


def _linked_publish_decision(state, index, packet, human_answer=None):
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or index < 0
        or index >= len(state["decision_history"])
    ):
        raise StateValidationError(
            "Approval decision-history linkage is invalid."
        )
    decision = state["decision_history"][index]
    if (
        decision["decision_type"] != "publish-approval"
        or decision["packet_identity"] != packet
        or (
            human_answer is not None
            and decision["answer"] != human_answer
        )
    ):
        raise StateValidationError(
            "Approval does not match its publish-approval decision."
        )
    return decision


def _validate_approval(state):
    approval = state["approval"]
    if approval is None:
        return
    _require_exact_object(approval, APPROVAL_FIELDS, "approval")
    if not isinstance(approval["valid"], bool):
        raise StateValidationError("approval.valid must be a boolean.")
    packet = _validate_packet_identity(
        approval["packet_identity"], "approval.packet_identity"
    )
    human_answer = _require_nonempty_string(
        approval["human_answer"], "approval.human_answer"
    )
    decision_index = approval["decision_history_index"]
    _linked_publish_decision(
        state,
        decision_index,
        packet,
        human_answer,
    )
    later_history = state["decision_history"][decision_index + 1 :]
    was_invalidated = any(
        decision["decision_type"] == "approval-invalidated"
        and decision["packet_identity"] == packet
        for decision in later_history
    )
    if approval["valid"] and was_invalidated:
        raise StateValidationError(
            "approval.valid cannot override later invalidation history."
        )
    if approval["valid"] and packet != _current_packet_identity(state):
        raise StateValidationError(
            "Valid approval packet does not match current PR changes."
        )
    if approval["valid"] and any(
        pending["question"] == PUBLISH_APPROVAL_QUESTION
        and pending["packet_identity"] == packet
        for pending in state["pending_decisions"]
    ):
        raise StateValidationError(
            "A valid approval cannot remain pending for the same packet."
        )


def _validate_publication(state):
    publication = state["publication"]
    if publication is None:
        return
    _require_exact_object(publication, PUBLICATION_FIELDS, "publication")
    for field in ("commit_sha", "pushed_sha"):
        value = publication[field]
        if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
            raise StateValidationError(f"publication.{field} is invalid.")
    packet = _validate_packet_identity(
        publication["packet_identity"], "publication.packet_identity"
    )
    approval = state["approval"]
    if (
        not isinstance(approval, dict)
        or approval["packet_identity"] != packet
        or approval["decision_history_index"]
        != publication["approval_decision_history_index"]
    ):
        raise StateValidationError(
            "Publication does not match the retained approval evidence."
        )
    _linked_publish_decision(
        state,
        publication["approval_decision_history_index"],
        packet,
    )
    _validate_string_list(
        publication["checks"],
        "publication.checks",
        minimum=1,
    )
    _require_nonempty_string(
        publication["published_at"], "publication.published_at"
    )


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
    if not isinstance(state["decision_history"], list):
        raise StateValidationError("decision_history must be a list.")
    if not isinstance(state["verification"], dict):
        raise StateValidationError("verification must be an object.")
    for key in ("phase", "status", "updated_at"):
        if not isinstance(state[key], str) or not state[key]:
            raise StateValidationError(f"{key} must be a non-empty string.")
    _validate_review_ledger(state["review_ledger"])
    _validate_changes(state["changes"])
    _validate_pending_decisions(state)
    _validate_decision_history(state)
    _validate_approval(state)
    _validate_publication(state)
    _reject_sensitive_content(state)
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
    if os.name != "posix":
        return
    os.chmod(path, mode)


def _has_current_invalidation_event(
    old_history,
    new_history,
    revision,
    packet_identity,
):
    return any(
        decision["decision_type"] == "approval-invalidated"
        and decision["revision"] == revision
        and decision["packet_identity"] == packet_identity
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
            _current_packet_identity(current) != _current_packet_identity(state)
            and isinstance(current_approval, dict)
            and current_approval.get("valid") is True
        ):
            approval = state["approval"]
            invalidated_approval = dict(current_approval)
            invalidated_approval["valid"] = False
            if (
                approval != invalidated_approval
                or not _has_current_invalidation_event(
                    old_history,
                    new_history,
                    state["revision"],
                    current_approval["packet_identity"],
                )
            ):
                raise StateValidationError(
                    "An approved packet change must invalidate approval and "
                    "append a matching current-revision approval-invalidated "
                    "decision."
                )
        _atomic_write(state_dir / STATE_FILENAME, state)
    return state


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
