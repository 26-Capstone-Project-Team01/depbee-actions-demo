"""What the fixture gate shows for the three scenes, hostile lockfile text and unreadable input."""

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "fixture_gate", ROOT / "tools" / "fixture_gate.py"
)
fixture_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture_gate)

SCENARIOS = ROOT / "fixtures" / "scenarios"
KNOWN_LIST = ROOT / "fixtures" / "known-list.json"
# Scene -> exit status, verdict, status of each changed entry, annotation (level, lockfile line).
EXPECTED = {
    "pass": (0, "pass", ["no_match"], None),
    "known-match": (1, "fail", ["known_match"], ("error", 15)),
    "hold-warning": (0, "warn", ["hold"], ("warning", 14)),
}
BASE = {"node_modules/ms": {"version": "2.1.1"}}
# RIGHT-TO-LEFT OVERRIDE, built here so that this source file holds no hidden character.
BIDI = chr(0x202E)


def lock(packages):
    return json.dumps(
        {"lockfileVersion": 3, "packages": {"": {}, **packages}}, indent=2
    )


def annotations(lines, level):
    return [line for line in lines if line.startswith(f"::{level}")]


def gate(head, base=None, extra=()):
    """Run main() on lockfile texts: (exit status, stdout lines, job summary, report or None)."""
    with tempfile.TemporaryDirectory() as temp:
        paths = {
            name: Path(temp, name) for name in ("base", "head", "summary", "report")
        }
        paths["base"].write_text(lock(BASE) if base is None else base, encoding="utf-8")
        if head is not None:
            paths["head"].write_text(head, encoding="utf-8")
        stdout = io.StringIO()
        argv = ["--base", str(paths["base"]), "--head", str(paths["head"])]
        argv += ["--report", str(paths["report"]), *extra]
        environ = {"GITHUB_STEP_SUMMARY": str(paths["summary"])}
        with mock.patch.dict(os.environ, environ), contextlib.redirect_stdout(stdout):
            status = fixture_gate.main(argv)
        report = paths["report"]
        return (
            status,
            stdout.getvalue().splitlines(),
            paths["summary"].read_text(encoding="utf-8"),
            json.loads(report.read_text(encoding="utf-8")) if report.exists() else None,
        )


