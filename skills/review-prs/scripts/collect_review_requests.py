#!/usr/bin/env python3
"""Collect pull requests that wait for the user's review, read-only.

Reports review requests, the user's last real review, review threads, CI
state, and other open pull requests that share a ticket key.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


CONFIG_VERSION = 1
OUTPUT_VERSION = 1
CONFIG_DIRECTORY = "review-prs"
SIBLING_CONFIG_DIRECTORY = "apply-pr-reviews"
CONFIG_FILENAME = "repositories.json"
REQUEST_SEARCH = "review-requested:@me -is:draft"
REQUEST_FIELDS = "number,title,url,author,headRefName,baseRefName,isDraft"
OPEN_PR_FIELDS = "number,title,headRefName"
PR_DETAIL_FIELDS = (
    "number,title,body,url,author,headRefName,headRefOid,baseRefName,"
    "baseRefOid,isCrossRepository,commits,statusCheckRollup"
)
TICKET_KEY = re.compile(r"[A-Z][A-Z0-9]+-[0-9]+")
NON_TICKET_PREFIXES = frozenset({"UTF", "SHA", "ISO", "RFC", "TLS"})
BRANCH_TICKET_KEY = re.compile(r"[A-Za-z][A-Za-z0-9]+-[0-9]+")
PR_REF = re.compile(r"^(?P<repository>[^/\s#]+/[^/\s#]+)#(?P<number>[0-9]+)$")
VERDICT_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED"})

REVIEW_THREADS_QUERY = """
query(
  $owner: String!,
  $repo: String!,
  $number: Int!,
  $cursor: String
) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          originalLine
          comments(first: 100) {
            nodes {
              databaseId
              author { login }
              body
              createdAt
              url
              commit { oid }
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
""".strip()


class CollectError(RuntimeError):
    """Base error for expected command-line failures."""


class ConfigurationError(CollectError):
    """Raised when repository configuration is missing or invalid."""


class ExternalCommandError(CollectError):
    """Raised when git or GitHub CLI fails."""


def run_command(command, *, cwd=None):
    """Run a command and return stdout, raising a concise actionable error."""
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise ExternalCommandError(
            f"Required command is not installed: {command[0]}"
        ) from error

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        rendered = " ".join(command)
        raise ExternalCommandError(
            f"Command failed ({completed.returncode}): {rendered}"
            + (f"\n{detail}" if detail else "")
        )
    return completed.stdout


def run_json(command, *, runner=run_command, cwd=None):
    """Run a command that emits one JSON value."""
    output = runner(command, cwd=cwd)
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise ExternalCommandError(
            f"Command returned invalid JSON: {' '.join(command)}"
        ) from error


def parse_github_remote(remote):
    """Return owner/name for supported github.com SSH and HTTPS remotes."""
    value = remote.strip()
    patterns = (
        r"^git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
        r"^https://github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$",
    )
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            return match.group("repo")
    raise ConfigurationError(
        "The origin remote must point to github.com using SSH or HTTPS: "
        + (value or "<empty>")
    )


def sibling_config_path(skill_name, environ=None, platform=None):
    """Return the per-user config path of a greenlight skill."""
    env = os.environ if environ is None else environ
    current_platform = sys.platform if platform is None else platform
    if current_platform.startswith("win") and env.get("APPDATA"):
        base = Path(env["APPDATA"])
    elif env.get("XDG_CONFIG_HOME"):
        base = Path(env["XDG_CONFIG_HOME"])
    else:
        base = Path.home() / ".config"
    return base / skill_name / CONFIG_FILENAME


def default_config_path(environ=None, platform=None):
    """Return this skill's config path without writing anything."""
    return sibling_config_path(
        CONFIG_DIRECTORY, environ=environ, platform=platform
    )


def build_config(paths, *, runner=run_command):
    """Validate local repository paths and derive GitHub names from origin."""
    if not paths:
        raise ConfigurationError("Choose at least one local repository path.")

    repositories = []
    seen_paths = set()
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_dir():
            raise ConfigurationError(
                f"Repository directory does not exist: {path}"
            )
        path_key = str(path)
        if path_key in seen_paths:
            continue

        remote = runner(
            ["git", "-C", path_key, "config", "--get", "remote.origin.url"],
            cwd=None,
        )
        repositories.append(
            {"path": path_key, "repository": parse_github_remote(remote)}
        )
        seen_paths.add(path_key)

    return {"version": CONFIG_VERSION, "repositories": repositories}


def validate_config(config):
    """Validate config shape and return it unchanged."""
    if not isinstance(config, dict) or config.get("version") != CONFIG_VERSION:
        raise ConfigurationError(
            f"Configuration must use version {CONFIG_VERSION}."
        )
    repositories = config.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise ConfigurationError(
            "Configuration must contain at least one repository."
        )
    for entry in repositories:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("path"), str)
            or not entry["path"]
            or not isinstance(entry.get("repository"), str)
            or "/" not in entry["repository"]
        ):
            raise ConfigurationError(
                "Every repository needs non-empty path and repository fields."
            )
    return config


