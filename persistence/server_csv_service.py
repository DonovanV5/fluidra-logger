from __future__ import annotations

import csv
import os
from typing import Any

from utils.path_utils import _safe_path_part


def server_csv_root_dir(server_csv_dir: Any) -> str:
    return str(server_csv_dir or "").strip()


def server_csv_station_dir(root: str, workcenter: Any, hostname: str) -> str:
    if not root:
        return ""
    workcenter_part = _safe_path_part(workcenter, "workcenter")
    station = _safe_path_part(hostname, "station")
    return os.path.join(root, workcenter_part, station)


def server_csv_path(station_dir: str, sheet_name: Any, filenames: dict[str, str]) -> str:
    if not station_dir:
        return ""
    filename = filenames.get(sheet_name, f"{_safe_path_part(sheet_name)}.csv")
    return os.path.join(station_dir, filename)


def server_product_csv_path(root: str) -> str:
    if not root:
        return ""
    return os.path.join(root, "products.csv")


def server_product_csv_paths(root: str, primary_product_path: str) -> list[str]:
    if not root:
        return []
    return [
        primary_product_path,
        os.path.join(root, "Products.csv"),
        os.path.join(root, "Products", "products.csv"),
        os.path.join(root, "Products", "Products.csv"),
    ]


def write_rows_to_csv_atomic(path: str, rows: list[dict[str, Any]], headers: list[str], run_id: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.{run_id}.tmp"
    with open(temp_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})
    os.replace(temp_path, path)


def read_csv_records(path: str) -> list[dict[str, str]]:
    if not path or not os.path.exists(path):
        return []
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))
