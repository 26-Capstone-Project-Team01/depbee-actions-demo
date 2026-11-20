"""Fixture gate of the depbee Actions demo. This is not depbee.

It compares the `packages` entries of two package-lock.json files by name and version, checks each
changed entry against the fictional list in fixtures/known-list.json and holds pre-release
versions. It downloads nothing, runs no package code and computes no ML score, so a pass says
nothing about safety. Standard library only: workflows run this file with `python3 -I` from the
trusted checkout, and the list and the default base lockfile come from that same checkout.

Exit status: 0 no list match (holds only warn), 1 a list match whose report and summary were
written, 2 nothing was decided or recorded (unreadable input, unwritable output, internal error).
With 0 and 1 the gate writes `report_ready=true` to GITHUB_OUTPUT as its last act; the workflows
upload the report only then.
"""

import argparse
import contextlib
import json
import os
import re
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWN_LIST = ROOT / "fixtures" / "known-list.json"
MAX_BYTES = 8 * 1024 * 1024
MAX_CHANGES = 20
NAME = re.compile(r"(@[A-Za-z0-9._~-]+/)?[A-Za-z0-9._~-]+")
VERSION = re.compile(r"\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?")
# status -> annotation level, label in the summary table
STATUSES = {
    "known_match": ("error", "가상 목록 일치"),
    "hold": ("warning", "보류(통과 아님)"),
    "no_match": (None, "해당 없음"),
}
VERDICTS = {
    "fail": "실패(가상 목록 일치)",
    "warn": "경고(보류 있음, 통과 아님)",
    "pass": "통과(fixture 규칙 기준)",
    "no_changes": "변경 없음",
}
TITLE = "fixture 게이트 (depbee 제품 아님)"
ERROR_TITLE = "fixture 게이트 오류 (판정 아님)"
UNDECIDED = (
    "검사를 끝내지 못했습니다. 통과가 아닙니다. "
    "이 실패는 가상 목록 일치 판정이 아닙니다."
)
NOTICE = (
    "fixture 시연입니다. depbee 제품은 실행되지 않았습니다. "
    "이 job의 성공이나 실패는 보안 판정이 아닙니다."
)
NOT_DEPBEE = (
    "이 결과는 depbee 제품이 만든 것이 아닙니다. "
    "이 저장소의 fixture 게이트(`tools/fixture_gate.py`)가 두 lockfile의 이름과 버전만 비교해 "
    "시연용 가상 목록(`fixtures/known-list.json`)과 대조했습니다. "
    "패키지 다운로드, 코드 분석, ML 위험 점수 계산, 실제 기지 악성 색인 대조는 하지 않았습니다. "
    "통과와 변경 없음은 안전 보증이 아닙니다."
)


class GateError(Exception):
    """Nothing could be evaluated: the step fails and is never reported as a pass."""


def clean(value, limit=120) -> str:
    """Printable ASCII only, bounded: lockfile strings must not steer the log or the summary."""
    text = re.sub(r"[^ -~]", lambda found: f"\\u{ord(found.group()):04x}", str(value))
    return text if len(text) <= limit else text[:limit] + "..."


def markdown(text: str) -> str:
    """Backslash-escape all ASCII punctuation (CommonMark), so text adds no markup or table cell."""
    return re.sub(r"([!-/:-@\[-`{-~])", r"\\\1", text)


def command(level: str, message: str, **properties) -> str:
    """One workflow command line, escaped as actions/toolkit command.ts does."""

    def data(text) -> str:
        return str(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    escaped = [
        f"{key}={data(value).replace(':', '%3A').replace(',', '%2C')}"
        for key, value in properties.items()
        if value is not None
    ]
    head = f"::{level} {','.join(escaped)}" if escaped else f"::{level}"
    return f"{head}::{data(message)}"


def load(path: Path, what: str) -> tuple:
    """(JSON object, text) of a file that a pull request may control."""
    if path.is_symlink() or not path.is_file():
        raise GateError(f"{what}: 파일이 없거나 일반 파일이 아닙니다.")
    if path.stat().st_size > MAX_BYTES:
        raise GateError(f"{what}: 크기가 {MAX_BYTES // 2**20} MiB를 넘습니다.")
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError, RecursionError) as exc:
        raise GateError(
            f"{what}: JSON으로 읽지 못했습니다({type(exc).__name__})."
        ) from exc
    if not isinstance(data, dict):
        raise GateError(f"{what}: 최상위가 JSON 객체가 아닙니다.")
    return data, text