def save_config(path, config):
    """Atomically save a validated private configuration file."""
    validate_config(config)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=str(destination.parent),
        text=True,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
            handle.write("\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, destination)
        os.chmod(destination, 0o600)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def load_config(path):
    """Load and validate repository configuration."""
    source = Path(path)
    if not source.is_file():
        raise ConfigurationError(
            f"Repository configuration not found: {source}. "
            "Run configure after the user chooses local repositories."
        )
    try:
        config = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(
            f"Cannot read repository configuration: {source}"
        ) from error
    return validate_config(config)


def suggest_paths(environ=None, platform=None):
    """Return repository paths from the apply-pr-reviews config, if any."""
    try:
        config = load_config(
            sibling_config_path(
                SIBLING_CONFIG_DIRECTORY, environ=environ, platform=platform
            )
        )
    except ConfigurationError:
        return []
    return [entry["path"] for entry in config["repositories"]]


def fetch_viewer_login(*, runner=run_command):
    """Return the login of the authenticated GitHub user."""
    login = runner(["gh", "api", "user", "--jq", ".login"], cwd=None).strip()
    if not login:
        raise ExternalCommandError(
            "Cannot read the authenticated GitHub login."
        )
    return login


def _gh_pr_list(repository, extra, fields, *, runner, state="open"):
    command = [
        "gh",
        "pr",
        "list",
        "--repo",
        repository,
        "--state",
        state,
        "--limit",
        "1000",
        *extra,
        "--json",
        fields,
    ]
    result = run_json(command, runner=runner)
    if not isinstance(result, list):
        raise ExternalCommandError(
            f"Unexpected PR list response for {repository}."
        )
    return result


def list_review_requests(repository, *, runner=run_command):
    """List open, non-draft PRs that request the user's review."""
    return _gh_pr_list(
        repository, ["--search", REQUEST_SEARCH], REQUEST_FIELDS, runner=runner
    )


def list_open_pr_titles(repository, *, runner=run_command):
    """List every open PR's number, title, and head branch."""
    return _gh_pr_list(repository, [], OPEN_PR_FIELDS, runner=runner)


def list_merged_pr_titles(repository, *, runner=run_command):
    """List recently merged PRs' number, title, and head branch."""
    return _gh_pr_list(
        repository, [], OPEN_PR_FIELDS, runner=runner, state="merged"
    )


def fetch_pr_summary(repository, number, *, runner=run_command):
    """Fetch the list fields for one named PR."""
    command = [
        "gh",
        "pr",
        "view",
        str(number),
        "--repo",
        repository,
        "--json",
        REQUEST_FIELDS,
    ]
    value = run_json(command, runner=runner)
    if not isinstance(value, dict):
        raise ExternalCommandError(
            f"Unexpected PR response for {repository}#{number}."
        )
    return value


def parse_pr_ref(ref):
    """Split an owner/repo#number reference."""
    match = PR_REF.match(ref.strip())
    if not match:
        raise ConfigurationError(
            f"Use owner/repository#number for a pull request: {ref}"
        )
    return match.group("repository"), int(match.group("number"))


def _repository_parts(repository):
    owner, _, name = repository.partition("/")
    if not owner or not name:
        raise ConfigurationError(
            f"Invalid GitHub repository name: {repository}"
        )
    return owner, name


def fetch_review_threads(repository, number, *, runner=run_command):
    """Fetch all review thread pages, including resolved and outdated state."""
    owner, name = _repository_parts(repository)
    threads = []
    cursor = None

    while True:
        command = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={REVIEW_THREADS_QUERY}",
            "-f",
            f"owner={owner}",
            "-f",
            f"repo={name}",
            "-F",
            f"number={number}",
        ]
        if cursor is not None:
            command.extend(["-f", f"cursor={cursor}"])

        response = run_json(command, runner=runner)
        try:
            page = response["data"]["repository"]["pullRequest"][
                "reviewThreads"
            ]
            nodes = page["nodes"]
            page_info = page["pageInfo"]
        except (KeyError, TypeError) as error:
            raise ExternalCommandError(
                f"Unexpected review thread response for {repository}#{number}."
            ) from error
        threads.extend(nodes or [])
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            raise ExternalCommandError(
                f"Missing review thread cursor for {repository}#{number}."
            )

    return threads


