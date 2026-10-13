# -*- coding: utf-8 -*-
"""Discord 自动日频道（按交易日命名）单元测试。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import mock

from src.notification_sender.discord_sender import DiscordSender


def _config(**overrides):
    base = dict(
        discord_bot_token="T",
        discord_main_channel_id="555",
        discord_webhook_url="https://discord.com/api/webhooks/999/tok",
        discord_webhook_username=None,
        discord_webhook_avatar_url=None,
        discord_max_words=2000,
        webhook_verify_ssl=True,
        discord_auto_daily_channel=True,
        discord_daily_channel_market="us",
        discord_daily_channel_category_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _response(status_code, payload=None):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.content = b"{}"
    resp.json.return_value = payload if payload is not None else {}
    resp.text = ""
    return resp


class TestDailyChannel:
    def _routes(self, channel_name):
        return {
            ("GET", "/channels/555"): {"guild_id": "G1"},
            ("GET", "/guilds/G1/channels"): [
                {"id": "C9", "name": channel_name, "type": 0},
            ],
        }

    def test_reuses_existing_channel_and_sends_via_bot(self):
        expected_name = "2026-10-09"
        routes = self._routes(expected_name)

        def fake_api(self, method, path, payload=None, **kwargs):
            return routes.get((method, path))

        with mock.patch("src.notification_sender.discord_sender.get_effective_trading_date",
                        return_value=date(2026, 10, 9)), \
                mock.patch.object(DiscordSender, "_discord_bot_request", fake_api), \
                mock.patch("src.notification_sender.discord_sender.requests.post",
                           return_value=_response(200)) as mock_post:
            sender = DiscordSender(_config())
            assert sender.send_to_discord("hello") is True

        url = mock_post.call_args[0][0]
        assert "/channels/C9/messages" in url
        assert mock_post.call_args[1]["headers"]["Authorization"] == "Bot T"

    def test_creates_channel_when_missing(self):
        expected_name = "2026-10-09"
        routes = {
            ("GET", "/channels/555"): {"guild_id": "G1"},
            ("GET", "/guilds/G1/channels"): [],
            ("POST", "/guilds/G1/channels"): {"id": "C10"},
        }
        create_calls = []

        def fake_api(self, method, path, payload=None, **kwargs):
            if (method, path) == ("POST", "/guilds/G1/channels"):
                create_calls.append(payload)
            return routes.get((method, path))

        with mock.patch("src.notification_sender.discord_sender.get_effective_trading_date",
                        return_value=date(2026, 10, 9)), \
                mock.patch.object(DiscordSender, "_discord_bot_request", fake_api), \
                mock.patch("src.notification_sender.discord_sender.requests.post",
                           return_value=_response(200)) as mock_post:
            sender = DiscordSender(_config())
            assert sender.send_to_discord("hello") is True

        assert create_calls and create_calls[0]["name"] == expected_name
        assert create_calls[0]["type"] == 0
        assert "/channels/C10/messages" in mock_post.call_args[0][0]

    def test_falls_back_to_webhook_when_bot_api_fails(self):
        def fake_api(self, method, path, payload=None, **kwargs):
            return None

        with mock.patch("src.notification_sender.discord_sender.get_effective_trading_date",
                        return_value=date(2026, 10, 9)), \
                mock.patch.object(DiscordSender, "_discord_bot_request", fake_api), \
                mock.patch("src.notification_sender.discord_sender.requests.post",
                           return_value=_response(204)) as mock_post:
            sender = DiscordSender(_config())
            assert sender.send_to_discord("hello") is True

        url = mock_post.call_args[0][0]
        assert "webhooks/999/tok" in url
        assert mock_post.call_args[1]["json"]["username"] == "A股分析机器人"

    def test_disabled_uses_webhook_without_bot_api(self):
        with mock.patch.object(DiscordSender, "_discord_bot_request") as mock_api, \
                mock.patch("src.notification_sender.discord_sender.requests.post",
                           return_value=_response(204)) as mock_post:
            sender = DiscordSender(_config(discord_auto_daily_channel=False))
            assert sender.send_to_discord("hello") is True

        mock_api.assert_not_called()
        assert "webhooks/999/tok" in mock_post.call_args[0][0]
