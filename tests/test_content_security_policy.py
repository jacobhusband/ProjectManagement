"""index.html must keep working under its Content-Security-Policy.

The policy refuses inline scripts and inline event handlers, so anything that
reintroduces them would silently stop working in the app.
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
SCRIPT_JS = (REPO_ROOT / "script.js").read_text(encoding="utf-8")


def _policy():
    match = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', INDEX_HTML)
    if not match:
        return None
    directives = {}
    for part in match.group(1).split(";"):
        tokens = part.split()
        if tokens:
            directives[tokens[0]] = tokens[1:]
    return directives


class ContentSecurityPolicyTests(unittest.TestCase):
    def test_policy_refuses_inline_script_eval_and_plugins(self):
        policy = _policy()
        self.assertIsNotNone(policy, "index.html is missing its Content-Security-Policy")
        self.assertNotIn("'unsafe-inline'", policy["script-src"])
        self.assertNotIn("'unsafe-eval'", policy["script-src"])
        self.assertEqual(["'none'"], policy["object-src"])
        self.assertEqual(["'none'"], policy["base-uri"])
        # The policy tag has to come before the resources it governs.
        self.assertLess(
            INDEX_HTML.index('http-equiv="Content-Security-Policy"'),
            INDEX_HTML.index("<script"),
        )

    def test_markup_has_no_inline_event_handlers_or_inline_scripts(self):
        self.assertEqual([], re.findall(r"<[^>]*\son[a-z]+\s*=", INDEX_HTML))
        inline_scripts = [
            tag for tag in re.findall(r"<script\b[^>]*>", INDEX_HTML) if "src=" not in tag
        ]
        self.assertEqual([], inline_scripts)

    def test_remote_scripts_are_pinned_allowed_and_integrity_checked(self):
        allowed = _policy()["script-src"]
        for tag in re.findall(r"<script\b[^>]*>", INDEX_HTML):
            source = re.search(r'src="([^"]+)"', tag).group(1)
            if not source.startswith("https://"):
                continue
            with self.subTest(source=source):
                self.assertIn(source, allowed)
                self.assertRegex(tag, r'integrity="sha(256|384|512)-[A-Za-z0-9+/=]+"')
                self.assertIn('crossorigin="anonymous"', tag)

    def test_every_click_action_has_a_handler(self):
        start = SCRIPT_JS.index("function getDeclarativeClickAction(name) {")
        end = SCRIPT_JS.index("function handleDeclarativeClick(event) {", start)
        handled = set(re.findall(r"^\s{4}([A-Za-z]+): \(\) =>", SCRIPT_JS[start:end], re.M))
        used = set(re.findall(r'data-click-action="([^"]+)"', INDEX_HTML))
        self.assertTrue(used)
        self.assertEqual(set(), used - handled)
        self.assertIn('document.addEventListener("click", handleDeclarativeClick, true);', SCRIPT_JS)

    def test_every_close_button_targets_an_existing_dialog(self):
        dialogs = set(re.findall(r'<dialog\b[^>]*\sid="([^"]+)"', INDEX_HTML))
        targets = set(re.findall(r'data-close-dialog="([^"]+)"', INDEX_HTML))
        self.assertTrue(targets)
        self.assertEqual(set(), targets - dialogs)

    def test_bootstrap_script_ships_with_both_specs(self):
        self.assertIn('<script src="app-bootstrap.js', INDEX_HTML)
        for spec in ("ACIES Scheduler.spec", "build-config/ACIES Scheduler.spec"):
            with self.subTest(spec=spec):
                self.assertIn("app-bootstrap.js", (REPO_ROOT / spec).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