def _flatten_pages(value, *, context):
    if not isinstance(value, list):
        raise ExternalCommandError(f"Unexpected paginated response: {context}.")
    if value and all(isinstance(page, list) for page in value):
        return [item for page in value for item in page]
    return value


def _fetch_paginated(repository, number, resource, *, runner):
    command = [
        "gh",
        "api",
        "--paginate",
        "--slurp",
        f"repos/{repository}/pulls/{number}/{resource}",
    ]
    return _flatten_pages(
        run_json(command, runner=runner),
        context=f"{repository}#{number} {resource}",
    )


def fetch_inline_comments(repository, number, *, runner=run_command):
    """Fetch every inline review comment with its review and reply links."""
    return _fetch_paginated(repository, number, "comments", runner=runner)


def fetch_reviews(repository, number, *, runner=run_command):
    """Fetch submitted pull-request reviews."""
    return _fetch_paginated(repository, number, "reviews", runner=runner)


def fetch_issue_comments(repository, number, *, runner=run_command):
    """Fetch pull-request conversation comments."""
    command = [
        "gh",
        "api",
        "--paginate",
        "--slurp",
        f"repos/{repository}/issues/{number}/comments",
    ]
    return _flatten_pages(
        run_json(command, runner=runner),
        context=f"{repository}#{number} conversation",
    )


def fetch_pr_details(repository, number, *, runner=run_command):
    """Fetch head, base, commits, and CI state for a PR."""
    command = [
        "gh",
        "pr",
        "view",
        str(number),
        "--repo",
        repository,
        "--json",
        PR_DETAIL_FIELDS,
    ]
    value = run_json(command, runner=runner)
    if not isinstance(value, dict):
        raise ExternalCommandError(
            f"Unexpected PR details response for {repository}#{number}."
        )
    return value


def ticket_keys(text):
    """Return ticket keys such as SHOP-12 in order of first appearance."""
    keys = []
    for key in TICKET_KEY.findall(text or ""):
        if key.split("-", 1)[0] in NON_TICKET_PREFIXES:
            continue
        if key not in keys:
            keys.append(key)
    return keys


def pr_ticket_keys(pull_request):
    """Return ticket keys from a PR title, else the first one in its branch.

    Branch names are often lowercase (feat/shop-300-export), so a branch
    segment that starts with a key matches in any case.
    """
    keys = ticket_keys(pull_request.get("title"))
    if keys:
        return keys
    for segment in (pull_request.get("headRefName") or "").split("/"):
        match = BRANCH_TICKET_KEY.match(segment)
        if match:
            key = match.group(0).upper()
            if key.split("-", 1)[0] not in NON_TICKET_PREFIXES:
                return [key]
    return []


