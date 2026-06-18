"""
Playwright 브라우저 관리 — stealth 설정, 재사용, 스크린샷
"""
import os
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import (
    sync_playwright,
    Playwright,
    Browser,
    BrowserContext,
    Page,
)

from .config import load_config


class BrowserManager:
    """브라우저 세션 관리자"""

    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = cfg or load_config()
        self.browser_cfg = self.cfg["browser"]
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def start(self) -> Page:
        """브라우저 시작 및 페이지 반환"""
        self._playwright = sync_playwright().__enter__()
        bc = self.browser_cfg

        launch_kwargs = {
            "headless": bc.get("headless", False),
            "slow_mo": bc.get("slow_mo", 50),
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        }

        channel = bc.get("channel", "chrome")
        if channel:
            if channel == "chrome" and bc.get("headless", False):
                launch_kwargs["args"].append("--headless=new")
            launch_kwargs["channel"] = channel

        self._browser = self._playwright.chromium.launch(**launch_kwargs)

        # 컨텍스트 생성
        context_kwargs = {
            "viewport": bc.get("viewport", {"width": 1280, "height": 900}),
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "locale": "ko-KR",
            "timezone_id": "Asia/Seoul",
        }

        user_data_dir = bc.get("user_data_dir")
        if user_data_dir:
            context_kwargs["user_data_dir"] = user_data_dir

        self._context = self._browser.new_context(**context_kwargs)
        self._page = self._context.new_page()

        # Anti-detection: navigator.webdriver 제거
        self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        """)

        return self._page

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._context

    def screenshot(self, name: str = "debug"):
        """스크린샷 저장"""
        shots_dir = Path(self.cfg["paths"].get("screenshot", "./screenshots"))
        shots_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = str(shots_dir / f"{name}_{ts}.png")
        self.page.screenshot(path=path, full_page=True)
        print(f"  📸 Screenshot: {path}")
        return path

    def save_html(self, name: str = "page"):
        """현재 페이지 HTML 저장 (디버깅용)"""
        html_dir = Path(self.cfg["paths"].get("download", "./downloads"))
        html_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = str(html_dir / f"{name}_{ts}.html")
        html = self.page.content()
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  📄 HTML saved: {path}")
        return path

    def close(self):
        """브라우저 종료"""
        try:
            if self._page:
                self._page.close()
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.__exit__(None, None, None)
        except Exception as e:
            print(f"  ⚠️ Browser close error: {e}")
