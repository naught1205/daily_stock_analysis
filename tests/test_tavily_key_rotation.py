# -*- coding: utf-8 -*-
"""Tavily 多 Key 额度轮换（drain-first + 运行中 failover）单元测试。"""

import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import TavilySearchProvider  # noqa: E402
from src.services import search_usage as su  # noqa: E402


class UsageLimitExceededError(Exception):
    """模拟 tavily.errors.UsageLimitExceededError（HTTP 429）。"""


class _FakeTavilyClient:
    behaviors = {}
    search_keys = []

    def __init__(self, api_key=None, **_kwargs):
        self.api_key = api_key

    def search(self, **_kwargs):
        type(self).search_keys.append(self.api_key)
        behavior = type(self).behaviors.get(self.api_key)
        if isinstance(behavior, Exception):
            raise behavior
        if behavior is not None:
            return behavior
        return {"results": [{"title": "t", "content": "c", "url": "https://example.com/a"}]}

    @classmethod
    def reset(cls):
        cls.behaviors = {}
        cls.search_keys = []


def _fake_tavily_module() -> ModuleType:
    module = ModuleType("tavily")
    module.TavilyClient = _FakeTavilyClient
    return module


def _patch_tavily():
    return patch.dict(sys.modules, {"tavily": _fake_tavily_module()})


def _patch_usage(usage_by_key=None):
    return patch.object(su, "fetch_tavily_usage_many", return_value=usage_by_key or {})


class TestTavilyKeyRotation(unittest.TestCase):
    def setUp(self):
        _FakeTavilyClient.reset()
        su.clear_tavily_usage_cache()

    def _provider(self, keys, usage_by_key=None):
        with _patch_usage(usage_by_key):
            return TavilySearchProvider(keys)

    def test_quota_error_fails_over_and_retries_same_query(self) -> None:
        provider = self._provider(["k1", "k2"])
        _FakeTavilyClient.behaviors = {
            "k1": UsageLimitExceededError("Your plan limit has been reached"),
        }
        with _patch_tavily():
            first = provider.search("q1")
            second = provider.search("q2")
        self.assertTrue(first.success)
        self.assertTrue(second.success)
        # q1: k1 额度错误后切 k2 重试；q2: k1 已标记，直接用 k2
        self.assertEqual(_FakeTavilyClient.search_keys, ["k1", "k2", "k2"])

    def test_all_keys_exhausted_returns_clear_message(self) -> None:
        provider = self._provider(["k1", "k2"])
        _FakeTavilyClient.behaviors = {
            "k1": UsageLimitExceededError("plan limit"),
            "k2": UsageLimitExceededError("plan limit"),
        }
        with _patch_tavily():
            response = provider.search("q")
        self.assertFalse(response.success)
        self.assertIn("所有 API Key 本月额度已用尽", response.error_message)
        self.assertEqual(_FakeTavilyClient.search_keys, ["k1", "k2"])

    def test_non_quota_error_does_not_failover(self) -> None:
        provider = self._provider(["k1", "k2"])
        _FakeTavilyClient.behaviors = {"k1": RuntimeError("boom")}
        with _patch_tavily():
            response = provider.search("q")
        self.assertFalse(response.success)
        self.assertIn("boom", response.error_message)
        self.assertEqual(_FakeTavilyClient.search_keys, ["k1"])

    def test_usage_order_prefers_key_with_remaining_credits(self) -> None:
        provider = self._provider(
            ["drained", "fresh"],
            usage_by_key={
                "drained": {"used": 1000, "limit": 1000},
                "fresh": {"used": 0, "limit": 1000},
            },
        )
        self.assertEqual(provider._api_keys, ["fresh", "drained"])
        with _patch_tavily():
            response = provider.search("q")
        self.assertTrue(response.success)
        self.assertEqual(_FakeTavilyClient.search_keys, ["fresh"])

    def test_news_topic_search_uses_failover(self) -> None:
        provider = self._provider(["k1", "k2"])
        _FakeTavilyClient.behaviors = {"k1": UsageLimitExceededError("plan limit")}
        with _patch_tavily():
            response = provider.search("news q", topic="news")
        self.assertTrue(response.success)
        self.assertEqual(_FakeTavilyClient.search_keys, ["k1", "k2"])

    def test_single_key_makes_no_usage_query(self) -> None:
        with patch.object(su, "fetch_tavily_usage_many") as mocked:
            provider = TavilySearchProvider(["only"])
        mocked.assert_not_called()
        self.assertEqual(provider._api_keys, ["only"])

    def test_usage_query_failure_falls_back_to_config_order(self) -> None:
        with patch.object(su, "fetch_tavily_usage_many", side_effect=RuntimeError("down")):
            provider = TavilySearchProvider(["a", "b"])
        self.assertEqual(provider._api_keys, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