def related_prs(pull_request, open_prs, merged_prs):
    """Return other open or merged PRs that share a ticket key."""
    keys = set(pr_ticket_keys(pull_request))
    related = []
    for state, others in (("open", open_prs), ("merged", merged_prs)):
        related.extend(
            {"number": other["number"], "state": state}
            for other in others
            if other["number"] != pull_request["number"]
            and keys & set(pr_ticket_keys(other))
        )
    return related


def _login(item):
    return ((item.get("user") or item.get("author") or {}).get("login") or "")


def last_review(reviews, inline_comments, viewer):
    """Return the viewer's newest review that is more than thread replies."""
    viewer_key = viewer.lower()
    new_comment_reviews = {
        comment.get("pull_request_review_id")
        for comment in inline_comments
        if comment.get("in_reply_to_id") is None
    }
    real_reviews = [
        review
        for review in reviews
        if _login(review).lower() == viewer_key
        and review.get("submitted_at")
        and (
            (review.get("body") or "").strip()
            or review.get("id") in new_comment_reviews
            or review.get("state") in VERDICT_STATES
        )
    ]
    if not real_reviews:
        return None
    newest = max(real_reviews, key=lambda review: review["submitted_at"])
    return {
        "id": newest["id"],
        "commit": newest.get("commit_id"),
        "submitted_at": newest["submitted_at"],
        "state": newest.get("state"),
    }


def review_bodies(reviews):
    """Return reviews that carry text in their body, from any author."""
    return [
        {
            "author": _login(review),
            "state": review.get("state"),
            "body": review["body"],
            "submitted_at": review.get("submitted_at"),
            "commit": review.get("commit_id"),
        }
        for review in reviews
        if (review.get("body") or "").strip()
    ]


def conversation(issue_comments):
    """Return PR conversation comments with author, text, and link."""
    return [
        {
            "author": _login(comment),
            "body": comment.get("body"),
            "created_at": comment.get("created_at"),
            "url": comment.get("html_url"),
        }
        for comment in issue_comments
    ]


def _first_author(thread):
    nodes = (thread.get("comments") or {}).get("nodes") or []
    if not nodes:
        return ""
    return (nodes[0].get("author") or {}).get("login") or ""


def split_threads(threads, viewer):
    """Split threads into the viewer's own and other people's open ones."""
    viewer_key = viewer.lower()
    mine = [
        thread for thread in threads if _first_author(thread).lower() == viewer_key
    ]
    open_others = [
        thread
        for thread in threads
        if _first_author(thread).lower() != viewer_key
        and not thread.get("isResolved")
    ]
    return {"mine": mine, "open_others": open_others}


def collect_pull_request(
    repository, request, open_prs, merged_prs, *, viewer, runner=run_command
):
    """Collect one PR's review data, or record why it failed."""
    number = request["number"]
    try:
        threads = fetch_review_threads(repository, number, runner=runner)
        inline_comments = fetch_inline_comments(
            repository, number, runner=runner
        )
        reviews = fetch_reviews(repository, number, runner=runner)
        issue_comments = fetch_issue_comments(
            repository, number, runner=runner
        )
        details = fetch_pr_details(repository, number, runner=runner)
    except CollectError as error:
        return {**request, "error": str(error)}
    return {
        **request,
        "details": details,
        "ticket_keys": pr_ticket_keys(request),
        "related_prs": related_prs(request, open_prs, merged_prs),
        "last_review": last_review(reviews, inline_comments, viewer),
        "threads": split_threads(threads, viewer),
        "review_bodies": review_bodies(reviews),
        "conversation": conversation(issue_comments),
    }


