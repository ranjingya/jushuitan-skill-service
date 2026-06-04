from __future__ import annotations

BASE_URL = "https://openapi.jushuitan.com"
INIT_TOKEN_URL = f"{BASE_URL}/openWeb/auth/getInitToken"
REFRESH_TOKEN_URL = f"{BASE_URL}/openWeb/auth/refreshToken"

INVENTORY_QUERY_PATH = "/open/inventory/query"
VIRTUAL_STOCK_QUERY_PATH = "/open/webapi/itemapi/iteminventory/getvirtualstock"
SKU_QUERY_PATH = "/open/sku/query"
ITEM_QUERY_PATH = "/open/mall/item/query"

MAIN_BATCH_LIMIT = 100
DETAIL_BATCH_LIMIT = 20
VIRTUAL_PAGE_SIZE_MAX = 500
TMALL_WAREHOUSE_IDS = {50}
TMALL_WAREHOUSE_KEYWORDS = ("天猫",)
