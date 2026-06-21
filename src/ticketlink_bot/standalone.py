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


# ── CDP 폼 하이재킹 헬퍼 ──────────────────────────────────────

def _maybe_activate_cdp_hijack(cfg: dict):
    """CDP 하이재킹이 설정된 경우 연결 + 스크립트 주입

    Returns:
        CdpHijack 인스턴스 (연결 성공 시) 또는 None
    """
    hijack_cfg = cfg.get("macro", {}).get("cdp_hijack", {})
    if not hijack_cfg.get("enabled"):
        return None

    product_id = hijack_cfg.get("product_id", "").strip()
    schedule_id = hijack_cfg.get("schedule_id", "").strip()
    port = int(hijack_cfg.get("port", 9222))

    if not product_id or not schedule_id:
        logger.warning("  ⚠️ CDP 하이재킹 활성화됨 but product_id/schedule_id 미설정")
        return None

    try:
        from .cdp_hijack import CdpHijack
        import asyncio

        hijack = CdpHijack(cdp_port=port)

        # 새 이벤트 루프 (기존 스레드와 독립)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            ok = loop.run_until_complete(hijack.connect())
            if not ok:
                logger.warning("  ⚠️ CDP 연결 실패 (Chrome CDP 포트 %d 확인)", port)
                return None

            ok = loop.run_until_complete(hijack.inject(product_id, schedule_id))
            if not ok:
                logger.warning("  ⚠️ CDP 하이재킹 주입 실패")
                loop.run_until_complete(hijack.close())
                return None

            # 검증
            status = loop.run_until_complete(hijack.verify())
            if status.get("active"):
                logger.info("  ✅ CDP 폼 하이재킹 활성 — product=%s schedule=%s",
                            product_id, schedule_id)
                # hijack.loop 저장 (종료 시 재사용)
                hijack._loop = loop
                return hijack
            else:
                logger.warning("  ⚠️ CDP 하이재킹 검증 실패: %s", status)
                loop.run_until_complete(hijack.close())
                return None
        except Exception:
            loop.close()
            raise
    except Exception as e:
        logger.error("  ❌ CDP 하이재킹 초기화 오류: %s", e)
        return None


def _close_cdp_hijack(hijack) -> None:
    """CDP 하이재킹 연결 종료"""
    if hijack is None:
        return
    try:
        loop = getattr(hijack, "_loop", None)
        if loop:
            loop.run_until_complete(hijack.close())
            loop.close()
        else:
            import asyncio
            asyncio.run(hijack.close())
    except Exception:
        pass


