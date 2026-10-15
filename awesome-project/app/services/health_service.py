"""Health checks.

Two separate questions, deliberately kept apart:

* **Liveness** — is this process alive and able to answer HTTP? It must not
  touch the database. A liveness probe that fails when the database is down
  causes orchestrators to restart an otherwise perfectly healthy process, which
  turns a database outage into a crash loop.

* **Readiness** — can the app actually serve a request right now? This one does
  connect, and reports how long it took.
"""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.orm import Session


class HealthService:
    def __init__(self, db: Session):
        self.db = db

    def check_database(self) -> tuple[bool, float, str | None]:
        """Run a trivial round-trip. Returns (ok, latency_ms, error)."""
        started = time.perf_counter()
        try:
            self.db.execute(text("SELECT 1"))
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            return False, elapsed, f"{type(exc).__name__}: {exc}"
        elapsed = (time.perf_counter() - started) * 1000
        return True, elapsed, None