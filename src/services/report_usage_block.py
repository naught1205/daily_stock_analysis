# -*- coding: utf-8 -*-
"""
===================================
报告用量块（可选）
===================================

当 REPORT_SHOW_TOKEN_USAGE=true 时，在主聚合报告末尾追加：
1. LLM token 用量 / 调用次数 / 模型 / 成本估算（LLM_PRICE_* 配置）
2. 搜索 API 用量（当前支持 Tavily：本次搜索次数 + 本期 credits 余额；
   配置多个 Key 时展示整个 Key 池的额度状态）

所有查询均 fail-open：任何异常只记录日志，不影响报告主流程。
"""

from __future__ import annotations

import calendar
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.services.search_usage import fetch_tavily_usage, fetch_tavily_usage_many

logger = logging.getLogger(__name__)

_USAGE_LABELS: Dict[str, Dict[str, str]] = {
    "zh": {
        "llm_heading": "本次用量",
        "input": "输入",
        "output": "输出",
        "total": "合计",
        "calls": "{count} 次调用",
        "model": "模型",
        "cost": "预估成本",
        "tavily_run": "本次搜索 {count} 次（约 {credits} credits）",
        "tavily_cycle": "本期已用 {used}/{limit} credits（剩余 {remaining}）",
        "tavily_cycle_unlimited": "本期已用 {used} credits（不限额度）",
        "tavily_plan": "方案：{plan}",
        "tavily_projected": "月底估算约 {projected}/{limit}",
        "tavily_warn": "⚠️ 已用超过 80%",
        "tavily_pool_total": "额度 {used}/{limit}（剩 {remaining}）",
        "tavily_key_sep": " ｜ ",
        "tavily_key_exhausted": "⛔已用尽",
        "tavily_key_unknown": "未知",
        "tavily_all_exhausted": "所有 Key 已用尽",
    },
    "en": {
        "llm_heading": "Usage",
        "input": "input",
        "output": "output",
        "total": "total",
        "calls": "{count} calls",
        "model": "model",
        "cost": "est. cost",
        "tavily_run": "searches this run: {count} (~{credits} credits)",
        "tavily_cycle": "this cycle {used}/{limit} credits ({remaining} left)",
        "tavily_cycle_unlimited": "this cycle {used} credits (unlimited)",
        "tavily_plan": "plan: {plan}",
        "tavily_projected": "month-end est. ~{projected}/{limit}",
        "tavily_warn": "⚠️ over 80% used",
        "tavily_pool_total": "pool {used}/{limit} ({remaining} left)",
        "tavily_key_sep": " | ",
        "tavily_key_exhausted": "⛔ exhausted",
        "tavily_key_unknown": "?",
        "tavily_all_exhausted": "all keys exhausted",
    },
    "ko": {
        "llm_heading": "사용량",
        "input": "입력",
        "output": "출력",
        "total": "합계",
        "calls": "{count}회 호출",
        "model": "모델",
        "cost": "예상 비용",
        "tavily_run": "이번 실행 검색 {count}회(약 {credits} credits)",
        "tavily_cycle": "이번 주기 {used}/{limit} credits(잔여 {remaining})",
        "tavily_cycle_unlimited": "이번 주기 {used} credits(무제한)",
        "tavily_plan": "플랜: {plan}",
        "tavily_projected": "월말 예상 ~{projected}/{limit}",
        "tavily_warn": "⚠️ 80% 초과",
        "tavily_pool_total": "풀 {used}/{limit}(잔여 {remaining})",
        "tavily_key_sep": " | ",
        "tavily_key_exhausted": "⛔ 소진",
        "tavily_key_unknown": "?",
        "tavily_all_exhausted": "모든 키 소진",
    },
}


def _labels(language: Optional[str]) -> Dict[str, str]:
    return _USAGE_LABELS.get((language or "").strip().lower(), _USAGE_LABELS["zh"])


def _format_cost(cost: float) -> str:
    if cost >= 0.01:
        return f"US${cost:.2f}"
    return f"US${cost:.4f}"


def format_llm_usage_line(summary: Dict[str, Any], config: Any, language: str = "zh") -> str:
    """Format the LLM token usage line; empty string when there is no usage."""
    labels = _labels(language)
    total_calls = int(summary.get("total_calls") or 0)
    if total_calls <= 0:
        return ""

    prompt_tokens = int(summary.get("total_prompt_tokens") or 0)
    completion_tokens = int(summary.get("total_completion_tokens") or 0)
    total_tokens = int(summary.get("total_tokens") or (prompt_tokens + completion_tokens))

    parts = [
        f"{labels['input']} {prompt_tokens:,}",
        f"{labels['output']} {completion_tokens:,}",
        f"{labels['total']} {total_tokens:,} tokens",
        labels["calls"].format(count=total_calls),
    ]
    line = f"🔢 {labels['llm_heading']}：" + " · ".join(parts)

    models = [
        str(entry.get("model"))
        for entry in (summary.get("by_model") or [])
        if entry.get("model")
    ]
    if models:
        line += f" · {labels['model']} {', '.join(models)}"

    price_in = float(getattr(config, "llm_price_input_per_1m", 0.0) or 0.0)
    price_out = float(getattr(config, "llm_price_output_per_1m", 0.0) or 0.0)
    if price_in > 0 or price_out > 0:
        cost = prompt_tokens / 1_000_000 * price_in + completion_tokens / 1_000_000 * price_out
        line += f" · {labels['cost']} ≈ {_format_cost(cost)}"
    return line


