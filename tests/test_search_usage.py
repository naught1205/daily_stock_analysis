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
