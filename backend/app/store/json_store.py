"""File-locked JSON repository used as the V1 "database".

All mutation paths flow through ``with self._lock: load -> mutate -> flush``.
The flush is atomic: write to a temp file in the same directory, ``os.replace``.
Reads outside a write block return a fresh deepcopy so callers can mutate the
returned dict without contaminating the in-memory snapshot.

The whole thing is intentionally swappable for a Postgres-backed
``PostgresStore`` later; method signatures are the migration boundary.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from filelock import FileLock

from .ids import new_id

log = logging.getLogger(__name__)

# Windows ``os.replace`` is implemented via MoveFileEx and can transiently
# fail with WinError 5 / 32 when an editor, indexer, or AV holds a read
# handle on the destination for a few ms. Retrying the rename clears it
# every time in practice. POSIX systems get the same loop with one shot
# and exit instantly.
_REPLACE_MAX_ATTEMPTS = 12
_REPLACE_BACKOFF_SECONDS = 0.05

_EMPTY_DB: dict[str, Any] = {
    "users": {},
    "watch_items": {},
    "source_configs": {},
    "source_documents": {},
    "security_events": {},
    "event_signals": [],
    "relevance_matches": [],
    "alerts": {},
    "runs": [],
    "wire_catalog_cache": None,
}


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    raise TypeError(f"object of type {type(value)!r} is not JSON serializable")


def _dump_json(value: Any) -> str:
    return json.dumps(value, default=_json_default, indent=2, sort_keys=True)


class _Repo:
    """Base class — holds the parent store reference and the section key."""

    section: str

    def __init__(self, store: "JsonStore") -> None:
        self._store = store


class _UsersRepo(_Repo):
    section = "users"

    def all(self) -> list[dict[str, Any]]:
        return list(self._store.snapshot()[self.section].values())

    def get(self, user_id: str) -> dict[str, Any] | None:
        return self._store.snapshot()[self.section].get(user_id)

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        for record in self._store.snapshot()[self.section].values():
            if record.get("email", "").lower() == email.lower():
                return record
        return None

    def upsert_by_email(self, email: str) -> dict[str, Any]:
        with self._store._write() as db:
            for record in db[self.section].values():
                if record.get("email", "").lower() == email.lower():
                    return copy.deepcopy(record)
            user_id = new_id("user")
            record = {
                "id": user_id,
                "email": email,
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            db[self.section][user_id] = record
            return copy.deepcopy(record)


class _WatchItemsRepo(_Repo):
    section = "watch_items"

    def by_user(self, user_id: str) -> list[dict[str, Any]]:
        return [
            record
            for record in self._store.snapshot()[self.section].values()
            if record.get("user_id") == user_id
        ]

    def replace_for_user(
        self, user_id: str, items: Iterable[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        with self._store._write() as db:
            db[self.section] = {
                wid: rec
                for wid, rec in db[self.section].items()
                if rec.get("user_id") != user_id
            }
            now = datetime.now(tz=timezone.utc).isoformat()
            written: list[dict[str, Any]] = []
            for raw in items:
                wid = new_id("watch_item")
                record = {
                    "id": wid,
                    "user_id": user_id,
                    "ecosystem": raw.get("ecosystem", "software"),
                    "name": raw["name"],
                    "raw_input": raw.get("raw_input", raw["name"]),
                    "aliases": list(raw.get("aliases", []) or []),
                    "version_spec": raw.get("version_spec"),
                    "created_at": now,
                }
                db[self.section][wid] = record
                written.append(copy.deepcopy(record))
            return written


class _SourceConfigsRepo(_Repo):
    section = "source_configs"

    def by_user(self, user_id: str) -> dict[str, Any] | None:
        return self._store.snapshot()[self.section].get(user_id)

    def replace_for_user(
        self, user_id: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        with self._store._write() as db:
            record = {
                "user_id": user_id,
                "config": config,
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            db[self.section][user_id] = record
            return copy.deepcopy(record)


class _SourceDocumentsRepo(_Repo):
    section = "source_documents"

    def all(self) -> list[dict[str, Any]]:
        return list(self._store.snapshot()[self.section].values())

    def has_recent_hash(self, content_hash: str, since: datetime) -> bool:
        snap = self._store.snapshot()[self.section]
        for record in snap.values():
            if record.get("content_hash") != content_hash:
                continue
            fetched = record.get("fetched_at")
            try:
                fetched_dt = datetime.fromisoformat(fetched)
            except (TypeError, ValueError):
                continue
            if fetched_dt.tzinfo is None:
                fetched_dt = fetched_dt.replace(tzinfo=timezone.utc)
            if fetched_dt >= since:
                return True
        return False

    def insert(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._store._write() as db:
            sd_id = record.get("id") or new_id("source_document")
            record = {**record, "id": sd_id}
            record.setdefault(
                "fetched_at", datetime.now(tz=timezone.utc).isoformat()
            )
            db[self.section][sd_id] = record
            return copy.deepcopy(record)


class _SecurityEventsRepo(_Repo):
    section = "security_events"

    def all(self) -> list[dict[str, Any]]:
        return list(self._store.snapshot()[self.section].values())

    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._store._write() as db:
            ev_id = record.get("id") or new_id("security_event")
            record = {**record, "id": ev_id}
            record["last_updated"] = datetime.now(tz=timezone.utc).isoformat()
            existing = db[self.section].get(ev_id)
            if existing is not None:
                merged = {**existing, **record}
                db[self.section][ev_id] = merged
                return copy.deepcopy(merged)
            record.setdefault("first_seen", record["last_updated"])
            db[self.section][ev_id] = record
            return copy.deepcopy(record)


class _EventSignalsRepo(_Repo):
    section = "event_signals"

    def append_many(self, signals: Iterable[dict[str, Any]]) -> None:
        with self._store._write() as db:
            db[self.section].extend(list(signals))


class _RelevanceMatchesRepo(_Repo):
    section = "relevance_matches"

    def append_many(self, matches: Iterable[dict[str, Any]]) -> None:
        with self._store._write() as db:
            db[self.section].extend(list(matches))


class _AlertsRepo(_Repo):
    section = "alerts"

    def has_for(self, user_id: str, event_id: str) -> bool:
        for record in self._store.snapshot()[self.section].values():
            if record.get("user_id") == user_id and record.get("event_id") == event_id:
                return True
        return False

    def insert(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._store._write() as db:
            alert_id = record.get("id") or new_id("alert")
            record = {**record, "id": alert_id}
            record.setdefault(
                "created_at", datetime.now(tz=timezone.utc).isoformat()
            )
            db[self.section][alert_id] = record
            return copy.deepcopy(record)

    def update_state(self, alert_id: str, state: str) -> None:
        with self._store._write() as db:
            existing = db[self.section].get(alert_id)
            if existing is not None:
                existing["state"] = state


class _RunsRepo(_Repo):
    section = "runs"

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._store._write() as db:
            run_id = record.get("id") or new_id("run")
            record = {**record, "id": run_id}
            db[self.section].append(record)
            return copy.deepcopy(record)

    def all(self) -> list[dict[str, Any]]:
        return list(self._store.snapshot()[self.section])


class _WireCatalogCacheRepo(_Repo):
    section = "wire_catalog_cache"

    def get(self) -> dict[str, Any] | None:
        return self._store.snapshot()[self.section]

    def set(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        with self._store._write() as db:
            payload = {
                "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
                "items": items,
            }
            db[self.section] = payload
            return copy.deepcopy(payload)


class _WriteContext:
    """Context manager yielded by ``JsonStore._write``.

    Holds the file lock for the duration of the block, hands the caller a
    mutable snapshot, then atomically flushes back to disk on exit.
    """

    def __init__(self, store: "JsonStore") -> None:
        self._store = store
        self._db: dict[str, Any] | None = None

    def __enter__(self) -> dict[str, Any]:
        self._store._file_lock.acquire()
        self._store._thread_lock.acquire()
        self._db = self._store._read_from_disk()
        return self._db

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None and self._db is not None:
                self._store._write_to_disk(self._db)
                self._store._memo = copy.deepcopy(self._db)
        finally:
            self._store._thread_lock.release()
            self._store._file_lock.release()


class JsonStore:
    """Thread- and process-safe JSON repo.

    Use :meth:`snapshot` to read; mutations live inside the per-section repo
    classes (``store.users.upsert_by_email(...)``, etc.) which all funnel
    through :meth:`_write`.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._file_lock = FileLock(str(self._lock_path), timeout=15)
        self._thread_lock = threading.RLock()
        self._memo: dict[str, Any] | None = None

        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write_to_disk(_EMPTY_DB)

        self.users = _UsersRepo(self)
        self.watch_items = _WatchItemsRepo(self)
        self.source_configs = _SourceConfigsRepo(self)
        self.source_documents = _SourceDocumentsRepo(self)
        self.events = _SecurityEventsRepo(self)
        self.event_signals = _EventSignalsRepo(self)
        self.relevance_matches = _RelevanceMatchesRepo(self)
        self.alerts = _AlertsRepo(self)
        self.runs = _RunsRepo(self)
        self.wire_catalog_cache = _WireCatalogCacheRepo(self)

    @property
    def path(self) -> Path:
        return self._path

    def snapshot(self) -> dict[str, Any]:
        with self._thread_lock:
            if self._memo is None:
                self._memo = self._read_from_disk()
            return copy.deepcopy(self._memo)

    def _write(self) -> _WriteContext:
        return _WriteContext(self)

    def _read_from_disk(self) -> dict[str, Any]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            db = copy.deepcopy(_EMPTY_DB)
            self._write_to_disk(db)
            return db
        if not raw.strip():
            return copy.deepcopy(_EMPTY_DB)
        loaded = json.loads(raw)
        for key, default in _EMPTY_DB.items():
            if key not in loaded:
                loaded[key] = copy.deepcopy(default)
        return loaded

    def _write_to_disk(self, db: dict[str, Any]) -> None:
        directory = self._path.parent
        fd, tmp_path = tempfile.mkstemp(
            prefix=self._path.name + ".",
            suffix=".tmp",
            dir=str(directory),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(_dump_json(db))
                handle.flush()
                os.fsync(handle.fileno())
            _replace_with_retry(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def _replace_with_retry(src: str, dst: Path) -> None:
    """``os.replace`` with a bounded retry for transient Windows locks.

    On Windows, an editor, indexer, or AV scanner holding a *read* handle on
    ``dst`` is enough to make ``MoveFileEx`` return ERROR_ACCESS_DENIED (5)
    or ERROR_SHARING_VIOLATION (32). Both clear within milliseconds. We
    attempt up to ``_REPLACE_MAX_ATTEMPTS`` times with a short linear-ish
    backoff before re-raising — that's still well under a second total.
    """

    last_exc: OSError | None = None
    for attempt in range(_REPLACE_MAX_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(_REPLACE_BACKOFF_SECONDS * (attempt + 1))
        except OSError as exc:
            # WinError 32 (sharing violation) maps to OSError, not
            # PermissionError — treat it the same.
            if getattr(exc, "winerror", None) in (5, 32):
                last_exc = exc
                time.sleep(_REPLACE_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise
    log.warning(
        "store atomic replace failed after %d attempts: %s",
        _REPLACE_MAX_ATTEMPTS,
        last_exc,
    )
    assert last_exc is not None
    raise last_exc


_singleton: JsonStore | None = None


def get_store(path: str | os.PathLike[str] | None = None) -> JsonStore:
    """Process-wide :class:`JsonStore` singleton.

    The first call sets the path; subsequent calls return the same instance
    regardless of the path argument so all code paths agree on one DB file.
    """

    global _singleton
    if _singleton is None:
        if path is None:
            raise RuntimeError("get_store() needs a path on first call")
        _singleton = JsonStore(path)
    return _singleton


def reset_store_for_tests() -> None:
    global _singleton
    _singleton = None
