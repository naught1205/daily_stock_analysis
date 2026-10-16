# -*- coding: utf-8 -*-
"""
===================================
搜索服务用量查询（Tavily）
===================================

通过 Tavily 官方 usage 端点查询当前计费周期的 credits 用量。
调用该端点不消耗 credits（限流：10 次/10 分钟），失败时一律 fail-open。

另提供多 Key 支持：
- fetch_tavily_usage_many：并行查询多个 Key 的用量（带短 TTL 缓存）
- remaining_credits：计算单个 Key 的剩余额度（未知时返回 None）
- select_tavily_key_order：按"先用有额度 Key"的顺序重排（额度用尽的排到最后）
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

TAVILY_USAGE_URL = "https://api.tavily.com/usage"
_USAGE_CACHE_TTL_SECONDS = 600.0
_usage_cache: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}
_usage_cache_lock = threading.Lock()


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


def fetch_tavily_usage_many(
    api_keys: Optional[Iterable[str]],
    timeout_seconds: float = 8.0,
    max_workers: int = 4,
    cache_ttl_seconds: float = _USAGE_CACHE_TTL_SECONDS,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Fetch usage for multiple keys in parallel, with a short-lived cache.

    Cache failures as well (None) to avoid hammering the endpoint within one
    run; the endpoint allows ~10 requests / 10 minutes.
    """
    unique_keys: List[str] = []
    seen = set()
    for key in api_keys or []:
        normalized = (key or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_keys.append(normalized)
    if not unique_keys:
        return {}

    now = time.time()
    result: Dict[str, Optional[Dict[str, Any]]] = {}
    to_fetch: List[str] = []
    with _usage_cache_lock:
        for key in unique_keys:
            cached = _usage_cache.get(key)
            if cached and now - cached[0] < cache_ttl_seconds:
                result[key] = cached[1]
            else:
                to_fetch.append(key)

    if to_fetch:
        workers = max(1, min(max_workers, len(to_fetch)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(fetch_tavily_usage, key, timeout_seconds): key
                for key in to_fetch
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    usage = future.result()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Tavily usage 并行查询异常: %s", exc)
                    usage = None
                result[key] = usage
        fetched_at = time.time()
        with _usage_cache_lock:
            for key in to_fetch:
                _usage_cache[key] = (fetched_at, result.get(key))

    return result


def remaining_credits(usage: Optional[Dict[str, Any]]) -> Optional[int]:
    """Remaining credits for one key; None when unknown (fail-open)."""
    if not usage:
        return None
    used = usage.get("used") or usage.get("plan_usage") or 0
    limit = usage.get("limit") or usage.get("plan_limit")
    if not limit:
        return None
    return max(0, int(limit) - int(used))


def select_tavily_key_order(
    api_keys: Optional[Iterable[str]],
    usage_by_key: Optional[Dict[str, Optional[Dict[str, Any]]]],
) -> List[str]:
    """Order keys for drain-first usage: available keys first, exhausted last.

    Unknown usage (None) keeps the key in the available group so failures
    fail-open to the original order.
    """
    available: List[str] = []
    exhausted: List[str] = []
    for key in api_keys or []:
        normalized = (key or "").strip()
        if not normalized:
            continue
        if remaining_credits((usage_by_key or {}).get(normalized)) == 0:
            exhausted.append(normalized)
        else:
            available.append(normalized)
    return available + exhausted


def clear_tavily_usage_cache() -> None:
    """Test helper: drop the in-process usage cache."""
    with _usage_cache_lock:
        _usage_cache.clear()