def format_tavily_usage_line(
    *,
    run_calls: Optional[int] = None,
    usage: Optional[Dict[str, Any]] = None,
    language: str = "zh",
    now: Optional[datetime] = None,
) -> str:
    """Format the Tavily usage line; empty string when there is nothing to show."""
    labels = _labels(language)
    segments = []

    if run_calls:
        segments.append(labels["tavily_run"].format(count=int(run_calls), credits=int(run_calls)))

    if usage:
        # Tavily 免费/订阅计划的 key.limit 可能为 null（key 本身不限），
        # 此时回退到账号级 plan_usage / plan_limit（例如 Free 计划 1000/月）。
        used = int(usage.get("used") or 0) or int(usage.get("plan_usage") or 0)
        limit = usage.get("limit") or usage.get("plan_limit")
        if limit:
            remaining = max(0, int(limit) - used)
            segments.append(
                labels["tavily_cycle"].format(used=used, limit=int(limit), remaining=remaining)
            )
            current = now or datetime.now()
            days_in_month = calendar.monthrange(current.year, current.month)[1]
            if used > 0 and current.day >= 1:
                projected = round(used / current.day * days_in_month)
                segments.append(
                    labels["tavily_projected"].format(projected=projected, limit=int(limit))
                )
            if used / int(limit) >= 0.8:
                segments.append(labels["tavily_warn"])
        else:
            segments.append(labels["tavily_cycle_unlimited"].format(used=used))
        plan = usage.get("plan")
        if plan:
            segments.append(labels["tavily_plan"].format(plan=plan))

    if not segments:
        return ""
    return "🔎 Tavily：" + " · ".join(segments)


def format_tavily_pool_line(
    *,
    run_calls: Optional[int] = None,
    usages: Optional[List[Optional[Dict[str, Any]]]] = None,
    language: str = "zh",
    now: Optional[datetime] = None,
) -> str:
    """Format the multi-key Tavily pool line; empty when fewer than 2 keys."""
    pool = list(usages or [])
    if len(pool) < 2:
        return ""

    labels = _labels(language)
    segments = []

    if run_calls:
        segments.append(labels["tavily_run"].format(count=int(run_calls), credits=int(run_calls)))

    key_parts = []
    used_total = 0
    limit_total = 0
    totals_complete = True
    known_count = 0
    exhausted_count = 0
    warn = False

    for usage in pool:
        used = None
        limit = None
        if usage:
            used = usage.get("used") or usage.get("plan_usage") or 0
            limit = usage.get("limit") or usage.get("plan_limit")
        if limit:
            used = int(used or 0)
            limit = int(limit)
            known_count += 1
            used_total += used
            limit_total += limit
            if used >= limit:
                exhausted_count += 1
                key_parts.append(labels["tavily_key_exhausted"])
            else:
                if used / limit >= 0.8:
                    warn = True
                key_parts.append(f"{used}/{limit}")
        else:
            totals_complete = False
            key_parts.append(labels["tavily_key_unknown"])

    if known_count and totals_complete:
        segments.append(
            labels["tavily_pool_total"].format(
                used=used_total,
                limit=limit_total,
                remaining=max(0, limit_total - used_total),
            )
        )

    segments.append(labels["tavily_key_sep"].join(key_parts))

    if known_count == len(pool) and exhausted_count == len(pool):
        segments.append(labels["tavily_all_exhausted"])
    elif warn:
        segments.append(labels["tavily_warn"])

    return "🔎 Tavily：" + " · ".join(segments)


def build_usage_block(
    *,
    config: Any,
    db: Any,
    from_dt: datetime,
    to_dt: datetime,
    language: str = "zh",
    search_service: Any = None,
    now: Optional[datetime] = None,
) -> str:
    """Build the optional usage block appended to aggregate reports."""
    if not getattr(config, "report_show_token_usage", False):
        return ""

    lines = []

    try:
        summary = db.get_llm_usage_summary(from_dt, to_dt)
    except Exception as exc:
        logger.warning("读取 LLM 用量失败: %s", exc)
        summary = None
    if summary:
        llm_line = format_llm_usage_line(summary, config, language)
        if llm_line:
            lines.append(llm_line)

    tavily_keys = [
        key.strip()
        for key in (getattr(config, "tavily_api_keys", None) or [])
        if (key or "").strip()
    ]
    run_calls: Optional[int] = None
    if search_service is not None:
        try:
            run_calls = search_service.get_search_call_counts().get("Tavily")
        except Exception as exc:
            logger.debug("读取搜索调用次数失败: %s", exc)
    if len(tavily_keys) > 1:
        usage_map = None
        try:
            usage_map = fetch_tavily_usage_many(tavily_keys)
        except Exception as exc:
            logger.warning("Tavily 多 Key 用量查询失败: %s", exc)
        tavily_line = format_tavily_pool_line(
            run_calls=run_calls,
            usages=[(usage_map or {}).get(key) for key in tavily_keys],
            language=language,
            now=now,
        )
    else:
        usage = fetch_tavily_usage(tavily_keys[0]) if tavily_keys else None
        tavily_line = format_tavily_usage_line(
            run_calls=run_calls,
            usage=usage,
            language=language,
            now=now,
        )
    if tavily_line:
        lines.append(tavily_line)

    if not lines:
        return ""
    return "\n\n---\n\n" + "\n".join(lines) + "\n"
