"""
🖥️ 독립형 예매 파이프라인 — Chrome/CDP 없이 시스템 매크로만 사용.

통합매크로 방식:
- pyautogui 시스템 클릭
- pyautogui 전체화면 스크린샷
- pytesseract + xAI Vision 캡차
- 타이머 기반 딜레이 (URL 감지 불필요)
- 글로벌 핫키 (F6/ESC)
"""
import logging
import threading
import time
from typing import Optional

from .system_bot import SystemBot
from .seats import find_seats_in_zones, find_consecutive_seats, find_seats_by_color
from .booking import _get_zones

logger = logging.getLogger("ticketlink_bot")


# ================================================================
#  독립형 예매
# ================================================================

def standalone_book(cfg: dict, stop_event: Optional[threading.Event] = None) -> dict:
    """
    CDP 없이 순수 시스템 매크로로 예매 실행.

    Args:
        cfg: 설정 딕셔너리 (load_config 결과)
        stop_event: 중지 신호 이벤트 (GUI 중지 버튼 대응)

    Returns:
        {"success": bool, "stage": str, "message": str}
    """
    result = {"success": False, "stage": "init", "message": ""}
    macro = cfg.get("macro", {})
    delays = macro.get("delays", {})
    click_wait = delays.get("click_wait", 3)
    seat_click_delay = delays.get("seat_click", 500) / 1000.0
    refresh_delay = delays.get("refresh", 2000) / 1000.0

    logger.info("=" * 50)
    logger.info("  🎫 티켓링크봇 — 독립형 매크로")
    logger.info("  Chrome 없이 시스템 레벨로 실행됩니다.")
    logger.info("=" * 50)

    def _click(x, y, label=""):
        SystemBot.click(x, y)
        logger.info("  🖱️ %s (%d, %d)", label, x, y)

    def _wait(t):
        logger.debug("  ⏳ %d초 대기...", t)
        time.sleep(t)

    # ===== 설정 검증 =====
    c1 = macro.get("click1", [0, 0])
    if c1[0] == 0 and c1[1] == 0:
        result["message"] = "❌ 예매하기 좌표(click1) 미설정"
        logger.error(result["message"])
        return result

    logger.info("✅ 설정 확인 완료")

    # ===== 1. 예매하기 클릭 =====
    _click(c1[0], c1[1], "예매하기")
    _wait(click_wait)

    # ===== 1.5 날짜/회차 =====
    dc = macro.get("date_click", [0, 0])
    rc = macro.get("round_click", [0, 0])
    if dc[0] != 0 or dc[1] != 0:
        _click(dc[0], dc[1], "날짜선택")
        _wait(1)
    if rc[0] != 0 or rc[1] != 0:
        _click(rc[0], rc[1], "회차선택")
        _wait(1)

    # ===== 2. 확인 클릭 =====
    c2 = macro.get("click2", [0, 0])
    if c2[0] != 0 or c2[1] != 0:
        _click(c2[0], c2[1], "확인")
        _wait(click_wait)

    # ===== 3. 캡차 처리 (시스템 스크린샷) =====
    auto_captcha = cfg.get("booking", {}).get("auto_captcha", True)
    solved = False
    if auto_captcha:
        # 중지 신호 확인
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            logger.warning("  ⏹️ %s", result["message"])
            return result

        logger.info("  🔍 캡차 처리 중...")
        try:
            solved = _standalone_captcha(stop_event=stop_event)
            if solved:
                logger.info("  ✅ 캡차 입력 완료 (서버 검증 대기)")
                _wait(1)
            else:
                logger.warning("  ⚠️ 캡차 해결 실패, 계속 진행")
        except Exception as e:
            logger.error("  ❌ 캡차 오류: %s", e)

    # ===== 3.5 캡차 확인 버튼 (캡차 성공 시에만) =====
    cs = macro.get("captcha_submit", [0, 0])
    if solved and (cs[0] != 0 or cs[1] != 0):
        _click(cs[0], cs[1], "보안문자 확인")
        _wait(click_wait)

    # ===== 4. 좌석 검색 (시스템 스크린샷) =====
    seat_area = macro.get("seat_area", [0, 0, 0, 0])
    seat_color = macro.get("seat_color", "C8C8C8")
    color_tolerance = macro.get("color_tolerance", 20)
    consecutive_n = macro.get("consecutive_seats", 2)
    seat_zones = _get_zones(macro)

    if any(seat_area) or seat_zones:
        logger.info("  🔍 좌석 검색: %d연석 %d개 구역",
                     consecutive_n, len(seat_zones) if seat_zones else 1)

        found_group = None
        screenshot_fails = 0
        for attempt in range(30):
            # 중지 신호 확인
            if stop_event and stop_event.is_set():
                result["message"] = "⏹️ 사용자 중지"
                logger.warning("  ⏹️ %s", result["message"])
                return result

            # 시스템 전체화면 스크린샷
            png = SystemBot.screenshot()
            if not png:
                screenshot_fails += 1
                logger.warning("  ⚠️ 스크린샷 실패 (%d/5)", screenshot_fails)
                if screenshot_fails >= 5:
                    logger.error("  ❌ 스크린샷 연속 실패 — 중단")
                    break
                continue

            if seat_zones:
                zone_result = find_seats_in_zones(png, seat_zones, max_results_per_zone=20)
                all_seats = zone_result.get("all", [])
                found_group = find_consecutive_seats(
                    all_seats, n=consecutive_n,
                    row_tolerance=30, gap_tolerance=40,
                )
            else:
                area = tuple(seat_area) if any(seat_area) else None
                seats = find_seats_by_color(
                    png, seat_color, tolerance=color_tolerance,
                    area=area, max_results=20,
                )
                if consecutive_n > 1:
                    found_group = find_consecutive_seats(
                        seats, n=consecutive_n,
                        row_tolerance=30, gap_tolerance=40,
                    )
                else:
                    found_group = [seats[0]] if seats else []

            if found_group:
                logger.info("  🎯 빈 좌석 발견! %d석 (%d/30)",
                             len(found_group), attempt + 1)
                break

            logger.info("  ↻ 빈 좌석 없음, 새로고침 (%d/30)", attempt + 1)
            _reload_page(refresh_delay)  # F5 키
            _click(c1[0], c1[1], "예매하기(재시도)")
            _wait(click_wait)
            if dc[0] != 0 or dc[1] != 0:
                _click(dc[0], dc[1], "날짜선택(재시도)")
                _wait(1)
            if rc[0] != 0 or rc[1] != 0:
                _click(rc[0], rc[1], "회차선택(재시도)")
                _wait(1)
            if c2[0] != 0 or c2[1] != 0:
                _click(c2[0], c2[1], "확인")
                _wait(click_wait)
            # 캡차 재해결 (새로고침 후 새 캡차 챌린지)
            retry_solved = False
            if auto_captcha:
                try:
                    retry_solved = _standalone_captcha(stop_event=stop_event)
                except Exception as e:
                    logger.error("  ❌ 재시도 캡차 오류: %s", e)
            if retry_solved and (cs[0] != 0 or cs[1] != 0):
                _click(cs[0], cs[1], "보안문자 확인(재시도)")
                _wait(click_wait)

        if found_group:
            for i, (sx, sy) in enumerate(found_group):
                _click(sx, sy, f"좌석선택({i+1})")
                _wait(seat_click_delay)
        else:
            result["message"] = f"빈 좌석 없음 ({consecutive_n}연석, 30회)"
            logger.warning("  ⚠️ %s", result["message"])
            return result
    else:
        result["message"] = "❌ 좌석 검색 영역 미설정 — 설정 탭에서 좌석 영역을 지정하세요."
        logger.warning(result["message"])
        return result

    # ===== 4.5 구역선택 =====
    sc = macro.get("section_click", [0, 0])
    if sc[0] != 0 or sc[1] != 0:
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            logger.warning("  ⏹️ %s", result["message"])
            return result
        _wait(1)
        _click(sc[0], sc[1], "구역선택")
        _wait(2)

    # ===== 5. 선택완료 =====
    c3 = macro.get("click3", [0, 0])
    if c3[0] != 0 or c3[1] != 0:
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            logger.warning("  ⏹️ %s", result["message"])
            return result
        _wait(1)
        _click(c3[0], c3[1], "선택완료")
        _wait(2)

    # ===== 6. 결제하기 =====
    c4 = macro.get("click4", [0, 0])
    if c4[0] != 0 or c4[1] != 0:
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            logger.warning("  ⏹️ %s", result["message"])
            return result
        _wait(1)
        _click(c4[0], c4[1], "결제하기")
        result["stage"] = "payment"
        result["message"] = "✅ 예매 완료! 결제 페이지로 이동했습니다."
    else:
        result["message"] = "✅ 예매 완료!"

    result["success"] = True
    if result["stage"] != "payment":
        result["stage"] = "complete"
    logger.info("  🎉 %s", result["message"])
    return result


