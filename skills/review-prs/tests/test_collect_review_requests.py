import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "collect_review_requests.py"
)
SPEC = importlib.util.spec_from_file_location(
    "collect_review_requests", SCRIPT_PATH
)
collect = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collect)


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


def thread(*logins, resolved=False):
    return {
        "id": "thread",
        "isResolved": resolved,
        "comments": {
            "nodes": [{"author": {"login": login}} for login in logins]
        },
    }


def review(review_id, login, body, commit, submitted_at):
    return {
        "id": review_id,
        "user": {"login": login},
        "body": body,
        "commit_id": commit,
        "submitted_at": submitted_at,
        "state": "COMMENTED",
    }


def inline_comment(review_id, in_reply_to=None):
    comment = {"pull_request_review_id": review_id}
    if in_reply_to is not None:
        comment["in_reply_to_id"] = in_reply_to
    return comment


def threads_page(nodes):
    return json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": nodes,
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        }
                    }
                }
            }
        }
    )


class SharedHelperTests(unittest.TestCase):
    def test_parses_supported_github_origin_formats(self):
        for remote in (
            "git@github.com:acme/widgets.git",
            "https://github.com/acme/widgets.git",
            "ssh://git@github.com/acme/widgets.git",
            "https://github.com/acme/widgets",
        ):
            with self.subTest(remote=remote):
                self.assertEqual(
                    collect.parse_github_remote(remote), "acme/widgets"
                )

    def test_rejects_non_github_remotes(self):
        with self.assertRaises(collect.ConfigurationError):
            collect.parse_github_remote("git@gitlab.com:acme/widgets.git")

    def test_default_config_path_uses_its_own_directory(self):
        path = collect.default_config_path(
            environ={"XDG_CONFIG_HOME": "/tmp/config"}, platform="linux"
        )

        self.assertEqual(
            path, Path("/tmp/config/review-prs/repositories.json")
        )

    def test_build_config_derives_repository_from_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = RecordingRunner(["git@github.com:acme/widgets.git\n"])

            config = collect.build_config([directory], runner=runner)

        self.assertEqual(config["repositories"][0]["repository"], "acme/widgets")

    def test_save_and_load_config_round_trip(self):
        config = {
            "version": 1,
            "repositories": [
                {"path": "/tmp/widgets", "repository": "acme/widgets"}
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "repositories.json")
            collect.save_config(path, config)

            self.assertEqual(collect.load_config(path), config)

    def test_fetch_viewer_login_strips_output(self):
        runner = RecordingRunner(["Dawid\n"])

        self.assertEqual(collect.fetch_viewer_login(runner=runner), "Dawid")
        self.assertEqual(
            runner.commands[0][0], ["gh", "api", "user", "--jq", ".login"]
        )


class SuggestedConfigTests(unittest.TestCase):
    def test_suggest_paths_reads_apply_pr_reviews_config(self):
        with tempfile.TemporaryDirectory() as directory:
            environ = {"XDG_CONFIG_HOME": directory}
            sibling = collect.sibling_config_path(
                "apply-pr-reviews", environ=environ, platform="linux"
            )
            collect.save_config(
                sibling,
                {
                    "version": 1,
                    "repositories": [
                        {"path": "/repos/shop", "repository": "acme/shop"}
                    ],
                },
            )

            self.assertEqual(
                collect.suggest_paths(environ=environ, platform="linux"),
                ["/repos/shop"],
            )

    def test_suggest_paths_is_empty_without_a_sibling_config(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                collect.suggest_paths(
                    environ={"XDG_CONFIG_HOME": directory}, platform="linux"
                ),
                [],
            )


class ReviewRequestTests(unittest.TestCase):
    def test_list_review_requests_searches_for_the_viewer_and_skips_drafts(
        self,
    ):
        runner = RecordingRunner(["[]"])

        collect.list_review_requests("acme/widgets", runner=runner)

        command = runner.commands[0][0]
        self.assertEqual(command[:3], ["gh", "pr", "list"])
        search = command[command.index("--search") + 1]
        self.assertIn("review-requested:@me", search)
        self.assertIn("-is:draft", search)
        for expected in ("--repo", "acme/widgets", "--state", "open"):
            self.assertIn(expected, command)

    def test_list_review_requests_skips_bot_authors(self):
        requests = [
            {"number": 1, "author": {"login": "app/renovate", "is_bot": True}},
            {"number": 2, "author": {"login": "dependabot[bot]", "is_bot": False}},
            {"number": 3, "author": {"login": "app/github-actions"}},
            {"number": 4, "author": {"login": "ola", "is_bot": False}},
        ]
        runner = RecordingRunner([json.dumps(requests)])

        result = collect.list_review_requests("acme/widgets", runner=runner)

        self.assertEqual([pr["number"] for pr in result], [4])

    def test_ticket_keys_are_unique_and_ordered(self):
        self.assertEqual(
            collect.ticket_keys("feat(SHOP-12): x SHOP-12 OPS-3"),
            ["SHOP-12", "OPS-3"],
        )
        self.assertEqual(collect.ticket_keys("chore: bump eslint"), [])

    def test_ticket_keys_ignore_standard_names(self):
        self.assertEqual(
            collect.ticket_keys("fix: use UTF-8 and SHA-256 for ISO-8601"), []
        )

    def test_pr_ticket_keys_read_lowercase_branches(self):
        self.assertEqual(
            collect.pr_ticket_keys(
                {"title": "feat: export", "headRefName": "feat/shop-300-export"}
            ),
            ["SHOP-300"],
        )

    def test_related_prs_share_a_ticket_key(self):
        pull_request = {
            "number": 11,
            "title": "feat(SHOP-300): part 1",
            "headRefName": "feat/SHOP-300/part-1",
        }
        open_prs = [
            pull_request,
            {
                "number": 12,
                "title": "feat: part 2",
                "headRefName": "feat/SHOP-300/part-2",
            },
            {"number": 13, "title": "fix(OPS-1): x", "headRefName": "fix/x"},
        ]
        merged_prs = [
            {"number": 9, "title": "feat(SHOP-300): part 0", "headRefName": "x"},
            {"number": 8, "title": "fix(OPS-2): y", "headRefName": "y"},
        ]

        self.assertEqual(
            collect.related_prs(pull_request, open_prs, merged_prs),
            [{"number": 12, "state": "open"}, {"number": 9, "state": "merged"}],
        )


class LastReviewTests(unittest.TestCase):
    def test_last_review_skips_reply_only_reviews(self):
        reviews = [
            review(1, "dawid", "Looks off", "c1", "2026-11-20T10:00:00Z"),
            review(2, "dawid", "", "c2", "2026-11-20T11:00:00Z"),
        ]
        comments = [inline_comment(2, in_reply_to=99)]

        result = collect.last_review(reviews, comments, "Dawid")

        self.assertEqual(result["commit"], "c1")

    def test_last_review_takes_the_newest_real_review(self):
        reviews = [
            review(1, "dawid", "First", "c1", "2026-11-20T10:00:00Z"),
            review(3, "dawid", "", "c3", "2026-11-21T12:00:00Z"),
            review(4, "marek", "Other", "c4", "2026-11-22T12:00:00Z"),
        ]
        comments = [inline_comment(3)]

        result = collect.last_review(reviews, comments, "dawid")

        self.assertEqual(
            result,
            {
                "id": 3,
                "commit": "c3",
                "submitted_at": "2026-11-21T12:00:00Z",
                "state": "COMMENTED",
            },
        )

    def test_last_review_counts_a_verdict_without_a_body(self):
        reviews = [
            review(1, "dawid", "Looks off", "c1", "2026-11-20T10:00:00Z"),
            {
                **review(2, "dawid", "", "c2", "2026-11-21T10:00:00Z"),
                "state": "APPROVED",
            },
        ]

        self.assertEqual(
            collect.last_review(reviews, [], "dawid")["commit"], "c2"
        )

    def test_last_review_is_none_without_a_review_by_the_viewer(self):
        reviews = [review(4, "marek", "Other", "c4", "2026-11-22T12:00:00Z")]

        self.assertIsNone(collect.last_review(reviews, [], "dawid"))


class TextSurfaceTests(unittest.TestCase):
    def test_review_bodies_keep_only_reviews_with_text(self):
        reviews = [
            review(1, "marek", "Missing null check in load.ts:10", "c1", "t1"),
            review(2, "dawid", "  ", "c2", "t2"),
        ]

        self.assertEqual(
            collect.review_bodies(reviews),
            [
                {
                    "author": "marek",
                    "state": "COMMENTED",
                    "body": "Missing null check in load.ts:10",
                    "submitted_at": "t1",
                    "commit": "c1",
                }
            ],
        )

    def test_conversation_keeps_author_body_and_link(self):
        comments = [
            {
                "user": {"login": "ola"},
                "body": "Fixed",
                "created_at": "t1",
                "html_url": "https://example.test/c/1",
            }
        ]

        self.assertEqual(
            collect.conversation(comments),
            [
                {
                    "author": "ola",
                    "body": "Fixed",
                    "created_at": "t1",
                    "url": "https://example.test/c/1",
                }
            ],
        )


class ThreadTests(unittest.TestCase):
    def test_review_threads_are_paginated_with_string_cursor(self):
        first = json.loads(threads_page([{"id": "t1"}]))
        first["data"]["repository"]["pullRequest"]["reviewThreads"][
            "pageInfo"
        ] = {"hasNextPage": True, "endCursor": "cursor-1"}
        runner = RecordingRunner(
            [json.dumps(first), threads_page([{"id": "t2"}])]
        )

        result = collect.fetch_review_threads("acme/shop", 7, runner=runner)

        self.assertEqual([item["id"] for item in result], ["t1", "t2"])
        second = runner.commands[1][0]
        self.assertEqual(second[second.index("cursor=cursor-1") - 1], "-f")

    def test_split_threads_by_first_author_and_open_state(self):
        threads = [
            thread("Dawid", "ola"),
            thread("marek", "ola"),
            thread("marek", resolved=True),
        ]

        result = collect.split_threads(threads, "dawid")

        self.assertEqual(len(result["mine"]), 1)
        self.assertEqual(len(result["open_others"]), 1)
        self.assertFalse(result["open_others"][0]["isResolved"])


class CollectionTests(unittest.TestCase):
    def test_collect_repository_combines_review_data(self):
        request = {
            "number": 11,
            "title": "feat(SHOP-300): part 1",
            "headRefName": "feat/SHOP-300/part-1",
            "baseRefName": "main",
        }
        open_prs = [
            request,
            {
                "number": 12,
                "title": "feat(SHOP-300): part 2",
                "headRefName": "feat/SHOP-300/part-2",
            },
        ]
        runner = RecordingRunner(
            [
                json.dumps([request]),
                json.dumps(open_prs),
                "[]",
                threads_page([thread("dawid"), thread("marek")]),
                json.dumps([inline_comment(1)]),
                json.dumps(
                    [review(1, "dawid", "", "c1", "2026-11-20T10:00:00Z")]
                ),
                json.dumps([]),
                json.dumps({"headRefOid": "h1", "baseRefOid": "b1"}),
            ]
        )

        result = collect.collect_repository(
            {"path": "/tmp/shop", "repository": "acme/shop"},
            viewer="dawid",
            runner=runner,
        )

        pull_request = result["pull_requests"][0]
        self.assertEqual(pull_request["ticket_keys"], ["SHOP-300"])
        self.assertEqual(
            pull_request["related_prs"], [{"number": 12, "state": "open"}]
        )
        self.assertEqual(pull_request["review_bodies"], [])
        self.assertEqual(pull_request["conversation"], [])
        self.assertEqual(pull_request["last_review"]["commit"], "c1")
        self.assertEqual(len(pull_request["threads"]["mine"]), 1)
        self.assertEqual(len(pull_request["threads"]["open_others"]), 1)
        self.assertEqual(pull_request["details"]["headRefOid"], "h1")

    def test_one_failing_pr_does_not_stop_the_others(self):
        first = {"number": 1, "title": "a", "headRefName": "a"}
        second = {"number": 2, "title": "b", "headRefName": "b"}
        runner = RecordingRunner(
            [
                json.dumps([first, second]),
                "[]",
                "[]",
                collect.ExternalCommandError("thread query failed"),
                threads_page([]),
                "[]",
                "[]",
                "[]",
                json.dumps({"headRefOid": "h2"}),
            ]
        )

        result = collect.collect_repository(
            {"path": "/tmp/shop", "repository": "acme/shop"},
            viewer="dawid",
            runner=runner,
        )

        broken, working = result["pull_requests"]
        self.assertEqual(broken["error"], "thread query failed")
        self.assertEqual(working["details"]["headRefOid"], "h2")

    def test_repository_without_requests_makes_one_call(self):
        runner = RecordingRunner(["[]"])

        result = collect.collect_repository(
            {"path": "/tmp/shop", "repository": "acme/shop"},
            viewer="dawid",
            runner=runner,
        )

        self.assertEqual(result["pull_requests"], [])
        self.assertEqual(len(runner.commands), 1)

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
                collect.ExternalCommandError("first is inaccessible"),
                "[]",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "repositories.json")
            collect.save_config(path, config)
            result = collect.collect_from_config(path, runner=runner)

        self.assertEqual(result["viewer"], "dawid")
        first, second = result["repositories"]
        self.assertEqual(first["error"], "first is inaccessible")
        self.assertEqual(second["pull_requests"], [])


