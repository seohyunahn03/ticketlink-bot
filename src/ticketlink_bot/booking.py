"""
🎫 티켓링크 예매 파이프라인

CDP Bot → 페이지 스캔 → "예매하기" 클릭 → 안심예매(캡차) → 좌석선택
"""
import asyncio
import json
import logging
from typing import Optional

from .bot import Bot
from .captcha import solve_captcha as _solve_captcha
from .seats import find_seats_by_color, find_seats_in_zones, find_consecutive_seats, pick_color_at

logger = logging.getLogger("ticketlink_bot")

TICKETLINK_DOMAIN = "ticketlink.co.kr"


async def scan_and_book(
    bot: Bot,
    auto: bool = False,
    team_keyword: str = "LG",
    captcha_enabled: bool = True,
) -> dict:
    """
    현재 페이지 스캔 → 예매 버튼 클릭 → 캡차 해결 → 좌석선택 페이지 확인.

    Returns:
        {"success": bool, "stage": str, "url": str, "message": str}
    """
    result = {"success": False, "stage": "init", "url": "", "message": ""}

    # 1. 페이지 정보
    title = await bot.get_title()
    url = await bot.get_url()
    text = await bot.get_page_text(1000)
    result["url"] = url
    logger.info("📄 %s", title)
    logger.info("📍 %s", url)

    if auto:
        # 2. 현재 페이지에서 "예매하기" 버튼 찾기
        btns = await bot.find_buttons(["예매하기", "바로예매", "안심예매", "클린예매", "안심", "예매"])

        # 네비게이션 버튼 제외
        btns = [
            b for b in btns
            if not any(
                exclude in b["text"]
                for exclude in ["예매확인", "예매내역", "예매취소", "예매변경"]
            )
        ]

        if not btns:
            # 특정 경기 카드 찾기
            logger.info("🔍 '%s' 경기 검색 중...", team_keyword)
            clicked = await _find_and_click_game(bot, team_keyword)
            if clicked:
                await asyncio.sleep(4)
                btns = await bot.find_buttons(["예매하기", "예매", "안심", "클린예매", "바로예매"])

        if btns:
            result["stage"] = "buttons_found"
            _log_buttons(btns)

            # 우선순위: 예매하기 > 예매 > 클린예매 > 안심 > 첫번째 visible
            target = _pick_best_button(btns)

            if target:
                logger.info("🔄 '%s' 클릭...", target["text"])

                if target.get("href"):
                    await bot.navigate(target["href"])
                elif target.get("cls") and "btn_reserve" in target["cls"]:
                    # 진짜 마우스 클릭 (CDP Input.dispatchMouseEvent)
                    clicked = await bot.click_real("a.btn_reserve")
                    logger.info("  → a.btn_reserve %s", "✅ CDP 클릭" if clicked else "❌ 실패")
                elif target.get("cls"):
                    first_cls = target["cls"].split()[0]
                    await bot.js(f"document.querySelector('{target['tag'].lower()}.{first_cls}')?.click()")
                    logger.info("  → %s.%s 클릭", target["tag"].lower(), first_cls)
                else:
                    await bot.click_element(target["text"][:10])

                # 2.5 모달 처리 (클린예매/취소표대기 선택)
                await asyncio.sleep(2)
                modal_closed = await _handle_booking_modal(bot)

                await asyncio.sleep(3)
                new_url = await bot.get_url()
                result["url"] = new_url
                logger.info("📍 %s", new_url)

                # 3. 캡차 확인
                if captcha_enabled:
                    solved = await _handle_captcha(bot, new_url)
                    if solved:
                        result["stage"] = "captcha_solved"
                        result["message"] = "안심예매 완료! 좌석선택 페이지 확인"
                    else:
                        result["stage"] = "captcha_failed"
                        result["message"] = "안심예매 해결 실패"
                else:
                    result["stage"] = "button_clicked"
                    result["message"] = "버튼 클릭 완료 (캡차 스킵)"

                # 4. 최종 페이지 확인
                await asyncio.sleep(3)
                final_url = await bot.get_url()
                final_text = await bot.get_page_text(500)
                result["url"] = final_url
                logger.info("💺 최종: %s", final_url)
                logger.info("  %s", final_text[:200])

                result["success"] = True
                return result

        result["stage"] = "no_buttons"
        result["message"] = "예매 버튼을 찾을 수 없습니다"
    else:
        result["stage"] = "scanned"
        result["message"] = "페이지 스캔 완료 (--auto 모드로 자동 예매)"

    return result


