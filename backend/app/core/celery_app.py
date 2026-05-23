"""
Celery application — background task queue backed by Redis.

Broker  = Redis db 1 (task messages: "please run this task")
Backend = Redis db 2 (task results: "this task finished with result X")

Workers run in a separate process:
    celery -A app.core.celery_app worker --loglevel=info
"""

import os

from celery import Celery

celery_app = Celery(
    "nexus_ai",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
    include=["app.workers.document_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,          # task shows STARTED state while running
    task_acks_late=True,              # ack only after task completes (safer on crash)
    worker_prefetch_multiplier=1,     # one task at a time per worker (fair for long tasks)
    task_routes={
        "app.workers.document_tasks.*": {"queue": "documents"},
    },
)
