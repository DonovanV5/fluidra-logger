from __future__ import annotations

from typing import Any


def create_local_event_store(db_path: str, store_cls: type[Any]) -> Any:
    return store_cls(db_path)
