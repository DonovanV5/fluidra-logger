from __future__ import annotations

from typing import Any


def duplicate_cache_lookup(
    normalized_barcode: str,
    scanned_barcodes: set[str],
    barcode_cache: set[str],
    last_barcode_check: Any,
    last_barcode_result: bool,
) -> tuple[bool | None, str, bool]:
    if normalized_barcode in scanned_barcodes:
        return True, "memory", False
    if normalized_barcode in barcode_cache:
        return True, "cache", False
    if normalized_barcode == last_barcode_check:
        return bool(last_barcode_result), "", True
    return None, "", False


def should_refresh_barcode_cache(last_update: float, ttl_seconds: float, current_time: float) -> bool:
    return current_time - last_update > ttl_seconds
