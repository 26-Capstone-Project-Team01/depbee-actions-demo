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
# The readiness probe asks for the depbee commit the scan pins and for this depbee-analyzer
# commit, which that depbee commit installs (its pyproject.toml).
COMMITS = "https://github.com/26-Capstone-Project-Team01/{}/commit/{}"
ANALYZER = "917ba903bb2e719419ad5f2daeb7d542940703d5"
# All it passes to curl before the address: no credential, no redirect followed, no body kept.
PROBE = (
    "--disable --silent --show-error --head --output /dev/null"
    " --write-out %{http_code} --proto =https --max-time 30 "
)
# How its one annotation starts: both titles say that the product did not scan.
PUBLIC = "::notice title=공개 여부만 확인 (제품 검사 미실행)::"
NOT_SCANNED = (
    "::error title=제품 검사 미실행::depbee 제품 검사는 실행되지 않았습니다."
    " 공개가 확인되지 않은 고정 커밋: "
)
# Stands in for curl: records its arguments and answers "<HTTP status> [<exit status>]".
FAKE_CURL = """#!/bin/sh
printf '%s\\n' "$*" >> calls
case "$*" in */depbee/commit/*) set -- $DEPBEE ;; *) set -- $ANALYZER ;; esac
printf %s "$1"
exit "${2:-0}"
"""


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

    def test_product_scan_is_off_and_the_manual_run_only_probes(self):
        text = WORKFLOWS[PRODUCT]
        triggers = text.split("\non:\n")[1].split("\npermissions:")[0]
        self.assertEqual(triggers.split(), ["workflow_dispatch:"])
        # Each job belongs to one event, so the manual run cannot reach the Action.
        readiness, scan = text.split("\n  scan:\n")
        self.assertIn("    if: github.event_name == 'workflow_dispatch'\n", readiness)
        self.assertIn("    if: github.event_name == 'pull_request'\n", scan)
        self.assertNotIn("uses:", readiness)
        # The scan is the checkout and the Action: no step of this repository runs npm or code.
        self.assertEqual(scripts(scan), [])

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


@unittest.skipUnless(
    os.name == "posix" and shutil.which("bash"),
    "runs the step with bash, like the runner",
)
class ProductReadiness(unittest.TestCase):
    """The manual run only asks whether the two pinned commits can be seen without signing in.

    A fake curl answers, so these tests send no request.
    """

    def probe(self, depbee="200", analyzer="200"):
        """(exit status, annotations, curl calls) when the fake curl gives these answers."""
        workflow = (ROOT / ".github" / "workflows" / PRODUCT).read_text("utf-8")
        (script,) = scripts(workflow)
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "step.sh").write_text(script, encoding="utf-8")
            fake = Path(temp, "curl")
            fake.write_text(FAKE_CURL, encoding="utf-8")
            fake.chmod(0o755)
            done = subprocess.run(
                ["bash", "-e", "step.sh"],
                cwd=temp,
                env={
                    "PATH": temp + os.pathsep + os.environ["PATH"],
                    "DEPBEE": depbee,
                    "ANALYZER": analyzer,
                },
                capture_output=True,
                timeout=60,
                check=False,
            )
            calls = Path(temp, "calls").read_text("utf-8").splitlines()
        output = done.stdout.decode("utf-8").splitlines()
        annotations = [line for line in output if line.startswith("::")]
        return done.returncode, annotations, calls

    def refused(self, named, **answers):
        status, annotations, calls = self.probe(**answers)
        self.assertEqual(status, 1)
        self.assertEqual(annotations, [NOT_SCANNED + named])
        # The second commit is asked for even when the first cannot be seen.
        self.assertEqual(len(calls), 2)

    def test_public_commits_are_reported_without_claiming_a_scan(self):
        status, (notice,), calls = self.probe()
        self.assertEqual(status, 0)
        self.assertTrue(notice.startswith(PUBLIC), notice)
        self.assertIn("depbee 제품 검사는 실행되지 않았습니다", notice)
        pinned = re.search(
            re.escape(PRODUCT_ACTION) + r"([0-9a-f]{40})\n", WORKFLOWS[PRODUCT]
        )
        self.assertEqual(
            calls,
            [
                PROBE + COMMITS.format("depbee", pinned.group(1)),
                PROBE + COMMITS.format("depbee-analyzer", ANALYZER),
            ],
        )

    def test_private_commit_fails_and_says_nothing_was_scanned(self):
        private = "(HTTP 404, 비공개이거나 없음)"
        self.refused("depbee" + private, depbee="404")
        self.refused("depbee-analyzer" + private, analyzer="404")
        self.refused(
            f"depbee{private}, depbee-analyzer{private}", depbee="404", analyzer="404"
        )

    def test_unreachable_commit_fails_and_says_nothing_was_scanned(self):
        # No response, a redirect (it is not followed), a status from a curl that then failed.
        for answer, shown in {"000 7": "000", "301": "301", "200 28": "000"}.items():
            with self.subTest(answer):
                self.refused(f"depbee(HTTP {shown}, 접근 실패)", depbee=answer)


if __name__ == "__main__":
    unittest.main()
