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


# ── 구단 Product ID 사전 ─────────────────────────────────────────
# 티켓링크에서 각 구단(팀)의 고정 productId
TEAM_PRODUCT_IDS = {
    "LG 트윈스": "61881",
    "한화 이글스": "62162",
    "삼성 라이온즈": "62111",
    "KT 위즈": "61322",
    "KIA 타이거즈": "62036",
    "두산 베어스": "61885",
    "SSG 랜더스": "62109",
    "NC 다이노스": "61884",
    "롯데 자이언츠": "61882",
    "키움 히어로즈": "62042",
}

# 역방향: productId → 팀명
PRODUCT_ID_TO_TEAM = {v: k for k, v in TEAM_PRODUCT_IDS.items()}


# ── 경기 데이터 추출 스크립트 ─────────────────────────────────────
# CDP Runtime.evaluate 로 페이지에서 경기 정보 읽기
FETCH_GAMES_JS = r"""(() => {
    const games = [];

    // 전략 1: data-* 속성 찾기
    const els = document.querySelectorAll('[data-schedule-id], [data-schedule], [data-game-id], [data-product-id]');
    for (const el of els) {
        const sid = el.dataset.scheduleId || el.dataset.schedule || el.dataset.gameId || '';
        const pid = el.dataset.productId || '';
        if (sid) {
            games.push({
                scheduleId: sid,
                productId: pid,
                text: (el.textContent || '').trim().substring(0, 100),
            });
        }
    }

    // 전략 2: window.__INITIAL_STATE__ or __NEXT_DATA__
    try {
        const state = window.__INITIAL_STATE__ || window.__DATA__ || window.__NEXT_DATA__;
        if (state) {
            games.push({_strategy: 'window.__INITIAL_STATE__', _data: JSON.stringify(state).substring(0, 500)});
        }
    } catch (e) {}

    // 전략 3: script 태그에서 JSON 찾기
    const scripts = document.querySelectorAll('script[type="application/json"], script#__NEXT_DATA__, script.__NEXT_DATA__');
    for (const s of scripts) {
        try {
            const data = JSON.parse(s.textContent);
            games.push({_strategy: 'script#' + s.id, _data: JSON.stringify(data).substring(0, 500)});
        } catch (e) {}
    }

    // 전략 4: 모든 링크에서 /reserve/product/ 패턴 찾기
    const links = document.querySelectorAll('a[href*="reserve/product"]');
    for (const a of links) {
        const m = a.href.match(/\/reserve\/product\/(\d+)\?scheduleId=(\d+)/);
        if (m) {
            games.push({
                scheduleId: m[2],
                productId: m[1],
                text: (a.textContent || '').trim().substring(0, 80),
                href: a.href.substring(0, 120),
            });
        }
    }

    return games;
})();
"""


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
    const m = document.querySelector('meta[name="tl-hijack"]');
    const active = m !== null;
    let pid = null, sid = null;
    if (active && m.content) {
        const parts = m.content.split('/');
        pid = parts[0] || null;
        sid = parts[1] || null;
    }
    return {active, pid, sid};
})();
"""


class CdpHijack:
    """Chrome CDP 연결 → 폼 하이재킹 스크립트 주입"""

    def __init__(self, cdp_port: int = 9222):
        self.cdp_port = cdp_port
        self.ws: Optional["websocket"] = None  # type: ignore
        self._script_ids: list[str] = []
        self._last_pid: Optional[str] = None
        self._last_sid: Optional[str] = None

    # ── 연결 ──────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """로컬 Chrome의 CDP WebSocket에 연결"""
        ws_url = self._find_page_ws_url()
        if not ws_url:
            return False

        try:
            import websockets
        except ImportError:
            raise ImportError(
                "websockets 라이브러리가 필요합니다. 설치: pip install websockets"
            )
        self.ws = await websockets.connect(ws_url, max_size=None)
        logger.info("🔗 CDP 연결 완료 (%s)", ws_url[:60])
        return True

    def _find_page_ws_url(self) -> Optional[str]:
        """Chrome의 /json 에서 page WebSocket URL 탐색"""
        # /json → page 타겟 우선 (개별 페이지 WS 필요: Page/Runtime 도메인)
        for path in ("/json", "/json/version"):
            try:
                resp = urllib.request.urlopen(
                    f"http://127.0.0.1:{self.cdp_port}{path}", timeout=5
                )
                data = json.loads(resp.read().decode())
                if path == "/json":
                    # /json returns a list of targets
                    for t in data:
                        if t.get("type") == "page":
                            ws = t.get("webSocketDebuggerUrl")
                            if ws:
                                return ws
                else:
                    # /json/version → browser-level WS (fallback)
                    ws = data.get("webSocketDebuggerUrl")
                    if ws:
                        logger.info(
                            "  ℹ️ 페이지 타겟 없음, 브라우저 레벨 WS 사용 "
                            "(Page 명령 제한됨)"
                        )
                        return ws
            except Exception:
                continue
        return None

    # ── 스크립트 주입 ─────────────────────────────────────────────

    async def inject(self, product_id: str, schedule_id: str) -> bool:
        """폼 하이재킹 스크립트 주입

        runImmediately=True 로 현재 페이지에 즉시 적용.
        Page.addScriptToEvaluateOnNewDocument 로 새 문서에도 자동 적용.

        Args:
            product_id: 구단 productId (예: "62162")
            schedule_id: 경기 scheduleId (예: "1492740043")

        Returns:
            True if 등록 성공
        """
        if not self.ws or not product_id or not schedule_id:
            return False

        # 값이 내장된 스크립트 생성
        hijack_js = f"""(() => {{
    const PID = {json.dumps(product_id)};
    const SID = {json.dumps(schedule_id)};
    const OS = HTMLFormElement.prototype.submit;
    HTMLFormElement.prototype.submit = function () {{
        try {{
            const pi = this.querySelector('input[name="productId"]');
            const si = this.querySelector('input[name="scheduleId"]');
            if (pi) pi.value = PID;
            if (si) si.value = SID;
        }} catch (e) {{}}
        return OS.apply(this, arguments);
    }};
    const OO = window.open;
    window.open = function (u, t, f) {{
        if (u && u.includes('/reserve/product/'))
            u = `/reserve/product/${{PID}}?scheduleId=${{SID}}`;
        return OO.call(window, u, t, f);
    }};
    // 검증용 DOM 마커
    const m = document.createElement('meta');
    m.name = 'tl-hijack';
    m.content = PID + '/' + SID;
    document.head?.appendChild(m);
}})();
"""

        # runImmediately=true: 현재 페이지 즉시 적용 + 새 문서에도 자동 적용
        result = await self._send_with_result(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": hijack_js, "runImmediately": True},
        )
        if result and "identifier" in result:
            self._script_ids.append(result["identifier"])
            self._last_pid = product_id
            self._last_sid = schedule_id
            logger.info(
                "✅ 폼 하이재킹 활성 (product=%s, schedule=%s)",
                product_id, schedule_id,
            )
            return True

        # fallback: runImmediately 없이 등록
        result = await self._send_with_result(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": hijack_js},
        )
        if result and "identifier" in result:
            self._script_ids.append(result["identifier"])
            self._last_pid = product_id
            self._last_sid = schedule_id
            logger.info(
                "✅ 폼 하이재킹 등록 (다음 페이지 로드 시 활성화)")
            return True

        logger.error(
            "❌ 스크립트 등록 실패 — Chrome CDP 포트 %d 확인",
            self.cdp_port,
        )
        return False

    # ── 재주입 (F5/내비게이션 후) ─────────────────────────────────

    async def re_inject(self) -> bool:
        """마지막으로 inject 한 값으로 다시 주입 (F5 후 호출)"""
        if not self._last_pid or not self._last_sid:
            return False
        return await self.inject(self._last_pid, self._last_sid)

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

    # ── 예매 페이지 URL에서 경기코드 추출 ──────────────────────────

    async def extract_ids_from_current_page(self) -> dict:
        """현재 페이지 URL/폼에서 productId + scheduleId 추출

        현재 연결된 페이지에서 추출 후, /reserve/product/ 가 없으면
        모든 CDP 페이지 타겟을 스캔해서 예매 팝업을 찾습니다.

        Returns:
            {"productId": "62162", "scheduleId": "1492740043", "url": "...",
             "source": "current_page"|"scanned_popup"}
            또는 실패 시 빈 dict
        """
        result = {}

        # 1. 현재 연결된 페이지에서 추출
        if self.ws:
            result = await self._extract_ids_from_ws()
            pid = result.get("productId_from_url") or result.get("productId_from_form") or ""
            sid = result.get("scheduleId_from_url") or result.get("scheduleId_from_form") or ""
            url = result.get("url", "")
            if "/reserve/product/" in url and pid and sid:
                result["source"] = "current_page"
                return self._normalize_ids(result)

        # 2. 모든 CDP 타겟 스캔 (HTTP /json) → 예매 팝업 찾기
        logger.info("  🔍 현재 페이지에 예매 URL 없음 — 모든 탭/팝업 스캔...")
        popup = self._find_reserve_page_target()
        if popup:
            url = popup.get("url", "")
            pid = self._parse_product_id(url)
            sid = self._parse_schedule_id(url)

            # URL에 productId가 없으면 → 팝업에 WS 연결해서 DOM에서 추출
            if not pid and popup.get("webSocketDebuggerUrl"):
                logger.info("  🔍 팝업 DOM에서 productId 추출 시도...")
                try:
                    popup_data = await self._extract_ids_from_popup_ws(
                        popup["webSocketDebuggerUrl"]
                    )
                    if popup_data:
                        pid = (pid or popup_data.get("productId_from_form")
                               or popup_data.get("productId_from_url") or "")
                        sid = (sid or popup_data.get("scheduleId_from_form")
                               or popup_data.get("scheduleId_from_url") or "")
                        if popup_data.get("url"):
                            url = popup_data["url"]
                        if pid:
                            logger.info("  ✅ 팝업 DOM에서 productId=%s 발견", pid)
                except Exception as e:
                    logger.debug("  ⚠️ 팝업 WS 추출 실패: %s", e)

            if pid or sid:
                logger.info("  ✅ 예매 팝업 발견: %s", url[:80])
                return self._normalize_ids({
                    "url": url,
                    "productId_from_url": pid or "",
                    "scheduleId_from_url": sid or "",
                    "source": "scanned_popup",
                })

        # 3. 현재 페이지 결과라도 반환
        if result:
            result["source"] = "current_page"
            return self._normalize_ids(result)

        return {}

    def _find_reserve_page_target(self) -> Optional[dict]:
        """CDP /json 에서 예매 관련 URL을 가진 페이지 타겟 찾기"""
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{self.cdp_port}/json", timeout=5
            )
            targets = json.loads(resp.read().decode())
            # 우선순위: /reserve/product/ > /reserve/ > scheduleId= > ticketlink reserve
            patterns = [
                "/reserve/product/",
                "/reserve/plan/",
                "/reserve/gate/",
                "/reserve/",
            ]
            for pattern in patterns:
                for t in targets:
                    if t.get("type") == "page":
                        url = t.get("url", "")
                        if pattern in url:
                            return t
            # fallback: scheduleId 쿼리파라미터
            for t in targets:
                if t.get("type") == "page":
                    url = t.get("url", "")
                    if "ticketlink" in url and "scheduleId=" in url:
                        return t
        except Exception:
            pass
        return None

    @staticmethod
    def _parse_product_id(url: str) -> str:
        """URL에서 productId 추출"""
        import re
        m = re.search(r"/reserve/product/(\d+)", url)
        return m.group(1) if m else ""

    @staticmethod
    def _parse_schedule_id(url: str) -> str:
        """URL에서 scheduleId 추출 (query param + path pattern)"""
        import re
        # query param: ?scheduleId=XXX
        m = re.search(r"[?&]scheduleId=(\d+)", url)
        if m:
            return m.group(1)
        # path pattern: /reserve/plan/schedule/XXXXX
        m = re.search(r"/reserve/plan/schedule/(\d+)", url)
        if m:
            return m.group(1)
        return ""

    async def _extract_ids_from_popup_ws(self, ws_url: str) -> dict:
        """팝업 WebSocket에 임시 연결 → DOM에서 productId/scheduleId 추출

        /reserve/plan/schedule/XXX 형식 URL은 productId가 없으므로
        팝업 페이지의 hidden form input에서 직접 읽어야 함.
        """
        import asyncio
        import websockets
        import json as _json
        try:
            async with websockets.connect(
                ws_url, max_size=2 ** 20, open_timeout=5,
            ) as tmp_ws:
                cmd = _json.dumps({
                    "id": 1, "method": "Runtime.evaluate",
                    "params": {
                        "expression": """
                            (() => {
                                const res = {};
                                const pi = document.querySelector('input[name="productId"]');
                                if (pi) res.productId_from_form = pi.value;
                                const si = document.querySelector('input[name="scheduleId"]');
                                if (si) res.scheduleId_from_form = si.value;
                                res.url = window.location.href;
                                const pidMatch = window.location.href.match(/\\/reserve\\/product\\/(\\d+)/);
                                if (pidMatch) res.productId_from_url = pidMatch[1];
                                return res;
                            })()
                        """,
                        "returnByValue": True,
                    },
                })
                await tmp_ws.send(cmd)
                resp = await asyncio.wait_for(tmp_ws.recv(), timeout=5)
                data = _json.loads(resp)
                return data.get("result", {}).get("value", {})
        except Exception:
            return {}

    @staticmethod
    def _normalize_ids(raw: dict) -> dict:
        """원시 추출 결과를 정규화된 dict로 변환"""
        pid = (raw.get("productId_from_url") or raw.get("productId_from_form")
               or raw.get("productId_from_path") or "")
        sid = (raw.get("scheduleId_from_url") or raw.get("scheduleId_from_form") or "")
        return {
            "productId": pid,
            "scheduleId": sid,
            "url": raw.get("url", ""),
            "source": raw.get("source", "unknown"),
        }

    async def _extract_ids_from_ws(self) -> dict:
        """현재 WebSocket 페이지에서 URL/폼 데이터 추출"""
        result = await self._send_with_result("Runtime.evaluate", {
            "expression": r"""(() => {
                const res = {};
                const url = window.location.href;
                res.url = url;

                const sidMatch = url.match(/[?&]scheduleId=(\d+)/);
                if (sidMatch) res.scheduleId_from_url = sidMatch[1];

                const pidMatch = url.match(/\/reserve\/product\/(\d+)/);
                if (pidMatch) res.productId_from_url = pidMatch[1];

                const pi = document.querySelector('input[name="productId"]');
                if (pi) res.productId_from_form = pi.value;

                const si = document.querySelector('input[name="scheduleId"]');
                if (si) res.scheduleId_from_form = si.value;

                try {
                    const path = window.location.pathname;
                    const pathPid = path.match(/\/reserve\/product\/(\d+)/);
                    if (pathPid) res.productId_from_path = pathPid[1];
                } catch(e) {}

                const m = document.querySelector('meta[name="build-timestamp"]');
                if (m) res.build_timestamp = m.content;

                return res;
            })()
            """,
            "returnByValue": True,
        })
        if result and "result" in result:
            return result["result"].get("value", {})
        return {}

    # ── 경기 목록 스크래핑 (deprecated — 안티봇 차단으로 미작동) ─────

    async def navigate(self, url: str, timeout: float = 15.0) -> bool:
        """CDP로 페이지 이동 + 로딩 대기"""
        if not self.ws:
            return False
        # Page.navigate
        await self._send("Page.navigate", {"url": url})
        # loadEventFired 기다리기
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            result = await self._send_with_result("Runtime.evaluate", {
                "expression": "document.readyState",
                "returnByValue": True,
            })
            state = ""
            if result and "result" in result:
                state = result["result"].get("value", "")
            if state == "complete":
                return True
            await asyncio.sleep(0.5)
        return False

    async def fetch_games(self, product_id: str) -> list[dict]:
        """⚠️ [DEPRECATED] 특정 구단의 경기 목록을 CDP로 스크래핑

        Ticketlink의 API 파라미터 난독화(안티봇)로 인해 작동하지 않습니다.
        대신 extract_ids_from_current_page()를 사용하세요.

        Args:
            product_id: 구단 productId (예: "62162" = 한화)

        Returns:
            [{"scheduleId": ..., "productId": ..., "text": ..., ...}]
        """
        if not self.ws:
            logger.warning("  ⚠️ CDP 미연결 — 먼저 connect() 호출 필요")
            return []

        # 팀 페이지로 이동
        team_url = f"https://www.ticketlink.co.kr/sports/137/{product_id}"
        logger.info("  📡 경기 목록 페이지 이동: %s", team_url)
        ok = await self.navigate(team_url, timeout=20.0)
        if not ok:
            logger.warning("  ⚠️ 페이지 로딩 실패 또는 타임아웃")
            return []

        # 추가 대기 (SPA 렌더링)
        import asyncio
        await asyncio.sleep(3)

        # 경기 데이터 추출
        result = await self._send_with_result("Runtime.evaluate", {
            "expression": FETCH_GAMES_JS,
            "returnByValue": True,
        })
        games = []
        if result and "result" in result:
            raw = result["result"].get("value", [])
            for g in raw:
                if g.get("scheduleId") or g.get("_strategy"):
                    games.append(g)

        if games:
            # data-* 속성이나 URL에서 찾은 실제 경기만 필터링
            real_games = [g for g in games if g.get("scheduleId") and not g.get("_strategy")]
            debug_info = [g for g in games if g.get("_strategy")]
            if real_games:
                logger.info("  🎯 %d개 경기 발견", len(real_games))
                for g in real_games:
                    tid = g.get("text", "")[:40]
                    logger.info("    ⚾ schedule=%s product=%s %s",
                                g["scheduleId"], g.get("productId", "?"), tid)
            else:
                logger.info("  ℹ️ 경기 직접발견 없음, 디버그: %s", debug_info[:3])
        else:
            logger.warning("  ⚠️ 경기 정보를 찾을 수 없음")

        return games

    # ── CDP Network Capture (새 API) ─────────────────────────────

    async def extract_games_via_network(self, timeout: float = 10.0) -> list[dict]:
        """CDP Network capture로 mapi/sports/schedules API 응답에서 경기 목록 추출

        Network.enable → Network.responseReceived 이벤트 대기 →
        Network.getResponseBody 로 응답 본문 수신 → JSON 파싱

        Args:
            timeout: API 응답 대기 최대 시간 (초)

        Returns:
            [{"productId": ..., "scheduleId": ..., "matchDate": ...,
              "matchTime": ..., "homeTeamName": ..., "awayTeamName": ...,
              "matchStatus": ...}, ...]
        """
        if not self.ws:
            logger.warning("  ⚠️ CDP 미연결 — 먼저 connect() 호출 필요")
            return []

        # 1. Network 활성화
        await self._send("Network.enable", {})
        logger.info("  📡 Network capture 활성화 — mapi/sports/schedules 응답 대기 중...")

        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout
        pending_request_ids: set[str] = set()

        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            try:
                raw = await asyncio.wait_for(
                    self.ws.recv(), timeout=max(0.1, remaining)
                )
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            method = msg.get("method")

            # ── 응답 헤더 수신 ──
            if method == "Network.responseReceived":
                params = msg.get("params", {})
                response = params.get("response", {})
                url = response.get("url", "")

                if "mapi/sports/schedules" in url:
                    request_id = params.get("requestId")
                    if request_id:
                        logger.info(
                            "  ✅ API 응답 발견 (headers): %s",
                            url[:80],
                        )
                        # loadingFinished 대기 목록에 등록
                        pending_request_ids.add(request_id)

                        # 바로 시도 (성공 시 빠른 반환)
                        await asyncio.sleep(0.3)
                        body = await self._get_response_body(request_id)
                        if body:
                            games = self._parse_schedules_response(body)
                            if games:
                                return games

            # ── 본문 수신 완료 ──
            elif method == "Network.loadingFinished":
                req_id = msg.get("params", {}).get("requestId")
                if req_id in pending_request_ids:
                    pending_request_ids.discard(req_id)
                    logger.info("  ✅ API 응답 본문 수신 완료")
                    body = await self._get_response_body(req_id)
                    if body:
                        games = self._parse_schedules_response(body)
                        if games:
                            return games

        logger.warning("  ⏰ API 응답 대기 타임아웃 (%ds)", timeout)
        return []

    async def _get_response_body(self, request_id: str) -> Optional[str]:
        """Network.getResponseBody로 응답 본문 가져오기"""
        result = await self._send_with_result("Network.getResponseBody", {
            "requestId": request_id,
        })
        if result:
            body = result.get("body", "")
            if result.get("base64Encoded"):
                import base64
                body = base64.b64decode(body).decode("utf-8", errors="replace")
            return body
        return None

    @staticmethod
    def _parse_schedules_response(body: str) -> list[dict]:
        """mapi/sports/schedules API JSON 응답 파싱

        다양한 응답 구조 지원:
          - {"data": [...]}
          - {"body": {"data": [...]}}
          - 직접 리스트 [...]
        """
        import json as _json
        try:
            data = _json.loads(body)
        except _json.JSONDecodeError:
            logger.warning("  ⚠️ API 응답 JSON 파싱 실패")
            return []

        # 응답 구조별 games 배열 찾기
        games_raw: list = []

        if isinstance(data, dict):
            # case 1: {"data": [...]}
            games_raw = (
                data.get("data")
                or data.get("result")
                or data.get("items")
                or data.get("list")
                or []
            )
            # case 2: {"body": {"data": [...]}} 중첩 구조
            if not games_raw:
                for key in ("body", "response", "result"):
                    val = data.get(key)
                    if isinstance(val, dict):
                        games_raw = (
                            val.get("data")
                            or val.get("items")
                            or val.get("list")
                            or val.get("result")
                            or []
                        )
                        if games_raw:
                            break
        elif isinstance(data, list):
            # case 3: 직접 리스트
            games_raw = data

        if not games_raw:
            preview = str(data)[:300]
            logger.info(
                "  ℹ️ 인식 가능한 경기 데이터 없음, 응답 구조: %s",
                preview,
            )
            return []

        games = []
        for g in games_raw:
            if not isinstance(g, dict):
                continue
            # 필드명 변환 (camelCase / snake_case 둘 다 지원)
            game = {
                "productId": str(
                    g.get("productId")
                    or g.get("product_id")
                    or g.get("productID")
                    or ""
                ),
                "scheduleId": str(
                    g.get("scheduleId")
                    or g.get("schedule_id")
                    or g.get("scheduleID")
                    or ""
                ),
                "matchDate": str(
                    g.get("matchDate")
                    or g.get("match_date")
                    or g.get("gameDate")
                    or ""
                ),
                "matchTime": str(
                    g.get("matchTime")
                    or g.get("match_time")
                    or g.get("gameTime")
                    or ""
                ),
                "homeTeamName": str(
                    g.get("homeTeamName")
                    or g.get("home_team_name")
                    or g.get("homeTeam")
                    or ""
                ),
                "awayTeamName": str(
                    g.get("awayTeamName")
                    or g.get("away_team_name")
                    or g.get("awayTeam")
                    or ""
                ),
                "matchStatus": str(
                    g.get("matchStatus")
                    or g.get("match_status")
                    or g.get("status")
                    or ""
                ),
            }
            if game["productId"] or game["scheduleId"]:
                games.append(game)

        if games:
            logger.info(
                "  🎯 %d개 경기 발견 (Network capture)", len(games)
            )
            for g in games:
                logger.info(
                    "    ⚾ %s vs %s | %s %s | product=%s schedule=%s (%s)",
                    g["homeTeamName"],
                    g["awayTeamName"],
                    g["matchDate"],
                    g["matchTime"],
                    g["productId"],
                    g["scheduleId"],
                    g["matchStatus"],
                )
        else:
            logger.warning(
                "  ⚠️ API 응답에서 productId/scheduleId 찾을 수 없음"
            )

        return games

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

    async def _send_with_result(self, method: str, params: dict, timeout: float = 30.0) -> Optional[dict]:
        """CDP 명령 전송 + 응답 대기 (타임아웃 적용)

        Args:
            timeout: 응답 대기 최대 시간(초). 기본 30초.
        """
        if not self.ws:
            return None
        CdpHijack._msg_id += 1
        msg_id = CdpHijack._msg_id
        msg = json.dumps({"id": msg_id, "method": method, "params": params})
        await self.ws.send(msg)
        # 응답 수신 (메시지 ID 매칭) — 타임아웃 적용
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=max(0.1, remaining))
            except asyncio.TimeoutError:
                continue
            try:
                resp = json.loads(raw)
                if resp.get("id") == msg_id:
                    return resp.get("result")
            except json.JSONDecodeError:
                continue
        logger.warning("  ⏰ CDP 명령 '%s' 응답 타임아웃 (%ds)", method, timeout)
        return None


# ── 동기 래퍼 (독립형 호출용) ──────────────────────────────────


def fetch_games_via_network(
    product_id: str = "", cdp_port: int = 9222
) -> list[dict]:
    """CDP Network capture로 경기 목록 가져오기 (동기 래퍼)

    새 이벤트 루프에서 CdpHijack.extract_games_via_network() 실행.

    Args:
        product_id: (unused in capture, kept for API compat) 구단 productId
        cdp_port: Chrome CDP 포트 (--remote-debugging-port)

    Returns:
        경기 목록 [{"productId": ..., "scheduleId": ..., ...}]
        또는 실패 시 빈 리스트
    """
    try:
        hijack = CdpHijack(cdp_port=cdp_port)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            ok = loop.run_until_complete(hijack.connect())
            if not ok:
                logger.warning("  ⚠️ CDP 연결 실패 (포트 %d)", cdp_port)
                return []

            games = loop.run_until_complete(
                hijack.extract_games_via_network()
            )
            loop.run_until_complete(hijack.close())
            return games
        except Exception:
            loop.close()
            raise
    except Exception as e:
        logger.error("  ❌ Network capture 오류: %s", e)
        return []
