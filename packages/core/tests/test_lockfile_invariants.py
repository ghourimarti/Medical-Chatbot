"""Workspace-level supply-chain invariants, enforced against uv.lock (P6.1a.6).

These are not unit tests of any module — they are guards on what the build is allowed to
pull in. A dependency change that violates one of them is a deployment problem that would
otherwise only surface as a slow CI runner or a disk-full failure, hours later and far
from the edit that caused it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCKFILE = REPO_ROOT / "uv.lock"

# Names that only exist to run CUDA kernels. Every service in this workspace is CPU-only
# (D5: bge-large + cross-encoder on CPU pods); the GPU venues are separate vLLM/SGLang
# containers with their own images and are not resolved from this lock.
CUDA_PACKAGE_RE = re.compile(r'^name = "(nvidia-[\w-]+|triton|cuda-[\w-]+)"', re.MULTILINE)


@pytest.fixture(scope="module")
def lock_text() -> str:
    if not LOCKFILE.is_file():
        pytest.skip("uv.lock not present")
    return LOCKFILE.read_text(encoding="utf-8")


def test_no_cuda_packages_in_lock(lock_text: str) -> None:
    """CUDA wheels are ~3.4 GB of kernels no CPU service can execute, and they are
    linux-only — so they are invisible in a Windows dev venv and only appear in the
    images, which is exactly where the cost lands (3 images over a CI runner's disk).

    If this fails: torch resolved from PyPI instead of the CPU index. The fix is not to
    delete the packages but to keep `torch = { index = "pytorch-cpu" }` binding — note it
    only binds where torch is a DECLARED dependency, never as a transitive one.
    """
    found = sorted(set(CUDA_PACKAGE_RE.findall(lock_text)))
    assert not found, (
        f"{len(found)} CUDA package(s) back in uv.lock: {found[:8]}"
        " — check [tool.uv.sources] torch pin and that torch stays explicitly declared"
    )


def test_torch_resolves_from_the_cpu_index(lock_text: str) -> None:
    """The positive form of the check above: absence of nvidia-* could also mean torch
    vanished entirely. This asserts the intended source is actually in use."""
    block = re.search(r'\[\[package\]\]\nname = "torch"\n(.*?)(?=\n\[\[package\]\])',
                      lock_text, re.DOTALL)
    assert block, "torch not found in uv.lock at all"
    assert "download.pytorch.org/whl/cpu" in block.group(1), (
        "torch is no longer resolving from the PyTorch CPU index"
    )
