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
def _get_zones(macro: dict) -> list[dict]:
    """하위호환: seat_zones가 없으면 seat_area/seat_color로 zone 생성"""
    zones = macro.get("seat_zones", [])
    if not zones:
        area = macro.get("seat_area", [0, 0, 0, 0])
        color = macro.get("seat_color", "C8C8C8")
        tol = macro.get("color_tolerance", 20)
        if any(area):
            zones = [{"area": area, "color": color, "tolerance": tol}]
    return zones

logger = logging.getLogger("ticketlink_bot")


# ================================================================
#  새로고침 봇 (F6)
# ================================================================

def refresh_bot(cfg: dict, stop_event: Optional[threading.Event] = None) -> dict:
    """
    **새로고침 봇** — F6 전용.

    1. 서버시간(booking.server_time) 도달 시까지 F5 새로고침
    2. 예매하기(click1) 클릭
    3. 확인(click2) 클릭

    Returns:
        {"success": bool, "stage": str, "message": str}
    """
    result = {"success": False, "stage": "refresh", "message": ""}
    macro = cfg.get("macro", {})
    delays = macro.get("delays", {})
    click_wait = delays.get("click_wait", 3)
    refresh_delay = delays.get("refresh", 500) / 1000.0

    c1 = macro.get("click1", [0, 0])
    if c1[0] == 0 and c1[1] == 0:
        result["message"] = "❌ 예매하기 좌표(click1) 미설정"
        logger.error(result["message"])
        return result

    # ── 서버시간 파싱 ──
    server_time_str = cfg.get("booking", {}).get("server_time", "").strip()
    target_epoch = 0
    if server_time_str:
        try:
            parts = list(map(int, server_time_str.replace("-", ":").split(":")))
            now = time.localtime()
            target_epoch = int(time.mktime((
                now.tm_year, now.tm_mon, now.tm_mday,
                parts[0], parts[1] if len(parts) > 1 else 0,
                parts[2] if len(parts) > 2 else 0,
                now.tm_wday, now.tm_yday, now.tm_isdst,
            )))
            # 이미 지난 시간이면 내일로
            if target_epoch < time.time():
                target_epoch += 86400
            logger.info("  🕐 서버시간: %s → %s까지 대기",
                        server_time_str,
                        time.strftime("%H:%M:%S", time.localtime(target_epoch)))
        except (ValueError, IndexError) as e:
            logger.warning("  ⚠️ 서버시간 파싱 실패: %s — 즉시 새로고침", e)
            target_epoch = 0

    # ── 서버시간 동기화 (F5 스팸) ──
    if target_epoch:
        # 3초 전부터 F5 스팸 시작
        pre_seconds = 3
        wait_seconds = max(0, target_epoch - time.time() - pre_seconds)
        if wait_seconds > 0:
            logger.info("  ⏳ %d초 후 새로고침 시작...", wait_seconds)
            # 1초 단위로 대기하며 중지 확인
            while wait_seconds > 0:
                if stop_event and stop_event.is_set():
                    result["message"] = "⏹️ 사용자 중지 (대기 중)"
                    return result
                time.sleep(1)
                wait_seconds -= 1
        # -3초 ~ 0초 사이: F5 스팸
        logger.info("  🚀 새로고침 시작!")
        spam_end = target_epoch + 2  # 2초 더
        while time.time() < spam_end:
            if stop_event and stop_event.is_set():
                result["message"] = "⏹️ 사용자 중지 (새로고침 중)"
                return result
            _reload_page(0.05)  # 50ms 간격 F5
    else:
        # 서버시간 없음: 그냥 한 번 F5
        logger.info("  🔄 서버시간 미설정 — 기본 새로고침")
        _reload_page(1.0)

    # ── 예매하기 ──
    if stop_event and stop_event.is_set():
        result["message"] = "⏹️ 사용자 중지"
        return result
    _click(c1[0], c1[1], "예매하기")
    _wait(click_wait)

    # ── 날짜/회차 (선택) ──
    dc = macro.get("date_click", [0, 0])
    rc = macro.get("round_click", [0, 0])
    if dc[0] != 0 or dc[1] != 0:
        _click(dc[0], dc[1], "날짜선택")
        _wait(1)
    if rc[0] != 0 or rc[1] != 0:
        _click(rc[0], rc[1], "회차선택")
        _wait(1)

    # ── 확인 (예매안내 모달) ──
    c2 = macro.get("click2", [0, 0])
    if c2[0] != 0 or c2[1] != 0:
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            return result
        _click(c2[0], c2[1], "확인")
        _wait(click_wait)

    result["success"] = True
    result["stage"] = "refresh_done"
    result["message"] = "✅ 새로고침 봇 완료 — 예매하기 + 확인까지 클릭함"
    logger.info("  ✅ %s", result["message"])
    return result


