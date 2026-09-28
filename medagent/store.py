"""Tiny JSON store for a clinician's watch topics and saved reading list."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from .models import Article


class WatchTopic(BaseModel):
    id: str
    query: str
    days: int = 30
    created: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    last_checked: str | None = None
    seen_ids: list[str] = Field(default_factory=list)


class StoreData(BaseModel):
    topics: list[WatchTopic] = Field(default_factory=list)
    library: list[Article] = Field(default_factory=list)


class Store:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "medagent.json"
        self._lock = threading.Lock()

    def load(self) -> StoreData:
        if not self.path.exists():
            return StoreData()
        try:
            return StoreData.model_validate_json(self.path.read_text())
        except (ValueError, OSError):
            return StoreData()

    def save(self, data: StoreData) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data.model_dump(mode="json"), indent=2))
            tmp.replace(self.path)