async def click_and_book(
    bot: Bot,
    click1: tuple[int, int],
    click2: tuple[int, int],
    captcha_enabled: bool = True,
) -> dict:
    """
    좌표 기반 예매 — JS 평가 없이 CDP Input.dispatchMouseEvent 사용.
    사용자가 지정한 좌표 2개를 순서대로 클릭 (예매하기 → 확인).

    Args:
        bot: CDP Bot
        click1: (x, y) — '예매하기' 버튼 좌표
        click2: (x, y) — '확인' 버튼 좌표
        captcha_enabled: 캡차 자동 입력 여부
    """
    result = {"success": False, "stage": "init", "url": "", "message": ""}

    url = await bot.get_url()
    title = await bot.get_title()
    result["url"] = url
    logger.info("📄 %s", title)
    logger.info("📍 %s", url)

    # 1. 예매하기 클릭
    x1, y1 = click1
    logger.info("🖱️ 예매하기 클릭 (%d, %d)", x1, y1)
    await bot.cmd("Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x1, "y": y1, "button": "left", "clickCount": 1,
    })
    await bot.cmd("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x1, "y": y1, "button": "left", "clickCount": 1,
    })
    await asyncio.sleep(4)

    # 2. 확인 클릭
    x2, y2 = click2
    logger.info("🖱️ 확인 클릭 (%d, %d)", x2, y2)
    await bot.cmd("Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x2, "y": y2, "button": "left", "clickCount": 1,
    })
    await bot.cmd("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x2, "y": y2, "button": "left", "clickCount": 1,
    })
    await asyncio.sleep(4)

    # 3. 페이지 변화 확인
    new_url = await bot.get_url()
    new_title = await bot.get_title()
    result["url"] = new_url
    logger.info("📍 %s", new_url)
    logger.info("📄 %s", new_title)

    # 4. 캡차 확인 및 해결
    if captcha_enabled:
        captcha_result = await _handle_captcha_coords(bot)
        if captcha_result:
            result["stage"] = "captcha_solved"
            result["message"] = "✅ 안심예매 완료!"
        else:
            result["stage"] = "captcha_failed"
            result["message"] = "⚠️ 보안문자 해결 실패"
    else:
        result["stage"] = "clicked"
        result["message"] = "✅ 좌표 클릭 완료 (캡차 스킵)"

    # 5. 최종 상태
    await asyncio.sleep(2)
    final_url = await bot.get_url()
    final_text = await bot.get_page_text(300)
    result["url"] = final_url
    logger.info("💺 최종: %s", final_url)
    logger.info("  %s", final_text[:150])

    result["success"] = True
    return result


