# -*- coding: utf-8 -*-
"""
===================================
搜索服务用量查询（Tavily）
===================================

通过 Tavily 官方 usage 端点查询当前计费周期的 credits 用量。
调用该端点不消耗 credits（限流：10 次/10 分钟），失败时一律 fail-open。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

TAVILY_USAGE_URL = "https://api.tavily.com/usage"


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_tavily_usage(
    api_key: Optional[str],
    timeout_seconds: float = 8.0,
) -> Optional[Dict[str, Any]]:
    """Fetch Tavily credit usage for the current billing cycle (best-effort).

    Returns a normalized dict:
        {used, limit, search_usage, plan, plan_usage, plan_limit}
    or None when the key is missing / the endpoint is unavailable.
    """
    key = (api_key or "").strip()
    if not key:
        return None

    try:
        import requests

        response = requests.get(
            TAVILY_USAGE_URL,
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout_seconds,
        )
        if response.status_code != 200:
            logger.warning("Tavily usage 查询失败: HTTP %s", response.status_code)
            return None
        data = response.json() or {}
    except Exception as exc:
        logger.warning("Tavily usage 查询异常: %s", exc)
        return None

    key_usage = data.get("key") or {}
    account = data.get("account") or {}
    limit = _as_int(key_usage.get("limit"))
    return {
        "used": _as_int(key_usage.get("usage")) or 0,
        "limit": limit,
        "search_usage": _as_int(key_usage.get("search_usage")),
        "plan": (account.get("current_plan") or "").strip() or None,
        "plan_usage": _as_int(account.get("plan_usage")),
        "plan_limit": _as_int(account.get("plan_limit")),
    }