def entries(lock: dict, what: str) -> dict:
    """location -> (name, version) of every non-root `packages` entry (lockfileVersion 2 or 3)."""
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise GateError(
            f"{what}: packages 객체가 없습니다. lockfileVersion 2 이상이 필요합니다."
        )
    found = {}
    for location, entry in packages.items():
        if location == "":
            continue
        entry = entry if isinstance(entry, dict) else {}
        name, version = entry.get("name"), entry.get("version")
        if not isinstance(name, str):
            name = location.rpartition("node_modules/")[2]
        found[location] = (name, version if isinstance(version, str) else None)
    return found


def changes(base: dict, head: dict) -> list:
    """Head entries that are new or whose name or version differs from the base."""
    return [
        {
            "location": location,
            "package": name,
            "before_version": base.get(location, (None, None))[1],
            "after_version": version,
        }
        for location, (name, version) in head.items()
        if base.get(location) != (name, version)
    ]


def evaluate(change: dict, known: dict) -> tuple:
    """(status, reason) of one change. A list match comes first: a hold never hides it."""
    name, version = change["package"], change["after_version"]
    if (name, version) in known:
        return "known_match", f"시연용 가상 목록과 일치({known[(name, version)]})"
    if len(name) > 214 or not NAME.fullmatch(name):
        return "hold", "패키지 이름 형식을 해석하지 못해 보류, 통과가 아님"
    parsed = VERSION.fullmatch(version or "")
    if not parsed:
        return "hold", "버전 형식을 해석하지 못해 보류, 통과가 아님"
    if parsed.group(1):
        return "hold", "사전 배포 버전이라 보류, 통과가 아님"
    return "no_match", "가상 목록에 없는 정식 버전"


def key_line(lines: list, location: str):
    """1-based line of this `packages` key (npm writes one key per line), or None."""
    key = f'"{location}":'
    return next(
        (n for n, line in enumerate(lines, 1) if line.strip().startswith(key)), None
    )


def run(base_path: Path, head_path: Path, shown: str) -> tuple:
    """(verdict, report rows, annotation lines) for the change from base to head."""
    base = entries(load(base_path, "기준 lockfile")[0], "기준 lockfile")
    head, text = load(head_path, "대상 lockfile")
    found = changes(base, entries(head, "대상 lockfile"))
    if len(found) > MAX_CHANGES:
        raise GateError(f"변경 항목 {len(found)}개가 상한 {MAX_CHANGES}개를 넘습니다.")
    listed, _ = load(KNOWN_LIST, "가상 목록")
    try:
        known = {
            (entry["name"], version): entry["id"]
            for entry in listed["entries"]
            for version in entry["versions"]
        }
    except (KeyError, TypeError) as exc:
        raise GateError(
            "가상 목록: entries의 name, versions, id를 읽지 못했습니다."
        ) from exc
    lines = text.splitlines()
    rows, annotations = [], []
    for change in found:
        status, reason = evaluate(change, known)
        row = {
            key: None if value is None else clean(value)
            for key, value in change.items()
        }
        rows.append({**row, "status": status, "reason": reason})
        level = STATUSES[status][0]
        if level:
            version = row["after_version"] or "버전 없음"
            message = f"{row['package']}@{version} ({row['location']}): {reason}"
            line = key_line(lines, change["location"])
            annotations.append(
                command(level, message, file=shown, line=line, title=TITLE)
            )
    statuses = {row["status"] for row in rows}
    if "known_match" in statuses:
        verdict = "fail"
    elif "hold" in statuses:
        verdict = "warn"
    else:
        verdict = "pass" if rows else "no_changes"
    return verdict, rows, annotations


