"""
🔄 하이브리드 새로고침 봇 — CDP 기반 DOM 폴링 + 예매하기 자동클릭

개념:
  1. CDP WebSocket으로 BEFORE 게임의 product 페이지(/product/{productId})로 이동
  2. 페이지 DOM에서 특정 scheduleId의 "예매하기" 버튼이 활성화(disabled 해제)될 때까지 폴링
  3. 활성화되면 해당 버튼 클릭 → /reserve/product/{id}?scheduleId={sid} 로 이동
  4. hijack이 활성화되어 있으면 window.open을 가로채서 TARGET 게임으로 리다이렉트
  5. reserve 페이지 도착 후 macro_bot(캡차+좌석+결제) 체인

사용법:
  result = hybrid_refresh_bot(cfg)                    # 새로고침만
  result = hybrid_book(cfg)                           # 새로고침 + 매크로 체인
"""
import asyncio
import json
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


# ── DOM 폴링 JavaScript ──────────────────────────────────────────

POLL_JS_SCRIPT = r"""(() => {
    const SCHEDULE_ID = {schedule_id_json};
    const card = document.querySelector('[data-schedule-id="' + SCHEDULE_ID + '"]');
    if (!card) {{
        // Fallback: data-game-id, data-schedule 등 다른 속성 시도
        const alt = document.querySelector(
            '[data-schedule*="' + SCHEDULE_ID + '"], ' +
            '[data-game-id="' + SCHEDULE_ID + '"], ' +
            '[data-id*="' + SCHEDULE_ID + '"]'
        );
        if (!alt) return {{found: false, reason: 'card not found', scheduleId: SCHEDULE_ID}};
        return {{found: false, reason: 'alt card found', scheduleId: SCHEDULE_ID}};
    }}

    // Find clickable element containing "예매하기" text
    const all = card.querySelectorAll('a, button, span, div, em, strong, label, input[type="submit"], input[type="button"]');
    let target = null;
    for (const el of all) {{
        const text = (el.textContent || '').trim();
        if (text.includes('예매하기')) {{
            target = el;
            break;
        }}
    }}
    if (!target) {{
        // Try parent card text directly
        const cardText = (card.textContent || '').trim();
        if (cardText.includes('예매하기')) {{
            // The card itself may be clickable
            target = card;
        }}
    }}
    if (!target) return {{found: false, reason: 'no 예매하기 text', scheduleId: SCHEDULE_ID}};

    const rect = target.getBoundingClientRect();
    const isVisible = rect.width > 0 && rect.height > 0;
    const isDisabled = target.disabled === true ||
        target.getAttribute('disabled') !== null ||
        target.classList.contains('disabled') ||
        (target.closest('[disabled]') !== null) ||
        (target.closest('.disabled') !== null) ||
        (target.closest('[class*="disabled"]') !== null);

    // Check aria-disabled
    const ariaDisabled = target.getAttribute('aria-disabled');
    const isAriaDisabled = ariaDisabled === 'true' || ariaDisabled === true;

    // Check cursor style
    const cursor = window.getComputedStyle(target).cursor;
    const isClickable = cursor === 'pointer' || cursor === 'hand';

    return {{
        found: true,
        disabled: isDisabled || isAriaDisabled,
        visible: isVisible,
        clickable: isClickable,
        tag: target.tagName,
        text: (target.textContent || '').trim().substring(0, 40),
        rect: {{
            top: rect.top,
            left: rect.left,
            width: rect.width,
            height: rect.height
        }},
        innerHTML: target.innerHTML.substring(0, 100),
        className: target.className || '',
        id: target.id || '',
        href: target.href || target.parentElement?.href || '',
    }};
}})()
"""

CLICK_JS_SCRIPT = r"""(() => {
    const SCHEDULE_ID = {schedule_id_json};
    const card = document.querySelector('[data-schedule-id="' + SCHEDULE_ID + '"]');
    if (!card) return {{clicked: false, reason: 'card not found'}};

    // Find by text
    const all = card.querySelectorAll('a, button, span, div, em, strong, label');
    let target = null;
    for (const el of all) {{
        if ((el.textContent || '').trim().includes('예매하기')) {{
            target = el;
            break;
        }}
    }}
    if (!target) {{
        if ((card.textContent || '').trim().includes('예매하기')) {{
            target = card;
        }}
    }}
    if (!target) return {{clicked: false, reason: 'target not found'}};

    // Scroll into view first
    target.scrollIntoView({{behavior: 'instant', block: 'center', inline: 'center'}});

    // Try multiple click methods
    try {{
        target.click();
        return {{clicked: true, method: 'native_click', tag: target.tagName, text: (target.textContent || '').trim().substring(0, 30)}};
    }} catch (e) {{}}

    // Fallback: MouseEvent dispatch
    try {{
        target.dispatchEvent(new MouseEvent('click', {{
            bubbles: true, cancelable: true, view: window,
            clientX: 0, clientY: 0,
        }}));
        return {{clicked: true, method: 'mouseevent_dispatch', tag: target.tagName}};
    }} catch (e) {{}}

    // Fallback: simulate pointerdown + pointerup
    try {{
        target.dispatchEvent(new PointerEvent('pointerdown', {{bubbles: true, cancelable: true}}));
        target.dispatchEvent(new PointerEvent('pointerup', {{bubbles: true, cancelable: true}}));
        return {{clicked: true, method: 'pointerevent_dispatch', tag: target.tagName}};
    }} catch (e) {{}}

    return {{clicked: false, reason: 'all click methods failed', tag: target.tagName}};
}})()
"""

