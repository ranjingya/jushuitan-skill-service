from __future__ import annotations

import hashlib
import json


def generate_sign(app_secret: str, params: dict) -> str:
    filtered_params = {k: v for k, v in params.items() if k != "sign" and v is not None and v != ""}
    sorted_keys = sorted(filtered_params.keys())

    param_str = ""
    for key in sorted_keys:
        value = filtered_params[key]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        param_str += f"{key}{value}"

    sign_str = f"{app_secret}{param_str}"
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest()
