"""Exercise the real bridge method without initializing application resources."""
import ast
from pathlib import Path
import types
import unittest
from unittest.mock import Mock


source = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8-sig"))
api_class = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "Api")
method = next(node for node in api_class.body if isinstance(node, ast.FunctionDef) and node.name == "validate_google_ai_api_key")


class OnboardingApiKeyTests(unittest.TestCase):
    def setUp(self):
        self.requests = Mock()
        namespace = {"requests": self.requests}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "main.py", "exec"), namespace)
        self.validate = types.MethodType(namespace[method.name], object())

    def test_blank_key_does_not_contact_google(self):
        self.assertEqual("error", self.validate("  ")["status"])
        self.requests.get.assert_not_called()

    def test_checks_access_without_generating_content_or_putting_key_in_url(self):
        self.requests.get.return_value = Mock(status_code=200)
        self.requests.get.return_value.json.return_value = {"models": [{"name": "models/example"}]}
        self.assertEqual({"status": "success"}, self.validate(" test-key "))
        self.requests.get.assert_called_once_with(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": "test-key"}, params={"pageSize": 1},
            timeout=(5, 15), allow_redirects=False,
        )

    def test_rejected_keys_and_temporary_failures_do_not_pass(self):
        for status in (400, 401, 403, 429, 500, 302):
            with self.subTest(status=status):
                self.requests.get.return_value = Mock(status_code=status)
                result = self.validate("secret-key")
                self.assertEqual("error", result["status"])
                self.assertNotIn("secret-key", result["message"])

    def test_empty_or_malformed_model_responses_do_not_pass(self):
        for payload in ({}, {"models": []}, {"models": "invalid"}, []):
            with self.subTest(payload=payload):
                response = Mock(status_code=200)
                response.json.return_value = payload
                self.requests.get.return_value = response
                self.assertEqual("error", self.validate("secret-key")["status"])

    def test_request_errors_do_not_expose_credentials(self):
        self.requests.get.side_effect = RuntimeError("request included secret-key")
        result = self.validate("secret-key")
        self.assertEqual("error", result["status"])
        self.assertNotIn("secret-key", result["message"])


if __name__ == "__main__":
    unittest.main()