NAVIGATION_WAIT_JS = r"""(() => {
    const url = window.location.href;
    const path = window.location.pathname;
    const hasReserve = path.includes('/reserve/product/') || url.includes('/reserve/product/');
    const sidMatch = url.match(/[?&]scheduleId=(\d+)/);
    const scheduleId = sidMatch ? sidMatch[1] : '';
    return {url: url, path: path, onReservePage: hasReserve, scheduleId: scheduleId};
})()
"""


# ── 하이브리드 모니터링 메인 ─────────────────────────────────────

async def monitor_product_page_until_onsale(
    hijack,
    source_product_id: str,
    source_schedule_id: str,
    target_product_id: str = "",
    target_schedule_id: str = "",
    stop_event: Optional[threading.Event] = None,
    poll_interval: float = 0.5,
    max_wait: float = 3600.0,
) -> dict:
    """
    BEFORE 게임 product 페이지에서 특정 scheduleId의 예매하기 버튼이
    활성화될 때까지 DOM 폴링. 활성화되면 클릭하여 reserve 페이지로 이동.

    Args:
        hijack: CdpHijack 인스턴스 (연결된 상태)
        source_product_id: BEFORE 게임의 구단 productId
        source_schedule_id: BEFORE 게임의 경기 scheduleId
        target_product_id: 타겟 productId (비어있으면 hijack 비활성)
        target_schedule_id: 타겟 scheduleId (비어있으면 hijack 비활성)
        stop_event: 중지 신호 이벤트
        poll_interval: DOM 폴링 간격 (초)
        max_wait: 최대 대기 시간 (초)

    Returns:
        {"success": True, "url": "...", "product_id": "...", "schedule_id": "...",
         "navigate_result": {...}}  또는 실패 시 {"success": False, ...}
    """
    result: dict = {"success": False, "stage": "init", "message": ""}
    navigate_to_target = bool(target_product_id and target_schedule_id)

    # ── 1. product 페이지로 이동 ──
    product_url = f"https://www.ticketlink.co.kr/product/{source_product_id}"
    logger.info("=" * 50)
    logger.info("  🔄 하이브리드 새로고침 시작")
    logger.info("  📄 BEFORE 상품: product=%s schedule=%s",
                source_product_id, source_schedule_id)
    if navigate_to_target:
        logger.info("  🎯 타겟: product=%s schedule=%s",
                    target_product_id, target_schedule_id)
    else:
        logger.info("  🎯 타겟: 동일 경기 (hijack 미사용)")
    logger.info("  🔗 %s", product_url)
    logger.info("=" * 50)

    await hijack.navigate(product_url)

    # ── 2. SPA 렌더링 대기 (초기 로딩) ──
    logger.info("  ⏳ SPA 렌더링 대기 중... (3초)")
    await asyncio.sleep(3.0)

    # ── 3. hijack 주입 (타겟 지정된 경우) ──
    if navigate_to_target:
        logger.info("  💉 CDP 폼 하이재킹 주입 (product=%s, schedule=%s)",
                    target_product_id, target_schedule_id)
        injected = await hijack.inject(target_product_id, target_schedule_id)
        if injected:
            logger.info("  ✅ 하이재킹 활성화 완료")
        else:
            logger.warning("  ⚠️ 하이재킹 주입 실패 — 계속 진행")
    else:
        logger.info("  ℹ️ 타겟 미지정 — hijack 없이 source 그대로 예매")

    # ── 4. DOM 폴링 루프 ──
    start_time = time.time()
    poll_count = 0
    last_status = ""

    while True:
        # 중지 확인
        if stop_event and stop_event.is_set():
            result["message"] = "⏹️ 사용자 중지 (폴링 중)"
            result["stage"] = "stopped"
            logger.warning("  ⏹️ %s", result["message"])
            return result

        # 타임아웃 확인
        elapsed = time.time() - start_time
        if elapsed > max_wait:
            result["message"] = f"⏰ 대기 시간 초과 ({max_wait:.0f}초)"
            result["stage"] = "timeout"
            logger.warning("  ⏰ %s", result["message"])
            return result

        poll_count += 1

        # DOM 폴링 실행
        js = POLL_JS_SCRIPT.replace("{schedule_id_json}", json.dumps(source_schedule_id))
        poll_result = await hijack._send_with_result("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
        })

        state = {}
        if poll_result and "result" in poll_result:
            state = poll_result["result"].get("value", {})

        found = state.get("found", False)
        disabled = state.get("disabled", True)
        visible = state.get("visible", False)
        reason = state.get("reason", "")

        # 상태 로깅 (추기 또는 변경 시)
        if poll_count == 1 or (poll_count % 20 == 0) or (found and not disabled):
            status = f"  🔍 #{poll_count} elapsed={elapsed:.1f}s"
            if not found:
                status += f" | card not found ({reason})"
            elif disabled:
                status += f" | 예매하기 disabled (visible={visible})"
            else:
                status += f" | ✅ 예매하기 활성! (visible={visible})"
            if status != last_status:
                logger.info(status)
                last_status = status

        if found and not disabled and visible:
            # ── 5. 활성화됨 → 클릭 ──
            logger.info("  🎯 예매하기 버튼 활성화 발견! 클릭 시도...")
            click_js = CLICK_JS_SCRIPT.replace(
                "{schedule_id_json}", json.dumps(source_schedule_id)
            )
            click_result = await hijack._send_with_result("Runtime.evaluate", {
                "expression": click_js,
                "returnByValue": True,
            })

            click_state = {}
            if click_result and "result" in click_result:
                click_state = click_result["result"].get("value", {})

            clicked = click_state.get("clicked", False)
            if clicked:
                logger.info("  ✅ 클릭 성공! (method=%s)", click_state.get("method", "?"))
            else:
                logger.warning("  ⚠️ JS 클릭 실패 (%s) — 좌표 클릭 fallback", click_state.get("reason", "?"))
                # Fallback: pyautogui 좌표 클릭 못하므로 페이지 이동 감지로 전환
                # 일부 SPA는 click 대신 <a> href 네비게이션 사용
                logger.info("  🔍 네비게이션 감지 대기...")

            # ── 6. reserve 페이지로 네비게이션 감지 ──
            logger.info("  ⏳ reserve 페이지 네비게이션 감지 중... (최대 15초)")
            nav_start = time.time()
            nav_timeout = 15.0
            on_reserve = False
            final_url = ""
            final_schedule_id = ""

            while time.time() - nav_start < nav_timeout:
                if stop_event and stop_event.is_set():
                    result["message"] = "⏹️ 사용자 중지 (네비게이션 대기 중)"
                    result["stage"] = "stopped"
                    return result

                await asyncio.sleep(0.3)
                nav_check = await hijack._send_with_result("Runtime.evaluate", {
                    "expression": NAVIGATION_WAIT_JS,
                    "returnByValue": True,
                })
                nav_state = {}
                if nav_check and "result" in nav_check:
                    nav_state = nav_check["result"].get("value", {})

                on_reserve = nav_state.get("onReservePage", False)
                final_url = nav_state.get("url", "")
                final_schedule_id = nav_state.get("scheduleId", "")

                if on_reserve:
                    logger.info("  ✅ reserve 페이지 도착!")
                    logger.info("  📍 URL: %s", final_url[:120])
                    result["success"] = True
                    result["stage"] = "on_reserve_page"
                    result["url"] = final_url
                    result["product_id"] = target_product_id or source_product_id
                    result["schedule_id"] = final_schedule_id or source_schedule_id
                    result["navigate_result"] = click_state
                    return result

            # 타임아웃: 페이지가 reserve로 이동하지 않음
            logger.warning("  ⚠️ reserve 페이지 감지 실패 (15초)")
            logger.info("  📍 현재 URL: %s", final_url[:120] if final_url else "unknown")
            result["message"] = "reserve 페이지 네비게이션 실패"
            result["stage"] = "nav_timeout"
            result["url"] = final_url
            return result

        # ── 폴링 간격 대기 ──
        await asyncio.sleep(poll_interval)


