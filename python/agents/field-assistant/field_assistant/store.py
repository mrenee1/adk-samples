"""Tiny document store: JSON files locally, Firestore in the cloud.

Collections: businesses, contacts, visits, tasks, plans, submissions,
records (surveys/ROEs), settings, uploads.
"""

from __future__ import annotations

import base64
import json
import threading
import uuid
from typing import Any, Protocol

from . import config


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Store(Protocol):
    def list(self, col: str) -> list[dict[str, Any]]: ...
    def get(self, col: str, doc_id: str) -> dict[str, Any] | None: ...
    def put(self, col: str, doc: dict[str, Any]) -> dict[str, Any]: ...
    def delete(self, col: str, doc_id: str) -> None: ...


class LocalStore:
    """One JSON file per collection. Fine for one person testing."""

    def __init__(self, root=config.DATA_DIR):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, col: str):
        return self.root / f"{col}.json"

    def _read(self, col: str) -> dict[str, dict]:
        p = self._path(col)
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))

    def _write(self, col: str, docs: dict[str, dict]) -> None:
        tmp = self._path(col).with_suffix(".tmp")
        tmp.write_text(json.dumps(docs, indent=1), encoding="utf-8")
        tmp.replace(self._path(col))

    def list(self, col):
        with self._lock:
            return list(self._read(col).values())

    def get(self, col, doc_id):
        with self._lock:
            return self._read(col).get(doc_id)

    def put(self, col, doc):
        with self._lock:
            docs = self._read(col)
            docs[doc["id"]] = doc
            self._write(col, docs)
        return doc

    def delete(self, col, doc_id):
        with self._lock:
            docs = self._read(col)
            docs.pop(doc_id, None)
            self._write(col, docs)


class FirestoreStore:
    """Same interface on Firestore (one top-level collection per name)."""

    def __init__(self):
        from google.cloud import firestore  # noqa: PLC0415

        self.db = firestore.Client()

    def list(self, col):
        return [d.to_dict() for d in self.db.collection(col).stream()]

    def get(self, col, doc_id):
        snap = self.db.collection(col).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def put(self, col, doc):
        self.db.collection(col).document(doc["id"]).set(doc)
        return doc

    def delete(self, col, doc_id):
        self.db.collection(col).document(doc_id).delete()


_store: Store | None = None


def get_store() -> Store:
    global _store  # noqa: PLW0603
    if _store is None:
        _store = (
            FirestoreStore()
            if config.DATA_BACKEND == "firestore"
            else LocalStore()
        )
    return _store


def set_store(store: Store) -> None:
    """Swap the store (tests)."""
    global _store  # noqa: PLW0603
    _store = store


# Photos are resized on the phone (~200 KB), so they fit in one document.
MAX_UPLOAD_BYTES = 900_000


def save_upload(data: bytes, mime: str, owner: str) -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Photo is too large; try again.")
    doc = {
        "id": new_id("U"),
        "owner": owner,
        "mime": mime,
        "data": base64.b64encode(data).decode(),
    }
    get_store().put("uploads", doc)
    return doc["id"]


def read_upload(upload_id: str) -> tuple[bytes, str] | None:
    doc = get_store().get("uploads", upload_id)
    if not doc:
        return None
    return base64.b64decode(doc["data"]), doc["mime"]
