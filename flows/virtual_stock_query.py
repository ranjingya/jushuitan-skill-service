from __future__ import annotations

from collections import OrderedDict
from typing import Any

from ..core.auth import LOGGER
from ..core.client import JushuitanClient
from ..core.config import (
    DETAIL_BATCH_LIMIT,
    INVENTORY_QUERY_PATH,
    MAIN_BATCH_LIMIT,
    SKU_QUERY_PATH,
    TMALL_WAREHOUSE_IDS,
    TMALL_WAREHOUSE_KEYWORDS,
    VIRTUAL_PAGE_SIZE_MAX,
    VIRTUAL_STOCK_QUERY_PATH,
)


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[idx:idx + size] for idx in range(0, len(values), size)]


def validate_virtual_stock_query_options(
    query_type: str | None,
    query_values: list[str],
    page_index: int,
    page_size: int,
) -> None:
    if page_index <= 0:
        raise RuntimeError("page_index must be greater than or equal to 1")
    if page_size <= 0 or page_size > VIRTUAL_PAGE_SIZE_MAX:
        raise RuntimeError(f"page_size must be between 1 and {VIRTUAL_PAGE_SIZE_MAX}")

    if not query_type or not query_values:
        raise RuntimeError("必须提供 sku_ids / i_ids / names 其中一种查询条件")

    if query_type not in {"sku_ids", "i_ids", "names"}:
        raise RuntimeError(f"unsupported query_type: {query_type}")


def _extract_virtual_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("code") != 0:
        return []
    data = result.get("data") or {}
    rows = data.get("data")
    return rows if isinstance(rows, list) else []


def _extract_inventory_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("code") != 0:
        return []
    data = result.get("data") or {}
    rows = data.get("inventorys")
    return rows if isinstance(rows, list) else []


def _extract_sku_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("code") != 0:
        return []
    data = result.get("data") or {}
    rows = data.get("datas")
    return rows if isinstance(rows, list) else []


def _is_tmall_warehouse(stock: dict[str, Any]) -> bool:
    lwh_id = stock.get("lwh_id")
    name = str(stock.get("name") or "")
    if lwh_id in TMALL_WAREHOUSE_IDS:
        return True
    return any(keyword in name for keyword in TMALL_WAREHOUSE_KEYWORDS)


