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
            "headRefName": "feature/parser",
            "baseRefName": "main",
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
                "[]",
            ]
        )

        result = collect_reviews.collect_repository(
            {"path": "/tmp/widgets", "repository": "acme/widgets"},
            viewer="dawid",
            runner=runner,
        )

        collected_pr = result["pull_requests"][0]
        self.assertEqual(collected_pr["review_threads"][0]["id"], "thread-1")
        self.assertEqual(collected_pr["reviews"][0]["id"], 101)
        self.assertEqual(collected_pr["issue_comments"][0]["id"], 201)
        self.assertEqual(collected_pr["details"]["headRefOid"], "abc123")
        self.assertEqual(
            collected_pr["stack"],
            {"parent": None, "merged_parent": None, "shared_head": False},
        )
        self.assertIn("awaiting_reviewer", collected_pr["review_threads"][0])
        self.assertNotIn("inline_comments", collected_pr)


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
                "dawid\n",
                collect_reviews.ExternalCommandError("first is inaccessible"),
                "[]",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "repositories.json")
            collect_reviews.save_config(path, config)
            result = collect_reviews.collect_from_config(path, runner=runner)

        self.assertEqual(result["version"], 2)
        self.assertEqual(result["viewer"], "dawid")
        first, second = result["repositories"]
        self.assertEqual(first["repository"], "acme/first")
        self.assertEqual(first["error"], "first is inaccessible")
        self.assertEqual(second["repository"], "acme/second")
        self.assertEqual(second["pull_requests"], [])


def thread_with_authors(*logins):
    return {
        "id": "thread",
        "comments": {
            "nodes": [{"author": {"login": login}} for login in logins]
        },
    }


def open_pr(number, head, base, commits=(), base_oid="base-tip"):
    return {
        "number": number,
        "headRefName": head,
        "baseRefName": base,
        "details": {
            "baseRefOid": base_oid,
            "commits": [{"oid": oid} for oid in commits],
        },
    }


class ViewerAndMergeStateTests(unittest.TestCase):
    def test_fetch_viewer_login_strips_output(self):
        runner = RecordingRunner(["Dawid\n"])

        login = collect_reviews.fetch_viewer_login(runner=runner)

        self.assertEqual(login, "Dawid")
        self.assertEqual(
            runner.commands[0][0], ["gh", "api", "user", "--jq", ".login"]
        )

    def test_pr_details_request_merge_state(self):
        fields = collect_reviews.PR_DETAIL_FIELDS.split(",")

        self.assertIn("mergeable", fields)
        self.assertIn("mergeStateStatus", fields)
        self.assertNotIn("files", fields)

    def test_list_merged_prs_is_scoped_to_current_user(self):
        runner = RecordingRunner(["[]"])

        collect_reviews.list_merged_prs("acme/widgets", runner=runner)

        command = runner.commands[0][0]
        self.assertEqual(command[:3], ["gh", "pr", "list"])
        for expected in ("--state", "merged", "--author", "@me", "--repo", "acme/widgets"):
            self.assertIn(expected, command)

    def test_thread_awaits_reviewer_only_when_viewer_wrote_last(self):
        cases = (
            (thread_with_authors("marek", "dawid"), True),
            (thread_with_authors("marek", "dawid", "marek"), False),
            ({"id": "thread", "comments": {"nodes": []}}, False),
            ({"id": "thread"}, False),
        )

        for thread, expected in cases:
            with self.subTest(thread=thread):
                marked = collect_reviews.mark_awaiting_reviewer(
                    [thread], "Dawid"
                )
                self.assertIs(marked[0]["awaiting_reviewer"], expected)
                self.assertNotIn("awaiting_reviewer", thread)


