#!/usr/bin/env python3
"""Persist private per-PR handoff context inside a repository's Git data."""

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 2
STORE_DIRECTORY = "apply-pr-reviews"
STATE_FILENAME = "state.json"
RECOVERY_FILENAME = "recovery.json"
REQUIRED_TOP_LEVEL = {
    "schema_version",
    "revision",
    "repository",
    "pull_request",
    "workspace",
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
    "question",
    "outcome",
    "recovery",
}
WORKSPACE_FIELDS = {"kind", "path", "base_sha", "head_sha"}
WORKSPACE_KINDS = {"worktree", "clone"}
PUBLISH_OUTCOMES = {"approved", "rejected", "changes-requested"}
RECOVERY_FIELDS = {"backup_name", "backup_path"}
BACKUP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
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
    r"(?m)^[A-Z_][A-Z0-9_]{1,}\s*=\s*(?P<value>\S.*)$"
)
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(?:authorization|api[_ -]?key|client[_ -]?secret|"
    r"password|secret|token|cookie)\b\s*[:=]\s*(?P<value>\S+)"
)
SAFE_SENTINELS = {"none", "redacted", "<redacted>", "unset", "not-set"}
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*:\s*(?:bearer|basic)\s+\S+"),
    re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{10,}|gh[pousr]_[A-Za-z0-9]{10,})\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(
        r"\b(?:sk-|sk_live_|sk_test_|sk-proj-)[A-Za-z0-9_-]{20,}\b"
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
        environment_values = [
            match.group("value").strip().lower()
            for match in RAW_ENV_ASSIGNMENT.finditer(value)
        ]
        assignment_values = [
            match.group("value").strip().lower()
            for match in SENSITIVE_ASSIGNMENT.finditer(value)
        ]
        has_raw_assignment = any(
            candidate not in SAFE_SENTINELS
            for candidate in environment_values + assignment_values
        )
        if has_raw_assignment or any(
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


def _validate_workspace_identity(workspace, pull_request):
    _require_exact_object(workspace, WORKSPACE_FIELDS, "workspace")
    if workspace["kind"] not in WORKSPACE_KINDS:
        raise StateValidationError("workspace.kind is invalid.")
    _require_nonempty_string(workspace["path"], "workspace.path")
    workspace_path = Path(workspace["path"])
    if not workspace_path.is_absolute():
        raise StateValidationError("workspace.path must be absolute.")
    if workspace_path != workspace_path.resolve():
        raise StateValidationError("workspace.path must be canonical.")
    for field in ("base_sha", "head_sha"):
        value = workspace[field]
        if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
            raise StateValidationError(f"workspace.{field} is invalid.")
    if (
        workspace["base_sha"] != pull_request["head_sha"]
        or workspace["head_sha"] != pull_request["head_sha"]
    ):
        raise StateValidationError(
            "workspace SHA identity must match pull_request.head_sha."
        )


def _workspace_head(workspace_path):
    if not workspace_path.is_dir():
        raise StateValidationError(
            f"Workspace directory is missing: {workspace_path}"
        )
    top_level = Path(
        run_command(
            ["git", "-C", str(workspace_path), "rev-parse", "--show-toplevel"]
        ).strip()
    ).resolve()
    if top_level != workspace_path:
        raise StateValidationError(
            "Workspace path must identify the Git worktree root."
        )
    return run_command(
        ["git", "-C", str(workspace_path), "rev-parse", "HEAD"]
    ).strip()


def _validate_workspace_runtime(state):
    workspace = state["workspace"]
    workspace_path = Path(workspace["path"])
    actual_head = _workspace_head(workspace_path)
    if actual_head != workspace["head_sha"]:
        raise StateValidationError(
            "Workspace HEAD does not match stored workspace.head_sha."
        )


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
        if not isinstance(decision["question"], str):
            raise StateValidationError(f"{path}.question must be a string.")
        packet = decision["packet_identity"]
        if packet is not None:
            _validate_packet_identity(packet, f"{path}.packet_identity")
        outcome = decision["outcome"]
        recovery = decision["recovery"]
        if recovery is not None:
            _require_exact_object(recovery, RECOVERY_FIELDS, f"{path}.recovery")
            for field in RECOVERY_FIELDS:
                _require_nonempty_string(
                    recovery[field], f"{path}.recovery.{field}"
                )
        if decision["decision_type"] == "publish-approval":
            if packet is None:
                raise StateValidationError(
                    f"{path}.packet_identity is required for publish approval."
                )
            _require_nonempty_string(decision["question"], f"{path}.question")
            if decision["question"] != PUBLISH_APPROVAL_QUESTION:
                raise StateValidationError(
                    f"{path}.question is not the publish approval question."
                )
            _validate_string_list(
                decision["options"],
                f"{path}.options",
                minimum=2,
                maximum=3,
                unique=True,
            )
            if decision["answer"] not in decision["options"]:
                raise StateValidationError(
                    f"{path}.answer must equal one displayed option."
                )
            if outcome not in PUBLISH_OUTCOMES:
                raise StateValidationError(f"{path}.outcome is invalid.")
            if recovery is not None:
                raise StateValidationError(
                    f"{path}.recovery must be null for publish approval."
                )
        elif outcome is not None:
            raise StateValidationError(
                f"{path}.outcome is only valid for publish approval."
            )
        if decision["decision_type"] == "state-recovery":
            _require_nonempty_string(decision["question"], f"{path}.question")
            if recovery is None:
                raise StateValidationError(
                    f"{path}.recovery is required for state recovery."
                )
        elif recovery is not None:
            raise StateValidationError(
                f"{path}.recovery is only valid for state recovery."
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
    linked_decision = _linked_publish_decision(
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
    if approval["valid"] and linked_decision["outcome"] != "approved":
        raise StateValidationError(
            "approval.valid requires an approved publish outcome."
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
        or approval["valid"] is not True
        or approval["packet_identity"] != packet
        or approval["decision_history_index"]
        != publication["approval_decision_history_index"]
    ):
        raise StateValidationError(
            "Publication does not match the retained approval evidence."
        )
    linked_decision = _linked_publish_decision(
        state,
        publication["approval_decision_history_index"],
        packet,
    )
    if linked_decision["outcome"] != "approved":
        raise StateValidationError(
            "Publication requires an approved publish outcome."
        )
    _validate_string_list(
        publication["checks"],
        "publication.checks",
        minimum=1,
    )
    _require_nonempty_string(
        publication["published_at"], "publication.published_at"
    )


def _run_bytes(command):
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise GitContextError(
            f"Required command is not installed: {command[0]}"
        ) from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise StateValidationError(
            f"Command failed ({completed.returncode}): {' '.join(command)}"
            + (f"\n{detail}" if detail else "")
        )
    return completed.stdout


def _validate_included_path(workspace, included_path):
    _require_nonempty_string(included_path, "included file")
    relative = Path(included_path)
    if (
        "\0" in included_path
        or relative.is_absolute()
        or included_path in {".", ".."}
        or ".." in relative.parts
    ):
        raise StateValidationError(
            f"Included file must stay inside workspace: {included_path}"
        )
    target = workspace.joinpath(*relative.parts)
    try:
        target.parent.resolve().relative_to(workspace)
    except ValueError as error:
        raise StateValidationError(
            f"Included file escaped workspace: {included_path}"
        ) from error
    return target


def _base_file_record(workspace, base_sha, included_path):
    output = _run_bytes(
        [
            "git",
            "-C",
            str(workspace),
            "ls-tree",
            "-z",
            base_sha,
            "--",
            included_path,
        ]
    )
    if not output:
        return b"missing", b""
    entries = [entry for entry in output.split(b"\0") if entry]
    if len(entries) != 1:
        raise StateValidationError(
            f"Included path is not one exact file: {included_path}"
        )
    metadata, returned_path = entries[0].split(b"\t", 1)
    mode, object_type, object_id = metadata.split(b" ", 2)
    if returned_path.decode("utf-8", "surrogateescape") != included_path:
        raise StateValidationError(
            f"Git returned a different included path: {included_path}"
        )
    if object_type != b"blob":
        raise StateValidationError(
            f"Included base path is not a file: {included_path}"
        )
    content = _run_bytes(
        ["git", "-C", str(workspace), "cat-file", "blob", object_id.decode()]
    )
    return mode, content


def _working_file_record(target, included_path):
    try:
        metadata = os.lstat(target)
    except FileNotFoundError:
        return b"missing", b""
    if stat.S_ISLNK(metadata.st_mode):
        return b"120000", os.fsencode(os.readlink(target))
    if not stat.S_ISREG(metadata.st_mode):
        raise StateValidationError(
            f"Included workspace path is not a regular file: {included_path}"
        )
    mode = b"100755" if metadata.st_mode & stat.S_IXUSR else b"100644"
    return mode, target.read_bytes()


def _framed(label, content):
    return label + struct.pack(">Q", len(content)) + content


def compute_packet_identity(
    *,
    workspace_path,
    workspace_kind,
    base_sha,
    head_repository,
    head_branch,
    head_sha,
    commit_message,
    included_files,
):
    workspace = Path(workspace_path).expanduser().resolve()
    if workspace_kind not in WORKSPACE_KINDS:
        raise StateValidationError("workspace_kind is invalid.")
    if not workspace.is_dir():
        raise StateValidationError(f"Workspace directory is missing: {workspace}")
    for name, value in (
        ("base_sha", base_sha),
        ("head_sha", head_sha),
    ):
        if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
            raise StateValidationError(f"{name} is invalid.")
    if base_sha != head_sha:
        raise StateValidationError("base_sha must equal the PR head_sha.")
    for name, value in (
        ("head_repository", head_repository),
        ("head_branch", head_branch),
        ("commit_message", commit_message),
    ):
        _require_nonempty_string(value, name)
    _validate_string_list(
        included_files,
        "included_files",
        minimum=1,
        unique=True,
    )
    actual_head = _workspace_head(workspace)
    if actual_head != base_sha:
        raise StateValidationError(
            "Workspace HEAD does not match the supplied base_sha."
        )

    canonical = bytearray(b"apply-pr-reviews-change-v1\0")
    sorted_files = sorted(included_files)
    for included_path in sorted_files:
        target = _validate_included_path(workspace, included_path)
        base_mode, base_content = _base_file_record(
            workspace, base_sha, included_path
        )
        work_mode, work_content = _working_file_record(target, included_path)
        if base_mode == work_mode and base_content == work_content:
            raise StateValidationError(
                f"Included file is unchanged: {included_path}"
            )
        if base_mode == b"missing" and work_mode == b"missing":
            raise StateValidationError(
                f"Included file is missing: {included_path}"
            )
        path_bytes = included_path.encode("utf-8", "surrogateescape")
        canonical.extend(_framed(b"P", path_bytes))
        canonical.extend(_framed(b"M", base_mode))
        canonical.extend(_framed(b"B", base_content))
        canonical.extend(_framed(b"m", work_mode))
        canonical.extend(_framed(b"W", work_content))

    final_head = run_command(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"]
    ).strip()
    if final_head != actual_head:
        raise StateValidationError(
            "Workspace HEAD changed while computing the fingerprint."
        )

    packet = {
        "head_repository": head_repository,
        "head_branch": head_branch,
        "head_sha": head_sha,
        "diff_sha256": hashlib.sha256(canonical).hexdigest(),
        "included_files": sorted_files,
        "commit_message": commit_message,
    }
    workspace_identity = {
        "kind": workspace_kind,
        "path": str(workspace),
        "base_sha": base_sha,
        "head_sha": actual_head,
    }
    return {
        "workspace": workspace_identity,
        "packet_identity": packet,
    }


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
    _validate_workspace_identity(state["workspace"], pull_request)
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
    if not os.path.lexists(path):
        return None
    if path.is_symlink():
        raise StateValidationError(
            f"Cannot read state through a symbolic link: {path}"
        )
    path = path.resolve()
    if path.parent != directory:
        raise StateValidationError("State file escaped the PR state directory.")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StateValidationError(f"Cannot read valid state: {path}") from error
    validate_state(state, pr_number)
    _validate_repository_path(state, repo_path)
    _validate_workspace_runtime(state)
    return state


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


def _validate_backup_name(backup_name):
    if (
        not isinstance(backup_name, str)
        or not BACKUP_NAME_PATTERN.fullmatch(backup_name)
        or backup_name in {STATE_FILENAME, RECOVERY_FILENAME, ".lock"}
    ):
        raise StateValidationError("backup_name is unsafe.")


def recover_state(
    repo_path,
    pr_number,
    *,
    backup_name,
    recovery_question,
    human_answer,
    runner=run_command,
):
    _validate_backup_name(backup_name)
    _require_nonempty_string(recovery_question, "recovery_question")
    _require_nonempty_string(human_answer, "human_answer")
    state_dir = state_directory(repo_path, pr_number, runner=runner)
    with pr_lock(state_dir):
        state_path = state_dir / STATE_FILENAME
        backup_path = state_dir / backup_name
        marker_path = state_dir / RECOVERY_FILENAME
        if not os.path.lexists(state_path):
            raise StateValidationError("No lexical state.json entry to recover.")
        if os.path.lexists(backup_path):
            raise StateValidationError("Recovery backup already exists.")
        if os.path.lexists(marker_path):
            raise StateValidationError("Recovery metadata already exists.")
        result = {
            "backup_name": backup_name,
            "backup_path": str(backup_path),
            "recovery_question": recovery_question,
            "human_answer": human_answer,
        }
        os.replace(state_path, backup_path)
        try:
            backup_mode = os.lstat(backup_path).st_mode
            if stat.S_ISDIR(backup_mode):
                _set_private_mode(backup_path, 0o700)
            elif not stat.S_ISLNK(backup_mode):
                _set_private_mode(backup_path, 0o600)
            _atomic_write(marker_path, result)
        except BaseException:
            if not os.path.lexists(state_path) and os.path.lexists(backup_path):
                os.replace(backup_path, state_path)
            raise
    return result


def _read_recovery_marker(state_dir):
    marker_path = state_dir / RECOVERY_FILENAME
    if not os.path.lexists(marker_path):
        return None
    if marker_path.is_symlink():
        raise StateValidationError("Recovery metadata cannot be a symlink.")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StateValidationError("Recovery metadata is unreadable.") from error
    required = {
        "backup_name",
        "backup_path",
        "recovery_question",
        "human_answer",
    }
    _require_exact_object(marker, required, "recovery metadata")
    _validate_backup_name(marker["backup_name"])
    for field in required:
        _require_nonempty_string(marker[field], f"recovery metadata.{field}")
    expected_path = state_dir / marker["backup_name"]
    if (
        marker["backup_path"] != str(expected_path)
        or not os.path.lexists(expected_path)
    ):
        raise StateValidationError("Recovery backup identity is invalid.")
    return marker


def _validate_recovery_initialization(state, state_dir):
    marker = _read_recovery_marker(state_dir)
    if marker is None:
        return None
    if not state["decision_history"]:
        raise StateValidationError(
            "Fresh state after recovery requires first decision-history entry."
        )
    first = state["decision_history"][0]
    expected_recovery = {
        "backup_name": marker["backup_name"],
        "backup_path": marker["backup_path"],
    }
    if (
        first["decision_type"] != "state-recovery"
        or first["question"] != marker["recovery_question"]
        or first["answer"] != marker["human_answer"]
        or first["recovery"] != expected_recovery
    ):
        raise StateValidationError(
            "First decision-history entry does not match authorized recovery."
        )
    return state_dir / RECOVERY_FILENAME


def initialize_state(repo_path, pr_number, state, *, runner=run_command):
    validate_state(state, pr_number)
    _validate_repository_path(state, repo_path)
    _validate_workspace_runtime(state)
    if state["revision"] != 0:
        raise StateValidationError("Initial state revision must be 0.")
    state_dir = state_directory(repo_path, pr_number, runner=runner)
    with pr_lock(state_dir):
        path = state_dir / STATE_FILENAME
        if os.path.lexists(path):
            raise RevisionConflict(
                f"State already exists for PR {pr_number}: {path}"
            )
        recovery_marker = _validate_recovery_initialization(state, state_dir)
        _atomic_write(path, state)
        if recovery_marker is not None:
            recovery_marker.unlink()
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
    _validate_workspace_runtime(state)
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
    for name in ("read", "init", "update", "recover"):
        command = subparsers.add_parser(name)
        command.add_argument("--repo", required=True, type=Path)
        command.add_argument("--pr", required=True, type=int)
        if name == "update":
            command.add_argument(
                "--expected-revision", required=True, type=int
            )
        elif name == "recover":
            command.add_argument("--backup-name", required=True)
            command.add_argument("--recovery-question", required=True)
            command.add_argument("--human-answer", required=True)
    fingerprint = subparsers.add_parser("fingerprint")
    fingerprint.add_argument("--workspace", required=True, type=Path)
    fingerprint.add_argument(
        "--workspace-kind",
        required=True,
        choices=sorted(WORKSPACE_KINDS),
    )
    fingerprint.add_argument("--base-sha", required=True)
    fingerprint.add_argument("--head-repository", required=True)
    fingerprint.add_argument("--head-branch", required=True)
    fingerprint.add_argument("--head-sha", required=True)
    fingerprint.add_argument("--commit-message", required=True)
    fingerprint.add_argument("--file", required=True, action="append")
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
        elif args.command == "update":
            result = update_state(
                args.repo,
                args.pr,
                args.expected_revision,
                _read_input(),
            )
        elif args.command == "recover":
            result = recover_state(
                args.repo,
                args.pr,
                backup_name=args.backup_name,
                recovery_question=args.recovery_question,
                human_answer=args.human_answer,
            )
        else:
            result = compute_packet_identity(
                workspace_path=args.workspace,
                workspace_kind=args.workspace_kind,
                base_sha=args.base_sha,
                head_repository=args.head_repository,
                head_branch=args.head_branch,
                head_sha=args.head_sha,
                commit_message=args.commit_message,
                included_files=args.file,
            )
    except ContextStoreError as error:
        parser.exit(2, f"error: {error}\n")
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
