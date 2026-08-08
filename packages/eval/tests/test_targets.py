from pathlib import Path

import pytest

from medeval.paths import DEMO_DIR, REPO_ROOT
from medeval.targets import demo_cwd, get_target


def test_repo_root_resolves_to_actual_repo() -> None:
    assert (REPO_ROOT / "pyproject.toml").exists()
    assert DEMO_DIR.name == "demo"


def test_demo_cwd_restores_previous_directory() -> None:
    before = Path.cwd()
    with demo_cwd():
        assert Path.cwd() == DEMO_DIR
    assert Path.cwd() == before


def test_unknown_target_raises() -> None:
    with pytest.raises(ValueError, match="unknown target"):
        get_target("nope")
