"""Rules the workflows must keep: pinned actions, read-only tokens, no pull request code run."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = "depbee.yml"
PRODUCT_ACTION = "26-Capstone-Project-Team01/depbee@"
# README: this workflow may be deleted once the product check runs on pull requests.
PULL_REQUEST_CHECK = "fixture-pr-check.yml"


def code(text):
    """The workflow without YAML comments (no value in these files contains ' #')."""
    return "\n".join(re.sub(r"(^|\s)#.*", "", line) for line in text.splitlines())


def scripts(text):
    """Shell text of every `run:` key: its own line and the more-indented lines after it."""
    lines, found = text.splitlines(), []
    for index, line in enumerate(lines):
        if not re.match(r" *(- )?run:", line):
            continue
        column, first = line.index("run:"), line.split("run:", 1)[1].strip()
        body = [] if re.fullmatch(r"[|>][+-]?", first) else [first]
        for following in lines[index + 1 :]:
            if following.strip() and len(following) - len(following.lstrip()) <= column:
                break
            body.append(following)
        found.append("\n".join(body))
    return found


WORKFLOWS = {
    path.name: code(path.read_text(encoding="utf-8"))
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
}
FIXTURE = {name: text for name, text in WORKFLOWS.items() if name != PRODUCT}


class WorkflowRules(unittest.TestCase):
    def test_expected_workflows_exist(self):
        self.assertEqual(
            set(WORKFLOWS) - {PULL_REQUEST_CHECK}, {PRODUCT, "fixture-demo.yml"}
        )

    def test_actions_are_pinned_to_full_commit_ids(self):
        for name, text in WORKFLOWS.items():
            used = re.findall(r"uses: *(\S+)", text)
            self.assertTrue(used, name)
            for action in used:
                with self.subTest(workflow=name, action=action):
                    self.assertRegex(
                        action, r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$"
                    )

    def test_tokens_are_read_only_and_not_kept(self):
        for name, text in WORKFLOWS.items():
            with self.subTest(name):
                # One block for the whole workflow, none per job.
                block = re.compile(r"^ *permissions:.*\n(?: +.+\n)*", re.MULTILINE)
                self.assertEqual(
                    block.findall(text), ["permissions:\n  contents: read\n"]
                )
                self.assertNotIn("secrets.", text)
                checkouts = text.count("uses: actions/checkout@")
                self.assertEqual(text.count("persist-credentials: false"), checkouts)

    def test_shell_scripts_take_values_from_the_environment_only(self):
        for name, text in WORKFLOWS.items():
            for script in scripts(text):
                with self.subTest(workflow=name, script=script):
                    self.assertNotIn("${{", script)
                    self.assertNotIn("|| true", script)

    def test_no_trigger_or_setting_runs_pull_request_code_with_trust(self):
        for name, text in WORKFLOWS.items():
            with self.subTest(name):
                for banned in (
                    "pull_request_target",
                    "workflow_run",
                    "continue-on-error",
                ):
                    self.assertNotIn(banned, text)

    def test_fixture_workflows_never_touch_the_product_or_npm(self):
        for name, text in FIXTURE.items():
            with self.subTest(name):
                self.assertNotIn(PRODUCT_ACTION, text)
                self.assertNotIn("vars.", text)
                self.assertIn("depbee 제품 미실행", text.splitlines()[0])
                self.assertIn("보안 게이트 아님", text)
                for script in scripts(text):
                    self.assertIsNone(
                        re.search(r"\b(npm|npx|node|yarn|pnpm)\b", script), script
                    )

    def test_pull_request_check_runs_only_base_branch_code(self):
        if PULL_REQUEST_CHECK not in WORKFLOWS:
            self.skipTest("the fixture pull request check was removed")
        text = WORKFLOWS[PULL_REQUEST_CHECK]
        self.assertIn(
            "ref: ${{ github.event.pull_request.base.sha }}\n          path: trusted",
            text,
        )
        # The other checkout takes one data file from the pull request and nothing else.
        self.assertEqual(text.count("uses: actions/checkout@"), 2)
        self.assertIn("path: untrusted", text)
        self.assertIn("sparse-checkout: /package-lock.json\n", text)
        self.assertIn("sparse-checkout-cone-mode: false", text)
        commands = [script.split() for script in scripts(text)]
        self.assertEqual(len(commands), 1)
        self.assertEqual(
            commands[0][:3], ["python3", "-I", "trusted/tools/fixture_gate.py"]
        )

    def test_readme_names_the_product_commit_the_workflow_pins(self):
        pinned = re.search(
            re.escape(PRODUCT_ACTION) + r"[0-9a-f]{40}\n", WORKFLOWS[PRODUCT]
        )
        self.assertIsNotNone(pinned)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(pinned.group().strip(), readme)


if __name__ == "__main__":
    unittest.main()