async def _handle_captcha_coords(bot: Bot) -> bool:
    """좌표 모드용 캡차 처리 — 보안문자 화면 감지 및 xAI Vision 자동 입력"""
    current_url = await bot.get_url()
    text = await bot.get_page_text(500)

    # 캡차 키워드 확인
    if not any(kw in text for kw in ["보안문자", "안심", "클린", "문자", "입력"]):
        logger.info("  → 보안문자 화면 아님, 통과")
        return True

    # sports 경로면 캡차 없음
    if "sports/137/59" in current_url.split("?")[0]:
        logger.info("  ✅ 좌석선택 페이지 (캡차 불필요)")
        return True

    logger.info("🔍 보안문자(캡차) 발견!")

    # 스크린샷 (캡차 영역 우선, b64 직통)
    b64_data = await bot.screenshot_element_b64()
    if not b64_data:
        logger.info("📸 캡차 요소 못 찾음, 전체 페이지 스크린샷 (b64)")
        b64_data = await bot.screenshot_b64()

    # 캡차 인식 (b64 직통)
    logger.info("🤖 캡차 인식 중...")
    try:
        from .captcha import solve_captcha_b64 as _solve_captcha
        captcha_text = _solve_captcha(b64_data)
        logger.info("✅ 인식: \"%s\"", captcha_text)
    except Exception as e:
        logger.error("❌ 인식 실패: %s", e)
        return False

    # 입력
    inputted = await bot.type_text(captcha_text)
    if inputted:
        logger.info("✅ 보안문자 입력 완료!")
    else:
        logger.warning("⚠️ 입력 필드 못 찾음")
        return False

    # "입력 완료" 또는 "확인" 클릭
    clicked = await bot.click_element("입력 완료")
    if not clicked:
        clicked = await bot.click_element("확인")
    if clicked:
        logger.info('✅ "입력 완료/확인" 클릭!')
    else:
        logger.warning("⚠️ 입력 완료 버튼 클릭 실패")

    await asyncio.sleep(3)
    return True


# ============================================================
# 🎯 좌표 따기 툴
# ============================================================

