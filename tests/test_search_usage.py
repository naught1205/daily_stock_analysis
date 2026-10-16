# -*- coding: utf-8 -*-
"""Tavily usage 端点查询单元测试。"""

from __future__ import annotations

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import search_usage as su


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class TestFetchTavilyUsage:
    def test_empty_key_returns_none(self):
        assert su.fetch_tavily_usage("") is None
        assert su.fetch_tavily_usage(None) is None

    @mock.patch("requests.get")
    def test_success_parses_key_and_account(self, mock_get):
        mock_get.return_value = _Resp(200, {
            "key": {"usage": 174, "limit": 1000, "search_usage": 174},
            "account": {"current_plan": "Researcher", "plan_usage": 174, "plan_limit": 1000},
        })
        result = su.fetch_tavily_usage("tvly-test")
        assert result == {
            "used": 174,
            "limit": 1000,
            "search_usage": 174,
            "plan": "Researcher",
            "plan_usage": 174,
            "plan_limit": 1000,
        }
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer tvly-test"

    @mock.patch("requests.get")
    def test_non_200_returns_none(self, mock_get):
        mock_get.return_value = _Resp(401)
        assert su.fetch_tavily_usage("bad") is None

    @mock.patch("requests.get")
    def test_exception_returns_none(self, mock_get):
        mock_get.side_effect = RuntimeError("boom")
        assert su.fetch_tavily_usage("k") is None

    @mock.patch("requests.get")
    def test_unlimited_limit_stays_none(self, mock_get):
        mock_get.return_value = _Resp(200, {"key": {"usage": 5, "limit": None}})
        result = su.fetch_tavily_usage("k")
        assert result["limit"] is None
        assert result["used"] == 5


class TestRemainingCredits:
    def test_key_level_limit(self):
        assert su.remaining_credits({"used": 174, "limit": 1000}) == 826

    def test_plan_limit_fallback(self):
        usage = {"used": 66, "limit": None, "plan_usage": 66, "plan_limit": 1000}
        assert su.remaining_credits(usage) == 934

    def test_unknown_limit_returns_none(self):
        assert su.remaining_credits({"used": 5, "limit": None}) is None
        assert su.remaining_credits(None) is None

    def test_exhausted_returns_zero(self):
        assert su.remaining_credits({"used": 1000, "limit": 1000}) == 0
        assert su.remaining_credits({"used": 1200, "limit": 1000}) == 0


class TestSelectTavilyKeyOrder:
    def test_exhausted_keys_move_last(self):
        usage = {
            "b": {"used": 1000, "limit": 1000},
            "c": None,
        }
        assert su.select_tavily_key_order(["a", "b", "c"], usage) == ["a", "c", "b"]

    def test_blank_keys_skipped(self):
        assert su.select_tavily_key_order(["a", " ", ""], {}) == ["a"]

    def test_all_unknown_keeps_order(self):
        assert su.select_tavily_key_order(["a", "b"], {}) == ["a", "b"]


class TestFetchTavilyUsageMany:
    def setup_method(self):
        su.clear_tavily_usage_cache()

    def test_parallel_fetch_dedupes_and_caches(self):
        calls = []

        def fake_fetch(key, timeout_seconds=8.0):
            calls.append(key)
            return {"used": 1, "limit": 1000}

        with mock.patch.object(su, "fetch_tavily_usage", side_effect=fake_fetch):
            first = su.fetch_tavily_usage_many(["k1", "k2", "k1"])
            second = su.fetch_tavily_usage_many(["k1", "k2"])

        assert set(first) == {"k1", "k2"}
        assert first["k1"] == {"used": 1, "limit": 1000}
        assert second == first
        assert sorted(calls) == ["k1", "k2"]

    def test_failures_are_cached(self):
        with mock.patch.object(su, "fetch_tavily_usage", return_value=None) as mocked:
            su.fetch_tavily_usage_many(["k1"])
            su.fetch_tavily_usage_many(["k1"])
        assert mocked.call_count == 1

    def test_empty_keys(self):
        assert su.fetch_tavily_usage_many([]) == {}
        assert su.fetch_tavily_usage_many(None) == {}
