# -*- coding: utf-8 -*-
"""报告用量块（LLM tokens/成本 + Tavily credits）单元测试。"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import report_usage_block as rub


def _config(**overrides):
    base = dict(
        report_show_token_usage=True,
        llm_price_input_per_1m=0.15,
        llm_price_output_per_1m=0.60,
        tavily_api_keys=["tvly-key"],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


SUMMARY = {
    "total_calls": 14,
    "total_prompt_tokens": 300_000,
    "total_completion_tokens": 10_000,
    "total_tokens": 310_000,
    "by_model": [{"model": "openai/deepseek-v4.1-flash"}],
}


class TestFormatLlmUsageLine:
    def test_line_includes_totals_calls_model_and_cost(self):
        line = rub.format_llm_usage_line(SUMMARY, _config(), "zh")
        assert "300,000" in line
        assert "310,000" in line
        assert "14 次调用" in line
        assert "openai/deepseek-v4.1-flash" in line
        assert "US$0.05" in line

    def test_no_calls_returns_empty(self):
        assert rub.format_llm_usage_line(dict(SUMMARY, total_calls=0), _config(), "zh") == ""

    def test_cost_hidden_when_prices_zero(self):
        line = rub.format_llm_usage_line(
            SUMMARY,
            _config(llm_price_input_per_1m=0.0, llm_price_output_per_1m=0.0),
            "zh",
        )
        assert "US$" not in line

    def test_english_labels(self):
        line = rub.format_llm_usage_line(SUMMARY, _config(), "en")
        assert "Usage" in line and "14 calls" in line


class TestFormatTavilyUsageLine:
    def test_run_calls_cycle_plan_and_projection(self):
        usage = {"used": 174, "limit": 1000, "plan": "Researcher"}
        line = rub.format_tavily_usage_line(
            run_calls=19,
            usage=usage,
            language="zh",
            now=datetime(2026, 10, 10),
        )
        assert "本次搜索 19 次" in line
        assert "174/1000" in line
        assert "剩余 826" in line
        assert "Researcher" in line
        assert "539" in line  # round(174 / 10 * 31)

    def test_warning_at_80_percent(self):
        usage = {"used": 850, "limit": 1000}
        line = rub.format_tavily_usage_line(
            usage=usage,
            language="zh",
            now=datetime(2026, 10, 31),
        )
        assert "80%" in line

    def test_unlimited_limit(self):
        usage = {"used": 5, "limit": None}
        line = rub.format_tavily_usage_line(usage=usage, language="zh")
        assert "不限额度" in line

    def test_null_key_limit_falls_back_to_plan_limit(self):
        usage = {"used": 66, "limit": None, "plan": "Researcher", "plan_usage": 66, "plan_limit": 1000}
        line = rub.format_tavily_usage_line(
            usage=usage,
            language="zh",
            now=datetime(2026, 10, 10),
        )
        assert "66/1000" in line
        assert "剩余 934" in line
        assert "不限额度" not in line

    def test_nothing_returns_empty(self):
        assert rub.format_tavily_usage_line() == ""


class TestFormatTavilyPoolLine:
    def test_two_known_keys_totals_per_key_and_warning(self):
        line = rub.format_tavily_pool_line(
            run_calls=43,
            usages=[
                {"used": 950, "limit": 1000},
                {"used": 250, "limit": 1000},
            ],
            language="zh",
        )
        assert "本次搜索 43 次" in line
        assert "额度 1200/2000（剩 800）" in line
        assert "950/1000" in line
        assert "250/1000" in line
        assert "80%" in line

    def test_exhausted_marker_and_all_exhausted(self):
        line = rub.format_tavily_pool_line(
            usages=[
                {"used": 1000, "limit": 1000},
                {"used": 1000, "limit": 1000},
            ],
            language="zh",
        )
        assert "⛔已用尽" in line
        assert "所有 Key 已用尽" in line

    def test_unknown_usage_omits_totals(self):
        line = rub.format_tavily_pool_line(
            usages=[{"used": 5, "limit": 1000}, None],
            language="zh",
        )
        assert "未知" in line
        assert "5/1000" in line
        assert "额度" not in line

    def test_single_or_no_key_returns_empty(self):
        assert rub.format_tavily_pool_line(usages=[{"used": 1, "limit": 1000}]) == ""
        assert rub.format_tavily_pool_line() == ""

    def test_english_labels(self):
        line = rub.format_tavily_pool_line(
            usages=[
                {"used": 950, "limit": 1000},
                {"used": 250, "limit": 1000},
            ],
            language="en",
        )
        assert "pool 1200/2000" in line
        assert "(800 left)" in line


class TestBuildUsageBlock:
    def test_disabled_returns_empty(self):
        block = rub.build_usage_block(
            config=_config(report_show_token_usage=False),
            db=mock.Mock(),
            from_dt=datetime(2026, 10, 10, 0, 0),
            to_dt=datetime(2026, 10, 10, 1, 0),
        )
        assert block == ""

    def test_enabled_builds_block_with_llm_and_tavily(self):
        db = mock.Mock()
        db.get_llm_usage_summary.return_value = SUMMARY
        with mock.patch.object(
            rub,
            "fetch_tavily_usage",
            return_value={"used": 10, "limit": 1000, "plan": "Researcher"},
        ):
            block = rub.build_usage_block(
                config=_config(),
                db=db,
                from_dt=datetime(2026, 10, 10, 0, 0),
                to_dt=datetime(2026, 10, 10, 1, 0),
                language="zh",
                now=datetime(2026, 10, 10),
            )
        assert block.startswith("\n\n---\n\n")
        assert "🔢" in block
        assert "🔎 Tavily" in block

    def test_run_count_from_search_service(self):
        db = mock.Mock()
        db.get_llm_usage_summary.return_value = SUMMARY
        search_service = mock.Mock()
        search_service.get_search_call_counts.return_value = {"Tavily": 7}
        with mock.patch.object(rub, "fetch_tavily_usage", return_value=None):
            block = rub.build_usage_block(
                config=_config(),
                db=db,
                from_dt=datetime(2026, 10, 10, 0, 0),
                to_dt=datetime(2026, 10, 10, 1, 0),
                language="zh",
                search_service=search_service,
                now=datetime(2026, 10, 10),
            )
        assert "本次搜索 7 次" in block

    def test_all_sources_fail_returns_empty(self):
        db = mock.Mock()
        db.get_llm_usage_summary.side_effect = RuntimeError("db down")
        with mock.patch.object(rub, "fetch_tavily_usage", return_value=None):
            block = rub.build_usage_block(
                config=_config(),
                db=db,
                from_dt=datetime(2026, 10, 10, 0, 0),
                to_dt=datetime(2026, 10, 10, 1, 0),
                language="zh",
            )
        assert block == ""

    def test_multi_key_config_uses_pool_line(self):
        db = mock.Mock()
        db.get_llm_usage_summary.return_value = SUMMARY
        usage_map = {
            "k1": {"used": 1000, "limit": 1000},
            "k2": {"used": 10, "limit": 1000},
        }
        with mock.patch.object(
            rub, "fetch_tavily_usage_many", return_value=usage_map
        ) as mocked_many, mock.patch.object(rub, "fetch_tavily_usage") as mocked_single:
            block = rub.build_usage_block(
                config=_config(tavily_api_keys=["k1", "k2"]),
                db=db,
                from_dt=datetime(2026, 10, 10, 0, 0),
                to_dt=datetime(2026, 10, 10, 1, 0),
                language="zh",
                now=datetime(2026, 10, 10),
            )
        assert "🔎 Tavily" in block
        assert "⛔已用尽" in block
        assert "10/1000" in block
        mocked_many.assert_called_once_with(["k1", "k2"])
        mocked_single.assert_not_called()