# ── 동기 래퍼 ────────────────────────────────────────────────────

def _run_async_in_thread(coro, loop=None):
    """별도 이벤트 루프에서 코루틴 실행 (동기 함수용)"""
    if loop is None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.close()
        except Exception:
            pass


def hybrid_refresh_bot(cfg: dict, stop_event: Optional[threading.Event] = None) -> dict:
    """
    하이브리드 새로고침 봇 — 동기 엔트리 포인트.

    설정(cfg['booking']['hybrid_refresh'])을 읽어서:
    1. CdpHijack 연결
    2. monitor_product_page_until_onsale 실행
    3. 연결 종료

    Args:
        cfg: 설정 딕셔너리 (load_config 결과)
        stop_event: 중지 신호 이벤트

    Returns:
        {"success": bool, "stage": str, "message": str, ...}
    """
    result = {"success": False, "stage": "init", "message": ""}
    hr = cfg.get("booking", {}).get("hybrid_refresh", {})

    source_product_id = hr.get("source_product_id", "").strip()
    source_schedule_id = hr.get("source_schedule_id", "").strip()
    target_product_id = hr.get("target_product_id", "").strip()
    target_schedule_id = hr.get("target_schedule_id", "").strip()
    poll_interval = float(hr.get("poll_interval", 0.5))
    max_wait_minutes = float(hr.get("max_wait_minutes", 60))
    max_wait = max_wait_minutes * 60.0

    if not source_product_id or not source_schedule_id:
        result["message"] = "❌ source_product_id / source_schedule_id 미설정"
        logger.error(result["message"])
        return result

    # CDP 포트 (macro.cdp_hijack.port 사용, 혹은 별도 설정)
    cdp_port = int(cfg.get("macro", {}).get("cdp_hijack", {}).get("port", 9222))

    try:
        from .cdp_hijack import CdpHijack

        hijack = CdpHijack(cdp_port=cdp_port)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # 연결
            ok = loop.run_until_complete(hijack.connect())
            if not ok:
                result["message"] = f"❌ CDP 연결 실패 (포트 {cdp_port})"
                logger.error(result["message"])
                return result

            # 모니터링 실행
            logger.info("  🚀 하이브리드 새로고침 봇 시작")
            monitor_result = loop.run_until_complete(
                monitor_product_page_until_onsale(
                    hijack=hijack,
                    source_product_id=source_product_id,
                    source_schedule_id=source_schedule_id,
                    target_product_id=target_product_id,
                    target_schedule_id=target_schedule_id,
                    stop_event=stop_event,
                    poll_interval=poll_interval,
                    max_wait=max_wait,
                )
            )

            monitoring_success = monitor_result.get("success", False)
            if monitoring_success:
                result["success"] = True
                result["stage"] = monitor_result.get("stage", "monitor_done")
                result["message"] = "✅ 하이브리드 새로고침 성공 — reserve 페이지 도착"
                result["url"] = monitor_result.get("url", "")
                result["product_id"] = monitor_result.get("product_id", "")
                result["schedule_id"] = monitor_result.get("schedule_id", "")
                logger.info("  ✅ %s", result["message"])
                logger.info("  📍 %s", result.get("url", "")[:120])
            else:
                result["message"] = monitor_result.get("message", "모니터링 실패")
                result["stage"] = monitor_result.get("stage", "monitor_fail")
                logger.warning("  ⚠️ %s", result["message"])

            return result

        finally:
            # 정리
            try:
                loop.run_until_complete(hijack.close())
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass

    except ImportError as e:
        result["message"] = f"❌ Import 오류: {e}"
        logger.error(result["message"])
        return result
    except Exception as e:
        result["message"] = f"❌ 하이브리드 새로고침 오류: {e}"
        result["stage"] = "error"
        logger.error(result["message"])
        import traceback
        traceback.print_exc()
        return result


