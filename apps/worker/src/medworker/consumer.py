"""SQS consumer.

Three properties the old reindex script lacked:

  Durability: a message survives a worker crash and is redelivered after the visibility
  timeout, so nothing is lost because a pod was rescheduled.

  Backpressure: long polling plus a visibility timeout longer than the job means a slow
  ingest doesn't cause duplicate concurrent runs of the same job.

  Poison-pill containment: after `max_receives` failed attempts SQS routes the message to a
  DLQ instead of retrying forever. A message that always fails must stop
                 consuming the worker, or one bad input starves every good one.

Deletion happens only AFTER successful processing: at-least-once delivery is a feature
here, because the job is idempotent (content-hash ids + atomic alias swap).
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from types import FrameType
from typing import Any

import boto3

from medcore.config import get_settings
from medworker.ingest import ingest_corpus

logger = logging.getLogger("medworker.consumer")

_shutdown = asyncio.Event()


def _handle_signal(signum: int, _frame: FrameType | None) -> None:
    """Graceful shutdown: finish the in-flight message, then stop. Killing mid-ingest is
    safe (the alias still points at the old collection) but wasteful."""
    logger.info("signal %s received; finishing current message then exiting", signum)
    _shutdown.set()


def build_sqs_client(settings: Any) -> Any:
    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:  # LocalStack
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client("sqs", **kwargs)


async def handle_message(settings: Any, body: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one job. Unknown types raise so the message reaches the DLQ rather than
    being quietly acknowledged; a dropped job is worse than a visible failure."""
    job = body.get("job")
    if job == "ingest":
        pdf = Path(body.get("pdf_path") or "")
        if not pdf.is_file():
            raise FileNotFoundError(f"corpus not found: {pdf}")
        result = await ingest_corpus(
            settings, pdf, alias=body.get("alias") or settings.qdrant_collection,
            limit=body.get("limit"),
        )
        return {
            "collection": result.collection, "alias": result.alias,
            "chunks": result.chunks, "duration_s": round(result.duration_s, 1),
            "previous_collection": result.previous_collection,
        }
    if job == "retention":
        from medworker.maintenance import run_retention

        return await run_retention(settings)
    raise ValueError(f"unknown job type: {job!r}")


async def consume_forever(settings: Any) -> None:
    sqs = build_sqs_client(settings)
    queue_url = settings.sqs_queue_url
    logger.info("worker polling %s", queue_url)

    while not _shutdown.is_set():
        response = await asyncio.to_thread(
            sqs.receive_message,
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=settings.worker_poll_seconds,  # long poll: no busy-wait
            VisibilityTimeout=settings.worker_visibility_timeout,
            AttributeNames=["ApproximateReceiveCount"],
        )
        for message in response.get("Messages", []):
            receipt = message["ReceiptHandle"]
            receives = int(message.get("Attributes", {}).get("ApproximateReceiveCount", 1))
            try:
                body = json.loads(message["Body"])
                logger.info("processing job (attempt %s): %s", receives, body.get("job"))
                result = await handle_message(settings, body)
                # Delete only after success, which is what makes redelivery-on-crash work.
                await asyncio.to_thread(
                    sqs.delete_message, QueueUrl=queue_url, ReceiptHandle=receipt
                )
                logger.info("job complete: %s", result)
            except Exception:
                # No delete => SQS redelivers after the visibility timeout, and routes to
                # the DLQ once maxReceiveCount is exceeded. Retry policy lives in the
                # queue configuration, not in this loop.
                logger.exception(
                    "job failed (attempt %s/%s)", receives, settings.worker_max_receives
                )


def main() -> None:  # pragma: no cover - entrypoint
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if not settings.sqs_queue_url:
        logger.error("SQS_QUEUE_URL is not set")
        sys.exit(1)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    asyncio.run(consume_forever(settings))
