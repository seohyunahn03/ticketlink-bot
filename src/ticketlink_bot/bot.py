"""
🎫 티켓링크봇 — Chrome CDP 직접 연결 Bot 클래스

CDP WebSocket 직접 연결로 Chrome을 제어합니다.
Playwright/Selenium 사용 안 함 → 탐지 제로.
"""
import asyncio
import json
import os
import subprocess
import time
import urllib.request
from typing import Optional

import websockets


def _chrome_launch_help() -> str:
    """OS별 Chrome CDP 실행 명령어 반환"""
    import sys, shutil
    system = sys.platform
    chrome_paths = {
        "darwin": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "win32": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "linux": "/usr/bin/google-chrome",
    }
    exe = chrome_paths.get(system, "google-chrome")
    alt = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium") or ""
    help_text = f"  {exe} --remote-debugging-port=9222 --user-data-dir=%USERPROFILE%\\.config\\chrome-cdp" if system == "win32" else \
                f"  {exe} --remote-debugging-port=9222 --user-data-dir=~/.config/chrome-cdp"
    if alt and alt != exe:
        help_text += f"\n  또는: {alt} --remote-debugging-port=9222"
    return help_text


def _find_chrome() -> str | None:
    """OS별 Chrome 실행 파일 경로 탐색"""
    import sys, shutil
    system = sys.platform
    candidates = []
    if system == "win32":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
    elif system == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    else:  # Linux
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]
    # PATH에서도 검색
    for name in ("chrome", "google-chrome", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            candidates.append(p)
    # 존재하는 첫 번째 경로 반환
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def launch_chrome(
    port: int = 9222,
    user_data_dir: str | None = None,
    timeout: float = 15.0,
) -> str | None:
    """
    Chrome을 CDP 모드로 자동 실행하고 WebSocket URL 반환.

    Args:
        port: CDP 포트 (기본 9222)
        user_data_dir: Chrome 사용자 데이터 디렉토리 (기본: ~/.config/chrome-cdp)
        timeout: CDP 준비 대기 최대 시간 (초)

    Returns:
        WebSocket URL (성공 시) or None (실패 시)
    """
    import subprocess, sys, time, urllib.request

    # 1. Chrome 실행 파일 찾기
    exe = _find_chrome()
    if not exe:
        return None

    # 2. 사용자 데이터 디렉토리
    if user_data_dir is None:
        home = os.path.expanduser("~")
        if sys.platform == "win32":
            user_data_dir = os.path.join(home, ".config", "chrome-cdp")
        else:
            user_data_dir = os.path.join(home, ".config", "chrome-cdp")
    os.makedirs(user_data_dir, exist_ok=True)

    # 3. Chrome 실행 (이미 CDP 포트로 실행 중이면 새 창만 띄움)
    import subprocess
    try:
        subprocess.Popen(
            [exe, f"--remote-debugging-port={port}", f"--user-data-dir={user_data_dir}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None

    # 4. CDP 준비 대기 (최대 timeout 초)
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urllib.request.urlopen(
                f"http://localhost:{port}/json/version", timeout=2
            )
            data = json.loads(resp.read())
            return data["webSocketDebuggerUrl"]
        except Exception:
            time.sleep(0.5)
    return None


def discover_cdp_url(ports: list[int] | None = None) -> Optional[str]:
    """
    로컬 Chrome CDP WebSocket URL 자동 탐지.
    9222 → 9223 순서로 시도.
    """
    if ports is None:
        ports = [9222, 9223]
    for port in ports:
        try:
            resp = urllib.request.urlopen(
                f"http://localhost:{port}/json/version", timeout=3
            )
            data = json.loads(resp.read())
            return data["webSocketDebuggerUrl"]
        except Exception:
            continue
    return None


class Bot:
    """Chrome CDP WebSocket 봇 — 탐지 제로 CDP 직접 연결"""

    def __init__(self):
        self.ws = None
        self._n = 0
        self.sid = None  # Target sessionId
        self._cdp_url = None
        self._stealth_applied = False

    async def apply_stealth(self) -> None:
        """봇 탐지 우회: 모든 알려진 탐지 벡터 차단 (OS 자동 감지)"""
        if self._stealth_applied:
            return
        if not self.sid:
            return

        import platform
        system = platform.system()

        # OS별 WebGL vendor/renderer
        if system == "Windows":
            webgl_vendor = "'Google Inc. (NVIDIA)'"
            webgl_renderer = "'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)'"
        elif system == "Linux":
            webgl_vendor = "'Intel'"
            webgl_renderer = "'Mesa DRI Intel(R) UHD Graphics (CML GT2)'"
        else:  # macOS
            webgl_vendor = "'Apple Inc.'" if platform.machine() == "arm64" else "'Intel Inc.'"
            webgl_renderer = "'Apple M-series GPU'" if platform.machine() == "arm64" else "'Intel(R) Iris(TM) Plus Graphics 655'"

        # OS별 User-Agent (Chrome 최신)
        if system == "Windows":
            user_agent = "'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'"
        elif system == "Linux":
            user_agent = "'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'"
        else:  # macOS
            mac_arch = "Intel Mac OS X 10_15_7" if platform.machine() != "arm64" else "Mac OS X 10_15_7"
            user_agent = f"'Mozilla/5.0 ({mac_arch}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'"

        source = r"""// === 종합 스텔스: 모든 알려진 봇 탐지 우회 ===


// 1. navigator.webdriver 제거
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true
});

// 2. chrome.runtime 정상화
if (window.chrome) {
    const _chrome = window.chrome;
    if (!_chrome.runtime) {
        Object.defineProperty(_chrome, 'runtime', {
            get: () => ({
                connect: () => {},
                sendMessage: () => {},
                onMessage: { addListener: () => {} },
                onConnect: { addListener: () => {} },
                id: 'nkeimhogjdpnpccoofpliimaahmaaome'
            }),
            configurable: true
        });
    }
    Object.defineProperty(_chrome, 'loadTimes', {
        get: () => function() { return {}; },
        configurable: true
    });
    Object.defineProperty(_chrome, 'csi', {
        get: () => function() { return {}; },
        configurable: true
    });
}

// 3. navigator.plugins 정상화 (5개 플러그인)
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
        { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        { name: 'Widevine Content Decryption Module', filename: 'widevinecdm', description: 'Enables Widevine licenses' },
        { name: 'Chromoting Viewer', filename: 'internal-remoting-viewer', description: '' }
    ],
    configurable: true
});

// 4. navigator.languages 정상화
Object.defineProperty(navigator, 'languages', {
    get: () => ['ko-KR', 'ko', 'en-US', 'en'],
    configurable: true
});

// 5. navigator.hardwareConcurrency
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 12,
    configurable: true
});

// 6. navigator.deviceMemory
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8,
    configurable: true
});

// 7. navigator.permissions.query 정상화
const originalQuery = navigator.permissions.query.bind(navigator.permissions);
navigator.permissions.query = (params) => {
    if (params.name === 'notifications' || params.name === 'clipboard-read' || params.name === 'clipboard-write') {
        return Promise.resolve({ state: 'prompt', onchange: null });
    }
    return originalQuery(params);
};

// 8. navigator.connection
Object.defineProperty(navigator, 'connection', {
    get: () => ({
        effectiveType: '4g',
        rtt: 50,
        downlink: 10,
        saveData: false
    }),
    configurable: true
});

// 9. WebGL vendor/renderer 정상화
try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Intel Inc.';  // __WEBGL_VENDOR__
        if (param === 37446) return 'Intel(R) Iris(TM) Plus Graphics 655';  // __WEBGL_RENDERER__
        return getParameter.call(this, param);
    };
} catch(e) {}

// 10. User-Agent 정상화 (navigator.userAgent는 읽기 전용이지만 defineProperty로 우회)
try {
    Object.defineProperty(navigator, 'userAgent', {
        get: () => 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36',  // __USER_AGENT__
        configurable: true
    });
} catch(e) {}

// 11. console.debugger 감지 우회
const _toString = Function.prototype.toString;
Function.prototype.toString = function() {
    if (this === _toString) return _toString.call(this);
    return _toString.call(this);
};

// 12. document.all 정상화 (IE detection trick)
Object.defineProperty(document, 'all', {
    get: () => HTMLAllCollection.prototype,
    configurable: true
});
"""
        # OS별 값 치환 (r-string은 f-string 불가)
        source = source.replace(
            "'Intel Inc.'  // __WEBGL_VENDOR__",
            webgl_vendor
        ).replace(
            "'Intel(R) Iris(TM) Plus Graphics 655'  // __WEBGL_RENDERER__",
            webgl_renderer
        ).replace(
            "'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'  // __USER_AGENT__",
            user_agent
        )
        # Page.addScriptToEvaluateOnNewDocument: 모든 새 문서에 스텔스 스크립트 주입
        await self.cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": source
        })
        # 현재 페이지에도 적용 (Runtime.evaluate로 직접 실행)
        await self.js("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined, configurable: true
            });
        """)
        self._stealth_applied = True
        logger = __import__('logging').getLogger("ticketlink_bot")
        logger.info("🛡️ 스텔스 우회 적용 (12개 항목)")

    async def connect(self, cdp_url: str | None = None, auto_launch: bool = True) -> None:
        """CDP WebSocket 연결"""
        if cdp_url:
            self._cdp_url = cdp_url
        if not self._cdp_url:
            self._cdp_url = discover_cdp_url()
        if not self._cdp_url and auto_launch:
            # Chrome 자동 실행 시도
            import logging
            logger = logging.getLogger("ticketlink_bot")
            logger.info("🚀 Chrome 자동 실행 중...")
            self._cdp_url = launch_chrome()
            if not self._cdp_url:
                raise ConnectionError(
                    "Chrome을 찾을 수 없거나 자동 실행에 실패했습니다.\n"
                    "Chrome을 직접 설치하거나 아래 명령어로 실행해주세요:\n"
                    + _chrome_launch_help()
                )
            logger.info("✅ Chrome 자동 실행 완료")
        if not self._cdp_url:
            raise ConnectionError(
                "Chrome CDP 연결 실패.\n"
                "Chrome을 --remote-debugging-port=9222 로 실행해주세요:\n"
                + _chrome_launch_help()
            )
        self.ws = await websockets.connect(self._cdp_url, max_size=10_000_000)

    async def cmd(self, method: str, params: dict | None = None, sid: str | None = None) -> dict:
        """CDP 명령 전송 → 결과 반환"""
        self._n += 1
        msg = {"id": self._n, "method": method, "params": params or {}}
        effective_sid = sid or self.sid
        if effective_sid:
            msg["sessionId"] = effective_sid
        await self.ws.send(json.dumps(msg))
        while True:
            res = json.loads(await asyncio.wait_for(self.ws.recv(), 30))
            if res.get("id") == self._n:
                if "error" in res:
                    code = res["error"].get("code")
                    if code == -32001:  # 세션 만료
                        raise ConnectionError("session_expired")
                    raise RuntimeError(json.dumps(res["error"], ensure_ascii=False))
                return res.get("result") or {}

    async def js(self, code: str) -> str | None:
        """JavaScript 실행 (세션 만료 시 자동 재연결)"""
        import logging as _logging
        _log = _logging.getLogger(__name__)
        try:
            result = await self.cmd("Runtime.evaluate", {
                "expression": code,
                "returnByValue": True,
                "awaitPromise": True,
            })
            # JS 실행 예외 로깅
            exc = result.get("exceptionDetails")
            if exc:
                _log.warning("⚠️ JS 예외: %s (line %s, col %s)",
                             exc.get("text", "?"), exc.get("lineNumber", "?"), exc.get("columnNumber", "?"))
                ex_obj = exc.get("exception")
                if ex_obj:
                    _log.warning("   type=%s className=%s description=%s",
                                 ex_obj.get("type", "?"), ex_obj.get("className", "?"),
                                 (ex_obj.get("description") or "")[:200])
                # 실행 중이던 코드 앞부분 로깅
                _log.warning("   code(60): %s", code.strip()[:60].replace("\n", "\\n"))
            return result.get("result", {}).get("value")
        except ConnectionError:
            await self._reattach()
            result = await self.cmd("Runtime.evaluate", {
                "expression": code,
                "returnByValue": True,
                "awaitPromise": True,
            })
            exc = result.get("exceptionDetails")
            if exc:
                _log.warning("⚠️ JS 예외 (재연결 후): %s (line %s, col %s)",
                             exc.get("text", "?"), exc.get("lineNumber", "?"), exc.get("columnNumber", "?"))
                ex_obj = exc.get("exception")
                if ex_obj:
                    _log.warning("   type=%s className=%s description=%s",
                                 ex_obj.get("type", "?"), ex_obj.get("className", "?"),
                                 (ex_obj.get("description") or "")[:200])
                _log.warning("   code(60): %s", code.strip()[:60].replace("\n", "\\n"))
            return result.get("result", {}).get("value")

    async def _reattach(self) -> None:
        """티켓링크 탭 자동 재연결"""
        # 반드시 sid를 먼저 초기화: Target.getTargets/attachToTarget은
        # browser-level 명령어로, 만료된 sessionId를 보내면 실패함.
        self.sid = None
        targets = (await self.cmd("Target.getTargets")).get("targetInfos", [])
        for t in targets:
            url = t.get("url", "")
            title = t.get("title", "")
            if "ticketlink" in url or "야구" in title:
                res = await self.cmd(
                    "Target.attachToTarget",
                    {"targetId": t["targetId"], "flatten": True},
                )
                self.sid = res["sessionId"]
                await self.apply_stealth()
                return
        raise ConnectionError("티켓링크 탭을 찾을 수 없습니다. Chrome에서 ticketlink.co.kr을 열어주세요.")

    async def screenshot(self) -> bytes:
        """현재 페이지 스크린샷 (PNG raw bytes)"""
        result = await self.cmd("Page.captureScreenshot", {
            "format": "png",
            "fromSurface": True,
        })
        import base64
        return base64.b64decode(result["data"])

    async def screenshot_b64(self) -> str:
        """현재 페이지 스크린샷 → **raw base64** (CDP→xAI 직통, 디코드 생략)"""
        result = await self.cmd("Page.captureScreenshot", {
            "format": "png",
            "fromSurface": True,
        })
        return result["data"]

    async def screenshot_element(self, selector: str | None = None) -> bytes | None:
        """
        특정 DOM 요소만 스크린샷 (CDP clip 파라미터 활용).
        selector가 None이면 자동으로 캡차 이미지 요소 탐색.

        CDP Page.captureScreenshot의 clip 옵션으로 정확한 영역만 캡쳐.
        전체 페이지 스크린샷보다 10~100배 작은 이미지 → Vision 속도 향상 + 정확도 개선.
        """
        raw = await self._screenshot_element_raw(selector)
        if raw is None:
            return None
        import base64
        return base64.b64decode(raw)

    async def screenshot_element_b64(self, selector: str | None = None) -> str | None:
        """요소 스크린샷 → **raw base64** (CDP→xAI 직통)"""
        return await self._screenshot_element_raw(selector)

    async def _screenshot_element_raw(self, selector: str | None = None) -> str | None:
        """요소 스크린샷의 CDP raw base64 반환 (내부 공유)"""
        # 1. 캡차 요소 찾기
        if selector is None:
            selector = await self._find_captcha_selector()
        if not selector:
            return None

        # 2. 요소의 viewport 내 위치 + 크기 획득
        rect_json = await self.js(f"""JSON.stringify(
            (() => {{
                const el = document.querySelector('{selector}');
                if (!el) return null;
                const r = el.getBoundingClientRect();
                // 요소가 화면 밖이면 스크롤
                if (r.bottom < 0 || r.top > window.innerHeight) {{
                    el.scrollIntoView({{behavior: 'instant', block: 'center'}});
                    // 스크롤 후 다시 계산
                    const r2 = el.getBoundingClientRect();
                    return {{
                        x: Math.max(0, r2.x),
                        y: Math.max(0, r2.y),
                        width: r2.width,
                        height: r2.height,
                        devicePixelRatio: window.devicePixelRatio || 1
                    }};
                }}
                return {{
                    x: Math.max(0, r.x),
                    y: Math.max(0, r.y),
                    width: r.width,
                    height: r.height,
                    devicePixelRatio: window.devicePixelRatio || 1
                }};
            }})()
        )""")
        if not rect_json:
            return None
        import json
        r = json.loads(rect_json)

        # 3. 요소 영역만 캡쳐 (clip)
        result = await self.cmd("Page.captureScreenshot", {
            "format": "png",
            "fromSurface": True,
            "clip": {
                "x": r["x"],
                "y": r["y"],
                "width": r["width"],
                "height": r["height"],
                "scale": 1,
            },
        })
        return result["data"]

    async def _find_captcha_selector(self) -> str | None:
        """캡차 이미지 요소를 여러 전략으로 탐색"""
        # 우선순위 선택자 목록
        selectors = [
            "img#imgCaptcha",              # 인터파크 스타일
            "img[alt*='보안']",             # 보안문자 alt
            "img[alt*='captcha']",
            "img[alt*='security']",
            ".captcha_img",
            ".security_img",
            ".captcha_container img",
            "img[src*='captcha']",
            "img[src*='Captcha']",
            "img[src*='security']",
            ".captcha img",
            "#captcha img",
        ]
        for sel in selectors:
            found = await self.js(f"document.querySelector('{sel}') !== null")
            if found:
                return sel

        # 폴백: input[placeholder*='문자'] 바로 앞의 img 찾기
        return await self.js(r"""(() => {
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {
                const ph = (inp.placeholder || '').includes('문자');
                if (!ph && inp.type !== 'text' && inp.type !== 'tel') continue;
                // 앞쪽 형제 중 img 찾기
                let el = inp.previousElementSibling;
                while (el) {
                    if (el.tagName === 'IMG') return el._hermes_selector || 'img';
                    if (el.querySelector('img')) return el.querySelector('img')._hermes_selector || 'img';
                    el = el.previousElementSibling;
                }
            }
            return null;
        })()""")

    async def find_tab(self, keyword: str = "ticketlink") -> dict | None:
        """키워드로 탭 검색"""
        targets = (await self.cmd("Target.getTargets")).get("targetInfos", [])
        for t in targets:
            url = t.get("url", "")
            title = t.get("title", "")
            if keyword in url or keyword in title:
                return t
        return None

    async def attach(self, target_id: str) -> None:
        """특정 탭에 연결"""
        result = await self.cmd(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True},
        )
        self.sid = result["sessionId"]

    async def navigate(self, url: str) -> None:
        """페이지 이동"""
        await self.cmd("Page.navigate", {"url": url})

    async def click_element(self, text_contains: str) -> bool:
        """텍스트로 요소 찾아 클릭 (JavaScript dispatchEvent)"""
        clicked = await self.js(f"""(() => {{
            const all = document.querySelectorAll('a, button, [role="button"], span, div, label');
            for (const el of all) {{
                if ((el.textContent || '').trim().includes('{text_contains}')) {{
                    el.dispatchEvent(new MouseEvent('click', {{
                        bubbles: true, cancelable: true, view: window
                    }}));
                    return true;
                }}
            }}
            return false;
        }})()""")
        return bool(clicked)

    async def get_page_text(self, max_len: int = 1000) -> str:
        """페이지 텍스트 내용"""
        return (await self.js(
            f"document.body?.innerText?.substring(0, {max_len}) || ''"
        )) or ""

    async def get_url(self) -> str:
        """현재 URL"""
        return (await self.js("document.location.href")) or ""

    async def get_title(self) -> str:
        """페이지 제목"""
        return (await self.js("document.title")) or ""

    async def find_buttons(self, keywords: list[str]) -> list[dict]:
        """키워드로 예매 버튼 검색 (푸터/네비게이션 제외)"""
        kw_json = json.dumps(keywords, ensure_ascii=False)
        raw = await self.js(f"""JSON.stringify(
Array.from(document.querySelectorAll('a,button,[role="button"],[class*="btn"],[class*="button"]')).filter(el => {{
if (el.closest('footer,nav,header,.footer,.nav,.header,[class*="footer"],[class*="nav"],[class*="header"]')) return false;
const t = (el.textContent || '').trim();
if (!t) return false;
return {kw_json}.some(kw => t.includes(kw));
}}).map(el => ({{
text: (el.textContent || '').trim().substring(0, 50),
tag: el.tagName,
visible: el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0,
inViewport: (() => {{
const r = el.getBoundingClientRect();
return r.top >= 0 && r.bottom <= (window.innerHeight || document.documentElement.clientHeight);
}})(),
href: el.href || '',
cls: (el.className || '').substring(0, 60)
}}))
)""")
        return json.loads(raw) if raw else []

    async def type_text(self, text: str) -> bool:
        """입력 필드에 텍스트 입력"""
        result = await self.js(f"""(() => {{
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {{
                if (inp.type === 'text' || inp.type === 'tel' || !inp.type) {{
                    const setter = Object.getOwnPropertyDescriptor(
                        HTMLInputElement.prototype, 'value'
                    ).set;
                    setter.call(inp, '{text}');
                    inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                    inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return true;
                }}
            }}
            return false;
        }})()""")
        return bool(result)

    async def click_real(self, selector: str) -> bool:
        """CDP Input.dispatchMouseEvent으로 진짜 마우스 클릭 (isTrusted=true)"""
        # 요소를 viewport 중앙으로 스크롤
        scrolled = await self.js(f"""(() => {{
            const el = document.querySelector('{selector}');
            if (!el) return false;
            el.scrollIntoView({{behavior: 'instant', block: 'center'}});
            return true;
        }})()""")
        if not scrolled:
            return False
        await asyncio.sleep(0.3)

        # 클릭할 좌표 계산
        rect_json = await self.js(f"""JSON.stringify(
            document.querySelector('{selector}')?.getBoundingClientRect() || null
        )""")
        if not rect_json:
            return False
        import json
        r = json.loads(rect_json)
        x = int(r['x'] + r['width'] / 2)
        y = int(r['y'] + r['height'] / 2)

        await self.cmd("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        await self.cmd("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        return True

    async def close(self) -> None:
        """연결 종료 + 페이지에 남은 오버레이 정리"""
        # 좌표 따기 오버레이 제거
        try:
            await self.js("""
                if (window._coord_ac) {
                    window._coord_ac.abort();
                    delete window._coord_ac;
                }
                const el = document.getElementById('_coord_picker_overlay');
                if (el) el.remove();
                delete window._captured_coords;
                delete window._coord_cancelled;
            """)
        except Exception:
            pass  # 연결이 이미 끊겨있으면 무시
        if self.ws:
            await self.ws.close()
