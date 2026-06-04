from __future__ import annotations

from collections import OrderedDict
from typing import Any

from ..core.auth import LOGGER
from ..core.client import JushuitanClient
from ..core.config import (
    DETAIL_BATCH_LIMIT,
    INVENTORY_QUERY_PATH,
    ITEM_QUERY_PATH,
    MAIN_BATCH_LIMIT,
    SKU_QUERY_PATH,
)


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[idx:idx + size] for idx in range(0, len(values), size)]


def validate_inventory_query_options(
    query_type: str | None,
    query_values: list[str],
    page_index: int,
    page_size: int,
) -> None:
    if page_index <= 0:
        raise RuntimeError("page_index must be greater than or equal to 1")
    if page_size <= 0 or page_size > 100:
        raise RuntimeError("page_size must be between 1 and 100")

    if not query_type or not query_values:
        raise RuntimeError("必须提供 sku_ids / i_ids / names 其中一种查询条件")

    if query_type and query_type not in {"sku_ids", "i_ids", "names"}:
        raise RuntimeError(f"unsupported query_type: {query_type}")


def _build_main_inventory_biz(
    query_type: str,
    batch: list[str],
    page_index: int,
    page_size: int,
) -> dict[str, Any]:
    biz: dict[str, Any] = {
        "has_lock_qty": True,
        "page_index": page_index,
        "page_size": page_size,
    }
    biz[query_type] = ",".join(batch)
    return biz


def _inventory_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("code") != 0:
        return []
    data = result.get("data") or {}
    rows = data.get("inventorys")
    return rows if isinstance(rows, list) else []


def _sku_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("code") != 0:
        return []
    data = result.get("data") or {}
    rows = data.get("datas")
    return rows if isinstance(rows, list) else []


def _item_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("code") != 0:
        return []
    data = result.get("data") or {}
    for key in ("datas", "items", "data"):
        rows = data.get(key)
        if isinstance(rows, list):
            return rows
    if isinstance(data, list):
        return data
    return []


