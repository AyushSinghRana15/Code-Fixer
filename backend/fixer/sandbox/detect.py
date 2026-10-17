"""Work out how to install a repo and run its tests, without an LLM (Plan.md §4, phase 2)."""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path

VENV = ".fixer-venv"
JUNIT_DIR = ".fixer"


class UnsupportedRepo(Exception):
    pass


@dataclass
class EnvSpec:
    language: str
    framework: str
    setup: list[str]  # shell commands, run once with network access
    test_all: str
    test_one: str  # contains {selector}
    junit_globs: list[str] = field(default_factory=list)
    clean: str = ""  # removes old reports before each run
    test_patterns: tuple[str, ...] = ()
    docker_image: str = "debian:stable-slim"
    selector_hint: str = ""  # tells the model how to address one test

    def is_test_path(self, rel: str) -> bool:
        name = rel.rsplit("/", 1)[-1]
        return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p) for p in self.test_patterns)


def _python(root: Path, has_uv: bool) -> EnvSpec:
    py = f"{VENV}/bin/python"
    install = f"uv pip install -q --python {py}" if has_uv else f"{py} -m pip install -q"
    setup = [f"uv venv {VENV} -q" if has_uv else f"python3 -m venv {VENV}"]
    if not has_uv:
        setup.append(f"{py} -m pip install -q --upgrade pip")
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists() or (root / "setup.cfg").exists():
        setup.append(f"{install} -e '.[test]' 2>/dev/null || {install} -e '.[dev]' 2>/dev/null || {install} -e .")
    for req in (
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-test.txt",
        "dev-requirements.txt",
        "test-requirements.txt",
        "requirements/dev.txt",
        "requirements/test.txt",
    ):
        if (root / req).exists():
            setup.append(f"{install} -r {req}")
    setup.append(f"{install} pytest")
    base = f"{py} -m pytest -q --tb=short -p no:cacheprovider -o junit_family=xunit1 --junitxml={JUNIT_DIR}/junit.xml"
    return EnvSpec(
        language="python",
        framework="pytest",
        setup=setup,
        test_all=base,
        test_one=base + " {selector}",
        junit_globs=[f"{JUNIT_DIR}/junit.xml"],
        clean=f"rm -rf {JUNIT_DIR} && mkdir -p {JUNIT_DIR}",
        test_patterns=("test_*.py", "*_test.py", "tests/*", "*/tests/*", "conftest.py"),
        docker_image="python:3.12-slim",
        selector_hint="a pytest node id, e.g. tests/test_cart.py::test_discount",
    )


def _node(root: Path) -> EnvSpec:
    pkg = json.loads((root / "package.json").read_text() or "{}")
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    install = (
        "npm ci --no-audit --no-fund" if (root / "package-lock.json").exists() else "npm install --no-audit --no-fund"
    )
    common = dict(
        language="node",
        setup=[install],
        clean=f"rm -rf {JUNIT_DIR} && mkdir -p {JUNIT_DIR}",
        test_patterns=("*.test.*", "*.spec.*", "__tests__/*", "*/__tests__/*", "test/*", "tests/*"),
        docker_image="node:22-slim",
    )
    if "vitest" in deps:
        base = f"npx vitest run --reporter=default --reporter=junit --outputFile.junit={JUNIT_DIR}/junit.xml"
        return EnvSpec(
            framework="vitest",
            test_all=base,
            test_one=base + " {selector}",
            junit_globs=[f"{JUNIT_DIR}/junit.xml"],
            selector_hint="a test file path",
            **common,
        )
    if "jest" in deps:
        return EnvSpec(
            framework="jest",
            test_all="npx jest --ci",
            test_one="npx jest --ci {selector}",
            selector_hint="a test file path",
            **common,
        )
    return EnvSpec(
        framework="npm test",
        test_all="npm test --silent",
        test_one="npm test --silent -- {selector}",
        selector_hint="a test file path",
        **common,
    )


def _java(root: Path) -> EnvSpec:
    patterns = ("src/test/*", "*Test.java", "*Tests.java")
    if (root / "pom.xml").exists():
        return EnvSpec(
            language="java",
            framework="maven",
            setup=["mvn -q -B -DskipTests test-compile"],
            test_all="mvn -q -B test",
            test_one="mvn -q -B test -Dsurefire.failIfNoSpecifiedTests=false -Dtest={selector}",
            junit_globs=["target/surefire-reports/TEST-*.xml"],
            clean="rm -rf target/surefire-reports",
            test_patterns=patterns,
            docker_image="maven:3.9-eclipse-temurin-21",
            selector_hint="ClassName#method, e.g. CartTest#appliesDiscount",
        )
    gradle = "./gradlew" if (root / "gradlew").exists() else "gradle"
    return EnvSpec(
        language="java",
        framework="gradle",
        setup=[f"{gradle} -q testClasses"],
        test_all=f"{gradle} -q test",
        test_one=f"{gradle} -q test --tests {{selector}}",
        junit_globs=["build/test-results/test/TEST-*.xml"],
        clean="rm -rf build/test-results",
        test_patterns=patterns,
        docker_image="gradle:8-jdk21",
        selector_hint="a fully-qualified test name, e.g. com.acme.CartTest.appliesDiscount",
    )


def detect(root: Path, has_uv: bool = False) -> EnvSpec:
    if (root / "pom.xml").exists() or (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        return _java(root)
    if (root / "package.json").exists():
        return _node(root)
    py_markers = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pytest.ini", "tox.ini")
    if any((root / m).exists() for m in py_markers) or any(root.glob("**/test_*.py")):
        return _python(root, has_uv)
    raise UnsupportedRepo("Couldn't detect a Python, JS/TS or Java project (no pyproject, package.json, pom.xml…).")
