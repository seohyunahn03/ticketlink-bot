"""
🖱️ 시스템 레벨 매크로 — pyautogui 기반 마우스/스크린샷/픽셀

CDP Input.dispatchMouseEvent 대신 실제 OS 마우스 이벤트를 발생시켜,
Chrome 팝업 창이나 다른 애플리케이션에서도 동작합니다.
"""
import logging
import time
from typing import Optional

try:
    import pyautogui
    pyautogui.FAILSAFE = True       # 모서리에서 강제 중지
    pyautogui.PAUSE = 0.03          # 클릭 사이 최소 간격
    _HAVE_PYAUTOGUI = True
except Exception:
    _HAVE_PYAUTOGUI = False


logger = logging.getLogger("ticketlink_bot")


class SystemBot:
    """
    시스템 레벨 매크로 봇.

    - pyautogui로 실제 마우스 클릭/이동
    - 전체 화면 스크린샷 + 픽셀 색상 추출
    - CDP 의존성 없음 → 팝업 창, 다른 브라우저에서도 동작
    """

    def __init__(self):
        self._screen_size = None

    # ── 가용성 ──

    @staticmethod
    def available() -> bool:
        return _HAVE_PYAUTOGUI

    @staticmethod
    def check_deps() -> str:
        """의존성 설치 안내 메시지"""
        if _HAVE_PYAUTOGUI:
            return ""
        return (
            "시스템 매크로를 사용하려면 pyautogui가 필요합니다:\n"
            "  pip install pyautogui\n"
            "  (macOS 추가: pip install pyobjc-core pyobjc-framework-Quartz)\n"
            "  (Linux 추가: sudo apt install python3-tk python3-dev scrot)"
        )

    # ── 마우스 ──

    @staticmethod
    def click(x: int, y: int, button: str = "left") -> None:
        """시스템 레벨 마우스 클릭 (절대 좌표)"""
        if not _HAVE_PYAUTOGUI:
            logger.error("pyautogui 미설치 — 시스템 클릭 불가")
            return
        pyautogui.click(x, y, button=button)
        logger.info("🖱️ 시스템 클릭 (%d, %d) %s", x, y, button)

    @staticmethod
    def click_left(x: int, y: int) -> None:
        """좌클릭 단축"""
        SystemBot.click(x, y, "left")

    @staticmethod
    def click_right(x: int, y: int) -> None:
        """우클릭 단축"""
        SystemBot.click(x, y, "right")

    @staticmethod
    def move(x: int, y: int, duration: float = 0.1) -> None:
        """마우스 이동"""
        if not _HAVE_PYAUTOGUI:
            return
        pyautogui.moveTo(x, y, duration=duration)

    @staticmethod
    def get_position() -> tuple[int, int]:
        """현재 마우스 위치"""
        if not _HAVE_PYAUTOGUI:
            return (0, 0)
        return pyautogui.position()

    # ── 스크린샷 / 픽셀 ──

    @staticmethod
    def screenshot() -> Optional[bytes]:
        """
        전체 화면 스크린샷 → PNG bytes.
        CDP screenshot 대체용.
        """
        if not _HAVE_PYAUTOGUI:
            return None
        import io
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def pixel(x: int, y: int) -> str:
        """
        특정 좌표의 픽셀 색상 → BGR hex (CDP screenshot pick_color_at 호환).
        예: SystemBot.pixel(800, 500) → "C8C8C8"
        """
        if not _HAVE_PYAUTOGUI:
            return "000000"
        r, g, b = pyautogui.pixel(x, y)
        # BGR 형식으로 변환 (CDP screenshot → openCV 호환)
        return f"{b:02X}{g:02X}{r:02X}"

    @staticmethod
    def screenshot_region(left: int, top: int, width: int, height: int) -> Optional[bytes]:
        """지정 영역 스크린샷 → PNG bytes"""
        if not _HAVE_PYAUTOGUI:
            return None
        import io
        img = pyautogui.screenshot(region=(left, top, width, height))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    # ── 키보드 ──

    @staticmethod
    def type_text(text: str, interval: float = 0.05) -> None:
        """키보드 입력 (한글은 OS 입력기 의존)

        Args:
            interval: 글자간 간격(초). 기본 0.05=50ms.
        """
        if not _HAVE_PYAUTOGUI:
            return
        pyautogui.write(text, interval=interval)

    @staticmethod
    def type_text_slow(text: str, char_delay_ms: int = 80) -> None:
        """캡차 입력용 — 문자당 지연시간 설정 가능, 비정상 빠른입력 방지

        Args:
            char_delay_ms: 글자당 지연시간(ms). 기본 80ms.
        """
        if not _HAVE_PYAUTOGUI:
            return
        interval = char_delay_ms / 1000.0
        # 20~30% 랜덤 지터 추가 (사람 입력처럼)
        import random
        for ch in text:
            pyautogui.write(ch, interval=0)
            jitter = random.uniform(0.8, 1.3)
            time.sleep(interval * jitter)

    @staticmethod
    def press(key: str) -> None:
        """단일 키 누름 (예: 'enter', 'escape', 'f6')"""
        if not _HAVE_PYAUTOGUI:
            return
        pyautogui.press(key)

    # ── 창 제어 ──

    @staticmethod
    def get_screen_size() -> tuple[int, int]:
        """화면 해상도"""
        if not _HAVE_PYAUTOGUI:
            return (1920, 1080)
        return pyautogui.size()

    # ── 유틸리티 ──

    @staticmethod
    def wait(seconds: float) -> None:
        """time.sleep 대체"""
        time.sleep(seconds)

    @staticmethod
    def hide_windows_except(title_keyword: str = "ticketlink") -> None:
        """
        특정 키워드가 포함된 창만 남기고 모두 최소화.
        macOS: pygetwindow / AppleScript
        Windows: pygetwindow
        """
        try:
            import pygetwindow as gw
            windows = gw.getAllWindows()
            for w in windows:
                if title_keyword.lower() not in (w.title or "").lower():
                    try:
                        w.minimize()
                    except Exception:
                        pass
        except ImportError:
            logger.info("  pygetwindow 미설치 — 창 최소화 스킵")
        except Exception as e:
            logger.debug("  창 최소화 실패: %s", e)