# ================================================================
#  매크로 봇 (F7)
# ================================================================

def macro_bot(cfg: dict, stop_event: Optional[threading.Event] = None) -> dict:
    """
    **매크로 봇** — F7 전용.

    1. 캡차 입력창 클릭 → OCR → 확인버튼
    2. 좌석 검색 (색상 기반, 루프)
    3. 구역선택 → 선택완료 → 결제하기

    Returns:
        {"success": bool, "stage": str, "message": str}
    """
    result = {"success": False, "stage": "macro", "message": ""}
    macro = cfg.get("macro", {})
    delays = macro.get("delays", {})
    click_wait = delays.get("click_wait", 3)
    seat_click_delay = delays.get("seat_click", 500) / 1000.0
    refresh_delay = delays.get("refresh", 2000) / 1000.0

    max_retries = macro.get("max_retries", 30)
    max_screenshot_fails = macro.get("max_screenshot_fails", 5)
    ss = macro.get("seat_search", {})
    row_tolerance = ss.get("row_tolerance", 30)
    gap_tolerance = ss.get("gap_tolerance", 40)
    max_results_per_zone = ss.get("max_results_per_zone", 20)

    logger.info("=" * 50)
    logger.info("  🎫 매크로 봇 — 캡차 + 좌석 매크로")
    logger.info("=" * 50)

    # ── 캡차 처리 ──
    auto_captcha = cfg.get("booking", {}).get("auto_captcha", True)
    xai_cfg = cfg.get("xai", {})
    captcha_method = xai_cfg.get("api_type", "oauth")
    solved = False

    if auto_captcha:
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            logger.warning("  ⏹️ %s", result["message"])
            return result

        # 캡차 입력창 클릭 (좌표가 설정된 경우)
        ci = macro.get("captcha_input", [0, 0])
        if ci[0] != 0 or ci[1] != 0:
            _click(ci[0], ci[1], "캡차 입력창")
            _wait(0.3)

        logger.info("  🔍 캡차 처리 중...")
        try:
            solved = _standalone_captcha(stop_event=stop_event, method=captcha_method)
            if solved:
                logger.info("  ✅ 캡차 입력 완료 (서버 검증 대기)")
                _wait(1)
            else:
                logger.warning("  ⚠️ 캡차 해결 실패, 계속 진행")
        except Exception as e:
            logger.error("  ❌ 캡차 오류: %s", e)

        # 캡차 확인 버튼
        cs = macro.get("captcha_submit", [0, 0])
        if solved and (cs[0] != 0 or cs[1] != 0):
            _click(cs[0], cs[1], "보안문자 확인")
            _wait(click_wait)

    # ── 좌석 검색 ──
    seat_zones = _get_zones(macro)
    if not seat_zones:
        result["message"] = "❌ 좌석 검색 영역 미설정 — 설정 탭에서 좌석 영역을 지정하세요."
        logger.warning(result["message"])
        return result

    consecutive_n = macro.get("consecutive_seats", 2)
    logger.info("  🔍 좌석 검색: %d연석 %d개 구역",
                consecutive_n, len(seat_zones))

    c1 = macro.get("click1", [0, 0])
    dc = macro.get("date_click", [0, 0])
    rc = macro.get("round_click", [0, 0])
    c2 = macro.get("click2", [0, 0])

    found_group = None
    screenshot_fails = 0
    for attempt in range(max_retries):
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            logger.warning("  ⏹️ %s", result["message"])
            return result

        png = SystemBot.screenshot()
        if not png:
            screenshot_fails += 1
            logger.warning("  ⚠️ 스크린샷 실패 (%d/%d)", screenshot_fails, max_screenshot_fails)
            if screenshot_fails >= max_screenshot_fails:
                result["message"] = f"스크린샷 연속 실패 ({max_screenshot_fails}회)"
                return result
            continue
        screenshot_fails = 0

        zone_result = find_seats_in_zones(png, seat_zones, max_results_per_zone=max_results_per_zone)
        all_seats = zone_result.get("all", [])
        if consecutive_n > 1:
            found_group = find_consecutive_seats(
                all_seats, n=consecutive_n,
                row_tolerance=row_tolerance, gap_tolerance=gap_tolerance,
            )
        else:
            found_group = [all_seats[0]] if all_seats else []

        if found_group:
            logger.info("  🎯 빈 좌석 발견! %d석 (%d/%d)",
                        len(found_group), attempt + 1, max_retries)
            break

        logger.info("  ↻ 빈 좌석 없음, 새로고침 (%d/%d)", attempt + 1, max_retries)
        _reload_page(refresh_delay)
        # 예매 경로 재진입
        if c1[0] != 0 or c1[1] != 0:
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
        # 캡차 재해결
        retry_solved = False
        if auto_captcha:
            try:
                retry_solved = _standalone_captcha(stop_event=stop_event, method=captcha_method)
            except Exception as e:
                logger.error("  ❌ 재시도 캡차 오류: %s", e)
        cs = macro.get("captcha_submit", [0, 0])
        if retry_solved and (cs[0] != 0 or cs[1] != 0):
            if stop_event and stop_event.is_set():
                result["message"] = "⏹️ 사용자 중지 (캡차 재시도)"
                return result
            _click(cs[0], cs[1], "보안문자 확인(재시도)")
            _wait(click_wait)

    if not found_group:
        result["message"] = f"빈 좌석 없음 ({consecutive_n}연석, {max_retries}회)"
        logger.warning("  ⚠️ %s", result["message"])
        return result

    # ── 좌석 클릭 ──
    for i, (sx, sy) in enumerate(found_group):
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지 (좌석 선택 중)"
            return result
        _click(sx, sy, f"좌석선택({i+1})")
        _wait(seat_click_delay)

    # ── 구역선택 ──
    sc = macro.get("section_click", [0, 0])
    if sc[0] != 0 or sc[1] != 0:
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            return result
        _wait(1)
        _click(sc[0], sc[1], "구역선택")
        _wait(2)

    # ── 선택완료 ──
    c3 = macro.get("click3", [0, 0])
    if c3[0] != 0 or c3[1] != 0:
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            return result
        _wait(1)
        _click(c3[0], c3[1], "선택완료")
        _wait(2)

    # ── 결제하기 ──
    c4 = macro.get("click4", [0, 0])
    if c4[0] != 0 or c4[1] != 0:
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
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
#  독립형 예매 (기존 — CLI --standalone 용)
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
    # 매크로 제어값 (설정 가능, 기본값은 config.py DEFAULT_CONFIG 참조)
    max_retries = macro.get("max_retries", 30)
    max_screenshot_fails = macro.get("max_screenshot_fails", 5)
    ss = macro.get("seat_search", {})
    row_tolerance = ss.get("row_tolerance", 30)
    gap_tolerance = ss.get("gap_tolerance", 40)
    max_results_per_zone = ss.get("max_results_per_zone", 20)

    logger.info("=" * 50)
    logger.info("  🎫 티켓링크봇 — 독립형 매크로")
    logger.info("  Chrome 없이 시스템 레벨로 실행됩니다.")
    logger.info("=" * 50)

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
    xai_cfg = cfg.get("xai", {})
    captcha_method = xai_cfg.get("api_type", "oauth")
    solved = False
    if auto_captcha:
        # 중지 신호 확인
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            logger.warning("  ⏹️ %s", result["message"])
            return result

        logger.info("  🔍 캡차 처리 중...")
        try:
            solved = _standalone_captcha(stop_event=stop_event, method=captcha_method)
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
        for attempt in range(max_retries):
            # 중지 신호 확인
            if stop_event and stop_event.is_set():
                result["message"] = "⏹️ 사용자 중지"
                logger.warning("  ⏹️ %s", result["message"])
                return result

            # 시스템 전체화면 스크린샷
            png = SystemBot.screenshot()
            if not png:
                screenshot_fails += 1
                logger.warning("  ⚠️ 스크린샷 실패 (%d/%d)", screenshot_fails, max_screenshot_fails)
                if screenshot_fails >= max_screenshot_fails:
                    logger.error("  ❌ 스크린샷 연속 실패 — 중단")
                    result["message"] = f"스크린샷 연속 실패 ({max_screenshot_fails}회)"
                    return result
                continue

            screenshot_fails = 0  # 성공 시 카운터 리셋

            if seat_zones:
                zone_result = find_seats_in_zones(png, seat_zones, max_results_per_zone=max_results_per_zone)
                all_seats = zone_result.get("all", [])
                if consecutive_n > 1:
                    found_group = find_consecutive_seats(
                        all_seats, n=consecutive_n,
                        row_tolerance=row_tolerance, gap_tolerance=gap_tolerance,
                    )
                else:
                    found_group = [all_seats[0]] if all_seats else []
            else:
                area = tuple(seat_area) if any(seat_area) else None
                seats = find_seats_by_color(
                    png, seat_color, tolerance=color_tolerance,
                    area=area, max_results=max_results_per_zone,
                )
                if consecutive_n > 1:
                    found_group = find_consecutive_seats(
                        seats, n=consecutive_n,
                        row_tolerance=row_tolerance, gap_tolerance=gap_tolerance,
                    )
                else:
                    found_group = [seats[0]] if seats else []

            if found_group:
                logger.info("  🎯 빈 좌석 발견! %d석 (%d/%d)",
                             len(found_group), attempt + 1, max_retries)
                break

            logger.info("  ↻ 빈 좌석 없음, 새로고침 (%d/%d)", attempt + 1, max_retries)
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
                    retry_solved = _standalone_captcha(stop_event=stop_event, method=captcha_method)
                except Exception as e:
                    logger.error("  ❌ 재시도 캡차 오류: %s", e)
            if retry_solved and (cs[0] != 0 or cs[1] != 0):
                if stop_event and stop_event.is_set():
                    result["message"] = "⏹️ 사용자 중지 (캡차 재시도)"
                    logger.warning("  ⏹️ %s", result["message"])
                    return result
                _click(cs[0], cs[1], "보안문자 확인(재시도)")
                _wait(click_wait)

        if found_group:
            for i, (sx, sy) in enumerate(found_group):
                if stop_event and stop_event.is_set():
                    result["message"] = "⏹️ 사용자 중지 (좌석 선택 중)"
                    logger.warning("  ⏹️ %s", result["message"])
                    return result
                _click(sx, sy, f"좌석선택({i+1})")
                _wait(seat_click_delay)
        else:
            result["message"] = f"빈 좌석 없음 ({consecutive_n}연석, {max_retries}회)"
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

def _standalone_captcha(stop_event: Optional[threading.Event] = None,
                        method: str = "oauth") -> bool:
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
    captcha_text = _solve_b64(b64, method=method)
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


# ── 유틸리티 (모듈 레벨) ──

def _click(x: int, y: int, label: str = ""):
    """좌표 클릭 + 로그"""
    SystemBot.click(x, y)
    logger.info("  🖱️ %s (%d, %d)", label, x, y)


def _wait(t: float):
    """대기 + 로그"""
    logger.debug("  ⏳ %d초 대기...", t)
    time.sleep(t)
