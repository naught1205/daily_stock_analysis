# -*- coding: utf-8 -*-
"""_append_usage_block 在未初始化 pipeline 上不得抛 AttributeError 的回归测试。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from src.core.pipeline import StockAnalysisPipeline


class TestAppendUsageBlockGuards:
    def test_without_init_returns_report_unchanged(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        assert pipeline._append_usage_block("hello report", []) == "hello report"

    def test_disabled_config_returns_report_unchanged(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(report_show_token_usage=False)
        pipeline.db = object()
        pipeline._usage_window_start = datetime.now()
        assert pipeline._append_usage_block("hello report", []) == "hello report"

    def test_missing_db_returns_report_unchanged(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(report_show_token_usage=True)
        pipeline._usage_window_start = datetime.now()
        assert pipeline._append_usage_block("hello report", []) == "hello report"
