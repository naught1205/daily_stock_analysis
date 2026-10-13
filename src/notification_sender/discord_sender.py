# -*- coding: utf-8 -*-
"""
Discord 发送提醒服务

职责：
1. 通过 webhook 或 Discord bot API 发送 Discord 消息
"""
import logging
import time
from datetime import datetime
from typing import Optional

import requests

from src.config import Config
from src.core.trading_calendar import get_effective_trading_date
from src.formatters import (
    MIN_MAX_WORDS,
    chunk_content_by_max_words,
    strip_hidden_markdown_metadata,
)


logger = logging.getLogger(__name__)


DISCORD_MAX_CONTENT_LENGTH = 2000
DISCORD_MAX_RETRIES = 3
DISCORD_CHUNK_SLEEP_SECONDS = 1


class DiscordSender:
    
    def __init__(self, config: Config):
        """
        初始化 Discord 配置

        Args:
            config: 配置对象
        """
        self._discord_config = {
            'bot_token': getattr(config, 'discord_bot_token', None),
            'channel_id': getattr(config, 'discord_main_channel_id', None),
            'webhook_url': getattr(config, 'discord_webhook_url', None),
            'webhook_username': getattr(config, 'discord_webhook_username', None),
            'webhook_avatar_url': getattr(config, 'discord_webhook_avatar_url', None),
        }
        self._discord_max_words = self._normalize_max_words(
            getattr(config, 'discord_max_words', DISCORD_MAX_CONTENT_LENGTH)
        )
        self._webhook_verify_ssl = getattr(config, 'webhook_verify_ssl', True)
        self._auto_daily_channel = bool(getattr(config, 'discord_auto_daily_channel', False))
        self._daily_channel_market = (
            getattr(config, 'discord_daily_channel_market', 'us') or 'us'
        ).strip().lower()
        self._daily_channel_category_id = (
            getattr(config, 'discord_daily_channel_category_id', None) or ''
        ).strip() or None
        self._daily_channel_cache: Optional[str] = None

    @staticmethod
    def _normalize_max_words(value) -> int:
        try:
            configured = int(value)
        except (TypeError, ValueError):
            configured = DISCORD_MAX_CONTENT_LENGTH
        return max(MIN_MAX_WORDS, min(configured, DISCORD_MAX_CONTENT_LENGTH))
    
    def _is_discord_configured(self) -> bool:
        """检查 Discord 配置是否完整（支持 Bot 或 Webhook）"""
        # 只要配置了 Webhook 或完整的 Bot Token+Channel，即视为可用
        bot_ok = bool(self._discord_config['bot_token'] and self._discord_config['channel_id'])
        webhook_ok = bool(self._discord_config['webhook_url'])
        return bot_ok or webhook_ok
    
    def send_to_discord(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        推送消息到 Discord（支持 Webhook 和 Bot API）
        
        Args:
            content: Markdown 格式的消息内容
            
        Returns:
            是否发送成功
        """
        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        if not sanitized_content:
            logger.warning("Discord 消息内容为空，跳过推送")
            return False

        # 分割内容，避免单条消息超过 Discord 限制
        chunks = self._split_discord_content(sanitized_content)

        # 可选：自动日频道模式（Bot 创建/复用按最近的已完成交易日命名的频道并发送）
        if (
            self._auto_daily_channel
            and self._discord_config.get('bot_token')
            and (self._discord_config.get('channel_id') or self._discord_config.get('webhook_url'))
        ):
            daily_channel_id = self._resolve_daily_channel_id()
            if daily_channel_id:
                return self._send_discord_chunks(
                    chunks,
                    lambda chunk, timeout_seconds=None: self._send_discord_bot(
                        chunk,
                        timeout_seconds=timeout_seconds,
                        channel_id=daily_channel_id,
                    ),
                    "Bot(daily)",
                    timeout_seconds=timeout_seconds,
                )
            logger.warning("自动日频道不可用，回退默认推送通道")

        # 优先使用 Webhook（配置简单，权限低）
        if self._discord_config['webhook_url']:
            return self._send_discord_chunks(
                chunks,
                self._send_discord_webhook,
                "Webhook",
                timeout_seconds=timeout_seconds,
            )

        # 其次使用 Bot API（权限高，需要 channel_id）
        if self._discord_config['bot_token'] and self._discord_config['channel_id']:
            return self._send_discord_chunks(
                chunks,
                self._send_discord_bot,
                "Bot",
                timeout_seconds=timeout_seconds,
            )

        logger.warning("Discord 配置不完整，跳过推送")
        return False

    def _split_discord_content(self, content: str) -> list[str]:
        """按 Discord content 上限拆分消息。"""
        try:
            chunks = chunk_content_by_max_words(content, self._discord_max_words)
            if len(chunks) > 1:
                chunks = chunk_content_by_max_words(
                    content,
                    self._discord_max_words,
                    add_page_marker=True,
                )
            return chunks
        except ValueError as e:
            logger.error("分割 Discord 消息失败: %s", e)
            return chunk_content_by_max_words(
                content,
                DISCORD_MAX_CONTENT_LENGTH,
                add_page_marker=True,
            )

    def _send_discord_chunks(
        self,
        chunks: list[str],
        send_once,
        channel_name: str,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """逐片发送 Discord 消息；失败片不应阻断后续片尝试。"""
        total_chunks = len(chunks)
        success_count = 0

        if total_chunks > 1:
            logger.info("Discord %s 分批发送：共 %d 批", channel_name, total_chunks)

        for i, chunk in enumerate(chunks):
            if send_once(chunk, timeout_seconds=timeout_seconds):
                success_count += 1
                if total_chunks > 1:
                    logger.info("Discord %s 第 %d/%d 批发送成功", channel_name, i + 1, total_chunks)
            else:
                logger.error("Discord %s 第 %d/%d 批发送失败", channel_name, i + 1, total_chunks)

            if i < total_chunks - 1:
                time.sleep(DISCORD_CHUNK_SLEEP_SECONDS)

        return success_count == total_chunks

  
    def _send_discord_webhook(self, content: str, *, timeout_seconds: Optional[float] = None) -> bool:
        """
        使用 Webhook 发送消息到 Discord
        
        Discord Webhook 支持 Markdown 格式
        
        Args:
            content: Markdown 格式的消息内容
            
        Returns:
            是否发送成功
        """
        payload = {
            'content': content,
            'username': self._discord_config.get('webhook_username') or 'A股分析机器人',
        }
        avatar_url = (self._discord_config.get('webhook_avatar_url') or '').strip()
        if avatar_url:
            payload['avatar_url'] = avatar_url

        return self._post_discord_message(
            self._discord_config['webhook_url'],
            payload,
            success_statuses=(200, 204),
            verify=self._webhook_verify_ssl,
            timeout_seconds=timeout_seconds,
            channel_name="Webhook",
        )
    
    def _send_discord_bot(
        self,
        content: str,
        *,
        timeout_seconds: Optional[float] = None,
        channel_id: Optional[str] = None,
    ) -> bool:
        """
        使用 Bot API 发送消息到 Discord
        
        Args:
            content: Markdown 格式的消息内容
            
        Returns:
            是否发送成功
        """
        target_channel_id = channel_id or self._discord_config["channel_id"]
        if not target_channel_id:
            logger.warning("Discord Bot 缺少频道 ID，跳过推送")
            return False
        headers = {
            'Authorization': f'Bot {self._discord_config["bot_token"]}',
            'Content-Type': 'application/json'
        }
        payload = {'content': content}
        url = f'https://discord.com/api/v10/channels/{target_channel_id}/messages'

        return self._post_discord_message(
            url,
            payload,
            headers=headers,
            success_statuses=(200,),
            timeout_seconds=timeout_seconds,
            channel_name="Bot",
        )

    def _daily_channel_name(self, *, current_time: Optional[datetime] = None) -> str:
        """按最近的已完成交易日（market 配置）生成频道名 YYYY-MM-DD。"""
        try:
            return get_effective_trading_date(self._daily_channel_market, current_time=current_time).isoformat()
        except Exception as exc:
            logger.warning("推导交易日日期失败，回退自然日: %s", exc)
            return (current_time or datetime.now()).strftime("%Y-%m-%d")

    def _webhook_info(self) -> Optional[dict]:
        """通过 URL 内嵌 token 的公开端点获取 Webhook 对象（含 channel_id/guild_id）。

        Discord 对不带 token 的 GET /webhooks/{id} 会返回 401，因此必须使用
        GET /webhooks/{id}/{token}。
        """
        webhook_url = (self._discord_config.get('webhook_url') or '').strip()
        marker = '/api/webhooks/'
        if marker not in webhook_url:
            return None
        remainder = webhook_url.split(marker, 1)[1].strip('/')
        parts = [part for part in remainder.split('/') if part]
        if not parts:
            return None
        webhook_id = parts[0]
        webhook_token = parts[1] if len(parts) > 1 else None
        if webhook_token:
            path = f"/webhooks/{webhook_id}/{webhook_token}"
        else:
            path = f"/webhooks/{webhook_id}"
        data = self._discord_bot_request(
            "GET",
            path,
            auth=False,
            channel_name="WebhookInfo",
        )
        return data if isinstance(data, dict) else None

    def _webhook_channel_id(self) -> Optional[str]:
        """从配置的 Webhook 解析绑定频道 ID。"""
        webhook = self._webhook_info()
        return webhook.get("channel_id") if webhook else None

    def _resolve_guild_id(self) -> Optional[str]:
        """解析 Bot 所在服务器 ID：优先显式频道，其次 Webhook 对象自带 guild_id。"""
        channel_id = self._discord_config.get('channel_id')
        if channel_id:
            data = self._discord_bot_request(
                "GET",
                f"/channels/{channel_id}",
                channel_name="ChannelInfo",
            )
            if isinstance(data, dict) and data.get("guild_id"):
                return data.get("guild_id")

        webhook = self._webhook_info()
        if webhook:
            if webhook.get("guild_id"):
                return webhook.get("guild_id")
            webhook_channel_id = webhook.get("channel_id")
            if webhook_channel_id:
                data = self._discord_bot_request(
                    "GET",
                    f"/channels/{webhook_channel_id}",
                    channel_name="ChannelInfo",
                )
                if isinstance(data, dict):
                    return data.get("guild_id")
        return None

    def _resolve_daily_channel_id(self) -> Optional[str]:
        """查找或创建「YYYY-MM-DD」文本频道；失败返回 None（调用方回退）。"""
        if self._daily_channel_cache:
            return self._daily_channel_cache

        guild_id = self._resolve_guild_id()
        if not guild_id:
            logger.warning("自动日频道：无法解析服务器 ID")
            return None

        channel_name = self._daily_channel_name()
        channels = self._discord_bot_request(
            "GET",
            f"/guilds/{guild_id}/channels",
            channel_name="GuildChannels",
        )
        if isinstance(channels, list):
            for channel in channels:
                if channel.get("type") == 0 and channel.get("name") == channel_name:
                    self._daily_channel_cache = channel.get("id")
                    return self._daily_channel_cache

        payload = {"name": channel_name, "type": 0}
        if self._daily_channel_category_id:
            payload["parent_id"] = self._daily_channel_category_id
        created = self._discord_bot_request(
            "POST",
            f"/guilds/{guild_id}/channels",
            payload=payload,
            channel_name="CreateChannel",
        )
        if isinstance(created, dict) and created.get("id"):
            logger.info("自动日频道已创建: %s (%s)", channel_name, created.get("id"))
            self._daily_channel_cache = created.get("id")
            return self._daily_channel_cache

        logger.warning("自动日频道创建失败: %s", channel_name)
        return None

    def _discord_bot_request(
        self,
        method: str,
        path: str,
        payload: Optional[dict] = None,
        *,
        auth: bool = True,
        timeout_seconds: Optional[float] = None,
        channel_name: str = "Bot API",
    ):
        """调用 Discord Bot API（有限重试）；失败返回 None，不抛出。"""
        url = f"https://discord.com/api/v10{path}"
        headers = {'Content-Type': 'application/json'}
        if auth:
            bot_token = self._discord_config.get('bot_token')
            if not bot_token:
                return None
            headers['Authorization'] = f'Bot {bot_token}'

        request_kwargs = {
            'headers': headers,
            'timeout': timeout_seconds or 10,
        }
        if payload is not None:
            request_kwargs['json'] = payload

        for attempt in range(1, DISCORD_MAX_RETRIES + 1):
            try:
                response = requests.request(method, url, **request_kwargs)
            except requests.exceptions.RequestException as e:
                if attempt < DISCORD_MAX_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                logger.error("Discord %s 请求异常: %s", channel_name, e)
                return None

            if 200 <= response.status_code < 300:
                if not getattr(response, 'content', b''):
                    return {}
                try:
                    return response.json()
                except ValueError:
                    return {}

            if response.status_code == 429 and attempt < DISCORD_MAX_RETRIES:
                time.sleep(self._get_retry_after_seconds(response, attempt))
                continue
            if response.status_code >= 500 and attempt < DISCORD_MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue

            logger.error(
                "Discord %s 调用失败: %s %s",
                channel_name,
                response.status_code,
                getattr(response, 'text', ''),
            )
            return None

        return None

    def _post_discord_message(
        self,
        url: str,
        payload: dict,
        *,
        success_statuses: tuple[int, ...],
        headers: Optional[dict] = None,
        verify: Optional[bool] = None,
        timeout_seconds: Optional[float] = None,
        channel_name: str,
    ) -> bool:
        """发送单条 Discord 消息，并复用 Telegram 的有限重试思路处理 429/5xx。"""
        request_kwargs = {
            'json': payload,
            'timeout': timeout_seconds or 10,
        }
        if headers:
            request_kwargs['headers'] = headers
        if verify is not None:
            request_kwargs['verify'] = verify

        for attempt in range(1, DISCORD_MAX_RETRIES + 1):
            try:
                response = requests.post(url, **request_kwargs)
            except requests.exceptions.RequestException as e:
                if attempt < DISCORD_MAX_RETRIES:
                    delay = 2 ** attempt
                    logger.warning(
                        "Discord %s 请求异常（%d/%d）：%s，%s 秒后重试",
                        channel_name,
                        attempt,
                        DISCORD_MAX_RETRIES,
                        e,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                logger.error("Discord %s 请求重试后仍失败: %s", channel_name, e)
                return False

            if response.status_code in success_statuses:
                logger.info("Discord %s 消息发送成功", channel_name)
                return True

            if response.status_code == 429 and attempt < DISCORD_MAX_RETRIES:
                retry_after = self._get_retry_after_seconds(response, attempt)
                logger.warning(
                    "Discord %s 触发限流，%s 秒后重试（%d/%d）",
                    channel_name,
                    retry_after,
                    attempt,
                    DISCORD_MAX_RETRIES,
                )
                time.sleep(retry_after)
                continue

            if response.status_code >= 500 and attempt < DISCORD_MAX_RETRIES:
                delay = 2 ** attempt
                logger.warning(
                    "Discord %s 服务端错误 HTTP %s（%d/%d），%s 秒后重试",
                    channel_name,
                    response.status_code,
                    attempt,
                    DISCORD_MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)
                continue

            logger.error(
                "Discord %s 发送失败: %s %s",
                channel_name,
                response.status_code,
                response.text,
            )
            return False

        return False

    @staticmethod
    def _get_retry_after_seconds(response, attempt: int) -> float:
        try:
            retry_after = response.json().get('retry_after')
            if retry_after is not None:
                return max(0.0, float(retry_after))
        except (AttributeError, TypeError, ValueError):
            pass

        try:
            retry_after = response.headers.get('Retry-After')
            if retry_after is not None:
                return max(0.0, float(retry_after))
        except AttributeError:
            pass

        return float(2 ** attempt)
