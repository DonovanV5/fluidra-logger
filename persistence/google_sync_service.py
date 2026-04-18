from __future__ import annotations

from typing import Any


def resolve_sheet_value(data_map: dict[str, Any], key: str) -> Any:
    normalized_key = (key or "").strip()
    if not normalized_key:
        return ""
    for candidate in (
        normalized_key,
        normalized_key.replace(" ", "_"),
        normalized_key.replace("_", " "),
    ):
        if candidate in data_map:
            return data_map.get(candidate, "")
    return ""


def build_sheet_row(data_map: dict[str, Any], headers: list[str]) -> list[Any]:
    row = []
    for col in headers:
        key = (col or "").strip()
        if not key:
            row.append("")
            continue
        row.append(resolve_sheet_value(data_map, key))
    return row


def normalize_sheet_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def format_sheet_row_ref(worksheet_title: str, row_number: Any) -> str | None:
    if not row_number:
        return None
    return f"{worksheet_title}!{int(row_number)}"


def sheet_row_matches_payload(row_values: list[Any], header_row: list[Any], data_map: dict[str, Any], sync_event_id_header: str) -> bool:
    for index, header in enumerate(header_row):
        key = normalize_sheet_text(header)
        if not key or key == sync_event_id_header:
            continue
        actual_value = normalize_sheet_text(row_values[index] if index < len(row_values) else "")
        expected_value = normalize_sheet_text(resolve_sheet_value(data_map, key))
        if actual_value != expected_value:
            return False
    return True
