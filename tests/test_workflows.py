"""Rules the workflows must keep: pinned actions, read-only tokens, no pull request code run."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = "depbee.yml"
PRODUCT_ACTION = "26-Capstone-Project-Team01/depbee@"
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
            set(WORKFLOWS), {PRODUCT, PULL_REQUEST_CHECK, "fixture-demo.yml"}
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

    def test_report_is_uploaded_only_on_the_ready_signal_of_the_gate(self):
        """A gate step that failed on a list match still uploads; one that errored never does.

        The gate writes `report_ready=true` as its last act (tests/test_fixture_gate.py), so a
        report left behind by a failed cleanup is not uploaded either.
        """
        upload = re.compile(
            r"if: \$\{\{ !cancelled\(\) && steps\.gate\.outputs\.report_ready == 'true' \}\}\n"
            r" +uses: actions/upload-artifact@[0-9a-f]{40}\n"
            r" +with:\n"
            r" +name: fixture-report.*\n"
            r" +path: \$\{\{ runner\.temp \}\}/fixture-report\.json\n"
        )
        for name, text in FIXTURE.items():
            with self.subTest(name):
                # The step with this id is the gate, and it writes the path that is uploaded.
                (step,) = re.findall(r" +id: gate\n((?: {8,}.*\n)+)", text)
                self.assertIn("tools/fixture_gate.py", step)
                self.assertIn('--report "$RUNNER_TEMP/fixture-report.json"', step)
                self.assertRegex(text, upload)
                self.assertEqual(text.count("uses: actions/upload-artifact@"), 1)

    def test_product_scan_runs_for_pull_requests_into_main_and_for_nothing_else(self):
        text = WORKFLOWS[PRODUCT]
        # The Action compares with the base commit of the pull request: no other event has one.
        triggers = text.split("\non:\n")[1].split("\npermissions:")[0]
        self.assertEqual(triggers.split(), ["pull_request:", "branches:", "[main]"])
        # The scan is the checkout and the Action: no step of this repository runs npm or code.
        self.assertEqual(
            re.findall(r"uses: *(\S+@)", text), ["actions/checkout@", PRODUCT_ACTION]
        )
        self.assertEqual(scripts(text), [])
        # depbee reads the base lockfile from git, so the checkout holds the whole history.
        self.assertIn("fetch-depth: 0\n", text)
        # README tells this check from the fixture checks by the name of its job.
        self.assertIn("    name: depbee scan (제품 실제 검사)\n", text)

    def test_product_action_gets_the_scene_policy_and_nothing_to_configure(self):
        text = WORKFLOWS[PRODUCT]
        # No repository variable, and no expression that could pass a token or a Release value.
        for absent in ("vars.", "${{"):
            self.assertNotIn(absent, text)
        # The Action is the last step and max-changes its only input.
        step = text.split("- uses: " + PRODUCT_ACTION)[1]
        self.assertRegex(step, r"^[0-9a-f]{40}\n +with:\n +max-changes: '1'\s*$")

    def test_readme_names_the_product_commit_the_workflow_pins(self):
        pinned = re.search(
            re.escape(PRODUCT_ACTION) + r"[0-9a-f]{40}\n", WORKFLOWS[PRODUCT]
        )
        self.assertIsNotNone(pinned)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(pinned.group().strip(), readme)
        # The decision rules README points to are the documentation of that same commit.
        sha = pinned.group().strip().split("@")[1]
        self.assertIn(
            f"https://github.com/26-Capstone-Project-Team01/depbee/blob/{sha}/docs/ci-cd.md",
            readme,
        )
        # A new pin must revisit README's claim of what it shares with the commit PR #8 ran.
        self.assertIn(f"지금 고정한 `{sha[:7]}`", readme)


if __name__ == "__main__":
    unittest.main()