def _fetch_games_from_cdp(product_id: str, cdp_port: int = 9222) -> list[dict]:
    """CDP로 특정 구단의 경기 목록 스크래핑 (동기 래퍼)

    Args:
        product_id: 구단 productId
        cdp_port: Chrome CDP 포트

    Returns:
        경기 목록 [{"scheduleId": ..., "productId": ..., "text": ...}]
        또는 실패 시 빈 리스트
    """
    try:
        from .cdp_hijack import CdpHijack
        import asyncio

        hijack = CdpHijack(cdp_port=cdp_port)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            ok = loop.run_until_complete(hijack.connect())
            if not ok:
                logger.warning("  ⚠️ CDP 연결 실패 (포트 %d)", cdp_port)
                return []

            games = loop.run_until_complete(hijack.fetch_games(product_id))
            loop.run_until_complete(hijack.close())
            return games
        except Exception:
            loop.close()
            raise
    except Exception as e:
        logger.error("  ❌ 경기 목록 스크래핑 오류: %s", e)
        return []


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
    click_wait = delays.get("click_wait", 1500) / 1000.0
    refresh_delay = delays.get("refresh", 300) / 1000.0

    c1 = macro.get("click1", [0, 0])
    if c1[0] == 0 and c1[1] == 0:
        result["message"] = "❌ 예매하기 좌표(click1) 미설정"
        logger.error(result["message"])
        return result

    # ── 서버시간 파싱 ──
    server_time_str = cfg.get("booking", {}).get("server_time", "").strip()
    target_epoch = 0
    # 서버시간 오프셋 (HTTP Date 헤더 측정값, local clock 보정용)
    server_offset = float(cfg.get("booking", {}).get("server_time_offset", 0))
    if server_time_str:
        try:
            parts = list(map(int, server_time_str.replace("-", ":").split(":")))
            # 오늘 자정 epoch (local 기준)
            now = time.localtime()
            today_midnight = int(time.mktime((
                now.tm_year, now.tm_mon, now.tm_mday,
                0, 0, 0,
                now.tm_wday, now.tm_yday, now.tm_isdst,
            )))
            # 서버시간 기준 target epoch = 오늘 자정 + HH:MM:SS - offset 보정
            h, m, s = parts[0], parts[1] if len(parts) > 1 else 0, parts[2] if len(parts) > 2 else 0
            local_target = today_midnight + h * 3600 + m * 60 + s
            # server_offset 만큼 보정 (local보다 server가 빠르면 offset > 0)
            target_epoch = local_target - server_offset
            # 이미 지난 시간이면 하루 더 (서버시간 기준)
            if target_epoch < time.time():
                target_epoch += 86400
            logger.info("  🕐 서버시간: %s → %s까지 대기 (offset=%.0fms)",
                        server_time_str,
                        time.strftime("%H:%M:%S", time.localtime(target_epoch)),
                        server_offset * 1000)
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
        _wait(0.5)
    if rc[0] != 0 or rc[1] != 0:
        _click(rc[0], rc[1], "회차선택")
        _wait(0.5)

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
    click_wait = delays.get("click_wait", 1500) / 1000.0
    seat_click_delay = delays.get("seat_click", 10) / 1000.0
    refresh_delay = delays.get("refresh", 300) / 1000.0
    section_move = delays.get("section_move", 100) / 1000.0

    max_retries = macro.get("max_retries", 30)
    max_screenshot_fails = macro.get("max_screenshot_fails", 5)
    ss = macro.get("seat_search", {})
    row_tolerance = ss.get("row_tolerance", 30)
    gap_tolerance = ss.get("gap_tolerance", 40)
    max_results_per_zone = ss.get("max_results_per_zone", 20)

    # ── CDP 폼 하이재킹 ──
    _cdp_hijack = _maybe_activate_cdp_hijack(cfg)

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
            _wait(0.1)

        logger.info("  🔍 캡차 처리 중...")
        try:
            solved = _standalone_captcha(stop_event=stop_event, method=captcha_method,
                                         captcha_area=macro.get("captcha_area"),
                                         captcha_typing_delay=delays.get("captcha_typing_delay", 15))
            if solved:
                logger.info("  ✅ 캡차 입력 완료")
                _wait(0.5)
            else:
                logger.warning("  ⚠️ 캡차 해결 실패, 계속 진행")
        except Exception as e:
            logger.error("  ❌ 캡차 오류: %s", e)

    # ── 전처리: 구역선택 → 직접선택 → 안내창확인 (좌석검색 전에 실행) ──
    logger.info("  🏁 전처리: 구역선택 → 직접선택 → 안내창확인")
    if not _do_preroll(macro, delays, stop_event, section_move, click_wait):
        result["message"] = "⏹️ 사용자 중지 (전처리 중)"
        return result

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
            _wait(0.5)
        if rc[0] != 0 or rc[1] != 0:
            _click(rc[0], rc[1], "회차선택(재시도)")
            _wait(0.5)
        if c2[0] != 0 or c2[1] != 0:
            _click(c2[0], c2[1], "확인")
            _wait(click_wait)
        # 캡차 재해결
        retry_solved = False
        if auto_captcha:
            ci = macro.get("captcha_input", [0, 0])
            if ci[0] != 0 or ci[1] != 0:
                _click(ci[0], ci[1], "캡차 입력창(재시도)")
                _wait(0.1)
            try:
                retry_solved = _standalone_captcha(stop_event=stop_event, method=captcha_method,
                                                     captcha_area=macro.get("captcha_area"),
                                                     captcha_typing_delay=delays.get("captcha_typing_delay", 15))
            except Exception as e:
                logger.error("  ❌ 재시도 캡차 오류: %s", e)
        # 재시도 시에도 전처리 다시 실행
        logger.info("  🔁 전처리 재실행 (구역선택 → 직접선택 → 안내창확인)")
        if not _do_preroll(macro, delays, stop_event, section_move, click_wait):
            result["message"] = "⏹️ 사용자 중지 (재시도 전처리 중)"
            return result

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

    # ── 선택완료 ──
    c3 = macro.get("click3", [0, 0])
    if c3[0] != 0 or c3[1] != 0:
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            return result
        _wait(0.5)
        _click(c3[0], c3[1], "선택완료")
        _wait(0.5)

    # ── 결제하기 ──
    c4 = macro.get("click4", [0, 0])
    if c4[0] != 0 or c4[1] != 0:
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            return result
        _wait(0.5)
        _click(c4[0], c4[1], "결제하기")
        result["stage"] = "payment"
        result["message"] = "✅ 예매 완료! 결제 페이지로 이동했습니다."
    else:
        result["message"] = "✅ 예매 완료!"

    result["success"] = True
    if result["stage"] != "payment":
        result["stage"] = "complete"
    logger.info("  🎉 %s", result["message"])
    _close_cdp_hijack(_cdp_hijack)
    return result