# ================================================================
#  캡차 (시스템 스크린샷 기반)
# ================================================================

def _standalone_captcha(stop_event: Optional[threading.Event] = None) -> bool:
    """
    시스템 스크린샷으로 캡차 해결.
    Chrome CDP 없이 pyautogui 전체화면 스크린샷 사용.
    """
    from .captcha import solve_captcha_b64 as _solve_b64
    import base64

    # 중지 신호 확인
    if stop_event and stop_event.is_set():
        logger.warning("  ⏹️ 캡차 처리 중단")
        return False

    # 1. 전체화면 스크린샷
    png = SystemBot.screenshot()
    if not png:
        logger.warning("  ⚠️ 스크린샷 실패")
        return False

    # 2. b64 변환 (xAI Vision API 호환)
    b64 = base64.b64encode(png).decode()

    # 3. 캡차 인식
    logger.info("  🤖 캡차 인식 중...")
    captcha_text = _solve_b64(b64)
    logger.info("  ✅ 인식: \"%s\"", captcha_text)

    # OCR 결과 검증 (빈 문자열이나 짧은 값이면 실패 처리)
    if not captcha_text or len(captcha_text.strip()) < 1:
        logger.warning("  ⚠️ 캡차 인식 결과 없음 — 건너뜀")
        return False

    # 4. 키보드 입력
    SystemBot.type_text(captcha_text)
    time.sleep(0.5)

    # 5. 엔터
    SystemBot.press("enter")
    return True


# ================================================================
#  새로고침
# ================================================================

def _reload_page(delay: float = 1.0):
    """F5 키로 페이지 새로고침"""
    SystemBot.press("f5")
    if delay:
        time.sleep(delay)
