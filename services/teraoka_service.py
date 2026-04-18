from __future__ import annotations

import json
import os
from typing import Any


def load_teraoka_config(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {"loaded": False}

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    config: dict[str, Any] = {"loaded": True}
    if isinstance(data.get('workcenters'), list) and data['workcenters']:
        config["workcenters"] = [
            {"id": str(item.get('id', '')).strip(), "name": str(item.get('name', '')).strip()}
            for item in data['workcenters'] if item.get('id')
        ]
    if data.get('wsdl_url'):
        config["wsdl_url"] = str(data['wsdl_url']).strip()
    if data.get('default_supervisor'):
        config["default_supervisor"] = str(data['default_supervisor']).strip()
    if data.get('admin_password'):
        config["admin_password"] = str(data['admin_password'])
    return config


def read_teraoka_status(teraoka_client: Any) -> dict[str, Any]:
    status = {
        "connected": False,
        "job": None,
        "product_code": None,
        "required_quantity": None,
        "total_quantity": None,
        "qty_made": None,
        "last_error": None,
    }
    if not teraoka_client:
        return status

    status["connected"] = bool(teraoka_client.is_connected())
    status["job"] = teraoka_client.current_job()
    if hasattr(teraoka_client, 'product_code'):
        status["product_code"] = teraoka_client.product_code()
    if hasattr(teraoka_client, 'required_quantity'):
        status["required_quantity"] = teraoka_client.required_quantity()
    if hasattr(teraoka_client, 'total_quantity'):
        status["total_quantity"] = teraoka_client.total_quantity()
    if status["connected"] and status["job"] and hasattr(teraoka_client, 'qty_made'):
        status["qty_made"] = teraoka_client.qty_made()
    status["last_error"] = teraoka_client.last_error()
    return status


def start_teraoka_client(client_class: type[Any], wsdl_url: str, workcenter: str, supervisor: str) -> Any:
    client = client_class(wsdl_url, workcenter, supervisor)
    client.start()
    return client


def shutdown_teraoka_client(client: Any) -> None:
    if client:
        client.shutdown()
