"""
CDP 폼 하이재킹 — Chrome DevTools Protocol로 productId/scheduleId 강제 변환

원리:
  HTMLFormElement.prototype.submit()을 오버라이드해서 폼 제출 직전에
  productId와 scheduleId 값을 사용자가 원하는 경기 코드로 변경.
  window.open도 가로채서 URL 자체를 조작.

사용법:
  hijack = CdpHijack(port=9222)
  if await hijack.connect():
      await hijack.inject(product_id="62162", schedule_id="1492740043")
      # ... 매크로 실행 ...
      hijack.close()
"""
import asyncio
import json
import logging
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)


# ── 하이재킹 스크립트 ─────────────────────────────────────────────
# Page.addScriptToEvaluateOnNewDocument 로 주입되어 모든 페이지 로드 시 실행됨
HIJACK_SCRIPT_JS = r"""(() => {
    const PID = window.__TL_PRODUCT_ID__;
    const SID = window.__TL_SCHEDULE_ID__;
    if (!PID || !SID) return;

    // 1. 폼 submit 가로채기
    const originalSubmit = HTMLFormElement.prototype.submit;
    HTMLFormElement.prototype.submit = function () {
        try {
            const prodInput = this.querySelector('input[name="productId"]');
            const schedInput = this.querySelector('input[name="scheduleId"]');
            if (prodInput) prodInput.value = PID;
            if (schedInput) schedInput.value = SID;
        } catch (e) { /* ignore */ }
        return originalSubmit.apply(this, arguments);
    };

    // 2. window.open 가로채기 (새 창 예매 URL)
    const originalOpen = window.open;
    window.open = function (url, target, features) {
        if (url && url.includes('/reserve/product/')) {
            url = `/reserve/product/${PID}?scheduleId=${SID}`;
        }
        return originalOpen.call(window, url, target, features);
    };
})();
"""


# ── 검증 스크립트 ─────────────────────────────────────────────────
VERIFY_SCRIPT_JS = """(() => {
    const pid = window.__TL_PRODUCT_ID__;
    const sid = window.__TL_SCHEDULE_ID__;
    const isHijacked = typeof HTMLFormElement.prototype.submit === 'function'
        && HTMLFormElement.prototype.submit.toString().includes('TARGET');
    return {
        active: Boolean(pid && sid),
        pid: pid || null,
        sid: sid || null,
        submitHijacked: isHijacked
    };
})();
"""


class CdpHijack:
    """Chrome CDP 연결 → 폼 하이재킹 스크립트 주입"""

    def __init__(self, cdp_port: int = 9222):
        self.cdp_port = cdp_port
        self.ws: Optional["websocket"] = None  # type: ignore
        self._script_ids: list[str] = []

    # ── 연결 ──────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """로컬 Chrome의 CDP WebSocket에 연결"""
        ws_url = self._find_page_ws_url()
        if not ws_url:
            return False

        import websockets
        self.ws = await websockets.connect(ws_url, max_size=None)
        logger.info("🔗 CDP 연결 완료 (%s)", ws_url[:60])
        return True

    def _find_page_ws_url(self) -> Optional[str]:
        """Chrome의 /json/version 또는 /json 에서 page WebSocket URL 탐색"""
        for path in ("/json/version", "/json"):
            try:
                resp = urllib.request.urlopen(
                    f"http://127.0.0.1:{self.cdp_port}{path}", timeout=5
                )
                data = json.loads(resp.read().decode())
                if path == "/json/version":
                    ws = data.get("webSocketDebuggerUrl")
                    if ws:
                        return ws
                else:
                    # /json → page 타겟 찾기
                    for t in data:
                        if t.get("type") == "page":
                            return t["webSocketDebuggerUrl"]
            except Exception:
                continue
        return None

    # ── 스크립트 주입 ─────────────────────────────────────────────

    async def inject(self, product_id: str, schedule_id: str) -> bool:
        """폼 하이재킹 스크립트 주입 (navigations 유지)"""
        if not self.ws or not product_id or not schedule_id:
            return False

        # 1) Runtime.evaluate → 전역 변수 설정
        globals_js = json.dumps({
            "__TL_PRODUCT_ID__": product_id,
            "__TL_SCHEDULE_ID__": schedule_id,
        })
        ok = await self._send("Runtime.evaluate", {
            "expression": f"(() => {{{globals_js[1:-1]}}})()",
            "returnByValue": False,
        })
        if not ok:
            return False

        # 2) 현재 페이지에 1회 실행
        ok = await self._send("Runtime.evaluate", {
            "expression": HIJACK_SCRIPT_JS,
            "returnByValue": False,
        })
        if not ok:
            return False

        # 3) 새로고침/내비게이션 후에도 유지
        result = await self._send_with_result("Page.addScriptToEvaluateOnNewDocument", {
            "source": HIJACK_SCRIPT_JS,
        })
        if result and "identifier" in result:
            self._script_ids.append(result["identifier"])
            logger.info(
                "✅ 폼 하이재킹 주입 완료  (product=%s, schedule=%s)",
                product_id, schedule_id,
            )
            return True

        logger.error("❌ Page.addScriptToEvaluateOnNewDocument 실패")
        return False

    # ── 검증 ──────────────────────────────────────────────────────

    async def verify(self) -> dict:
        """하이재킹 활성 상태 확인"""
        result = await self._send_with_result("Runtime.evaluate", {
            "expression": VERIFY_SCRIPT_JS,
            "returnByValue": True,
        })
        if result and "result" in result:
            return result["result"].get("value", {})
        return {"active": False, "error": "verify failed"}

    # ── 정리 ──────────────────────────────────────────────────────

    async def close(self):
        """CDP WebSocket 연결 종료"""
        if self._script_ids:
            for sid in self._script_ids:
                try:
                    await self._send("Page.removeScriptToEvaluateOnNewDocument", {
                        "identifier": sid,
                    })
                except Exception:
                    pass
            self._script_ids.clear()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
            logger.info("🔌 CDP 연결 종료")

    # ── 내부 CDP 메시지 ───────────────────────────────────────────

    _msg_id: int = 0

    async def _send(self, method: str, params: dict) -> bool:
        """CDP 명령 전송 (응답 대기 안 함)"""
        if not self.ws:
            return False
        CdpHijack._msg_id += 1
        msg = json.dumps({"id": CdpHijack._msg_id, "method": method, "params": params})
        await self.ws.send(msg)
        return True

    async def _send_with_result(self, method: str, params: dict) -> Optional[dict]:
        """CDP 명령 전송 + 응답 대기"""
        if not self.ws:
            return None
        CdpHijack._msg_id += 1
        msg_id = CdpHijack._msg_id
        msg = json.dumps({"id": msg_id, "method": method, "params": params})
        await self.ws.send(msg)
        # 응답 수신 (메시지 ID 매칭)
        while True:
            raw = await self.ws.recv()
            try:
                resp = json.loads(raw)
                if resp.get("id") == msg_id:
                    return resp.get("result")
            except json.JSONDecodeError:
                continue
