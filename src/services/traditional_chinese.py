# -*- coding: utf-8 -*-
"""
===================================
简体 -> 繁体中文报告转换（可选）
===================================

当 ``REPORT_TRADITIONAL_ZH=true`` 时，推送到通知渠道和保存到本地的最终报告
文本会在送达前由 OpenCC 统一转换为繁体中文（默认香港变体 ``hk``），覆盖
LLM 生成正文与代码内置标签；转换失败时始终回退原文，不阻断主分析流程。

依赖：``opencc-python-reimplemented``（可选；未安装时静默降级为原文）。
"""

from __future__ import annotations

import logging
import threading
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# 用户配置变体 -> OpenCC 配置名
_VARIANT_TO_OPENCC = {
    "hk": "s2hk",
    "tw": "s2twp",
    "twp": "s2twp",
    "s2t": "s2t",
}
_DEFAULT_VARIANT = "hk"

_converter_lock = threading.Lock()
_converters: dict = {}
_unavailable_logged = False


def _normalize_variant(variant: Optional[str]) -> str:
    key = (variant or _DEFAULT_VARIANT).strip().lower()
    if key not in _VARIANT_TO_OPENCC:
        logger.warning(
            "REPORT_TRADITIONAL_VARIANT '%s' invalid, fallback to '%s' (valid: hk/tw/twp/s2t)",
            variant,
            _DEFAULT_VARIANT,
        )
        key = _DEFAULT_VARIANT
    return key


def _get_converter(variant: Optional[str]):
    """Return a cached OpenCC converter; None when the optional dependency is missing."""
    global _unavailable_logged
    config_name = _VARIANT_TO_OPENCC[_normalize_variant(variant)]
    with _converter_lock:
        if config_name in _converters:
            return _converters[config_name]
        try:
            from opencc import OpenCC

            converter = OpenCC(config_name)
        except Exception as exc:  # dependency missing or OpenCC init failed
            if not _unavailable_logged:
                logger.warning(
                    "繁体中文转换不可用（请安装 opencc-python-reimplemented）: %s",
                    exc,
                )
                _unavailable_logged = True
            converter = None
        _converters[config_name] = converter
        return converter


def _resolve_config() -> Tuple[bool, str]:
    """Read REPORT_TRADITIONAL_* from the global config; fail-open to disabled."""
    try:
        from src.config import get_config

        config = get_config()
        enabled = bool(getattr(config, "report_traditional_zh", False))
        variant = getattr(config, "report_traditional_variant", _DEFAULT_VARIANT) or _DEFAULT_VARIANT
        return enabled, variant
    except Exception:
        return False, _DEFAULT_VARIANT


def apply_traditional_chinese(
    text: Optional[str],
    variant: Optional[str] = None,
) -> Optional[str]:
    """Convert report text to Traditional Chinese (best-effort, never raises).

    Args:
        text: Final rendered report text. Non-string values are returned as-is.
        variant: Explicit OpenCC variant (hk/tw/twp/s2t). When omitted, the
            conversion follows ``REPORT_TRADITIONAL_ZH`` / ``REPORT_TRADITIONAL_VARIANT``.

    Returns:
        Converted text, or the original text when conversion is disabled,
        the optional dependency is missing, or conversion fails.
    """
    if not text or not isinstance(text, str):
        return text

    if variant is None:
        enabled, configured_variant = _resolve_config()
        if not enabled:
            return text
        variant = configured_variant

    converter = _get_converter(variant)
    if converter is None:
        return text

    try:
        return converter.convert(text)
    except Exception as exc:
        logger.warning("繁体中文转换失败，返回原文: %s", exc)
        return text
