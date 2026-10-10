# 繁体中文报告输出（可选）

本仓库支持在推送与本地保存前，将最终报告文本统一转换为繁体中文。转换覆盖 LLM 生成正文与代码内置标签，不影响分析流程本身。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `REPORT_TRADITIONAL_ZH` | `false` | 设为 `true` 时启用繁体转换 |
| `REPORT_TRADITIONAL_VARIANT` | `hk` | 繁体变体：`hk`(香港) / `tw` / `twp`(台湾惯用词) / `s2t`(通用繁体) |

配合 `REPORT_LANGUAGE=zh` 使用：LLM 以中文生成报告，送达前统一转换为繁体。

GitHub Actions 工作流已透传以上两个变量（Variables 优先、Secrets 回退），无需修改 workflow。

## 生效范围

- 所有通知渠道推送：个股汇总（含逐渠道直发路径：Discord / Telegram / 邮件 / 自定义 Webhook 等）、单股推送、大盘复盘、合并推送、企业微信精简报告、分组邮件，以及 Markdown 转图片渲染输入。
- 通过 `save_report_to_file()` 保存的 `reports/*.md` 文件（含飞书文件上传链路与回退写盘路径）。
- 不包含：Web UI 界面文案（仍为简体/英文）、即时交互式 Agent 对话。

## 实现与降级

- 转换模块：`src/services/traditional_chinese.py`，基于 OpenCC（`s2hk` / `s2twp` / `s2t`）。
- 依赖：`opencc-python-reimplemented`（`requirements.txt`，纯 Python，无平台限制）。
- 降级：依赖缺失、变体非法或转换异常时自动返回原文并记录 warning，不阻断主流程；转换器按变体缓存，线程安全。
- 幂等：`s2hk` 等配置对已转换文本再次转换结果稳定。

## 验证

```bash
python -m pytest --noconftest -q tests/test_traditional_chinese.py
```

覆盖：香港/台湾/通用变体转换、非法变体回退、英文与数字透传、空值透传、幂等、配置开关行为、依赖缺失降级。

## 回滚

1. 将 `REPORT_TRADITIONAL_ZH` 置为 `false`（或删除该变量）即可立即关闭转换，无需回滚代码。
2. 如需整体回滚：还原 `src/notification.py`、`src/core/pipeline.py`、`src/config.py`、`requirements.txt`、`.github/workflows/00-daily-analysis.yml` 的对应改动并删除本模块与测试。
