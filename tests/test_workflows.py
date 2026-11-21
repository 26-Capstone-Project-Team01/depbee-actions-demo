"""Rules the workflows must keep: pinned actions, read-only tokens, no pull request code run."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = "depbee.yml"
PRODUCT_ACTION = "26-Capstone-Project-Team01/depbee@"
# README: this workflow may be deleted once the product check runs on pull requests.
PULL_REQUEST_CHECK = "fixture-pr-check.yml"
# Repository variables of the product check, here with values its input check accepts.
VARIABLES = {
    "DEPBEE_MODEL_VERSION": "model-v1.0",
    "DEPBEE_MODEL_SHA256": "0" * 64,
    "DEPBEE_MANIFEST_SHA256": "a" * 64,
    "DEPBEE_KNOWN_MALICIOUS_VERSION": "known_2026.11",
    "DEPBEE_KNOWN_MALICIOUS_SHA256": "f" * 64,
}


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

    def test_readme_names_the_product_commit_the_workflow_pins(self):
        pinned = re.search(
            re.escape(PRODUCT_ACTION) + r"[0-9a-f]{40}\n", WORKFLOWS[PRODUCT]
        )
        self.assertIsNotNone(pinned)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(pinned.group().strip(), readme)


@unittest.skipUnless(
    os.name == "posix" and shutil.which("bash"),
    "runs the step with bash, like the runner",
)
class ProductReadiness(unittest.TestCase):
    """The readiness step refuses what the pinned depbee Action refuses in its input check.

    That check takes a Release tag that starts with a letter or digit and continues with up to 99
    letters, digits, dots, underscores or hyphens, and a digest of 64 lowercase hex digits.
    """

    def check(self, **changed):
        """(exit status, names the step reports) for the valid variables with these changes."""
        workflow = (ROOT / ".github" / "workflows" / PRODUCT).read_text("utf-8")
        (script,) = [found for found in scripts(workflow) if "missing=()" in found]
        with tempfile.TemporaryDirectory() as temp:
            step = Path(temp, "step.sh")
            step.write_text(script, encoding="utf-8")
            done = subprocess.run(
                ["bash", "-e", str(step)],
                env={"PATH": os.environ["PATH"], **VARIABLES, **changed},
                capture_output=True,
                timeout=60,
                check=False,
            )
        output = done.stdout.decode("utf-8")
        expected = (
            "::error title=제품 연동 미구성::" if done.returncode else "::notice "
        )
        self.assertTrue(output.startswith(expected), output)
        return done.returncode, sorted(re.findall(r"DEPBEE_[A-Z0-9_]+", output))

    def test_well_formed_variables_are_accepted(self):
        self.assertEqual(self.check(), (0, []))
        self.assertEqual(self.check(DEPBEE_MODEL_VERSION="1" + "-" * 99), (0, []))

    def test_nothing_registered_names_all_five(self):
        self.assertEqual(
            self.check(**dict.fromkeys(VARIABLES, "")), (1, sorted(VARIABLES))
        )

    def test_tags_the_action_refuses_are_refused(self):
        refused = ("", "demo release", "-v1", ".v1", "release/v1", "v1 ", "v" * 101)
        for name in ("DEPBEE_MODEL_VERSION", "DEPBEE_KNOWN_MALICIOUS_VERSION"):
            for tag in (*refused, "버전1"):
                with self.subTest(name=name, tag=tag):
                    self.assertEqual(self.check(**{name: tag}), (1, [name]))

    def test_digests_the_action_refuses_are_refused(self):
        for name in (key for key in VARIABLES if key.endswith("SHA256")):
            for digest in ("", "0" * 63, "0" * 65, "A" * 64, "g" * 64):
                with self.subTest(name=name, digest=digest):
                    self.assertEqual(self.check(**{name: digest}), (1, [name]))


if __name__ == "__main__":
    unittest.main()
