"""Tests for scripts/version.py release helper."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "version.py"
MANIFEST = Path("custom_components/yahoofinance/manifest.json")


def run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the script inside the repo."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def git(repo: Path, *args: str) -> None:
    """Run git in the repo."""
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def write_manifest(repo: Path, **fields) -> None:
    """Write the manifest."""
    path = repo / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"domain": "yahoofinance", "name": "Yahoo Finance", "version": "2.1.1"}
    data.update(fields)
    path.write_text(json.dumps(data, indent=2) + "\n")


def commit(repo: Path, message: str = "c") -> None:
    """Commit everything."""
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Create a repo with a released v2.1.1."""
    git(tmp_path, "init", "-q")
    write_manifest(tmp_path)
    (tmp_path / "README.md").write_text("readme\n")
    commit(tmp_path)
    git(tmp_path, "tag", "v2.1.1")
    return tmp_path


@pytest.mark.parametrize(
    ("bump", "expected"),
    [("patch", "2.1.2"), ("minor", "2.2.0"), ("major", "3.0.0")],
)
def test_next_version_bumps(repo: Path, bump: str, expected: str) -> None:
    """Next version honours the bump kind."""
    assert run(repo, "next", "--bump", bump).stdout.strip() == expected


def test_next_version_uses_highest_tag(repo: Path) -> None:
    """Tags newer than the manifest win, e.g. release commits not on master."""
    git(repo, "tag", "v2.4.0")
    assert run(repo, "next").stdout.strip() == "2.4.1"
    assert run(repo, "latest-tag").stdout.strip() == "v2.4.0"


def test_unchanged_after_docs_only_change(repo: Path) -> None:
    """README changes do not trigger a release."""
    (repo / "README.md").write_text("new readme\n")
    commit(repo)
    assert run(repo, "changed").returncode == 1


def test_unchanged_when_only_version_differs(repo: Path) -> None:
    """A tag whose release commit bumped the version is not a change."""
    write_manifest(repo, version="2.1.2")
    commit(repo, "release")
    git(repo, "tag", "v2.1.2")
    git(repo, "checkout", "-q", "HEAD~1")
    assert run(repo, "changed").returncode == 1


def test_changed_when_integration_code_changes(repo: Path) -> None:
    """Code changes trigger a release."""
    (repo / "custom_components/yahoofinance/sensor.py").write_text("x = 1\n")
    commit(repo)
    assert run(repo, "changed").returncode == 0


def test_changed_when_manifest_content_changes(repo: Path) -> None:
    """Manifest changes other than the version trigger a release."""
    write_manifest(repo, requirements=["foo==1"])
    commit(repo)
    assert run(repo, "changed").returncode == 0


def test_set_and_check(repo: Path) -> None:
    """Set writes the version and check verifies it."""
    assert run(repo, "set", "v2.2.0").returncode == 0
    assert json.loads((repo / MANIFEST).read_text())["version"] == "2.2.0"
    assert run(repo, "check", "2.2.0").returncode == 0
    assert run(repo, "check", "2.2.1").returncode == 1
