#!/usr/bin/env python3
"""Configure local repositories and collect GitHub PR review data read-only."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


CONFIG_VERSION = 1
CONFIG_DIRECTORY = "apply-pr-reviews"
CONFIG_FILENAME = "repositories.json"
PR_LIST_FIELDS = (
    "number,title,url,headRefName,headRefOid,headRepository,"
    "headRepositoryOwner,baseRefName,isCrossRepository,isDraft,updatedAt"
)
PR_DETAIL_FIELDS = (
    "number,title,url,body,headRefName,headRefOid,headRepository,"
    "headRepositoryOwner,baseRefName,baseRefOid,isCrossRepository,isDraft,"
    "reviewDecision,statusCheckRollup,files,commits"
)

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
          startLine
          originalStartLine
          diffSide
          startDiffSide
          comments(first: 100) {
            nodes {
              id
              databaseId
              author { login }
              body
              createdAt
              updatedAt
              url
              diffHunk
              commit { oid }
              originalCommit { oid }
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


class CollectReviewsError(RuntimeError):
    """Base error for expected command-line failures."""


class ConfigurationError(CollectReviewsError):
    """Raised when repository configuration is missing or invalid."""


class ExternalCommandError(CollectReviewsError):
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


def default_config_path(environ=None, platform=None):
    """Return a per-user config path without writing anything."""
    env = os.environ if environ is None else environ
    current_platform = sys.platform if platform is None else platform
    if current_platform.startswith("win") and env.get("APPDATA"):
        base = Path(env["APPDATA"])
    elif env.get("XDG_CONFIG_HOME"):
        base = Path(env["XDG_CONFIG_HOME"])
    else:
        base = Path.home() / ".config"
    return base / CONFIG_DIRECTORY / CONFIG_FILENAME


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
        repository = parse_github_remote(remote)
        repositories.append({"path": path_key, "repository": repository})
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


def list_open_prs(repository, *, runner=run_command):
    """List open PRs authored by the authenticated GitHub user."""
    command = [
        "gh",
        "pr",
        "list",
        "--repo",
        repository,
        "--author",
        "@me",
        "--state",
        "open",
        "--limit",
        "1000",
        "--json",
        PR_LIST_FIELDS,
    ]
    result = run_json(command, runner=runner)
    if not isinstance(result, list):
        raise ExternalCommandError(
            f"Unexpected PR list response for {repository}."
        )
    return result


def _repository_parts(repository):
    try:
        owner, name = repository.split("/", 1)
    except ValueError as error:
        raise ConfigurationError(
            f"Invalid GitHub repository name: {repository}"
        ) from error
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
            "-F",
            f"owner={owner}",
            "-F",
            f"repo={name}",
            "-F",
            f"number={number}",
        ]
        if cursor is not None:
            command.extend(["-F", f"cursor={cursor}"])

        response = run_json(command, runner=runner)
        try:
            pull_request = response["data"]["repository"]["pullRequest"]
            page = pull_request["reviewThreads"]
            nodes = page["nodes"]
            page_info = page["pageInfo"]
        except (KeyError, TypeError) as error:
            raise ExternalCommandError(
                f"Unexpected review thread response for {repository}#{number}."
            ) from error
        if pull_request is None:
            raise ExternalCommandError(
                f"Pull request not found: {repository}#{number}."
            )
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


def fetch_reviews(repository, number, *, runner=run_command):
    """Fetch submitted pull-request reviews."""
    command = [
        "gh",
        "api",
        "--paginate",
        "--slurp",
        f"repos/{repository}/pulls/{number}/reviews",
    ]
    value = run_json(command, runner=runner)
    return _flatten_pages(value, context=f"{repository}#{number} reviews")


def fetch_inline_comments(repository, number, *, runner=run_command):
    """Fetch every inline review comment, including long thread replies."""
    command = [
        "gh",
        "api",
        "--paginate",
        "--slurp",
        f"repos/{repository}/pulls/{number}/comments",
    ]
    value = run_json(command, runner=runner)
    return _flatten_pages(
        value, context=f"{repository}#{number} inline comments"
    )


def fetch_issue_comments(repository, number, *, runner=run_command):
    """Fetch pull-request conversation comments."""
    command = [
        "gh",
        "api",
        "--paginate",
        "--slurp",
        f"repos/{repository}/issues/{number}/comments",
    ]
    value = run_json(command, runner=runner)
    return _flatten_pages(value, context=f"{repository}#{number} comments")


def fetch_pr_details(repository, number, *, runner=run_command):
    """Fetch current branch, commit, file, and check metadata for a PR."""
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


def collect_repository(entry, *, runner=run_command):
    """Collect every review surface for one configured repository."""
    repository = entry["repository"]
    pull_requests = []
    for pull_request in list_open_prs(repository, runner=runner):
        number = pull_request["number"]
        pull_requests.append(
            {
                **pull_request,
                "review_threads": fetch_review_threads(
                    repository, number, runner=runner
                ),
                "inline_comments": fetch_inline_comments(
                    repository, number, runner=runner
                ),
                "reviews": fetch_reviews(repository, number, runner=runner),
                "issue_comments": fetch_issue_comments(
                    repository, number, runner=runner
                ),
                "details": fetch_pr_details(
                    repository, number, runner=runner
                ),
            }
        )
    return {
        "path": entry["path"],
        "repository": repository,
        "pull_requests": pull_requests,
    }


def collect_from_config(path, *, runner=run_command):
    """Collect review data for every configured repository."""
    config = load_config(path)
    repositories = []
    for entry in config["repositories"]:
        try:
            repositories.append(collect_repository(entry, runner=runner))
        except CollectReviewsError as error:
            repositories.append(
                {
                    "path": entry["path"],
                    "repository": entry["repository"],
                    "pull_requests": [],
                    "error": str(error),
                }
            )
    return {
        "version": 1,
        "repositories": repositories,
    }


def create_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Configure local GitHub repositories and collect open PR review "
            "data without changing repositories or GitHub."
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
        "collect", help="collect open PR reviews as JSON (default)"
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
        else:
            result = collect_from_config(args.config)
    except CollectReviewsError as error:
        parser.exit(2, f"error: {error}\n")

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
