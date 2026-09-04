"""Operator CLI: enqueue jobs, or run one directly.

`--direct` bypasses the queue for local development and the initial bootstrap, before a
queue exists. It is not the production path: without SQS there is no retry, no DLQ, and no
protection against two operators ingesting at once.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from medcore.config import get_settings
from medworker.ingest import ingest_corpus

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PDF = REPO_ROOT / "demo" / "data" / "The_GALE_ENCYCLOPEDIA_of_MEDICINE_SECOND.pdf"


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(prog="medworker-ingest")
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--alias", default=None, help="defaults to QDRANT_COLLECTION")
    ap.add_argument("--limit", type=int, default=None, help="dev only — NEVER for evaluation")
    ap.add_argument("--direct", action="store_true", help="run now instead of enqueuing")
    args = ap.parse_args()

    settings = get_settings()
    alias = args.alias or settings.qdrant_collection

    if args.direct or not settings.sqs_queue_url:
        result = asyncio.run(
            ingest_corpus(settings, args.pdf, alias=alias, limit=args.limit)
        )
        print(
            f"done: {result.chunks} chunks -> {result.collection} "
            f"(alias {result.alias}, was {result.previous_collection}) "
            f"in {result.duration_s:.0f}s"
        )
        return

    from medworker.consumer import build_sqs_client

    body = {"job": "ingest", "pdf_path": str(args.pdf), "alias": alias, "limit": args.limit}
    sqs = build_sqs_client(settings)
    sqs.send_message(QueueUrl=settings.sqs_queue_url, MessageBody=json.dumps(body))
    print(f"enqueued: {body}")
