"""S9: idempotency, versioning, and the alias-swap invariant (D11)."""

from __future__ import annotations

from medworker.ingest import _next_collection_name, chunk_id

# --- idempotency -------------------------------------------------------------------


def test_chunk_id_is_content_addressed() -> None:
    """SQS delivers at-least-once, so a duplicate message MUST overwrite the same points
    rather than duplicate them. Content-addressed ids are what make that true."""
    a = chunk_id("Cirrhosis is scarring of the liver.", 42)
    b = chunk_id("Cirrhosis is scarring of the liver.", 42)
    assert a == b


def test_chunk_id_distinguishes_text_and_page() -> None:
    base = chunk_id("same text", 1)
    assert base != chunk_id("same text", 2)  # same text, different page
    assert base != chunk_id("other text", 1)  # same page, different text


# --- collection versioning ---------------------------------------------------------


def test_version_increments_from_existing_alias_target() -> None:
    assert _next_collection_name("gale", "gale_v1") == "gale_v2"
    assert _next_collection_name("gale", "gale_v9") == "gale_v10"


def test_first_ingest_gets_a_fresh_name() -> None:
    name = _next_collection_name("gale", None)
    assert name.startswith("gale_v")


def test_unparseable_previous_name_does_not_crash() -> None:
    """An alias pointing at a hand-created collection must not break the next ingest."""
    name = _next_collection_name("gale", "some_legacy_collection")
    assert name.startswith("gale_v")


def test_new_name_never_collides_with_previous() -> None:
    """Reusing a name would delete the rollback target before the swap succeeds."""
    for previous in ("gale_v1", "gale_v42", None, "weird"):
        assert _next_collection_name("gale", previous) != previous
