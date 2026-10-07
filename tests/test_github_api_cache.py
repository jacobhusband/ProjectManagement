"""GitHub lookups survive an office sharing one IP address's anonymous API allowance.

GitHub lets an anonymous client make 60 API requests an hour per IP address. Release
lookups are therefore kept on disk, reused while fresh, and used as a fallback when
GitHub refuses or cannot be reached. With nothing saved, a refusal says it was a rate
limit instead of claiming that no release was published.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import main as main_module
from main import Api, GitHubRateLimitError

LATEST_URL = f"{main_module.GITHUB_API_BASE}/repos/jacobhusband/ProjectManagement/releases/latest"
PLUGIN_URL = f"{main_module.GITHUB_API_BASE}/repos/jacobhusband/ElectricalCommands/releases/latest"


class FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None, text=""):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} Client Error")


def rate_limited(reset=None):
    headers = {"X-RateLimit-Remaining": "0"}
    if reset is not None:
        headers["X-RateLimit-Reset"] = str(reset)
    return FakeResponse(
        {"message": "API rate limit exceeded"}, status_code=403, headers=headers,
        text='{"message":"API rate limit exceeded for 203.0.113.7."}',
    )


def release(tag="v2.1.1"):
    return {
        "tag_name": tag,
        "body": "notes",
        "html_url": f"https://github.com/example/releases/tag/{tag}",
        "assets": [{
            "name": main_module.APP_INSTALLER_NAME,
            "browser_download_url": f"https://github.com/jacobhusband/ProjectManagement/releases/download/{tag}/x.exe",
            "digest": "sha256:abc",
        }],
    }


class GitHubApiCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acies-gh-cache-")
        self.addCleanup(self.temp.cleanup)
        self.cache_file = Path(self.temp.name) / "github_api_cache.json"
        patcher = patch.object(main_module, "GITHUB_API_CACHE_FILE", str(self.cache_file))
        patcher.start()
        self.addCleanup(patcher.stop)

        self.api = Api.__new__(Api)
        self.api.app_update_repo = "jacobhusband/ProjectManagement"
        self.api.github_repo = "jacobhusband/ElectricalCommands"
        self.api.app_installer_name = main_module.APP_INSTALLER_NAME
        self.api.app_version = "2.1.0"
        self.api.release_tag = None
        self.api.app_plugins_folder = self.temp.name

    def get(self, *responses):
        """Patches requests.get to answer with each response in turn."""
        return patch.object(main_module.requests, "get", side_effect=list(responses))

    def save(self, url, payload, age_seconds):
        main_module._remember_github_api_answer(url, payload, time.time() - age_seconds)

    # --- the cache itself ---

    def test_a_fresh_answer_is_reused_without_asking_github_again(self):
        with self.get(FakeResponse(release())) as get:
            first = self.api._github_api_json(LATEST_URL)
            second = self.api._github_api_json(LATEST_URL)

        self.assertEqual(first, second)
        self.assertEqual(1, get.call_count)

    def test_an_answer_older_than_the_fresh_window_is_asked_for_again(self):
        self.save(LATEST_URL, release("v2.0.0"), age_seconds=main_module.GITHUB_API_CACHE_FRESH_SECONDS + 60)

        with self.get(FakeResponse(release("v2.1.1"))) as get:
            payload = self.api._github_api_json(LATEST_URL)

        self.assertEqual("v2.1.1", payload["tag_name"])
        self.assertEqual(1, get.call_count)

    def test_max_age_zero_always_asks_github(self):
        self.save(LATEST_URL, release("v2.0.0"), age_seconds=5)

        with self.get(FakeResponse(release("v2.1.1"))) as get:
            payload = self.api._github_api_json(LATEST_URL, max_age=0)

        self.assertEqual("v2.1.1", payload["tag_name"])
        self.assertEqual(1, get.call_count)

    def test_a_saved_answer_covers_for_a_rate_limited_github(self):
        self.save(LATEST_URL, release("v2.0.0"), age_seconds=3 * 3600)

        with self.get(rate_limited()):
            payload = self.api._github_api_json(LATEST_URL)

        self.assertEqual("v2.0.0", payload["tag_name"])

    def test_a_saved_answer_covers_for_an_unreachable_github(self):
        self.save(LATEST_URL, release("v2.0.0"), age_seconds=3 * 3600)

        with patch.object(main_module.requests, "get", side_effect=ConnectionError("offline")):
            payload = self.api._github_api_json(LATEST_URL)

        self.assertEqual("v2.0.0", payload["tag_name"])

    def test_a_saved_empty_list_still_counts_as_an_answer(self):
        self.save(LATEST_URL, [], age_seconds=5)

        with self.get() as get:
            self.assertEqual([], self.api._github_api_json(LATEST_URL))
        get.assert_not_called()

    def test_with_nothing_saved_a_rate_limit_is_reported_as_one(self):
        reset = int(time.time()) + 20 * 60

        with self.get(rate_limited(reset)):
            with self.assertRaises(GitHubRateLimitError) as caught:
                self.api._github_api_json(LATEST_URL)

        message = str(caught.exception)
        self.assertIn("limiting", message)
        self.assertIn("Try again after", message)

    def test_a_forbidden_response_that_is_not_a_rate_limit_is_an_ordinary_error(self):
        forbidden = FakeResponse({"message": "Resource not accessible"}, status_code=403,
                                 headers={"X-RateLimit-Remaining": "41"}, text="forbidden")

        with self.get(forbidden):
            with self.assertRaises(RuntimeError):
                self.api._github_api_json(LATEST_URL)

    def test_not_found_is_none_and_is_not_saved(self):
        with self.get(FakeResponse(None, status_code=404)):
            self.assertIsNone(self.api._github_api_json(LATEST_URL))

        self.assertFalse(self.cache_file.exists())

    def test_a_cache_that_cannot_be_written_never_breaks_a_lookup(self):
        self.cache_file.mkdir()  # a folder where the file should go

        with self.get(FakeResponse(release())):
            self.assertEqual("v2.1.1", self.api._github_api_json(LATEST_URL)["tag_name"])

    def test_a_corrupt_cache_file_is_treated_as_empty(self):
        self.cache_file.write_text("{not json", encoding="utf-8")

        with self.get(FakeResponse(release())):
            self.assertEqual("v2.1.1", self.api._github_api_json(LATEST_URL)["tag_name"])

        self.assertEqual("v2.1.1", json.loads(self.cache_file.read_text("utf-8"))["entries"][LATEST_URL]["payload"]["tag_name"])

    def test_the_cache_keeps_only_the_newest_entries(self):
        for index in range(main_module.GITHUB_API_CACHE_MAX_ENTRIES + 6):
            self.save(f"https://api.github.com/x/{index}", {"n": index}, age_seconds=1000 - index)

        entries = json.loads(self.cache_file.read_text("utf-8"))["entries"]

        self.assertEqual(main_module.GITHUB_API_CACHE_MAX_ENTRIES, len(entries))
        self.assertIn(f"https://api.github.com/x/{main_module.GITHUB_API_CACHE_MAX_ENTRIES + 5}", entries)
        self.assertNotIn("https://api.github.com/x/0", entries)

    # --- what the app reports ---

    def test_update_check_under_a_rate_limit_says_so_and_asks_github_only_once(self):
        with self.get(rate_limited(), rate_limited()) as get:
            result = self.api.get_app_update_status()

        self.assertEqual("error", result["status"])
        self.assertTrue(result["rateLimited"])
        self.assertIn("limiting", result["message"])
        self.assertNotIn("No published releases", result["message"])
        self.assertEqual(1, get.call_count)

    def test_update_check_without_a_rate_limit_is_not_flagged_as_one(self):
        with self.get(FakeResponse(None, status_code=404), FakeResponse(None, status_code=404)):
            result = self.api.get_app_update_status()

        self.assertEqual("error", result["status"])
        self.assertFalse(result["rateLimited"])
        self.assertIn("No published releases", result["message"])

    def test_update_check_still_works_from_a_saved_answer_when_rate_limited(self):
        self.save(LATEST_URL, release("v2.2.0"), age_seconds=3 * 3600)

        with self.get(rate_limited()):
            result = self.api.get_app_update_status()

        self.assertEqual("success", result["status"])
        self.assertTrue(result["update_available"])
        self.assertEqual("2.2.0", result["latest_version"])

    def test_a_manual_update_check_asks_github_even_when_the_saved_answer_is_fresh(self):
        self.save(LATEST_URL, release("v2.1.0"), age_seconds=5)

        with self.get(FakeResponse(release("v2.3.0"))) as get:
            result = self.api.get_app_update_status(force=True)

        self.assertEqual("2.3.0", result["latest_version"])
        self.assertEqual(1, get.call_count)

    def test_the_automatic_update_check_does_not_spend_a_request_while_the_answer_is_fresh(self):
        self.save(LATEST_URL, release("v2.1.0"), age_seconds=5)

        with self.get() as get:
            result = self.api.get_app_update_status()

        self.assertEqual("success", result["status"])
        get.assert_not_called()

    def test_plugin_list_under_a_rate_limit_carries_a_notice_instead_of_silence(self):
        with self.get(rate_limited()):
            result = self.api.get_bundle_statuses()

        self.assertEqual("success", result["status"])
        self.assertIn("limiting", result["notice"])
        self.assertTrue(result["data"])  # the known plugin catalog is still listed

    def test_plugin_list_has_no_notice_when_github_answers(self):
        plugin_release = {
            "tag_name": "v0.2.1",
            "assets": [{"name": "ElectricalCommands.CleanCADCommands-v0.2.1.zip",
                        "browser_download_url": "https://github.com/x/clean.zip"}],
        }
        with self.get(FakeResponse(plugin_release)):
            result = self.api.get_bundle_statuses()

        self.assertEqual("success", result["status"])
        self.assertNotIn("notice", result)
        clean = next(item for item in result["data"] if item["name"] == "ElectricalCommands.CleanCADCommands")
        self.assertEqual("not_installed", clean["state"])
        self.assertEqual("v0.2.1", clean["remote_version"])

    def test_plugin_list_still_shows_the_real_release_from_a_saved_answer_when_rate_limited(self):
        plugin_release = {
            "tag_name": "v0.2.1",
            "assets": [{"name": "ElectricalCommands.CleanCADCommands-v0.2.1.zip",
                        "browser_download_url": "https://github.com/x/clean.zip"}],
        }
        self.save(PLUGIN_URL, plugin_release, age_seconds=3 * 3600)

        with self.get(rate_limited()):
            result = self.api.get_bundle_statuses()

        self.assertNotIn("notice", result)
        clean = next(item for item in result["data"] if item["name"] == "ElectricalCommands.CleanCADCommands")
        self.assertEqual("not_installed", clean["state"])  # installable, not "not published"


if __name__ == "__main__":
    unittest.main()
