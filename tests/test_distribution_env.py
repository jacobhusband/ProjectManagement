"""A shareable installer must not inherit personal credentials from a local .env."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values


spec = importlib.util.spec_from_file_location(
    "distribution_env", Path(__file__).resolve().parents[1] / "build-config" / "distribution_env.py"
)
distribution_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(distribution_env)


class DistributionEnvTests(unittest.TestCase):
    def test_only_sign_in_configuration_survives_and_source_is_unchanged(self):
        original = (
            'GOOGLE_API_KEY="personal-ai-key"\n'
            'OTHER_SECRET="unknown-secret"\n'
            'MICROSOFT_CLIENT_SECRET="private-credential"\n'
            'GOOGLE_OAUTH_CLIENT_ID="desktop-client"\n'
            'GOOGLE_CLIENT_SECRET="desktop-client-config"\n'
            'MICROSOFT_OAUTH_CLIENT_ID="microsoft-client"\n'
            'MICROSOFT_OAUTH_TENANT_ID="organizations"\n'
        )
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / ".env"
            destination = Path(folder) / "distribution" / ".env"
            source.write_text(original, encoding="utf-8")
            destination.parent.mkdir()
            destination.write_text('STALE_SECRET="old-key"\n', encoding="utf-8")
            distribution_env.write_distribution_env(source, destination)
            values = dotenv_values(destination)
            self.assertEqual(set(distribution_env.PUBLIC_CONFIG_KEYS), set(values))
            self.assertEqual("desktop-client", values["GOOGLE_OAUTH_CLIENT_ID"])
            self.assertNotIn("personal-ai-key", destination.read_text(encoding="utf-8"))
            self.assertEqual(original, source.read_text(encoding="utf-8"))

    def test_environment_expansion_cannot_copy_a_personal_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / ".env"
            destination = Path(folder) / "distribution" / ".env"
            source.write_text("GOOGLE_OAUTH_CLIENT_ID='${PRIVATE_TOKEN}'\n", encoding="utf-8")
            with patch.dict(os.environ, {"PRIVATE_TOKEN": "personal-secret"}):
                distribution_env.write_distribution_env(source, destination)
            self.assertEqual("${PRIVATE_TOKEN}", dotenv_values(destination, interpolate=False)["GOOGLE_OAUTH_CLIENT_ID"])
            self.assertNotIn("personal-secret", destination.read_text(encoding="utf-8"))

    def test_refuses_to_overwrite_source_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / ".env"
            source.write_text("GOOGLE_API_KEY=personal\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                distribution_env.write_distribution_env(source, source)
            self.assertEqual("GOOGLE_API_KEY=personal\n", source.read_text(encoding="utf-8"))

    def test_sign_in_values_round_trip_quotes_and_backslashes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / ".env"
            destination = Path(folder) / "distribution" / ".env"
            source.write_text("GOOGLE_CLIENT_SECRET=\"desktop's \\\\client\"\n", encoding="utf-8")
            distribution_env.write_distribution_env(source, destination)
            self.assertEqual(dotenv_values(source), dotenv_values(destination))


if __name__ == "__main__":
    unittest.main()