async def pick_coordinates(bot: Bot, click_timeout: int = 60) -> dict:
    """
    좌표 따기 툴 — Chrome 페이지에 오버레이를 띄워 우클릭 좌표 캡처.

    통합매크로 방식: 실시간 마우스 좌표 표시, 우클릭 저장, ESC 취소.

    Args:
        bot: CDP Bot
        click_timeout: 최대 대기 시간 (초)

    Returns:
        {"x": x, "y": y} — 우클릭한 좌표, 또는 {} (타임아웃/취소)
    """
    import json as _json

    url = await bot.get_url()
    logger.info("📍 현재 페이지: %s", url)
    logger.info("🎯 좌표 따기 — Chrome에서 우클릭하세요!")
    logger.info("   🖱️ 우클릭 → 좌표 저장")
    logger.info("   ⌨️ ESC → 취소")
    logger.info("   (우클릭해도 컨텍스트 메뉴 안 뜹니다)")

    # 오버레이 스크립트 주입 (통합매크로 스타일)
    await bot.js("""
        const old = document.getElementById('_coord_picker_overlay');
        if (old) old.remove();

        const overlay = document.createElement('div');
        overlay.id = '_coord_picker_overlay';
        overlay.innerHTML = `
            <div style="
                position:fixed; top:0; left:0; width:100%; height:100%;
                z-index:999999; pointer-events:none;
                font-family:monospace;
            ">
                <!-- 상단 고정 안내 -->
                <div id="_coord_help" style="
                    position:fixed; top:10px; left:50%; transform:translateX(-50%);
                    background:rgba(0,0,0,0.8); color:#0f0;
                    padding:8px 20px; border-radius:6px;
                    border:1px solid #0f0;
                    font-size:13px; text-align:center; z-index:999999;
                    pointer-events:none;
                ">🎯 좌표따기 — 우클릭 저장  |  ESC 취소</div>

                <!-- 하단 좌표 표시 -->
                <div id="_coord_display" style="
                    position:fixed; bottom:30px; left:50%; transform:translateX(-50%);
                    background:rgba(0,0,0,0.9); color:#0f0;
                    padding:16px 32px; border-radius:10px;
                    border:2px solid #0f0;
                    z-index:999999;
                    font-size:22px; font-weight:bold; text-align:center;
                    pointer-events:none;
                    box-shadow: 0 0 20px rgba(0,255,0,0.3);
                ">📍 준비 — 페이지를 우클릭하세요</div>

                <!-- 크로스헤어 (마우스 따라다님) -->
                <div id="_coord_crosshair" style="
                    position:fixed; top:0; left:0; width:24px; height:24px;
                    z-index:999999; pointer-events:none;
                    display:none;
                ">
                    <div style="
                        position:absolute; top:50%; left:50%;
                        width:24px; height:24px;
                        transform:translate(-50%,-50%);
                    ">
                        <div style="
                            position:absolute; top:50%; left:50%;
                            width:20px; height:2px; background:rgba(255,0,0,0.8);
                            transform:translate(-50%,-50%);
                        "></div>
                        <div style="
                            position:absolute; top:50%; left:50%;
                            width:2px; height:20px; background:rgba(255,0,0,0.8);
                            transform:translate(-50%,-50%);
                        "></div>
                        <div style="
                            position:absolute; top:50%; left:50%;
                            width:8px; height:8px; border:2px solid rgba(255,255,0,0.9);
                            border-radius:50%; transform:translate(-50%,-50%);
                        "></div>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        // 실시간 마우스 좌표 표시
        document.addEventListener('mousemove', e => {
            const ch = document.getElementById('_coord_crosshair');
            if (ch) {
                ch.style.left = e.clientX + 'px';
                ch.style.top = e.clientY + 'px';
                ch.style.display = 'block';
            }
            const d = document.getElementById('_coord_display');
            if (d) {
                d.innerHTML = '📍 (' + e.clientX + ', ' + e.clientY + ')';
                d.style.borderColor = '#0f0';
            }
        }, true);

        // 우클릭 좌표 저장 (컨텍스트 메뉴 차단)
        document.addEventListener('contextmenu', e => {
            e.preventDefault();
            const x = e.clientX, y = e.clientY;
            const d = document.getElementById('_coord_display');
            if (d) {
                d.innerHTML = '✅ 📍 (' + x + ', ' + y + ') — 저장됨!';
                d.style.borderColor = '#ff0';
                d.style.color = '#ff0';
                setTimeout(() => {
                    d.style.borderColor = '#0f0';
                    d.style.color = '#0f0';
                }, 800);
            }
            if (!window._captured_coords) window._captured_coords = [];
            window._captured_coords.push({x, y, time: Date.now()});
        }, true);

        // ESC 키 감지
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                window._coord_cancelled = true;
            }
        }, true);
    """)

    logger.info("✅ 좌표 오버레이 주입 완료! 우클릭해보세요.")

    # 클릭 대기 (최대 click_timeout 초, 0.5초 간격 폴링)
    for _ in range(click_timeout * 2):
        # ESC 취소 확인
        cancelled = await bot.js("window._coord_cancelled === true")
        if cancelled:
            logger.info("  ⏹️ ESC 취소")
            return {}

        coords = await bot.js("JSON.stringify(window._captured_coords || [])")
        if coords and coords != "[]":
            items = _json.loads(coords)
            for c in items:
                logger.info("  📌 (%d, %d)", c["x"], c["y"])
            last = items[-1]
            logger.info("✅ 최종 좌표: (%d, %d)", last["x"], last["y"])
            return {"x": last["x"], "y": last["y"]}
        await asyncio.sleep(0.5)

    logger.warning("⏱️ 좌표 캡처 타임아웃")
    return {}


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