def hybrid_book(cfg: dict, stop_event: Optional[threading.Event] = None) -> dict:
    """
    하이브리드 새로고침 + 매크로 체인.

    1. hybrid_refresh_bot() 실행 → reserve 페이지 도착
    2. macro_bot() 실행 (캡차 + 좌석 + 결제)

    Args:
        cfg: 설정 딕셔너리
        stop_event: 중지 신호 이벤트

    Returns:
        {"success": bool, "stage": str, "message": str}
    """
    logger.info("=" * 50)
    logger.info("  🎯 하이브리드 예매 시작 (새로고침 + 매크로)")
    logger.info("=" * 50)

    # 1단계: 하이브리드 새로고침
    refresh_result = hybrid_refresh_bot(cfg, stop_event=stop_event)
    if not refresh_result.get("success"):
        logger.warning("  ⚠️ 하이브리드 새로고침 실패: %s",
                       refresh_result.get("message", ""))
        return {
            "success": False,
            "stage": "hybrid_refresh_failed",
            "message": refresh_result.get("message", "새로고침 실패"),
        }

    logger.info("  ✅ 하이브리드 새로고침 완료 → 매크로 체인 시작")

    # 2단계: 매크로 봇 (캡차 + 좌석 + 결제)
    try:
        from .standalone import macro_bot
        macro_result = macro_bot(cfg, stop_event=stop_event)
        # macro_bot()은 자체적으로 CDP hijack을 처리하므로
        # 여기서는 결과만 반환
        return macro_result
    except Exception as e:
        logger.error("  ❌ 매크로 봇 체인 오류: %s", e)
        return {
            "success": False,
            "stage": "macro_chain_error",
            "message": f"매크로 체인 실패: {e}",
        }
