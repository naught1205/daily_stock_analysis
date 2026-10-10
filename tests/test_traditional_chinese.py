# -*- coding: utf-8 -*-
"""REPORT_TRADITIONAL_ZH 繁体中文转换模块单元测试。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import traditional_chinese as tc

pytest.importorskip("opencc")


class TestApplyTraditionalChinese:
    def test_hk_variant_conversion(self):
        assert tc.apply_traditional_chinese("软件 数据 优化", variant="hk") == "軟件 數據 優化"

    def test_tw_variant_uses_taiwan_phrases(self):
        assert tc.apply_traditional_chinese("软件", variant="tw") == "軟體"

    def test_s2t_generic_variant(self):
        assert tc.apply_traditional_chinese("网络", variant="s2t") == "網絡"

    def test_invalid_variant_falls_back_to_hk(self):
        assert tc.apply_traditional_chinese("软件", variant="not-a-variant") == "軟件"

    def test_english_and_numbers_pass_through(self):
        text = "Hello AAPL 123, MSFT -1.2%"
        assert tc.apply_traditional_chinese(text, variant="hk") == text

    def test_none_and_empty_pass_through(self):
        assert tc.apply_traditional_chinese(None, variant="hk") is None
        assert tc.apply_traditional_chinese("", variant="hk") == ""

    def test_conversion_is_idempotent(self):
        once = tc.apply_traditional_chinese("软件 数据", variant="hk")
        twice = tc.apply_traditional_chinese(once, variant="hk")
        assert once == twice

    def test_disabled_config_returns_original(self, monkeypatch):
        monkeypatch.setattr(tc, "_resolve_config", lambda: (False, "hk"))
        assert tc.apply_traditional_chinese("软件") == "软件"

    def test_enabled_config_uses_configured_variant(self, monkeypatch):
        monkeypatch.setattr(tc, "_resolve_config", lambda: (True, "hk"))
        assert tc.apply_traditional_chinese("软件") == "軟件"

    def test_missing_converter_degrades_to_original(self, monkeypatch):
        monkeypatch.setattr(tc, "_get_converter", lambda variant: None)
        assert tc.apply_traditional_chinese("软件", variant="hk") == "软件"
