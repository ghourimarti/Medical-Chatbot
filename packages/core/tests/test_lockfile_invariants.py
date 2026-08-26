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


# --- .env parsing traps -------------------------------------------------------------

ENV_EXAMPLE = REPO_ROOT / ".env.example"


def test_no_env_value_is_actually_a_comment() -> None:
    """`VAR=   # explanation` gives python-dotenv the COMMENT as the value.

    A trailing comment is only stripped when a real value precedes it; with an empty value
    the `#...` IS the value. That silently turned VLLM_RUNPOD_URL, OPENAI_API_KEY and
    SQS_QUEUE_URL into non-empty strings, so the failover chain believed two GPU venues
    were configured, the OpenAI leg believed it had a key, and the worker believed it had a
    queue. Every one of those reads as "configured" to code that only checks emptiness.

    Put the comment on its own line above an empty assignment.
    """
    from dotenv import dotenv_values

    if not ENV_EXAMPLE.is_file():
        pytest.skip(".env.example not present")
    offenders = {
        k: v for k, v in dotenv_values(ENV_EXAMPLE).items()
        if v is not None and v.lstrip().startswith("#")
    }
    assert not offenders, (
        f"{len(offenders)} .env value(s) are actually comments: {sorted(offenders)}. "
        "Move the comment above the line: `# NAME — why`, then `NAME=`."
    )


def test_env_example_documents_only_names_something_reads() -> None:
    """A name nothing reads is silent (P6.4.3): Settings uses extra='ignore', so a typo or
    a renamed variable does nothing at all and the symptom appears far from the cause.
    Every documented name must be a real Settings field, an infra name used by
    compose/Makefile/Helm, or explicitly tagged [inert]."""
    import re

    from dotenv import dotenv_values

    from medcore.config import Settings

    if not ENV_EXAMPLE.is_file():
        pytest.skip(".env.example not present")
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    live_fields = {f.upper() for f in Settings.model_fields}
    compose = "".join(
        f.read_text(encoding="utf-8") for f in sorted(REPO_ROOT.glob("docker-compose*.y*ml"))
    )
    infra = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", compose))
    infra |= set(re.findall(r"\$\$?\{?([A-Z][A-Z0-9_]{3,})", (REPO_ROOT / "Makefile").read_text(
        encoding="utf-8")))
    # The WEB TIER reads .env too (S10.14). It is a real consumer, not infrastructure, so
    # its `process.env.NAME` accesses count as "something reads this" exactly as a Settings
    # field does. Added because this guard fired on UPSTREAM_TIMEOUT_MS — correctly, since
    # it only knew about Python readers, while the variable is read by src/lib/env.ts. A
    # guard whose scope lags the codebase produces false positives, and false positives are
    # how a guard gets disabled.
    web_src = REPO_ROOT / "apps" / "web" / "src"
    if web_src.is_dir():
        web_text = "".join(
            f.read_text(encoding="utf-8", errors="ignore")
            for f in web_src.rglob("*.ts*")
        )
        infra |= set(re.findall(r"process\.env\.([A-Z][A-Z0-9_]*)", web_text))

    # A name may also be tagged [inert] / [infra], a deliberate claim that it is read
    # somewhere ungreppable (boto3 reading AWS_* straight from the environment) or not yet
    # read at all.
    #
    # The tag used to be required on the SAME line as the assignment. That stopped working
    # when .env moved every comment ABOVE its variable — trailing comments are parsed
    # differently by python-dotenv, a shell `source`, and everything else, and this repo
    # has been bitten by that twice. The tag is now looked for in the comment block
    # immediately above, which is where comments now live.
    tagged = set(re.findall(r"^([A-Z][A-Z0-9_]*)=.*?\[(?:inert|infra)\]", text, re.M))
    tagged |= set(re.findall(r"^# ([A-Z][A-Z0-9_]*) — .*", text, re.M))

    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if not match:
            continue
        # Walk back over the contiguous comment block that documents this variable.
        for above in range(index - 1, -1, -1):
            if not lines[above].startswith("#"):
                break
            if "[infra]" in lines[above] or "[inert]" in lines[above]:
                tagged.add(match.group(1))
                break

    unknown = sorted(
        k for k in dotenv_values(ENV_EXAMPLE)
        if k not in live_fields and k not in infra and k not in tagged
    )
    assert not unknown, (
        f"{len(unknown)} documented name(s) are read by nothing and are not tagged "
        f"[infra]/[inert]: {unknown}"
    )
