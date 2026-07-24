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


SCHEMA_VERSION = 3
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
CHOICE_FIELDS = {"outcome", "label"}
PUBLISH_APPROVAL_QUESTION = "Approve this exact commit and push for this PR?"
PUBLISH_RECOMMENDATION = (
    "Approve only if the displayed evidence and target are correct."
)
DECISION_SCOPE = "This PR only."
PUBLISH_CHOICES = (
    ("approved", "Approve the exact displayed commit and push."),
    ("rejected", "Reject it and keep the verified diff local."),
    ("changes-requested", "Request changes to the proposed work."),
)
RECOVERY_QUESTION = "How should the preserved invalid local state be handled?"
RECOVERY_RECOMMENDATION = (
    "Leave it untouched until its provenance is understood."
)
RECOVERY_CHOICES = (
    (
        "leave-untouched",
        "Leave the preserved state untouched and stop this PR.",
    ),
    (
        "backup-authorized",
        "Authorize moving the invalid state to a named private backup, then "
        "initialize fresh state.",
    ),
)
RECOVERY_FIELDS = {"backup_name", "backup_path"}
BACKUP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
APPROVAL_FIELDS = {
    "valid",
    "outcome",
    "packet_identity",
    "decision_history_index",
    "human_answer",
}
PUBLICATION_FIELDS = {
    "status",
    "commit_sha",
    "pushed_sha",
    "packet_identity",
    "approval_decision_history_index",
    "checks",
    "published_at",
}
PUBLICATION_STATUSES = {"committed", "pushed"}
RAW_ENV_ASSIGNMENT = re.compile(
    r"(?m)^\s*[A-Z_][A-Z0-9_]{1,}\s*=\s*(?P<value>.*?)\s*$"
)
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:authorization|api[_ -]?key|client[_ -]?secret|"
    r"password|secret|token|cookie)\s*[:=]\s*(?P<value>.*?)\s*$"
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
            _normalized_assignment_value(match.group("value"))
            for match in RAW_ENV_ASSIGNMENT.finditer(value)
        ]
        assignment_values = [
            _normalized_assignment_value(match.group("value"))
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


def _normalized_assignment_value(value):
    normalized = value.strip()
    if (
        len(normalized) >= 2
        and normalized[0] == normalized[-1]
        and normalized[0] in {"'", '"'}
    ):
        normalized = normalized[1:-1].strip()
    return normalized.lower()


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


def _choice_documents(canonical):
    return [
        {"outcome": outcome, "label": label}
        for outcome, label in canonical
    ]


def _validate_canonical_choices(value, canonical, path):
    expected = _choice_documents(canonical)
    if value != expected:
        raise StateValidationError(f"{path} must equal the canonical choices.")
    for index, choice in enumerate(value):
        _require_exact_object(choice, CHOICE_FIELDS, f"{path}[{index}]")
    return value


def _selected_choice_outcome(options, answer, path):
    for choice in options:
        if choice["label"] == answer:
            return choice["outcome"]
    raise StateValidationError(f"{path}.answer must select a displayed choice.")


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


def _validate_workspace_identity(workspace):
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
    if state["publication"] is not None:
        _validate_committed_git_snapshot(state)


def _current_packet_identity(state):
    return {
        "head_repository": state["pull_request"]["head_repository"],
        "head_branch": state["pull_request"]["head_branch"],
        "head_sha": state["workspace"]["base_sha"],
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
        packet = decision["packet_identity"]
        if packet is not None:
            _validate_packet_identity(packet, f"{path}.packet_identity")
            if packet != current_packet:
                raise StateValidationError(
                    f"{path}.packet_identity is not current."
                )
            if (
                decision["question"] != PUBLISH_APPROVAL_QUESTION
                or decision["recommendation"] != PUBLISH_RECOMMENDATION
                or decision["scope"] != DECISION_SCOPE
            ):
                raise StateValidationError(
                    f"{path} must equal the canonical publish gate."
                )
            _validate_canonical_choices(
                decision["options"], PUBLISH_CHOICES, f"{path}.options"
            )
        else:
            _validate_string_list(
                decision["options"],
                f"{path}.options",
                minimum=2,
                maximum=3,
                unique=True,
            )
            if decision["question"] == PUBLISH_APPROVAL_QUESTION:
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
        _validate_string_list(decision["evidence"], f"{path}.evidence")
        if not isinstance(decision["options"], list):
            raise StateValidationError(f"{path}.options must be a list.")
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
            if (
                decision["recommendation"] != PUBLISH_RECOMMENDATION
                or decision["scope"] != DECISION_SCOPE
            ):
                raise StateValidationError(
                    f"{path} must preserve the canonical publish gate."
                )
            options = _validate_canonical_choices(
                decision["options"], PUBLISH_CHOICES, f"{path}.options"
            )
            selected_outcome = _selected_choice_outcome(
                options, decision["answer"], path
            )
            if outcome != selected_outcome:
                raise StateValidationError(
                    f"{path}.outcome does not match the selected choice."
                )
            if recovery is not None:
                raise StateValidationError(
                    f"{path}.recovery must be null for publish approval."
                )
        elif decision["decision_type"] == "state-recovery":
            if recovery is None:
                raise StateValidationError(
                    f"{path}.recovery is required for state recovery."
                )
            if (
                decision["question"] != RECOVERY_QUESTION
                or decision["recommendation"] != RECOVERY_RECOMMENDATION
                or decision["scope"] != DECISION_SCOPE
            ):
                raise StateValidationError(
                    f"{path} must preserve the canonical recovery gate."
                )
            options = _validate_canonical_choices(
                decision["options"], RECOVERY_CHOICES, f"{path}.options"
            )
            selected_outcome = _selected_choice_outcome(
                options, decision["answer"], path
            )
            if outcome != selected_outcome or outcome != "backup-authorized":
                raise StateValidationError(
                    f"{path} requires the canonical backup authorization."
                )
        elif outcome is not None:
            raise StateValidationError(
                f"{path}.outcome is only valid for a typed human decision."
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
    if approval["outcome"] not in PUBLISH_OUTCOMES:
        raise StateValidationError("approval.outcome is invalid.")
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
    if approval["outcome"] != linked_decision["outcome"]:
        raise StateValidationError(
            "Approval outcome does not match its selected publish choice."
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
    if approval["valid"] and approval["outcome"] != "approved":
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
        pull_head = state["pull_request"]["head_sha"]
        workspace = state["workspace"]
        if (
            workspace["base_sha"] != pull_head
            or workspace["head_sha"] != pull_head
        ):
            raise StateValidationError(
                "Pre-publication workspace SHAs must equal the PR head."
            )
        return
    _require_exact_object(publication, PUBLICATION_FIELDS, "publication")
    if publication["status"] not in PUBLICATION_STATUSES:
        raise StateValidationError("publication.status is invalid.")
    commit_sha = publication["commit_sha"]
    if not isinstance(commit_sha, str) or not SHA_PATTERN.fullmatch(commit_sha):
        raise StateValidationError("publication.commit_sha is invalid.")
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
    workspace = state["workspace"]
    pull_head = state["pull_request"]["head_sha"]
    if (
        packet != _current_packet_identity(state)
        or workspace["base_sha"] != packet["head_sha"]
        or workspace["head_sha"] != commit_sha
    ):
        raise StateValidationError(
            "Publication does not retain the approved pre-commit packet."
        )
    if publication["status"] == "committed":
        if (
            publication["pushed_sha"] is not None
            or publication["published_at"] is not None
            or pull_head != workspace["base_sha"]
        ):
            raise StateValidationError(
                "Committed checkpoint has incoherent push or PR-head fields."
            )
    else:
        if (
            publication["pushed_sha"] != commit_sha
            or pull_head != commit_sha
        ):
            raise StateValidationError(
                "Pushed publication must advance the PR head to the commit."
            )
        _require_nonempty_string(
            publication["published_at"], "publication.published_at"
        )


def _run_bytes(command, *, env=None):
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
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


def _tree_file_record(workspace, treeish, included_path):
    output = _run_bytes(
        [
            "git",
            "-C",
            str(workspace),
            "ls-tree",
            "-z",
            treeish,
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
            f"Included tree path is not a file: {included_path}"
        )
    content = _run_bytes(
        ["git", "-C", str(workspace), "cat-file", "blob", object_id.decode()]
    )
    return mode, content


def _index_environment(index_path):
    environment = os.environ.copy()
    environment["GIT_INDEX_FILE"] = str(index_path)
    return environment


@contextmanager
def _temporary_index(workspace, base_sha):
    descriptor, index_name = tempfile.mkstemp(prefix="apply-pr-reviews-index.")
    os.close(descriptor)
    os.unlink(index_name)
    index_path = Path(index_name)
    environment = _index_environment(index_path)
    try:
        _run_bytes(
            ["git", "-C", str(workspace), "read-tree", base_sha],
            env=environment,
        )
        yield environment
    finally:
        try:
            index_path.unlink()
        except FileNotFoundError:
            pass


def _index_changed_paths(workspace, base_sha, *, env=None):
    output = _run_bytes(
        [
            "git",
            "-C",
            str(workspace),
            "diff",
            "--cached",
            "--name-only",
            "-z",
            base_sha,
            "--",
        ],
        env=env,
    )
    return sorted(
        path.decode("utf-8", "surrogateescape")
        for path in output.split(b"\0")
        if path
    )


def _write_index_tree(workspace, *, env=None):
    return _run_bytes(
        ["git", "-C", str(workspace), "write-tree"],
        env=env,
    ).decode("ascii").strip()


def _snapshot_working_tree(workspace, base_sha, included_files):
    if _index_changed_paths(workspace, base_sha):
        raise StateValidationError(
            "The real Git index must be empty before working fingerprinting."
        )
    for included_path in included_files:
        _validate_included_path(workspace, included_path)
    with _temporary_index(workspace, base_sha) as environment:
        literal_paths = [
            f":(literal){included_path}" for included_path in included_files
        ]
        _run_bytes(
            [
                "git",
                "-C",
                str(workspace),
                "add",
                "-A",
                "--",
                *literal_paths,
            ],
            env=environment,
        )
        changed_paths = _index_changed_paths(
            workspace, base_sha, env=environment
        )
        if changed_paths != included_files:
            raise StateValidationError(
                "Working snapshot changes do not equal included_files."
            )
        return _write_index_tree(workspace, env=environment)


def _snapshot_real_index(workspace, base_sha, included_files):
    for included_path in included_files:
        _validate_included_path(workspace, included_path)
    changed_paths = _index_changed_paths(workspace, base_sha)
    if changed_paths != included_files:
        raise StateValidationError(
            "Staged paths do not exactly equal included_files."
        )
    return _write_index_tree(workspace)


def _framed(label, content):
    return label + struct.pack(">Q", len(content)) + content


def _canonical_tree_difference(
    workspace,
    base_tree,
    snapshot_tree,
    included_files,
):
    canonical = bytearray(b"apply-pr-reviews-change-v1\0")
    for included_path in included_files:
        base_mode, base_content = _tree_file_record(
            workspace, base_tree, included_path
        )
        work_mode, work_content = _tree_file_record(
            workspace, snapshot_tree, included_path
        )
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
    return bytes(canonical)


def _tree_changed_paths(workspace, base_sha, commit_sha):
    output = _run_bytes(
        [
            "git",
            "-C",
            str(workspace),
            "diff",
            "--name-only",
            "-z",
            base_sha,
            commit_sha,
            "--",
        ]
    )
    return sorted(
        path.decode("utf-8", "surrogateescape")
        for path in output.split(b"\0")
        if path
    )


def _validate_committed_git_snapshot(state):
    workspace = Path(state["workspace"]["path"])
    base_sha = state["workspace"]["base_sha"]
    publication = state["publication"]
    commit_sha = publication["commit_sha"]
    parent_sha = run_command(
        ["git", "-C", str(workspace), "rev-parse", f"{commit_sha}^"]
    ).strip()
    if parent_sha != base_sha:
        raise StateValidationError(
            "Published commit must directly follow the approved base SHA."
        )
    included_files = publication["packet_identity"]["included_files"]
    if _tree_changed_paths(workspace, base_sha, commit_sha) != included_files:
        raise StateValidationError(
            "Published commit paths do not equal approved included_files."
        )
    commit_tree = run_command(
        ["git", "-C", str(workspace), "rev-parse", f"{commit_sha}^{{tree}}"]
    ).strip()
    canonical = _canonical_tree_difference(
        workspace,
        base_sha,
        commit_tree,
        included_files,
    )
    if (
        hashlib.sha256(canonical).hexdigest()
        != publication["packet_identity"]["diff_sha256"]
    ):
        raise StateValidationError(
            "Published commit tree does not match the approved fingerprint."
        )
    commit_message = run_command(
        ["git", "-C", str(workspace), "show", "-s", "--format=%B", commit_sha]
    ).rstrip("\n")
    if commit_message != publication["packet_identity"]["commit_message"]:
        raise StateValidationError(
            "Published commit message does not match the approved packet."
        )


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
    source="working",
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

    sorted_files = sorted(included_files)
    if source == "working":
        snapshot_tree = _snapshot_working_tree(
            workspace, base_sha, sorted_files
        )
    elif source == "index":
        snapshot_tree = _snapshot_real_index(
            workspace, base_sha, sorted_files
        )
    else:
        raise StateValidationError("source must be working or index.")
    canonical = _canonical_tree_difference(
        workspace,
        base_sha,
        snapshot_tree,
        sorted_files,
    )

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
        "snapshot_tree": snapshot_tree,
        "source": source,
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
    _validate_workspace_identity(state["workspace"])
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


def _read_state_document(
    repo_path,
    pr_number,
    *,
    runner=run_command,
    validate_runtime,
):
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
    if validate_runtime:
        _validate_workspace_runtime(state)
    return state


def read_state(repo_path, pr_number, *, runner=run_command):
    return _read_state_document(
        repo_path,
        pr_number,
        runner=runner,
        validate_runtime=True,
    )


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
    outcome,
    runner=run_command,
):
    _validate_backup_name(backup_name)
    if (
        recovery_question != RECOVERY_QUESTION
        or human_answer != RECOVERY_CHOICES[1][1]
        or outcome != RECOVERY_CHOICES[1][0]
    ):
        raise StateValidationError(
            "Recovery requires the canonical backup-authorized choice."
        )
    state_dir = state_directory(repo_path, pr_number, runner=runner)
    with pr_lock(state_dir):
        state_path = state_dir / STATE_FILENAME
        backup_path = state_dir / backup_name
        marker_path = state_dir / RECOVERY_FILENAME
        if not os.path.lexists(state_path):
            raise StateValidationError("No lexical state.json entry to recover.")
        try:
            valid_state = read_state(repo_path, pr_number, runner=runner)
        except ContextStoreError:
            valid_state = None
        if valid_state is not None:
            raise StateValidationError(
                "Recovery refuses state that validates normally for this PR."
            )
        if os.path.lexists(backup_path):
            raise StateValidationError("Recovery backup already exists.")
        if os.path.lexists(marker_path):
            raise StateValidationError("Recovery metadata already exists.")
        result = {
            "backup_name": backup_name,
            "backup_path": str(backup_path),
            "question": RECOVERY_QUESTION,
            "options": _choice_documents(RECOVERY_CHOICES),
            "recommendation": RECOVERY_RECOMMENDATION,
            "answer": human_answer,
            "outcome": outcome,
            "scope": DECISION_SCOPE,
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
        "question",
        "options",
        "recommendation",
        "answer",
        "outcome",
        "scope",
    }
    _require_exact_object(marker, required, "recovery metadata")
    _validate_backup_name(marker["backup_name"])
    for field in required - {"options"}:
        _require_nonempty_string(marker[field], f"recovery metadata.{field}")
    _validate_canonical_choices(
        marker["options"], RECOVERY_CHOICES, "recovery metadata.options"
    )
    if (
        marker["question"] != RECOVERY_QUESTION
        or marker["recommendation"] != RECOVERY_RECOMMENDATION
        or marker["answer"] != RECOVERY_CHOICES[1][1]
        or marker["outcome"] != RECOVERY_CHOICES[1][0]
        or marker["scope"] != DECISION_SCOPE
    ):
        raise StateValidationError("Recovery decision evidence is invalid.")
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
        or first["question"] != marker["question"]
        or first["options"] != marker["options"]
        or first["recommendation"] != marker["recommendation"]
        or first["answer"] != marker["answer"]
        or first["outcome"] != marker["outcome"]
        or first["scope"] != marker["scope"]
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


def _without(mapping, field):
    return {key: value for key, value in mapping.items() if key != field}


def _validate_publication_transition(current, state):
    current_publication = current["publication"]
    new_publication = state["publication"]
    if current_publication is None and new_publication is None:
        _validate_workspace_runtime(current)
        return
    if current["approval"] != state["approval"]:
        raise StateValidationError(
            "Publication lifecycle must retain the approved decision."
        )
    if current["changes"] != state["changes"]:
        raise StateValidationError(
            "Publication lifecycle must retain approved changes."
        )
    for field in ("kind", "path", "base_sha"):
        if current["workspace"][field] != state["workspace"][field]:
            raise StateValidationError(
                "Publication lifecycle cannot replace its workspace identity."
            )

    if current_publication is None:
        if new_publication["status"] != "committed":
            raise StateValidationError(
                "Publication must persist committed before pushed."
            )
        if current["pull_request"] != state["pull_request"]:
            raise StateValidationError(
                "Committed checkpoint cannot advance the PR head."
            )
        if (
            current["workspace"]["head_sha"]
            != current["workspace"]["base_sha"]
            or state["workspace"]["head_sha"]
            != new_publication["commit_sha"]
        ):
            raise StateValidationError(
                "Committed checkpoint has an invalid workspace transition."
            )
        return

    if new_publication is None:
        raise StateValidationError("Publication lifecycle cannot regress.")
    old_status = current_publication["status"]
    new_status = new_publication["status"]
    allowed = {
        ("committed", "committed"),
        ("committed", "pushed"),
        ("pushed", "pushed"),
    }
    if (old_status, new_status) not in allowed:
        raise StateValidationError("Publication status transition is invalid.")
    for field in (
        "commit_sha",
        "packet_identity",
        "approval_decision_history_index",
    ):
        if current_publication[field] != new_publication[field]:
            raise StateValidationError(
                f"Publication transition changed {field}."
            )
    if (
        state["workspace"] != current["workspace"]
        or _without(state["pull_request"], "head_sha")
        != _without(current["pull_request"], "head_sha")
    ):
        raise StateValidationError(
            "Publication transition changed immutable target identity."
        )
    old_checks = current_publication["checks"]
    if state["publication"]["checks"][: len(old_checks)] != old_checks:
        raise StateValidationError(
            "Publication checks must preserve their existing prefix."
        )
    if old_status == new_status and state["pull_request"] != current["pull_request"]:
        raise StateValidationError(
            "PR head can advance only on committed-to-pushed transition."
        )


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
        current = _read_state_document(
            repo_path,
            pr_number,
            runner=runner,
            validate_runtime=False,
        )
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
        _validate_publication_transition(current, state)
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
            command.add_argument("--outcome", required=True)
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
    fingerprint.add_argument(
        "--source",
        choices=("working", "index"),
        default="working",
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
                outcome=args.outcome,
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
                source=args.source,
            )
    except ContextStoreError as error:
        parser.exit(2, f"error: {error}\n")
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