def summary(verdict: str, rows: list, base: str, head: str) -> str:
    out = [f"## fixture 시연 결과: {VERDICTS[verdict]}", "", f"> {NOT_DEPBEE}", ""]
    if rows:
        out += [
            "| 패키지 | 이전 버전 | 새 버전 | fixture 판정 | 근거 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in rows:
            cells = [
                row["package"],
                row["before_version"] or "없음",
                row["after_version"] or "없음",
            ]
            cells += [STATUSES[row["status"]][1], row["reason"]]
            out.append("| " + " | ".join(markdown(cell) for cell in cells) + " |")
    else:
        out.append("이름이나 버전이 바뀌거나 새로 추가된 lockfile 항목이 없습니다.")
    out += [
        "",
        f"비교한 파일: 기준 {markdown(clean(base))}, 대상 {markdown(clean(head))}",
        "",
    ]
    return "\n".join(out)


def write_summary(text: str) -> None:
    """Append to the job summary, or print it when run outside GitHub Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(text)
    else:
        print(text)


def unwritable(what: str, exc: OSError) -> GateError:
    """The error for an output that could not be written."""
    where = f" 쓰지 못한 파일: {clean(exc.filename)}" if exc.filename else ""
    return GateError(f"운영 오류: {what}({type(exc).__name__}).{where}")


def record(report_path, verdict: str, rows: list, base: str, head: str) -> None:
    """Write the report, then the summary. Raises GateError when either cannot be written."""
    report = {
        "tool": "depbee-actions-demo fixture gate",
        "depbee_executed": False,
        "verdict": verdict,
        "base": clean(base),
        "head": clean(head),
        "results": rows,
    }
    # Both texts are built before the first write, so only a failing write can interrupt it.
    report_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    summary_text = summary(verdict, rows, base, head)
    try:
        if report_path:
            report_path.write_text(report_text, encoding="utf-8")
        write_summary(summary_text)
    except OSError as exc:
        raise unwritable("결과를 기록하지 못했습니다", exc) from exc


def announce(annotations: list, report_path) -> None:
    """Print the verdict annotations, then signal the workflow that the report is ready.

    The workflows upload the report only on `report_ready`. Its file is opened before anything
    is printed and written after the annotations are out: no verdict annotation without a
    writable signal, no signal without the annotations. Raises GateError on either failure.
    """
    target = os.environ.get("GITHUB_OUTPUT") if report_path else None
    try:
        with (
            open(target, "a", encoding="utf-8") if target else contextlib.nullcontext()
        ) as ready:
            for annotation in annotations:
                print(annotation)
            sys.stdout.flush()
            if ready:
                ready.write("report_ready=true\n")
    except OSError as exc:
        raise unwritable("판정을 알리지 못했습니다", exc) from exc


def fail(problem: str, report_path) -> int:
    """Say that nothing was decided, leave no report behind and return exit status 2.

    Every step is best effort and none may raise: an exception here would end the process with
    status 1. The workflows do not rely on the removal, they upload only on `report_ready`.
    """
    with contextlib.suppress(Exception):
        print(command("error", f"{UNDECIDED} {problem}", title=ERROR_TITLE), flush=True)
    with contextlib.suppress(Exception):
        write_summary(
            f"## fixture 시연 결과: 검사하지 못함\n\n> {NOT_DEPBEE}\n\n"
            f"{UNDECIDED} {markdown(problem)}\n"
        )
    with contextlib.suppress(Exception):
        if report_path:
            report_path.unlink()
    return 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--head", required=True, type=Path, help="package-lock.json to evaluate"
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=ROOT / "package-lock.json",
        help="package-lock.json to compare with (default: the one next to this checkout)",
    )
    parser.add_argument(
        "--annotate-as", help="repository path shown for --head (default: --head)"
    )
    parser.add_argument(
        "--report", type=Path, help="write the JSON report to this file"
    )
    args = parser.parse_args(argv)
    shown = args.annotate_as or args.head.as_posix()
    base = args.base.relative_to(ROOT) if args.base.is_relative_to(ROOT) else args.base
    # Record, announce, then signal: a run that fails anywhere on the way must end as an error,
    # never with a list match annotation, exit status 1 or a report marked ready for upload.
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        print(command("notice", NOTICE, title=TITLE))
        verdict, rows, annotations = run(args.base, args.head, shown)
        record(args.report, verdict, rows, base.as_posix(), shown)
        announce(annotations, args.report)
    except GateError as exc:
        return fail(str(exc), args.report)
    # Anything uncaught would end the process with status 1, which means a list match.
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            traceback.print_exc()
        problem = f"운영 오류: 게이트 내부 오류입니다({type(exc).__name__})."
        return fail(problem, args.report)
    return 1 if verdict == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