# ================================================================
#  전처리: 구역선택 → 직접선택 → 안내창확인
# ================================================================

def _do_preroll(macro: dict, delays: dict, stop_event=None,
                section_move=0.1, click_wait=1.5) -> bool:
    """구역선택 → 직접선택 → 안내창확인 (좌석검색 전에 실행)

    Returns:
        False면 중지 요청 (호출자는 즉시 반환해야 함)
    """
    # 구역선택
    sc = macro.get("section_click", [0, 0])
    if sc[0] != 0 or sc[1] != 0:
        if stop_event and stop_event.is_set():
            return False
        _wait(section_move)
        _click(sc[0], sc[1], "구역선택")
        _wait(section_move)

    # 직접선택 (선택)
    ds = macro.get("direct_select", [0, 0])
    if ds[0] != 0 or ds[1] != 0:
        if stop_event and stop_event.is_set():
            return False
        _wait(0.5)
        _click(ds[0], ds[1], "직접선택")
        _wait(click_wait)

    # 안내창 확인 (선택)
    cg = macro.get("click_guide", [0, 0])
    if cg[0] != 0 or cg[1] != 0:
        if stop_event and stop_event.is_set():
            return False
        _wait(0.5)
        _click(cg[0], cg[1], "안내창 확인")
        _wait(click_wait)

    return True


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
    click_wait = delays.get("click_wait", 1500) / 1000.0
    seat_click_delay = delays.get("seat_click", 10) / 1000.0
    refresh_delay = delays.get("refresh", 300) / 1000.0
    section_move = delays.get("section_move", 100) / 1000.0
    # 매크로 제어값 (설정 가능, 기본값은 config.py DEFAULT_CONFIG 참조)
    max_retries = macro.get("max_retries", 30)
    max_screenshot_fails = macro.get("max_screenshot_fails", 5)
    ss = macro.get("seat_search", {})
    row_tolerance = ss.get("row_tolerance", 30)
    gap_tolerance = ss.get("gap_tolerance", 40)
    max_results_per_zone = ss.get("max_results_per_zone", 20)

    # ── CDP 폼 하이재킹 ──
    _cdp_hijack = _maybe_activate_cdp_hijack(cfg)

    logger.info("=" * 50)
    logger.info("  🎫 티켓링크봇 — 독립형 매크로")
    logger.info("  Chrome 없이 시스템 레벨로 실행됩니다.")
    logger.info("=" * 50)

    # ===== 설정 검증 =====
    c1 = macro.get("click1", [0, 0])
    if c1[0] == 0 and c1[1] == 0:
        result["message"] = "❌ 예매하기 좌표(click1) 미설정"
        logger.error(result["message"])
        _close_cdp_hijack(_cdp_hijack)
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
        _wait(0.5)
    if rc[0] != 0 or rc[1] != 0:
        _click(rc[0], rc[1], "회차선택")
        _wait(0.5)

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
            solved = _standalone_captcha(stop_event=stop_event, method=captcha_method,
                                         captcha_area=macro.get("captcha_area"),
                                         captcha_typing_delay=delays.get("captcha_typing_delay", 15))
            if solved:
                logger.info("  ✅ 캡차 입력 완료 (서버 검증 대기)")
                _wait(0.5)
            else:
                logger.warning("  ⚠️ 캡차 해결 실패, 계속 진행")
        except Exception as e:
            logger.error("  ❌ 캡차 오류: %s", e)

    # ===== 3.5 전처리: 구역선택 → 직접선택 → 안내창확인 =====
    logger.info("  🏁 전처리: 구역선택 → 직접선택 → 안내창확인")
    if not _do_preroll(macro, delays, stop_event, section_move, click_wait):
        result["message"] = "⏹️ 사용자 중지 (전처리 중)"
        return result

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
                _wait(0.5)
            if rc[0] != 0 or rc[1] != 0:
                _click(rc[0], rc[1], "회차선택(재시도)")
                _wait(0.5)
            if c2[0] != 0 or c2[1] != 0:
                _click(c2[0], c2[1], "확인")
                _wait(click_wait)
            # 캡차 재해결 (새로고침 후 새 캡차 챌린지)
            retry_solved = False
            if auto_captcha:
                try:
                    retry_solved = _standalone_captcha(stop_event=stop_event, method=captcha_method,
                                                       captcha_area=macro.get("captcha_area"),
                                                       captcha_typing_delay=delays.get("captcha_typing_delay", 15))
                except Exception as e:
                    logger.error("  ❌ 재시도 캡차 오류: %s", e)
            # 재시도 시에도 전처리 다시 실행
            logger.info("  🔁 전처리 재실행 (구역선택 → 직접선택 → 안내창확인)")
            if not _do_preroll(macro, delays, stop_event, section_move, click_wait):
                result["message"] = "⏹️ 사용자 중지 (재시도 전처리 중)"
                return result

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

    # ===== 5. 선택완료 =====
    c3 = macro.get("click3", [0, 0])
    if c3[0] != 0 or c3[1] != 0:
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            logger.warning("  ⏹️ %s", result["message"])
            return result
        _wait(0.5)
        _click(c3[0], c3[1], "선택완료")
        _wait(0.5)

    # ===== 6. 결제하기 =====
    c4 = macro.get("click4", [0, 0])
    if c4[0] != 0 or c4[1] != 0:
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지"
            logger.warning("  ⏹️ %s", result["message"])
            return result
        _wait(0.5)
        _click(c4[0], c4[1], "결제하기")
        result["stage"] = "payment"
        result["message"] = "✅ 예매 완료! 결제 페이지로 이동했습니다."
    else:
        result["message"] = "✅ 예매 완료!"

    result["success"] = True
    if result["stage"] != "payment":
        result["stage"] = "complete"
    logger.info("  🎉 %s", result["message"])
    _close_cdp_hijack(_cdp_hijack)
    return result