class NamedPrTests(unittest.TestCase):
    def test_parse_pr_ref(self):
        self.assertEqual(collect.parse_pr_ref("acme/shop#12"), ("acme/shop", 12))
        for bad in ("acme/shop", "shop#12", "acme/shop#x"):
            with self.subTest(ref=bad):
                with self.assertRaises(collect.ConfigurationError):
                    collect.parse_pr_ref(bad)

    def test_collect_named_prs_uses_the_same_pipeline(self):
        config = {
            "version": 1,
            "repositories": [
                {"path": "/tmp/shop", "repository": "acme/shop"},
                {"path": "/tmp/other", "repository": "acme/other"},
            ],
        }
        runner = RecordingRunner(
            [
                "dawid\n",
                json.dumps({"number": 7, "title": "fix(SHOP-1): x", "headRefName": "x"}),
                "[]",
                "[]",
                threads_page([]),
                "[]",
                "[]",
                "[]",
                json.dumps({"headRefOid": "h7"}),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "repositories.json")
            collect.save_config(path, config)
            result = collect.collect_from_config(
                path, runner=runner, named=["acme/shop#7"]
            )

        self.assertEqual(
            [entry["repository"] for entry in result["repositories"]],
            ["acme/shop"],
        )
        pull_request = result["repositories"][0]["pull_requests"][0]
        self.assertEqual(pull_request["number"], 7)
        self.assertEqual(pull_request["ticket_keys"], ["SHOP-1"])
        view = runner.commands[1][0]
        self.assertEqual(view[:4], ["gh", "pr", "view", "7"])

    def test_named_pr_outside_the_configuration_is_an_error(self):
        config = {
            "version": 1,
            "repositories": [{"path": "/tmp/shop", "repository": "acme/shop"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "repositories.json")
            collect.save_config(path, config)
            with self.assertRaises(collect.ConfigurationError):
                collect.collect_from_config(
                    path,
                    runner=RecordingRunner(["dawid\n"]),
                    named=["acme/elsewhere#1"],
                )


if __name__ == "__main__":
    unittest.main()
