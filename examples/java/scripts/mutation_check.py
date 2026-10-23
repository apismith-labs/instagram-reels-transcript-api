#!/usr/bin/env python3
"""Prove four safety regressions are caught, using isolated temporary Maven copies."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

MODULE = pathlib.Path(__file__).resolve().parents[1]
MUTATIONS = [
    (
        "blank errMsg is misclassified as actor_error",
        "src/main/java/com/apismith/instagram/transcriptapi/TranscriptClient.java",
        "if(!err.asText().isBlank())return new Classification(Status.ACTOR_ERROR,null,List.of(),err.asText());",
        "if(true)return new Classification(Status.ACTOR_ERROR,null,List.of(),err.asText());",
        "com.apismith.instagram.transcriptapi.TranscriptClientTest#blankOrNullErrMsgDoesNotOverrideTranscript",
        "blankOrNullErrMsgDoesNotOverrideTranscript",
    ),
    (
        "CSV continues after a terminal Journal failure",
        "src/main/java/com/apismith/instagram/transcriptapi/TranscriptClient.java",
        'if(journalFailure||"creation_unknown".equals(ex.stage())){stopped=true;fatal=JsonSupport.redact(ex.getMessage());break;}',
        'if("creation_unknown".equals(ex.stage())){stopped=true;fatal=JsonSupport.redact(ex.getMessage());break;}',
        "com.apismith.instagram.transcriptapi.TranscriptClientTest#csvJournalFailureStopsLaterRows",
        "csvJournalFailureStopsLaterRows",
    ),
    (
        "JDK transport follows a POST redirect",
        "src/main/java/com/apismith/instagram/transcriptapi/JdkHttpTransport.java",
        "followRedirects(HttpClient.Redirect.NEVER)",
        "followRedirects(HttpClient.Redirect.NORMAL)",
        "com.apismith.instagram.transcriptapi.JdkHttpTransportTest#postRedirectIsReturnedAndNeverFollowed",
        "postRedirectIsReturnedAndNeverFollowed",
    ),
    (
        "creation_unknown exit code drifts from 10",
        "src/main/java/com/apismith/instagram/cli/Main.java",
        'catch(CreationUnknownException e){return failure(err,"CreationUnknownException",e,10);}',
        'catch(CreationUnknownException e){return failure(err,"CreationUnknownException",e,8);}',
        "com.apismith.instagram.cli.MainTest#creationUnknownUsesExitCodeTen",
        "creationUnknownUsesExitCodeTen",
    ),
]


def copy_module(destination: pathlib.Path) -> None:
    shutil.copy2(MODULE / "pom.xml", destination / "pom.xml")
    shutil.copytree(MODULE / "src", destination / "src")


def mutate(path: pathlib.Path, before: str, after: str) -> None:
    source = path.read_text(encoding="utf-8")
    if source.count(before) != 1:
        raise RuntimeError(f"expected exactly one mutation point in {path.name}; found {source.count(before)}")
    path.write_text(source.replace(before, after), encoding="utf-8")


def expected_test_failure(reports: pathlib.Path, witness: str) -> str | None:
    for report in reports.glob("TEST-*.xml"):
        try:
            root = ET.parse(report).getroot()
        except (OSError, ET.ParseError):
            continue
        for case in root.iter("testcase"):
            if witness in case.attrib.get("name", ""):
                for child in case:
                    if child.tag in {"failure", "error"}:
                        return (child.attrib.get("message") or (child.text or "test failed")).strip().splitlines()[0]
    return None


def run_one(case: tuple[str, str, str, str, str, str]) -> tuple[bool, str]:
    label, relative, before, after, selector, witness = case
    with tempfile.TemporaryDirectory(prefix="java-mutation-") as raw:
        temp = pathlib.Path(raw)
        copy_module(temp)
        mutate(temp / relative, before, after)
        command = ["mvn", "-B", "-o", "-q"]
        settings = os.environ.get("MAVEN_SETTINGS")
        repository = os.environ.get("MAVEN_REPO_LOCAL")
        if settings:
            command.extend(["-s", settings])
        if repository:
            command.append(f"-Dmaven.repo.local={repository}")
        command.extend(["-f", str(temp / "pom.xml"), f"-Dtest={selector}", "test"])
        result = subprocess.run(command, cwd=temp, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        failure = expected_test_failure(temp / "target/surefire-reports", witness)
        detected = result.returncode != 0 and failure is not None
        evidence = f"{label}: test={selector}; exit={result.returncode}; expected test failure={'yes' if detected else 'no'}"
        if detected:
            evidence += f"; observed failure={failure}"
        if not detected:
            evidence += "\n" + result.stdout[-4000:]
        return detected, evidence


def main() -> int:
    results = [run_one(item) for item in MUTATIONS]
    for _, evidence in results:
        print(evidence)
    passed = sum(1 for detected, _ in results if detected)
    print(f"Mutation detection: {passed}/{len(MUTATIONS)} expected regressions caught")
    return 0 if passed == len(MUTATIONS) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Mutation check blocked: {exc}", file=sys.stderr)
        raise SystemExit(2)