async def full_auto_book(bot: Bot, cfg: dict) -> dict:
    """
    전체 자동 예매 파이프라인 (예전 매크로 방식 + 보안문자 자동해결).

    Flow:
        1. click1 — 예매하기 클릭
        2. click2 — 확인 클릭 (예매안내 모달)
        3. 보안문자 자동 해결 (xAI Vision)
        4. seat_area — 좌석 색상 검색 → 빈 좌석 찾기
        5. 빈 좌석 클릭
        6. click3 — 선택완료 클릭
    """
    result = {"success": False, "stage": "init", "url": "", "message": ""}
    macro = cfg.get("macro", {})
    delays = macro.get("delays", {})
    click_wait = delays.get("click_wait", 3)
    seat_click_delay = delays.get("seat_click", 10) / 1000.0
    refresh_delay = delays.get("refresh", 500) / 1000.0

    url = await bot.get_url()
    title = await bot.get_title()
    result["url"] = url
    logger.info("📄 %s", title)
    logger.info("📍 %s", url)

    async def _click(x, y, label=""):
        await bot.cmd("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1,
        })
        await bot.cmd("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1,
        })
        logger.info("🖱️ %s (%d, %d)", label, x, y)

    # ===== 1. 예매하기 클릭 =====
    c1 = macro.get("click1", [0, 0])
    if c1[0] == 0 and c1[1] == 0:
        result["message"] = "❌ 예매하기 좌표(click1) 미설정"
        logger.error(result["message"])
        return result
    await _click(c1[0], c1[1], "예매하기")
    await asyncio.sleep(click_wait)

    # ===== 1.5 날짜/회차 자동선택 =====
    dc = macro.get("date_click", [0, 0])
    rc = macro.get("round_click", [0, 0])
    if dc[0] != 0 or dc[1] != 0:
        await _click(dc[0], dc[1], "날짜선택")
        await asyncio.sleep(1)
    if rc[0] != 0 or rc[1] != 0:
        await _click(rc[0], rc[1], "회차선택")
        await asyncio.sleep(1)

    # ===== 2. 확인 클릭 =====
    c2 = macro.get("click2", [0, 0])
    if c2[0] != 0 or c2[1] != 0:
        await _click(c2[0], c2[1], "확인")
        await asyncio.sleep(click_wait)

    # ===== 3. 보안문자 처리 =====
    if cfg.get("booking", {}).get("auto_captcha", True):
        if not await _handle_captcha_coords(bot):
            result["stage"] = "captcha_failed"
            result["message"] = "보안문자 해결 실패"
            return result
        logger.info("✅ 보안문자 처리 완료")
        await asyncio.sleep(2)

    # ===== 4. 좌석 색상 검색 & 클릭 (다중 구역 지원) =====
    seat_area = macro.get("seat_area", [0, 0, 0, 0])
    seat_color = macro.get("seat_color", "C8C8C8")
    color_tolerance = macro.get("color_tolerance", 20)
    consecutive_n = macro.get("consecutive_seats", 2)

    # zones 설정 (통합매크로 방식: 여러 구역 각각 영역+색상)
    seat_zones = _get_zones(macro)

    if any(seat_area) or seat_zones:
        if seat_zones:
            logger.info("🔍 좌석 검색: %d개 구역, %d연석", len(seat_zones), consecutive_n)
        else:
            logger.info("🔍 좌석 검색: 색상=%s, 오차=%d, %d연석, 영역=%s",
                         seat_color, color_tolerance, consecutive_n, seat_area)

        found_group = []

        for attempt in range(30):
            png = await bot.screenshot()

            if seat_zones:
                # 다중 구역 검색
                zone_result = find_seats_in_zones(png, seat_zones, max_results_per_zone=20)
                all_seats = zone_result["all"]
                found_group = find_consecutive_seats(
                    all_seats, n=consecutive_n,
                    row_tolerance=30, gap_tolerance=40,
                )
            else:
                # 단일 영역 (하위호환)
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
                logger.info("🎯 빈 좌석 발견! %d석 (%d/30)",
                             len(found_group), attempt + 1)
                break

            logger.info("  ↻ 빈 좌석 없음, 새로고침 (%d/30)", attempt + 1)
            await bot.cmd("Page.reload", {})
            await asyncio.sleep(refresh_delay)
            await _click(c1[0], c1[1], "예매하기(재시도)")
            await asyncio.sleep(click_wait)
            if c2[0] != 0 or c2[1] != 0:
                await _click(c2[0], c2[1], "확인")
                await asyncio.sleep(click_wait)

        if found_group:
            # 좌석들 순서대로 클릭
            for i, (sx, sy) in enumerate(found_group):
                await _click(sx, sy, f"좌석선택({i+1})")
                await asyncio.sleep(seat_click_delay)
        else:
            result["message"] = f"빈 좌석을 찾을 수 없음 ({consecutive_n}연석, 30회)"
            logger.warning("⚠️ %s", result["message"])
            return result

    # ===== 4.5 구역선택 (있는 경우) =====
    sc = macro.get("section_click", [0, 0])
    if sc[0] != 0 or sc[1] != 0:
        await asyncio.sleep(1)
        await _click(sc[0], sc[1], "구역선택")
        await asyncio.sleep(2)

    # ===== 5. 선택완료 클릭 =====
    c3 = macro.get("click3", [0, 0])
    if c3[0] != 0 or c3[1] != 0:
        await asyncio.sleep(1)
        await _click(c3[0], c3[1], "선택완료")
        await asyncio.sleep(2)

    # ===== 6. 결제하기 클릭 =====
    c4 = macro.get("click4", [0, 0])
    if c4[0] != 0 or c4[1] != 0:
        await asyncio.sleep(1)
        await _click(c4[0], c4[1], "결제하기")
        result["stage"] = "payment"
        result["message"] = "✅ 예매 완료! 결제 페이지로 이동했습니다."
    else:
        result["message"] = "✅ 예매 완료! (결제 좌표 미설정)"

    final_url = await bot.get_url()
    result["url"] = final_url
    result["success"] = True
    result["stage"] = "complete"
    result["message"] = "✅ 예매 완료!"
    logger.info("💺 %s", final_url)
    return result


