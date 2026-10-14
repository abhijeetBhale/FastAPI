"""Idempotency for mutating requests.

A client that retries `POST` after a timeout must not create a second row. It
sends `Idempotency-Key: <uuid>`, and on replay we return the stored response.

```text
first request   -> no key row -> do the work -> store {status, response}
replayed request -> key found -> return the stored response, do no work
```
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from database import utcnow
from models.idempotency_key import IdempotencyKey

#: Keys older than this are treated as absent and pruned.
RETENTION_HOURS = 24


class IdempotencyService:
    def __init__(self, db: Session):
        self.db = db

    def lookup(self, key: str, endpoint: str) -> Optional[IdempotencyKey]:
        found = self.db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.key == key,
                IdempotencyKey.endpoint == endpoint,
            )
        ).scalar_one_or_none()

        if found is None:
            return None
        if found.expires_at and found.expires_at < utcnow():
            self.db.delete(found)
            self.db.commit()
            return None
        return found

    def store(
        self,
        key: str,
        endpoint: str,
        status_code: int,
        response: dict[str, Any],
    ) -> None:
        self.db.add(
            IdempotencyKey(
                key=key,
                endpoint=endpoint,
                status_code=status_code,
                response=response,
                expires_at=utcnow() + timedelta(hours=RETENTION_HOURS),
            )
        )
        self.db.commit()

    def purge_expired(self) -> int:
        result = self.db.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.expires_at < utcnow()
            )
        )
        self.db.commit()
        return result.rowcount