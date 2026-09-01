"""Every third-party module the application imports must be declared in pyproject.toml.

The container installs `[project].dependencies` and nothing else. A module that is
imported but never declared therefore works perfectly in development - where a transitive
install, or a package a developer once added by hand, happens to provide it - and then
kills the container on import the moment it is deployed. The platform reports that as a
failed or, worse, a timed-out deploy, which says nothing about the missing package.

This is not hypothetical: `sse-starlette` and `cryptography` were both absent from the
image's dependency list while present in pyproject.toml, because the Dockerfile carried a
second copy of the list that nobody remembered to update. The first killed the service on
boot; the second would have silently downgraded OAuth token encryption to the weaker
fallback in `app.services.token_vault`.

These tests turn that class of deployment failure into a test failure.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = BACKEND_ROOT / "app"
PYPROJECT = BACKEND_ROOT / "pyproject.toml"
DOCKERFILE = BACKEND_ROOT / "Dockerfile"

#: First-party package names, which are never installed from an index.
FIRST_PARTY = {"app", "tests"}


def normalize(name: str) -> str:
    """PEP 503 name normalisation, so `sse_starlette` and `sse-starlette` compare equal."""
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_dependencies() -> set[str]:
    """Normalised distribution names from `[project].dependencies`."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    names = set()
    for spec in data["project"]["dependencies"]:
        # Strip environment markers, extras and version constraints: the name is the
        # leading run of name characters.
        match = re.match(r"^\s*([A-Za-z0-9._-]+)", spec)
        assert match, f"could not read a distribution name from {spec!r}"
        names.add(normalize(match.group(1)))
    return names


def imported_modules() -> dict[str, set[str]]:
    """Top-level module name -> the app files that import it.

    Relative imports carry no distribution and are skipped.
    """
    found: dict[str, set[str]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                if top in sys.stdlib_module_names or top in FIRST_PARTY:
                    continue
                found.setdefault(top, set()).add(str(path.relative_to(BACKEND_ROOT)))
    return found


def satisfying_distributions(module: str) -> set[str]:
    """Normalised distributions that provide `module`, as installed.

    Falls back to the module's own name when the package is not installed here - several
    providers import their SDK lazily inside a function precisely so the application runs
    without it, so absence locally is expected and is not what this test is checking.
    """
    dists = packages_distributions().get(module)
    if dists:
        return {normalize(d) for d in dists}
    return {normalize(module)}


class TestDeclaredDependencies:
    def test_every_imported_package_is_declared(self):
        declared = declared_dependencies()
        undeclared: dict[str, set[str]] = {}

        for module, users in imported_modules().items():
            if not (satisfying_distributions(module) & declared):
                undeclared[module] = users

        assert not undeclared, (
            "These modules are imported by the application but are not in "
            "pyproject.toml's [project].dependencies. The container installs only what is "
            "declared there, so it will fail on import at deploy time:\n"
            + "\n".join(
                f"  {module}  (imported by {', '.join(sorted(users))})"
                for module, users in sorted(undeclared.items())
            )
        )

    def test_the_packages_this_broke_on_are_declared(self):
        """A named regression guard for the two that actually went missing."""
        declared = declared_dependencies()
        assert "sse-starlette" in declared, "SSE realtime endpoints import it at module level"
        assert "cryptography" in declared, (
            "Without it app.services.token_vault falls back from AES-256-GCM to a weaker "
            "cipher for OAuth tokens at rest, warning but not failing."
        )

    def test_dependency_specifiers_are_parseable(self):
        """The image builds its requirements file from these strings, so they must parse."""
        packaging_requirements = pytest.importorskip("packaging.requirements")
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        for spec in data["project"]["dependencies"]:
            packaging_requirements.Requirement(spec)


class TestDockerfileHasNoSecondList:
    """The root cause was a duplicated dependency list, not a forgotten package."""

    def test_image_installs_from_pyproject(self):
        content = DOCKERFILE.read_text(encoding="utf-8")
        assert "pip install -r requirements.txt" in content, (
            "The image must install from a requirements file generated out of "
            "pyproject.toml, so the two can never disagree."
        )
        assert "tomllib" in content, "requirements.txt should be generated from pyproject.toml"

    def test_no_hand_written_package_list(self):
        """Catch a literal list creeping back in."""
        content = DOCKERFILE.read_text(encoding="utf-8")
        # A pinned specifier inside a quoted string is what a hand-maintained list looks
        # like. Comments are exempt so the reasoning above the RUN can name packages.
        code = "\n".join(
            line for line in content.splitlines() if not line.lstrip().startswith("#")
        )
        literals = re.findall(r"\"[A-Za-z0-9._-]+(?:\[[a-z]+\])?[<>=]=[0-9]", code)
        assert not literals, (
            "The Dockerfile appears to pin packages directly: "
            f"{literals}. Add them to pyproject.toml instead - a second list drifts."
        )
