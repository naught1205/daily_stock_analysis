# -*- coding: utf-8 -*-
"""Discord Webhook 显示名称/头像覆盖配置单元测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from src.notification_sender.discord_sender import DiscordSender


def _config(**overrides):
    base = dict(
        discord_bot_token=None,
        discord_main_channel_id=None,
        discord_webhook_url="https://discord.com/webhook/1",
        discord_webhook_username=None,
        discord_webhook_avatar_url=None,
        discord_max_words=2000,
        webhook_verify_ssl=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _response(status_code):
    resp = mock.Mock()
    resp.status_code = status_code
    return resp


class TestDiscordWebhookIdentity:
    @mock.patch("src.notification_sender.discord_sender.requests.post")
    def test_default_username_kept_and_no_avatar(self, mock_post):
        mock_post.return_value = _response(204)
        sender = DiscordSender(_config())
        assert sender.send_to_discord("hello") is True
        payload = mock_post.call_args[1]["json"]
        assert payload["username"] == "A股分析机器人"
        assert "avatar_url" not in payload

    @mock.patch("src.notification_sender.discord_sender.requests.post")
    def test_username_and_avatar_overrides(self, mock_post):
        mock_post.return_value = _response(204)
        sender = DiscordSender(_config(
            discord_webhook_username="My Frd",
            discord_webhook_avatar_url="https://example.com/avatar.jpg",
        ))
        assert sender.send_to_discord("hello") is True
        payload = mock_post.call_args[1]["json"]
        assert payload["username"] == "My Frd"
        assert payload["avatar_url"] == "https://example.com/avatar.jpg"