def query_sku_details(client: JushuitanClient, sku_ids: list[str]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    details: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    if not sku_ids:
        return details, failures

    for batch_index, batch in enumerate(chunked(sku_ids, DETAIL_BATCH_LIMIT), start=1):
        result = client.call(api_path=SKU_QUERY_PATH, biz_params={"sku_ids": ",".join(batch)})
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

        for row in _extract_sku_rows(result):
            sku_id = str(row.get("sku_id") or "")
            if not sku_id:
                continue
            details[sku_id] = {
                "item_name": str(row.get("name") or ""),
                "color_spec": str(row.get("properties_value") or "").strip(),
            }

    return details, failures


def resolve_query_to_sku_ids(
    client: JushuitanClient,
    query_type: str,
    query_values: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    if query_type == "sku_ids":
        return list(OrderedDict.fromkeys(query_values)), []

    sku_ids: list[str] = []
    failures: list[dict[str, Any]] = []

    for batch_index, batch in enumerate(chunked(query_values, MAIN_BATCH_LIMIT), start=1):
        page_index = 1
        while True:
            result = client.call(
                api_path=INVENTORY_QUERY_PATH,
                biz_params={
                    query_type: ",".join(batch),
                    "page_index": page_index,
                    "page_size": 100,
                    "has_lock_qty": False,
                },
            )
            if result.get("code") != 0:
                failures.append(
                    {
                        "source": "sku_resolve",
                        "batch_index": batch_index,
                        "page": page_index,
                        "batch": batch,
                        "code": result.get("code"),
                        "msg": result.get("msg"),
                    }
                )
                break

            page_rows = _extract_inventory_rows(result)
            sku_ids.extend(str(row.get("sku_id") or "") for row in page_rows if row.get("sku_id"))

            data = result.get("data") or {}
            page_count = data.get("page_count")
            if isinstance(page_count, int) and page_index >= page_count:
                break
            if len(page_rows) < 100:
                break
            page_index += 1

    return list(OrderedDict.fromkeys([sku_id for sku_id in sku_ids if sku_id])), failures


def query_virtual_stock(
    client: JushuitanClient,
    sku_ids: list[str],
    wms_co_id: str | None,
    start_page_index: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    batches = chunked(sku_ids, MAIN_BATCH_LIMIT) if sku_ids else [[]]

    for batch_index, batch in enumerate(batches, start=1):
        current_page = start_page_index
        while True:
            biz: dict[str, Any] = {
                "page": {
                    "current_page": str(current_page),
                    "page_size": str(page_size),
                }
            }
            if batch:
                biz["sku_ids"] = batch
            if wms_co_id:
                biz["wms_co_id"] = wms_co_id

            result = client.call(api_path=VIRTUAL_STOCK_QUERY_PATH, biz_params=biz)
            if result.get("code") != 0:
                failures.append(
                    {
                        "source": "virtual_stock",
                        "batch_index": batch_index,
                        "page": current_page,
                        "batch": batch,
                        "code": result.get("code"),
                        "msg": result.get("msg"),
                    }
                )
                break

            page_rows = _extract_virtual_rows(result)
            for item in page_rows:
                sku_id = str(item.get("sku_id") or "")
                stocks = item.get("stocks") or []
                for stock in stocks:
                    if not isinstance(stock, dict):
                        continue
                    if not _is_tmall_warehouse(stock):
                        continue
                    rows.append(
                        {
                            "sku_id": sku_id,
                            "warehouse_name": str(stock.get("name") or ""),
                            "lwh_id": stock.get("lwh_id"),
                            "qty": int(stock.get("qty") or 0),
                            "pick_lock": int(stock.get("pick_lock") or 0),
                            "order_lock": int(stock.get("order_lock") or 0),
                            "order_able_qty": int(stock.get("order_able_qty") or 0),
                            "modified": str(stock.get("modified") or ""),
                        }
                    )

            data = result.get("data") or {}
            has_next = bool(data.get("has_next"))
            if not has_next:
                break
            current_page += 1

    return rows, failures


def normalize_virtual_stock_rows(
    rows: list[dict[str, Any]],
    sku_details: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized: list[dict[str, Any]] = []
    enrichment_failures: list[dict[str, Any]] = []

    for row in rows:
        sku_id = row["sku_id"]
        detail = sku_details.get(sku_id, {})
        color_spec = str(detail.get("color_spec") or "").strip() or "N/A"
        item_name = str(detail.get("item_name") or "").strip() or "N/A"

        if color_spec == "N/A":
            enrichment_failures.append(
                {
                    "source": "enrichment",
                    "batch_index": "",
                    "page": "",
                    "batch": [sku_id],
                    "code": "",
                    "msg": "颜色/规格缺失，已使用 N/A 占位",
                }
            )

        normalized.append(
            {
                "sku_id": sku_id,
                "color_spec": color_spec,
                "name": item_name,
                "qty": row["qty"],
                "pick_lock": row["pick_lock"],
                "order_able_qty": row["order_able_qty"],
            }
        )

    normalized.sort(key=lambda item: (item["name"], item["color_spec"], item["sku_id"]))
    return normalized, enrichment_failures


def run_virtual_stock_query(
    query_type: str,
    query_values: list[str],
    wms_co_id: str | None = None,
    timeout: int = 30,
    page_index: int = 1,
    page_size: int = 500,
) -> dict[str, Any]:
    validate_virtual_stock_query_options(
        query_type=query_type,
        query_values=query_values,
        page_index=page_index,
        page_size=page_size,
    )

    client = JushuitanClient(timeout=timeout)
    resolved_sku_ids, resolve_failures = resolve_query_to_sku_ids(client, query_type, query_values)
    rows, failures = query_virtual_stock(
        client=client,
        sku_ids=resolved_sku_ids,
        wms_co_id=wms_co_id,
        start_page_index=page_index,
        page_size=page_size,
    )
    failures = resolve_failures + failures

    detail_sku_ids = list(OrderedDict.fromkeys(row["sku_id"] for row in rows))
    sku_details, sku_failures = query_sku_details(client, detail_sku_ids)
    failures.extend(sku_failures)

    normalized_rows, enrichment_failures = normalize_virtual_stock_rows(rows, sku_details)
    failures.extend(enrichment_failures)

    LOGGER.info(
        "virtual stock query finished query_type=%s input_count=%s resolved_sku_count=%s row_count=%s failure_count=%s page_index=%s page_size=%s",
        query_type,
        len(query_values),
        len(resolved_sku_ids),
        len(normalized_rows),
        len(failures),
        page_index,
        page_size,
    )

    return {
        "query_type": query_type,
        "input_count": len(query_values),
        "resolved_sku_count": len(resolved_sku_ids),
        "rows": normalized_rows,
        "failures": failures,
    }