async def _find_and_click_game(bot: Bot, team: str) -> bool:
    """경기 목록에서 특정 팀 경기 찾아 클릭"""
    clicked = await bot.js(f"""(() => {{
        const items = document.querySelectorAll(
            '[class*="product"], [class*="card"], li, [class*="item"]'
        );
        for (const item of items) {{
            if (item.textContent.includes('{team}')) {{
                const btn = item.querySelector('a, button');
                if (btn && btn.textContent.includes('예매')) {{
                    btn.dispatchEvent(new MouseEvent('click', {{
                        bubbles: true, cancelable: true, view: window
                    }}));
                    return btn.textContent.trim();
                }}
            }}
        }}
        return null;
    }})()""")
    if clicked:
        logger.info("  → '%s' 클릭!", clicked)
        return True
    logger.warning("  ⚠️ '%s' 경기/예매 버튼 없음", team)
    return False


async def _handle_booking_modal(bot: Bot) -> bool:
    """예매안내 모달 처리 — '확인' 버튼 클릭"""
    await asyncio.sleep(1)

    # "예매안내" 모달 확인
    has_guide = await bot.js("""(() => {
        const guide = document.querySelector('.common_modal_wrap, .common_modal, [class*="modal_wrap"]');
        if (!guide) return false;
        return guide.textContent.includes('예매안내') || guide.textContent.includes('예매 안내');
    })()""")
    if not has_guide:
        logger.info("  → 예매안내 모달 없음, 통과")
        return True

    logger.info("🔔 예매안내 모달 감지 → 확인 클릭")

    # 첫 번째로 보이는 "확인" 버튼 클릭
    clicked = await bot.js("""(() => {
        const confirmBtns = document.querySelectorAll('button.common_modal_close, .common_modal_footer button, .common_modal_footer a');
        for (const btn of confirmBtns) {
            if (btn.textContent.trim() === '확인') {
                btn.click();
                return true;
            }
        }
        return false;
    })()""")
    if clicked:
        logger.info('  ✅ "확인" 클릭!')
        await asyncio.sleep(2)
        return True

    # fallback: textContent로 "확인" 전체 검색 (modal 내부)
    clicked = await bot.js("""(() => {
        const btns = document.querySelectorAll('button, a');
        for (const btn of btns) {
            const t = (btn.textContent || '').trim();
            const rect = btn.getBoundingClientRect();
            if (t === '확인' && rect.width > 0 && rect.height > 0) {
                btn.click();
                return true;
            }
        }
        return false;
    })()""")
    if clicked:
        logger.info('  ✅ "확인" fallback 클릭!')
        await asyncio.sleep(2)
        return True

    logger.warning('  ⚠️ "확인" 버튼 찾기 실패')
    return False