class StackTests(unittest.TestCase):
    def test_stacks_order_parents_before_children(self):
        pull_requests = [
            open_pr(13, "b13", "b12"),
            open_pr(11, "b11", "main"),
            open_pr(12, "b12", "b11"),
        ]

        result = collect_reviews.annotate_stacks(pull_requests, [])

        self.assertEqual([pr["number"] for pr in result], [11, 12, 13])
        self.assertEqual(
            {pr["number"]: pr["stack"]["parent"] for pr in result},
            {11: None, 12: 11, 13: 12},
        )

    def test_base_without_open_pr_has_no_parent(self):
        result = collect_reviews.annotate_stacks(
            [open_pr(11, "b11", "someone-else")], []
        )

        self.assertEqual(
            result[0]["stack"],
            {"parent": None, "merged_parent": None, "shared_head": False},
        )

    def test_merged_parent_found_by_base_branch(self):
        merged = [
            {
                "number": 10,
                "headRefName": "b10",
                "headRefOid": "m10",
                "baseRefName": "main",
            }
        ]

        result = collect_reviews.annotate_stacks(
            [open_pr(11, "b11", "b10", base_oid="m10")], merged
        )

        self.assertEqual(
            result[0]["stack"]["merged_parent"],
            {"number": 10, "head_oid": "m10", "base_branch": "main"},
        )

    def test_long_lived_base_branch_is_not_a_merged_parent(self):
        promotion = {
            "number": 1706,
            "headRefName": "test",
            "headRefOid": "test-tip",
            "baseRefName": "beta",
        }
        feature = {
            "number": 1700,
            "headRefName": "feat/z",
            "headRefOid": "z1",
            "baseRefName": "test",
        }

        result = collect_reviews.annotate_stacks(
            [open_pr(11, "b11", "test", base_oid="test-tip")],
            [promotion, feature],
        )

        self.assertIsNone(result[0]["stack"]["merged_parent"])

    def test_base_branch_moved_after_merge_is_not_a_merged_parent(self):
        merged = [
            {
                "number": 10,
                "headRefName": "b10",
                "headRefOid": "m10",
                "baseRefName": "main",
            }
        ]

        result = collect_reviews.annotate_stacks(
            [open_pr(11, "b11", "b10", base_oid="newer")], merged
        )

        self.assertIsNone(result[0]["stack"]["merged_parent"])

    def test_merged_parent_found_by_commits_after_retarget(self):
        merged = [
            {
                "number": 10,
                "headRefName": "b10",
                "headRefOid": "m10",
                "baseRefName": "main",
            }
        ]

        result = collect_reviews.annotate_stacks(
            [open_pr(11, "b11", "main", commits=("m10", "c11"))], merged
        )

        self.assertEqual(result[0]["stack"]["merged_parent"]["number"], 10)

    def test_commit_match_requires_the_same_base(self):
        merged = [
            {
                "number": 10,
                "headRefName": "b10",
                "headRefOid": "m10",
                "baseRefName": "test",
            }
        ]

        result = collect_reviews.annotate_stacks(
            [open_pr(11, "hotfix", "beta", commits=("m10", "c11"))], merged
        )

        self.assertIsNone(result[0]["stack"]["merged_parent"])

    def test_commit_match_prefers_the_nearest_merged_ancestor(self):
        merged = [
            {
                "number": 9,
                "headRefName": "b9",
                "headRefOid": "m9",
                "baseRefName": "main",
            },
            {
                "number": 10,
                "headRefName": "b10",
                "headRefOid": "m10",
                "baseRefName": "main",
            },
        ]

        result = collect_reviews.annotate_stacks(
            [open_pr(11, "b11", "main", commits=("m9", "m10", "c11"))], merged
        )

        self.assertEqual(result[0]["stack"]["merged_parent"]["number"], 10)

    def test_head_that_other_prs_merge_into_is_shared(self):
        merged = [
            {
                "number": 1700,
                "headRefName": "feat/z",
                "headRefOid": "z1",
                "baseRefName": "test",
            }
        ]

        result = collect_reviews.annotate_stacks(
            [open_pr(1706, "test", "beta"), open_pr(11, "b11", "test")],
            merged,
        )

        self.assertEqual(
            {pr["number"]: pr["stack"]["shared_head"] for pr in result},
            {1706: True, 11: False},
        )

    def test_stack_cycle_is_an_error(self):
        with self.assertRaises(collect_reviews.CollectReviewsError):
            collect_reviews.annotate_stacks(
                [open_pr(1, "a", "b"), open_pr(2, "b", "a")], []
            )


if __name__ == "__main__":
    unittest.main()