class Scenes(unittest.TestCase):
    def test_each_scene_as_the_workflow_runs_it(self):
        for scene, (status, verdict, statuses, annotation) in EXPECTED.items():
            with self.subTest(scene), tempfile.TemporaryDirectory() as temp:
                head = f"fixtures/scenarios/{scene}/package-lock.json"
                report = Path(temp, "report.json")
                summary = Path(temp, "summary.md")
                done = subprocess.run(
                    [sys.executable, "-I", "tools/fixture_gate.py"]
                    + ["--head", head, "--report", str(report)],
                    cwd=ROOT,
                    env={**os.environ, "GITHUB_STEP_SUMMARY": str(summary)},
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
                lines = done.stdout.decode("utf-8").splitlines()
                self.assertEqual(
                    done.returncode, status, done.stderr.decode("utf-8", "replace")
                )

                found = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual(found["verdict"], verdict)
                self.assertEqual([row["status"] for row in found["results"]], statuses)
                self.assertIs(found["depbee_executed"], False)

                marked = annotations(lines, "error") + annotations(lines, "warning")
                if annotation is None:
                    self.assertEqual(marked, [])
                else:
                    level, line = annotation
                    self.assertEqual(len(marked), 1)
                    self.assertTrue(
                        marked[0].startswith(f"::{level} file={head},line={line},")
                    )
                # Every run says on the run page and in the summary that depbee did not run.
                self.assertEqual(len(annotations(lines, "notice")), 1)
                self.assertIn("depbee 제품은 실행되지 않았습니다", lines[0])
                self.assertIn(
                    "depbee 제품이 만든 것이 아닙니다", summary.read_text("utf-8")
                )

    def test_workflow_offers_exactly_the_fixture_scenes(self):
        workflow = (ROOT / ".github/workflows/fixture-demo.yml").read_text(
            encoding="utf-8"
        )
        options = (
            re.search(r"options:\n((?: +- [a-z-]+\n)+)", workflow)
            .group(1)
            .split()[1::2]
        )
        matrix = json.loads(re.search(r"'(\[[^']+\])'", workflow).group(1))
        folders = {path.name for path in SCENARIOS.iterdir()}
        self.assertEqual(set(options) - {"all"}, set(EXPECTED))
        self.assertEqual(set(matrix), set(EXPECTED))
        self.assertEqual(folders, set(EXPECTED))

    def test_pull_request_annotations_name_the_repository_path(self):
        head = (SCENARIOS / "known-match" / "package-lock.json").read_text(
            encoding="utf-8"
        )
        status, lines, _, _ = gate(head, extra=["--annotate-as", "package-lock.json"])
        self.assertEqual(status, 1)
        self.assertTrue(
            annotations(lines, "error")[0].startswith(
                "::error file=package-lock.json,line=15,"
            )
        )

    def test_known_list_names_cannot_be_published_or_downloaded(self):
        names = {
            entry["name"]
            for entry in json.loads(KNOWN_LIST.read_text("utf-8"))["entries"]
        }
        self.assertTrue(names)
        for name in names:
            # npm allows no uppercase letter in a new package name: nobody can publish these.
            self.assertNotEqual(name, name.lower())
        for path in SCENARIOS.glob("*/package-lock.json"):
            packages = json.loads(path.read_text(encoding="utf-8"))["packages"]
            for location, entry in packages.items():
                if location.rpartition("node_modules/")[2] in names:
                    self.assertEqual(set(entry), {"version"}, f"{path}: {location}")


class Rules(unittest.TestCase):
    def test_version_and_name_forms(self):
        expected = {
            "node_modules/stable": ("1.2.3", "no_match"),
            "node_modules/build-metadata": ("1.2.3+build.5", "no_match"),
            "node_modules/@scope/pkg": ("1.0.0", "no_match"),
            "node_modules/a/node_modules/nested": ("2.0.0", "no_match"),
            "node_modules/prerelease": ("1.2.3-rc.1", "hold"),
            "node_modules/tag": ("latest", "hold"),
            "node_modules/range": ("^1.2.3", "hold"),
            "node_modules/no-version": (None, "hold"),
            "node_modules/bad name": ("1.0.0", "hold"),
        }
        head = lock(
            {loc: {"version": version} for loc, (version, _) in expected.items()}
        )
        status, lines, _, report = gate(head, base=lock({}))
        self.assertEqual(status, 0)
        self.assertEqual(report["verdict"], "warn")
        found = {row["location"]: row["status"] for row in report["results"]}
        self.assertEqual(found, {loc: status for loc, (_, status) in expected.items()})
        self.assertEqual(len(annotations(lines, "warning")), 5)

    def test_alias_is_matched_by_its_real_name(self):
        entry = {"name": "DEPBEE-DEMO-SENTINEL", "version": "9.9.9"}
        status, _, _, report = gate(
            lock({**BASE, "node_modules/harmless-alias": entry})
        )
        self.assertEqual(status, 1)
        self.assertEqual(report["results"][0]["status"], "known_match")

    def test_list_match_is_never_downgraded_to_a_hold(self):
        change = {"package": "x", "after_version": "1.0.0-rc.1"}
        status, _ = fixture_gate.evaluate(change, {("x", "1.0.0-rc.1"): "DEMO"})
        self.assertEqual(status, "known_match")

    def test_unchanged_and_removed_entries_are_not_reported(self):
        for label, head in {"same": lock(BASE), "removed": lock({})}.items():
            with self.subTest(label):
                status, lines, summary, report = gate(head)
                self.assertEqual(status, 0)
                self.assertEqual(report["verdict"], "no_changes")
                self.assertEqual(report["results"], [])
                self.assertEqual(
                    annotations(lines, "error") + annotations(lines, "warning"), []
                )
                self.assertIn("변경 없음", summary)


class UntrustedInput(unittest.TestCase):
    def test_lockfile_text_cannot_forge_commands_or_markdown(self):
        head = lock(
            {
                "node_modules/x\n::error::forged": {
                    "version": "1.0.0\n## forged heading"
                },
                "node_modules/y": {
                    "name": "a|b<img src=x>`" + BIDI,
                    "version": "1.0.0",
                },
                # The runner decodes %0A in a command into a line break.
                "node_modules/z%0Aforged line": {"version": "1.0.0"},
            }
        )
        status, lines, summary, report = gate(head, base=lock({}))
        self.assertEqual(status, 0)
        self.assertEqual(annotations(lines, "error"), [])
        self.assertEqual(len(annotations(lines, "warning")), 3)
        self.assertEqual(len(lines), 4, lines)
        self.assertIn("z%250Aforged line", lines[3])
        self.assertNotIn("\n## forged", summary)
        # A backslash before "<", "|" or "`" makes it literal text in the rendered summary.
        self.assertIn("a\\|b\\<img src\\=x\\>\\`", summary)
        self.assertNotIn(BIDI, summary + "".join(lines) + json.dumps(report))
        self.assertNotIn("\n", report["results"][0]["location"])

    def test_unreadable_input_fails_instead_of_passing(self):
        many = {f"node_modules/p{number}": {"version": "1.0.0"} for number in range(21)}
        cases = {
            "missing file": None,
            "not JSON": "not json",
            "not an object": "[]",
            "lockfileVersion 1": json.dumps({"lockfileVersion": 1, "dependencies": {}}),
            "deeply nested": "[" * 100000,
            "more than 20 changes": lock(many),
        }
        for label, head in cases.items():
            with self.subTest(label):
                status, lines, summary, report = gate(head, base=lock({}))
                self.assertEqual(status, 2)
                self.assertEqual(len(annotations(lines, "error")), 1)
                self.assertIn("통과가 아닙니다", summary)
                self.assertIsNone(report)

    def test_unreadable_list_fails_instead_of_passing(self):
        with tempfile.TemporaryDirectory() as temp:
            broken = Path(temp, "known-list.json")
            broken.write_text('{"entries": [{"name": "x"}]}', encoding="utf-8")
            with mock.patch.object(fixture_gate, "KNOWN_LIST", broken):
                status, lines, _, report = gate(lock(BASE))
        self.assertEqual(status, 2)
        self.assertEqual(len(annotations(lines, "error")), 1)
        self.assertIsNone(report)

    def test_twenty_changes_are_evaluated(self):
        many = {f"node_modules/p{number}": {"version": "1.0.0"} for number in range(20)}
        status, _, _, report = gate(lock(many), base=lock({}))
        self.assertEqual(status, 0)
        self.assertEqual(len(report["results"]), 20)

    def test_linked_lockfile_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            link = Path(temp, "package-lock.json")
            try:
                link.symlink_to(SCENARIOS / "pass" / "package-lock.json")
            except (OSError, NotImplementedError):
                self.skipTest("this platform or account cannot create symbolic links")
            # Without a summary file main() prints the summary: keep it out of a real job summary.
            with mock.patch.dict(os.environ), contextlib.redirect_stdout(io.StringIO()):
                os.environ.pop("GITHUB_STEP_SUMMARY", None)
                self.assertEqual(fixture_gate.main(["--head", str(link)]), 2)


if __name__ == "__main__":
    unittest.main()
