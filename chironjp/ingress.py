"""Thin NDJSON bridge from the public career-ops adapter into Chiron SQLite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import IO, Any

from .store import Store


def import_stream(store: Store, stream: IO[str]) -> dict[str, int]:
    counts = {"scanned": 0, "inserted": 0, "updated": 0, "unchanged": 0}
    for line_number, line in enumerate(stream, 1):
        if not line.strip():
            continue
        counts["scanned"] += 1
        try:
            value: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid NDJSON on line {line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"source record on line {line_number} is not an object")
        outcome, _ = store.upsert_source_job(value)
        counts[outcome] += 1
    return counts


def import_path(database: str | Path, input_path: str | Path) -> dict[str, int]:
    store = Store(database)
    store.initialize()
    with Path(input_path).open("r", encoding="utf-8") as handle:
        return import_stream(store, handle)