def _collect_requests(entry, requests, *, viewer, runner):
    repository = entry["repository"]
    pull_requests = []
    if requests:
        open_prs = list_open_pr_titles(repository, runner=runner)
        merged_prs = list_merged_pr_titles(repository, runner=runner)
        pull_requests = [
            collect_pull_request(
                repository,
                request,
                open_prs,
                merged_prs,
                viewer=viewer,
                runner=runner,
            )
            for request in requests
        ]
    return {
        "path": entry["path"],
        "repository": repository,
        "pull_requests": pull_requests,
    }


def collect_repository(entry, *, viewer, runner=run_command):
    """Collect every PR that waits for the viewer's review in one repository."""
    requests = list_review_requests(entry["repository"], runner=runner)
    return _collect_requests(entry, requests, viewer=viewer, runner=runner)


def collect_named(entry, numbers, *, viewer, runner=run_command):
    """Collect the named PRs of one repository, requested or not."""
    requests = [
        fetch_pr_summary(entry["repository"], number, runner=runner)
        for number in numbers
    ]
    return _collect_requests(entry, requests, viewer=viewer, runner=runner)


def _named_by_repository(config, named):
    entries = {entry["repository"]: entry for entry in config["repositories"]}
    grouped = {}
    for ref in named:
        repository, number = parse_pr_ref(ref)
        if repository not in entries:
            raise ConfigurationError(
                f"Repository is not configured: {repository}"
            )
        grouped.setdefault(repository, []).append(number)
    return [(entries[repository], numbers) for repository, numbers in grouped.items()]


def collect_from_config(path, *, runner=run_command, named=None):
    """Collect review requests, or the named PRs, for configured repositories."""
    config = load_config(path)
    viewer = fetch_viewer_login(runner=runner)
    if named:
        jobs = [
            (entry, lambda entry=entry, numbers=numbers: collect_named(
                entry, numbers, viewer=viewer, runner=runner
            ))
            for entry, numbers in _named_by_repository(config, named)
        ]
    else:
        jobs = [
            (entry, lambda entry=entry: collect_repository(
                entry, viewer=viewer, runner=runner
            ))
            for entry in config["repositories"]
        ]
    repositories = []
    for entry, job in jobs:
        try:
            repositories.append(job())
        except CollectError as error:
            repositories.append(
                {
                    "path": entry["path"],
                    "repository": entry["repository"],
                    "pull_requests": [],
                    "error": str(error),
                }
            )
    return {
        "version": OUTPUT_VERSION,
        "viewer": viewer,
        "repositories": repositories,
    }


def create_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Configure local GitHub repositories (configure writes a private "
            "config file) and collect pull requests that wait for your "
            "review. Nothing is written to GitHub."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="configuration path (default: %(default)s)",
    )
    subparsers = parser.add_subparsers(dest="command")
    configure_parser = subparsers.add_parser(
        "configure", help="save selected local repository paths"
    )
    configure_parser.add_argument("paths", nargs="+")
    subparsers.add_parser("show-config", help="print current configuration")
    subparsers.add_parser(
        "suggest-config",
        help="print repository paths configured for apply-pr-reviews",
    )
    collect_parser = subparsers.add_parser(
        "collect", help="collect review requests as JSON (default)"
    )
    collect_parser.add_argument(
        "--pr",
        action="append",
        default=[],
        metavar="OWNER/REPO#NUMBER",
        help="collect only these pull requests, requested or not",
    )
    return parser


def main(argv=None):
    parser = create_parser()
    args = parser.parse_args(argv)
    command = args.command or "collect"
    try:
        if command == "configure":
            config = build_config(args.paths)
            save_config(args.config, config)
            result = {
                "config": str(args.config),
                "repositories": config["repositories"],
            }
        elif command == "show-config":
            result = load_config(args.config)
        elif command == "suggest-config":
            result = {"paths": suggest_paths()}
        else:
            result = collect_from_config(
                args.config, named=getattr(args, "pr", None)
            )
    except CollectError as error:
        parser.exit(2, f"error: {error}\n")

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