async def _handle_captcha(bot: Bot, current_url: str) -> bool:
    """
    안심예매(캡차) 화면 감지 및 자동 해결.
    URL이 sports/137/59 (야구) 경로를 포함하면 캡차 없음.
    """
    if "sports/137/59" in current_url.split("?")[0]:
        logger.info("  ✅ 캡차 없음, 좌석선택 페이지")
        return True

    text = await bot.get_page_text(1000)
    if not any(kw in text for kw in ["안심", "클린", "문자", "입력"]):
        logger.info("  → 안심예매 화면 아님")
        return True  # 캡차가 없는 페이지면 통과

    logger.info("🔍 안심예매(캡차) 발견!")

    # 스크린샷 (캡차 영역 우선, b64 직통)
    b64_data = await bot.screenshot_element_b64()
    if not b64_data:
        logger.info("📸 캡차 요소 못 찾음, 전체 페이지 스크린샷 (b64)")
        b64_data = await bot.screenshot_b64()

    # xAI Vision 인식 (b64 직통)
    logger.info("🤖 캡차 인식 중...")
    try:
        from .captcha import solve_captcha_b64 as _solve_captcha
        captcha_text = _solve_captcha(b64_data)
        logger.info("✅ 인식: \"%s\"", captcha_text)
    except Exception as e:
        logger.error("❌ 인식 실패: %s", e)
        return False

    # 입력
    inputted = await bot.type_text(captcha_text)
    if inputted:
        logger.info("✅ 캡차 입력 완료!")
    else:
        logger.warning("⚠️ 입력 필드 못 찾음")
        return False

    # "입력 완료" 클릭
    clicked = await bot.click_element("입력 완료")
    if clicked:
        logger.info('✅ "입력 완료" 클릭!')
    else:
        # "확인"이나 "완료" 시도
        clicked = await bot.click_element("확인") or await bot.click_element("완료")

    await asyncio.sleep(3)
    return True


def _pick_best_button(btns: list[dict]) -> Optional[dict]:
    """우선순위에 따라 최적의 버튼 선택"""
    # 1순위: <a> 태그 + '예매하기'/'바로예매' 정확 매칭 (viewport 우선, 없으면 visible)
    for in_vp in [True, False]:
        for b in btns:
            t = b["text"].strip()
            vp_ok = b.get("inViewport") if in_vp else b.get("visible")
            if vp_ok and b.get("tag") in ("A",) and t in ("예매하기", "바로예매"):
                return b
    # 2순위: viewport + 우선순위 키워드 + 20자 미만
    for priority_text in ["예매하기", "바로예매", "예매", "클린예매", "안심예매", "안심"]:
        for b in btns:
            t = b["text"].strip()
            if b.get("inViewport") and priority_text in t and len(t) < 20:
                return b
    # 3순위: visible + 키워드 매칭
    for priority_text in ["예매하기", "바로예매", "예매", "클린예매", "안심예매", "안심"]:
        for b in btns:
            t = b["text"].strip()
            if b.get("visible") and priority_text in t and len(t) < 20:
                return b
    # 4순위: visible + 50자 미만
    for b in btns:
        t = b["text"].strip()
        if b.get("visible") and len(t) < 50:
            return b
    return None


def _log_buttons(btns: list[dict]) -> None:
    """버튼 목록 로그 출력"""
    logger.info("🎯 버튼 %d개", len(btns))
    for i, b in enumerate(btns):
        vis = "👁️" if b.get("visible") else "🚫"
        vp = "📌" if b.get("inViewport") else "  "
        logger.info("  %s%s [%d] %s", vis, vp, i + 1, b["text"])