def query_main_inventory(
    client: JushuitanClient,
    query_type: str,
    values: list[str],
    start_page_index: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    batches = chunked(values, MAIN_BATCH_LIMIT)

    for batch_index, batch in enumerate(batches, start=1):
        page_index = start_page_index
        while True:
            result = client.call(
                api_path=INVENTORY_QUERY_PATH,
                biz_params=_build_main_inventory_biz(
                    query_type=query_type,
                    batch=batch,
                    page_index=page_index,
                    page_size=page_size,
                ),
            )
            if result.get("code") != 0:
                failures.append(
                    {
                        "source": "main_inventory",
                        "batch_index": batch_index,
                        "query_type": query_type,
                        "batch": batch,
                        "code": result.get("code"),
                        "msg": result.get("msg"),
                    }
                )
                break

            page_rows = _inventory_rows(result)
            rows.extend(page_rows)

            data = result.get("data") or {}
            page_count = data.get("page_count")
            if isinstance(page_count, int) and page_index >= page_count:
                break
            if len(page_rows) < page_size:
                break
            page_index += 1

    return rows, failures


def query_sku_details(client: JushuitanClient, sku_ids: list[str]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    details: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    if not sku_ids:
        return details, failures

    for batch_index, batch in enumerate(chunked(sku_ids, DETAIL_BATCH_LIMIT), start=1):
        result = client.call(
            api_path=SKU_QUERY_PATH,
            biz_params={"sku_ids": ",".join(batch)},
        )
        if result.get("code") != 0:
            failures.append(
                {
                    "source": "sku_detail",
                    "batch_index": batch_index,
                    "batch": batch,
                    "code": result.get("code"),
                    "msg": result.get("msg"),
                }
            )
            continue

        for row in _sku_rows(result):
            sku_id = str(row.get("sku_id") or "")
            if not sku_id:
                continue
            details[sku_id] = {
                "i_id": str(row.get("i_id") or ""),
                "item_name": str(row.get("name") or ""),
                "color_spec": str(row.get("properties_value") or "").strip(),
            }

    return details, failures


def query_item_details(client: JushuitanClient, i_ids: list[str]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    details: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    if not i_ids:
        return details, failures

    for batch_index, batch in enumerate(chunked(i_ids, DETAIL_BATCH_LIMIT), start=1):
        result = client.call(
            api_path=ITEM_QUERY_PATH,
            biz_params={"i_ids": ",".join(batch)},
        )
        if result.get("code") != 0:
            failures.append(
                {
                    "source": "item_detail",
                    "batch_index": batch_index,
                    "batch": batch,
                    "code": result.get("code"),
                    "msg": result.get("msg"),
                }
            )
            continue

        for row in _item_rows(result):
            i_id = str(row.get("i_id") or row.get("item_id") or row.get("item_code") or "")
            if not i_id:
                continue
            details[i_id] = {
                "item_name": str(
                    row.get("name")
                    or row.get("item_name")
                    or row.get("i_name")
                    or row.get("title")
                    or ""
                ),
                "color_spec": str(row.get("properties_value") or row.get("properties_name") or "").strip(),
            }

    return details, failures


def normalize_inventory_rows(
    main_rows: list[dict[str, Any]],
    sku_details: dict[str, dict[str, Any]],
    item_details: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized: list[dict[str, Any]] = []
    missing_enrichment: list[dict[str, Any]] = []
    for row in main_rows:
        sku_id = str(row.get("sku_id") or "")
        i_id = str(row.get("i_id") or "")
        qty = int(row.get("qty") or 0)
        order_lock = int(row.get("order_lock") or 0)
        lock_qty = int(row.get("lock_qty") or 0)
        purchase_qty = int(row.get("purchase_qty") or 0)
        in_qty = int(row.get("in_qty") or 0)
        sku_detail = sku_details.get(sku_id, {})
        item_detail = item_details.get(i_id, {})
        item_name = (
            str(row.get("name") or "").strip()
            or str(sku_detail.get("item_name") or "").strip()
            or str(item_detail.get("item_name") or "").strip()
            or "N/A"
        )
        color_spec = (
            str(sku_detail.get("color_spec") or "").strip()
            or str(item_detail.get("color_spec") or "").strip()
            or "N/A"
        )

        if color_spec == "N/A":
            missing_enrichment.append(
                {
                    "source": "enrichment",
                    "batch_index": "",
                    "page": "",
                    "code": "",
                    "msg": "颜色/规格缺失，已使用 N/A 占位",
                    "batch": [sku_id],
                }
            )

        normalized.append(
            {
                "sku_id": sku_id,
                "i_id": i_id,
                "name": item_name,
                "color_spec": color_spec,
                "qty": qty,
                "lock_qty": lock_qty,
                "order_lock": order_lock,
                "purchase_qty": purchase_qty,
                "in_qty": in_qty,
                "available_qty": qty - order_lock,
            }
        )

    normalized.sort(key=lambda item: (item["name"], item["i_id"], item["color_spec"], item["sku_id"]))
    return normalized, missing_enrichment


def run_inventory_query(
    query_type: str,
    query_values: list[str],
    timeout: int = 30,
    page_index: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    validate_inventory_query_options(
        query_type=query_type,
        query_values=query_values,
        page_index=page_index,
        page_size=page_size,
    )
    client = JushuitanClient(timeout=timeout)
    main_rows, failures = query_main_inventory(
        client=client,
        query_type=query_type,
        values=query_values,
        start_page_index=page_index,
        page_size=page_size,
    )
    sku_ids = list(OrderedDict.fromkeys(str(row.get("sku_id") or "") for row in main_rows if row.get("sku_id")))
    sku_details, sku_failures = query_sku_details(client, sku_ids)
    failures.extend(sku_failures)

    missing_item_ids = list(
        OrderedDict.fromkeys(
            str(row.get("i_id") or "")
            for row in main_rows
            if row.get("i_id") and not str(sku_details.get(str(row.get("sku_id") or ""), {}).get("color_spec") or "").strip()
        )
    )
    item_details, item_failures = query_item_details(client, missing_item_ids)
    failures.extend(item_failures)

    normalized_rows, enrichment_failures = normalize_inventory_rows(main_rows, sku_details, item_details)
    failures.extend(enrichment_failures)

    LOGGER.info(
        "inventory query finished query_type=%s input_count=%s row_count=%s failure_count=%s page_index=%s page_size=%s",
        query_type,
        len(query_values),
        len(normalized_rows),
        len(failures),
        page_index,
        page_size,
    )

    return {
        "query_type": query_type,
        "input_count": len(query_values),
        "rows": normalized_rows,
        "failures": failures,
    }