# ================================================================
#  캡차 (시스템 스크린샷 기반)
# ================================================================

def _standalone_captcha(stop_event: Optional[threading.Event] = None,
                        method: str = "oauth",
                        captcha_area: Optional[list] = None,
                        captcha_typing_delay: int = 15) -> bool:
    """
    시스템 스크린샷으로 캡차 해결.
    Chrome CDP 없이 pyautogui 전체화면 스크린샷 사용.

    Args:
        captcha_area: [x1, y1, x2, y2] — 지정 시 해당 영역만 크롭하여 OCR 처리
    """
    from .captcha import solve_captcha_b64 as _solve_b64
    import base64
    from PIL import Image
    import io

    # 중지 신호 확인
    if stop_event and stop_event.is_set():
        logger.warning("  ⏹️ 캡차 처리 중단")
        return False

    # 1. 전체화면 스크린샷
    png = SystemBot.screenshot()
    if not png:
        logger.warning("  ⚠️ 스크린샷 실패")
        return False

    # 1.5 캡차 영역 크롭 (지정된 경우)
    if captcha_area and len(captcha_area) == 4 and any(captcha_area):
        x1, y1, x2, y2 = captcha_area
        try:
            img = Image.open(io.BytesIO(png))
            # 좌표 정규화 (x1 < x2, y1 < y2)
            cx1, cx2 = min(x1, x2), max(x1, x2)
            cy1, cy2 = min(y1, y2), max(y1, y2)
            cropped = img.crop((cx1, cy1, cx2, cy2))
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            png = buf.getvalue()
            logger.info("  📐 캡차 영역 크롭: (%d,%d)-(%d,%d)", cx1, cy1, cx2, cy2)
        except Exception as e:
            logger.warning("  ⚠️ 캡차 영역 크롭 실패: %s — 전체화면 사용", e)

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

    # 4. 키보드 입력 (비정상 빠른입력 방지를 위해 지연+랜덤지터)
    from .system_bot import SystemBot as _SB
    _SB.type_text_slow(captcha_text, char_delay_ms=captcha_typing_delay)
    # 5. 사람처럼 Enter 누르기 전에 잠시 망설임 (0.1~0.3초)
    import random as _rand
    time.sleep(_rand.uniform(0.1, 0.3))
    SystemBot.press("enter")
    time.sleep(0.2)
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
    logger.debug("  ⏳ %.1f초 대기...", t)
    time.sleep(t)
