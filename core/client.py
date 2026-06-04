from __future__ import annotations

import json
import time
from typing import Any

import requests

from .auth import LOGGER, ensure_token, get_access_token, mask, preview_text, refresh_token, require_credentials
from .config import BASE_URL
from .sign import generate_sign


class JushuitanClient:
    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.app_key, self.app_secret = require_credentials()

    def call(
        self,
        api_path: str,
        biz_params: dict[str, Any] | None = None,
        version: str = "2",
        charset: str = "utf-8",
        refresh_once: bool = True,
    ) -> dict[str, Any]:
        ensure_token(timeout=self.timeout)
        access_token = get_access_token()

        result = self._call_once(
            api_path=api_path,
            biz_params=biz_params,
            access_token=access_token,
            version=version,
            charset=charset,
        )
        if refresh_once and self._is_access_token_expired(result):
            LOGGER.info("client detected expired access_token, refreshing once")
            refresh_token(timeout=self.timeout)
            new_access_token = get_access_token()
            if new_access_token:
                result = self._call_once(
                    api_path=api_path,
                    biz_params=biz_params,
                    access_token=new_access_token,
                    version=version,
                    charset=charset,
                )
        return result

    def _call_once(
        self,
        api_path: str,
        biz_params: dict[str, Any] | None,
        access_token: str,
        version: str,
        charset: str,
    ) -> dict[str, Any]:
        url = f"{BASE_URL}{api_path}"
        timestamp = int(time.time())
        params: dict[str, Any] = {
            "app_key": self.app_key,
            "access_token": access_token,
            "timestamp": timestamp,
            "version": version,
            "charset": charset,
            "biz": json.dumps(biz_params or {}, ensure_ascii=False, separators=(",", ":")),
        }
        params["sign"] = generate_sign(self.app_secret, params)

        LOGGER.info(
            "client request api_path=%s access_token=%s biz=%s",
            api_path,
            mask(access_token),
            params["biz"],
        )

        try:
            response = requests.post(
                url,
                data=params,
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
            LOGGER.info("client response api_path=%s body=%s", api_path, preview_text(json.dumps(result, ensure_ascii=False)))
            return result
        except requests.RequestException as exc:
            LOGGER.exception("client request failed api_path=%s", api_path)
            return {"code": -1, "msg": f"请求异常: {str(exc)}"}
        except json.JSONDecodeError as exc:
            LOGGER.exception("client json decode failed api_path=%s", api_path)
            return {
                "code": -1,
                "msg": f"JSON解析错误: {str(exc)}",
                "raw_response": response.text if "response" in locals() else None,
            }

    @staticmethod
    def _is_access_token_expired(result: dict[str, Any]) -> bool:
        if result.get("code") != 100:
            return False
        message = str(result.get("msg") or "").replace(" ", "")
        return "access_token已过期" in message
