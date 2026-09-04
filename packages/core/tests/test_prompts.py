import pytest

from medcore.prompts import list_prompts, load_prompt


def test_system_prompt_loads_and_has_stable_sha() -> None:
    p1 = load_prompt("system", "v1")
    p2 = load_prompt("system", "v1")
    assert p1.sha256 == p2.sha256
    assert len(p1.sha256) == 64
    assert p1.version == "v1"


def test_system_prompt_encodes_safety_and_citation_rules() -> None:
    """The safety layer the baseline lacked lives here as reviewable text.
    Assert on tokens, not exact phrasing, so markdown emphasis doesn't make it brittle."""
    text = load_prompt("system", "v1").text.lower()
    assert "diagnose" in text  # refusal policy: no personal diagnosis
    assert "dosage" in text  # refusal policy: no dosages
    assert "emergency" in text  # emergency redirect
    assert "cite" in text  # citation requirement
    assert "reference data" in text  # instruction-hierarchy / injection framing


def test_answer_prompt_renders_placeholders() -> None:
    rendered = load_prompt("answer", "v1").render(context="CTX", question="Q?")
    assert "CTX" in rendered and "Q?" in rendered


def test_missing_placeholder_raises_loudly() -> None:
    with pytest.raises(KeyError):
        load_prompt("answer", "v1").render(context="only context")  # no question


def test_unknown_prompt_lists_available() -> None:
    with pytest.raises(FileNotFoundError, match="available:"):
        load_prompt("nonexistent", "v1")


def test_list_prompts_finds_registry() -> None:
    names = list_prompts()
    assert "system_v1" in names and "answer_v1" in names
