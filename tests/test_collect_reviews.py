import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "collect_reviews.py"
)
SPEC = importlib.util.spec_from_file_location("collect_reviews", SCRIPT_PATH)
collect_reviews = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collect_reviews)


class RecordingRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.commands = []

    def __call__(self, command, *, cwd=None):
        self.commands.append((command, cwd))
        if not self.responses:
            raise AssertionError(f"Unexpected command: {command}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class RemoteParsingTests(unittest.TestCase):
    def test_parses_supported_github_origin_formats(self):
        cases = {
            "git@github.com:acme/widgets.git": "acme/widgets",
            "https://github.com/acme/widgets.git": "acme/widgets",
            "ssh://git@github.com/acme/widgets.git": "acme/widgets",
            "https://github.com/acme/widgets": "acme/widgets",
        }

        for remote, expected in cases.items():
            with self.subTest(remote=remote):
                self.assertEqual(
                    collect_reviews.parse_github_remote(remote), expected
                )

    def test_rejects_non_github_and_malformed_remotes(self):
        for remote in (
            "git@gitlab.com:acme/widgets.git",
            "https://example.com/acme/widgets.git",
            "github.com/acme",
            "",
        ):
            with self.subTest(remote=remote):
                with self.assertRaises(collect_reviews.ConfigurationError):
                    collect_reviews.parse_github_remote(remote)


class ConfigTests(unittest.TestCase):
    def test_default_config_path_uses_xdg_config_home(self):
        path = collect_reviews.default_config_path(
            {"XDG_CONFIG_HOME": "/tmp/custom-config"}, platform="linux"
        )
        self.assertEqual(
            path,
            Path("/tmp/custom-config/apply-pr-reviews/repositories.json"),
        )

    def test_build_config_resolves_paths_derives_remotes_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory, "first")
            second = Path(directory, "second")
            first.mkdir()
            second.mkdir()
            runner = RecordingRunner(
                [
                    "git@github.com:acme/first.git\n",
                    "https://github.com/acme/second.git\n",
                    "git@github.com:acme/first.git\n",
                ]
            )

            config = collect_reviews.build_config(
                [str(first), str(second), str(first)], runner=runner
            )

        self.assertEqual(
            config,
            {
                "version": 1,
                "repositories": [
                    {"path": str(first.resolve()), "repository": "acme/first"},
                    {
                        "path": str(second.resolve()),
                        "repository": "acme/second",
                    },
                ],
            },
        )

    def test_save_and_load_config_round_trip(self):
        config = {
            "version": 1,
            "repositories": [
                {"path": "/tmp/project", "repository": "acme/project"}
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "nested", "repositories.json")
            collect_reviews.save_config(path, config)
            loaded = collect_reviews.load_config(path)
            file_mode = path.stat().st_mode & 0o777

        self.assertEqual(loaded, config)
        self.assertEqual(file_mode, 0o600)

    def test_load_config_rejects_missing_or_invalid_config(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory, "missing.json")
            with self.assertRaises(collect_reviews.ConfigurationError):
                collect_reviews.load_config(missing)

            invalid = Path(directory, "invalid.json")
            invalid.write_text(
                json.dumps({"version": 2, "repositories": []}),
                encoding="utf-8",
            )
            with self.assertRaises(collect_reviews.ConfigurationError):
                collect_reviews.load_config(invalid)


class CollectionTests(unittest.TestCase):
    def test_list_open_prs_is_read_only_and_scoped_to_current_user(self):
        runner = RecordingRunner(
            [
                json.dumps(
                    [
                        {
                            "number": 17,
                            "title": "Improve parser",
                            "url": "https://github.com/acme/widgets/pull/17",
                        }
                    ]
                )
            ]
        )

        result = collect_reviews.list_open_prs("acme/widgets", runner=runner)

        self.assertEqual(result[0]["number"], 17)
        command, cwd = runner.commands[0]
        self.assertEqual(command[:3], ["gh", "pr", "list"])
        self.assertIn("--author", command)
        self.assertIn("@me", command)
        self.assertIn("--state", command)
        self.assertIn("open", command)
        self.assertIn("--repo", command)
        self.assertIn("acme/widgets", command)
        self.assertIsNone(cwd)

    def test_review_threads_are_paginated(self):
        first_page = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [{"id": "thread-1"}],
                            "pageInfo": {
                                "hasNextPage": True,
                                "endCursor": "cursor-1",
                            },
                        }
                    }
                }
            }
        }
        second_page = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [{"id": "thread-2"}],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        }
                    }
                }
            }
        }
        runner = RecordingRunner(
            [json.dumps(first_page), json.dumps(second_page)]
        )

        result = collect_reviews.fetch_review_threads(
            "acme/widgets", 17, runner=runner
        )

        self.assertEqual(
            [thread["id"] for thread in result], ["thread-1", "thread-2"]
        )
        first_command = runner.commands[0][0]
        second_command = runner.commands[1][0]
        self.assertNotIn("cursor=cursor-1", first_command)
        self.assertIn("cursor=cursor-1", second_command)

    def test_collect_repository_combines_all_review_surfaces(self):
        pr = {
            "number": 17,
            "title": "Improve parser",
            "url": "https://github.com/acme/widgets/pull/17",
        }
        runner = RecordingRunner(
            [
                json.dumps([pr]),
                json.dumps(
                    {
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "reviewThreads": {
                                        "nodes": [{"id": "thread-1"}],
                                        "pageInfo": {
                                            "hasNextPage": False,
                                            "endCursor": None,
                                        },
                                    }
                                }
                            }
                        }
                    }
                ),
                json.dumps([{"id": 301, "body": "Inline comment"}]),
                json.dumps([{"id": 101, "state": "CHANGES_REQUESTED"}]),
                json.dumps([{"id": 201, "body": "General comment"}]),
                json.dumps(
                    {
                        "headRefName": "feature/parser",
                        "headRefOid": "abc123",
                        "isCrossRepository": False,
                        "reviewDecision": "CHANGES_REQUESTED",
                    }
                ),
            ]
        )

        result = collect_reviews.collect_repository(
            {"path": "/tmp/widgets", "repository": "acme/widgets"},
            runner=runner,
        )

        collected_pr = result["pull_requests"][0]
        self.assertEqual(collected_pr["review_threads"][0]["id"], "thread-1")
        self.assertEqual(collected_pr["inline_comments"][0]["id"], 301)
        self.assertEqual(collected_pr["reviews"][0]["id"], 101)
        self.assertEqual(collected_pr["issue_comments"][0]["id"], 201)
        self.assertEqual(collected_pr["details"]["headRefOid"], "abc123")


class CliTests(unittest.TestCase):
    def test_collect_requires_existing_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory, "repositories.json")
            with self.assertRaises(collect_reviews.ConfigurationError):
                collect_reviews.collect_from_config(missing)

    def test_collection_reports_one_repository_error_and_continues(self):
        config = {
            "version": 1,
            "repositories": [
                {"path": "/tmp/first", "repository": "acme/first"},
                {"path": "/tmp/second", "repository": "acme/second"},
            ],
        }
        runner = RecordingRunner(
            [
                collect_reviews.ExternalCommandError("first is inaccessible"),
                "[]",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "repositories.json")
            collect_reviews.save_config(path, config)
            result = collect_reviews.collect_from_config(path, runner=runner)

        first, second = result["repositories"]
        self.assertEqual(first["repository"], "acme/first")
        self.assertEqual(first["error"], "first is inaccessible")
        self.assertEqual(second["repository"], "acme/second")
        self.assertEqual(second["pull_requests"], [])


if __name__ == "__main__":
    unittest.main()
