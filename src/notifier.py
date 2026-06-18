"""
알림 모듈 — 텔레그램 발송
"""
import requests
from typing import Optional

from .config import load_config


class Notifier:
    """텔레그램 알림"""

    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = cfg or load_config()
        self.tg = self.cfg.get("telegram", {})
        self.enabled = self.tg.get("enabled", False)
        self.token = self.tg.get("token", "")
        self.chat_id = self.tg.get("chat_id", "")

    def send(self, message: str):
        """메시지 발송"""
        if not self.enabled or not self.token or not self.chat_id:
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            requests.post(url, json={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
            }, timeout=10)
        except Exception as e:
            print(f"  ⚠️ Telegram send error: {e}")

    def alert_ticket_open(self, platform: str, title: str, url: str):
        """티켓 오픈 알림"""
        self.send(
            f"🎫 <b>[{platform}] 티켓 오픈!</b>\n"
            f"{title}\n"
            f"🔗 <a href='{url}'>바로가기</a>"
        )

    def alert_reservation_done(self, platform: str, title: str, info: str = ""):
        """예매 완료 알림"""
        self.send(
            f"✅ <b>[{platform}] 예매 완료!</b>\n"
            f"{title}\n"
            f"{info}"
        )

    def alert_error(self, platform: str, error: str):
        """에러 알림"""
        self.send(
            f"❌ <b>[{platform}] 오류</b>\n"
            f"{error}"
        )
