"""
🎯 글로벌 좌표 따기 — 시스템 전체에서 우클릭으로 좌표 캡처

Chrome CDP 오버레이 대신 pynput 글로벌 리스너로,
어떤 창/애플리케이션에서도 우클릭 좌표를 캡처합니다.

사용법:
    picker = GlobalPicker()
    coord = await picker.pick(timeout=60)  # 우클릭 대기
    # coord = {"x": 1234, "y": 567} 또는 None
    picker.close()
"""
import asyncio
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("ticketlink_bot")

# ── 전역 마우스/키보드 리스너 (pynput) ──
_HOOKS_AVAILABLE = False
_mouse_listener = None
_keyboard_listener = None

try:
    from pynput import mouse, keyboard
    _HOOKS_AVAILABLE = True
except ImportError:
    mouse = None
    keyboard = None


class _GlobalState:
    """pynput 리스너와 좌표 큐 공유"""
    def __init__(self):
        self.captured: list[dict] = []
        self.cancelled = False
        self.listening = False
        self._lock = threading.Lock()


class GlobalPicker:
    """
    글로벌 좌표 따기 (pynput 기반).

    - 시스템 전체에서 우클릭 감지
    - ESC 키로 취소
    - 실시간 좌표 표시 (콘솔 또는 GUI 콜백)
    """

    def __init__(self, status_callback=None):
        """
        Args:
            status_callback: 실시간 좌표 표시용 콜백 (x, y) → None
        """
        self._state = _GlobalState()
        self._mouse = None
        self._keyboard = None
        self._status_cb = status_callback
        self._loop = None  # asyncio event loop reference

    @staticmethod
    def available() -> bool:
        """pynput 설치 여부"""
        return _HOOKS_AVAILABLE

    @staticmethod
    def check_deps() -> str:
        if _HOOKS_AVAILABLE:
            return ""
        return "글로벌 좌표 따기에 pynput이 필요합니다:\n  pip install pynput"

    async def pick(self, timeout: int = 60) -> Optional[dict]:
        """
        사용자 우클릭 대기 → 좌표 반환.

        Returns:
            {"x": int, "y": int} 또는 None (timeout/cancel)
        """
        if not _HOOKS_AVAILABLE:
            logger.warning("⚠️ pynput 미설치 — 글로벌 좌표 따기 불가")
            return None

        self._loop = asyncio.get_running_loop()
        self._state.captured.clear()
        self._state.cancelled = False

        logger.info("🎯 글로벌 좌표 따기 — 아무 창에서나 우클릭하세요!")
        logger.info("   🖱️ 우클릭 → 좌표 저장")
        logger.info("   ⌨️ ESC → 취소")
        logger.info("   (모든 애플리케이션에서 동작)")

        self._start_listeners()

        try:
            start = time.time()
            while time.time() - start < timeout:
                if self._state.cancelled:
                    logger.info("  ⏹️ ESC 취소")
                    return None

                with self._state._lock:
                    if self._state.captured:
                        last = self._state.captured[-1]
                        logger.info("✅ 최종 좌표: (%d, %d)", last["x"], last["y"])
                        return {"x": last["x"], "y": last["y"]}

                await asyncio.sleep(0.1)

            logger.warning("⏱️ 좌표 캡처 타임아웃")
            return None
        finally:
            self._stop_listeners()

    def _start_listeners(self):
        """글로벌 마우스 + 키보드 리스너 시작"""
        if self._state.listening:
            return

        try:
            self._mouse = mouse.Listener(
                on_click=self._on_click,
            )
            self._keyboard = keyboard.Listener(
                on_press=self._on_press,
            )
            self._mouse.daemon = True
            self._keyboard.daemon = True
            self._mouse.start()
            self._keyboard.start()
            self._state.listening = True
            logger.debug("  pynput 리스너 시작")
        except Exception as e:
            logger.warning("  ⚠️ 리스너 시작 실패: %s", e)

    def _stop_listeners(self):
        """리스너 중지"""
        self._state.listening = False
        try:
            if self._mouse and self._mouse.running:
                self._mouse.stop()
        except Exception:
            pass
        try:
            if self._keyboard and self._keyboard.running:
                self._keyboard.stop()
        except Exception:
            pass

    def _on_click(self, _x, _y, button, pressed):
        """마우스 클릭 콜백 (별도 스레드)"""
        if not pressed:
            return  # press event만 처리
        if button != mouse.Button.right:
            return  # 우클릭만

        x, y = _x, _y
        with self._state._lock:
            self._state.captured.append({"x": x, "y": y})

        logger.info("  📌 (%d, %d)", x, y)

        # GUI 콜백
        if self._status_cb:
            try:
                self._status_cb(x, y)
            except Exception:
                pass

    def _on_press(self, key):
        """키보드 콜백 (별도 스레드)"""
        try:
            if key == keyboard.Key.esc:
                self._state.cancelled = True
                logger.info("  ⏹️ ESC 감지")
        except Exception:
            pass

    def close(self):
        """리소스 정리"""
        self._stop_listeners()
