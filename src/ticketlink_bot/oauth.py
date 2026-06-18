"""
🔐 xAI OAuth PKCE 인증 모듈

Authorization Code Flow + PKCE를 사용한 xAI/Grok OAuth 인증.
로컬 HTTP 서버에서 콜백을 받아 토큰을 교환하고 저장/자동갱신.

사용법:
    from .oauth import xai_oauth_login, get_xai_token

    # 첫 실행: 브라우저 OAuth 로그인
    token = xai_oauth_login()

    # 이후: 저장된 토큰 사용 (만료 시 자동 갱신)
    token = get_xai_token()
"""
import base64
import hashlib
import json
import logging
import os
import ssl
import threading
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("ticketlink_bot")

# ============================================================
# xAI OAuth 설정 (Hermes Agent에서 추출)
# ============================================================
XAI_OAUTH_ISSUER = "https://auth.x.ai"
XAI_OAUTH_DISCOVERY_URL = f"{XAI_OAUTH_ISSUER}/.well-known/openid-configuration"
XAI_OAUTH_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_OAUTH_SCOPE = "openid profile email offline_access grok-cli:access api:access"
XAI_OAUTH_REDIRECT_HOST = "127.0.0.1"
XAI_OAUTH_REDIRECT_PORT = 56121
XAI_OAUTH_REDIRECT_PATH = "/callback"
XAI_OAUTH_REDIRECT_URI = (
    f"http://{XAI_OAUTH_REDIRECT_HOST}:{XAI_OAUTH_REDIRECT_PORT}"
    f"{XAI_OAUTH_REDIRECT_PATH}"
)
XAI_API_BASE_URL = "https://api.x.ai/v1"

# 토큰 저장 경로
TOKEN_PATH = Path.home() / ".config" / "ticketlink-bot" / "auth.json"


# ============================================================
# OIDC Discovery
# ============================================================

def _xai_discover(timeout: float = 15.0) -> dict:
    """xAI OIDC Discovery — 인증/토큰 엔드포인트 조회"""
    req = urllib.request.Request(
        XAI_OAUTH_DISCOVERY_URL,
        headers={"Accept": "application/json"},
    )
    ctx = ssl.create_default_context()
    resp = urllib.request.urlopen(req, context=ctx, timeout=timeout)
    data = json.loads(resp.read())

    auth_endpoint = (data.get("authorization_endpoint") or "").strip()
    token_endpoint = (data.get("token_endpoint") or "").strip()

    if not auth_endpoint or not token_endpoint:
        raise RuntimeError(
            "xAI OIDC discovery 응답에 authorization_endpoint 또는 "
            "token_endpoint가 없습니다."
        )
    return {
        "authorization_endpoint": auth_endpoint,
        "token_endpoint": token_endpoint,
    }


# ============================================================
# PKCE
# ============================================================

def _pkce_code_verifier() -> str:
    """PKCE code_verifier 생성 (S256)"""
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()


def _pkce_code_challenge(verifier: str) -> str:
    """PKCE code_challenge = base64url(sha256(verifier))"""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ============================================================
# Authorization URL 생성
# ============================================================

def _build_authorize_url(
    auth_endpoint: str,
    code_challenge: str,
    state: str,
    nonce: str,
) -> str:
    """브라우저에서 열 xAI OAuth 인증 URL 생성"""
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": XAI_OAUTH_CLIENT_ID,
        "redirect_uri": XAI_OAUTH_REDIRECT_URI,
        "scope": XAI_OAUTH_SCOPE,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    return f"{auth_endpoint}?{params}"


# ============================================================
# 로컬 콜백 서버
# ============================================================

class _CallbackHandler(BaseHTTPRequestHandler):
    """OAuth 콜백을 받는 로컬 HTTP 서버 핸들러"""

    def do_GET(self):
        self.server.callback_result = {  # type: ignore
            "path": self.path,
            "headers": dict(self.headers),
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        # xAI가 요구하는 CORS preflight-friendly 응답
        body = (
            "<html><body><h1>✅ 인증 완료!</h1>"
            "<p>이 창은 닫아도 됩니다. 터미널로 돌아가세요.</p>"
            "<script>window.close()</script>"
            "</body></html>"
        ).encode("utf-8")
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # 조용히


def _start_callback_server() -> tuple[HTTPServer, threading.Thread, dict]:
    """로컬 콜백 서버 시작"""
    result: dict = {}
    server = HTTPServer(
        (XAI_OAUTH_REDIRECT_HOST, XAI_OAUTH_REDIRECT_PORT),
        _CallbackHandler,
    )
    server.callback_result = result  # type: ignore
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, result


# ============================================================
# 토큰 교환 (Authorization Code → Access Token)
# ============================================================

def _exchange_code(
    token_endpoint: str,
    code: str,
    code_verifier: str,
    timeout: float = 20.0,
) -> dict:
    """Authorization Code를 Access Token으로 교환"""
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": XAI_OAUTH_REDIRECT_URI,
        "client_id": XAI_OAUTH_CLIENT_ID,
        "code_verifier": code_verifier,
    }).encode()

    req = urllib.request.Request(
        token_endpoint,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    ctx = ssl.create_default_context()
    resp = urllib.request.urlopen(req, context=ctx, timeout=timeout)
    return json.loads(resp.read())


# ============================================================
# 토큰 갱신
# ============================================================

def _refresh_token(
    refresh_token: str,
    token_endpoint: str,
    timeout: float = 20.0,
) -> dict:
    """Refresh Token으로 Access Token 갱신"""
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": XAI_OAUTH_CLIENT_ID,
        "refresh_token": refresh_token,
    }).encode()

    req = urllib.request.Request(
        token_endpoint,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    ctx = ssl.create_default_context()
    resp = urllib.request.urlopen(req, context=ctx, timeout=timeout)
    result = json.loads(resp.read())
    return result


# ============================================================
# 토큰 저장/로드
# ============================================================

def _save_tokens(tokens: dict) -> Path:
    """토큰을 auth.json에 저장"""
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        json.dump(tokens, f, indent=2)
    logger.info("🔐 토큰 저장 완료: %s", TOKEN_PATH)
    return TOKEN_PATH


def _load_tokens() -> Optional[dict]:
    """auth.json에서 토큰 로드"""
    if not TOKEN_PATH.exists():
        return None
    try:
        with open(TOKEN_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ============================================================
# xAI OAuth 로그인 (PKCE + 로컬 콜백)
# ============================================================

def xai_oauth_login(
    timeout_seconds: float = 120.0,
    open_browser: bool = True,
) -> dict:
    """
    xAI OAuth PKCE 로그인 플로우 실행.

    1. OIDC Discovery
    2. PKCE code_verifier/challenge 생성
    3. 로컬 HTTP 서버 시작 (포트 56121)
    4. 브라우저에서 xAI 인증 URL 열기
    5. 콜백 수신 → Authorization Code 획득
    6. Token Exchange → Access/Refresh Token 저장
    7. 저장된 토큰 반환

    Returns:
        {"access_token": str, "refresh_token": str, "expires_at": int, ...}
    """
    logger.info("🔐 xAI OAuth 로그인 시작...")

    # 1. Discovery
    logger.info("   OIDC discovery 중...")
    discovery = _xai_discover()
    auth_endpoint = discovery["authorization_endpoint"]
    token_endpoint = discovery["token_endpoint"]

    # 2. PKCE
    code_verifier = _pkce_code_verifier()
    code_challenge = _pkce_code_challenge(code_verifier)
    state = uuid.uuid4().hex
    nonce = uuid.uuid4().hex

    # 3. 로컬 콜백 서버
    server, thread, callback_result = _start_callback_server()

    try:
        # 4. 인증 URL 생성
        auth_url = _build_authorize_url(
            auth_endpoint, code_challenge, state, nonce,
        )

        print(f"\n{'='*60}")
        print(f"  🔐 xAI OAuth 인증")
        print(f"{'='*60}")
        print(f"  브라우저가 열리면 xAI 계정으로 로그인하세요.")
        print(f"  (자동으로 열리지 않으면 아래 URL을 직접 열어주세요)")
        print(f"\n  {auth_url}")
        print(f"\n  콜백 대기 중... http://127.0.0.1:{XAI_OAUTH_REDIRECT_PORT}")
        print(f"{'='*60}\n")

        # 5. 브라우저 열기
        if open_browser:
            try:
                webbrowser.open(auth_url)
            except Exception:
                pass

        # 6. 콜백 대기
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if callback_result:
                break
            time.sleep(0.5)

        if not callback_result:
            raise TimeoutError(
                f"⏱️ OAuth 콜백 타임아웃 ({timeout_seconds}초). "
                "다시 시도하려면 --setup 을 다시 실행하세요."
            )

        # 7. Authorization Code 추출
        path = callback_result["path"]
        parsed = urllib.parse.urlparse(f"http://localhost{path}")
        params = urllib.parse.parse_qs(parsed.query)

        if "code" not in params:
            error = params.get("error", ["unknown"])[0]
            raise RuntimeError(
                f"❌ xAI OAuth 인증 실패 (error={error})"
            )

        code = params["code"][0]

        # 8. Token Exchange
        logger.info("   Authorization Code → Token 교환 중...")
        token_result = _exchange_code(token_endpoint, code, code_verifier)

    finally:
        # 콜백 서버 종료
        server.shutdown()
        thread.join(timeout=2)

    # 9. 토큰 정리 및 저장
    tokens = _normalize_tokens(token_result)
    _save_tokens(tokens)

    expires_in = tokens.get("expires_in", 0)
    logger.info(
        "✅ OAuth 로그인 완료! (Access Token: %d자, %d초 유효)",
        len(tokens.get("access_token", "")),
        expires_in,
    )

    return tokens


# ============================================================
# 토큰 정규화
# ============================================================

def _normalize_tokens(raw: dict) -> dict:
    """원시 토큰 응답을 표준 형식으로 변환"""
    now = int(time.time())
    expires_in = int(raw.get("expires_in", 21600))  # 기본 6시간
    return {
        "access_token": raw.get("access_token", ""),
        "refresh_token": raw.get("refresh_token", ""),
        "expires_at": now + expires_in,
        "expires_in": expires_in,
        "token_type": raw.get("token_type", "Bearer"),
        "scope": raw.get("scope", ""),
        "saved_at": now,
    }


# ============================================================
# 토큰 획득 (저장된 토큰 → 만료 시 자동 갱신)
# ============================================================

def get_xai_token() -> str:
    """
    사용 가능한 xAI Access Token 반환.

    1. auth.json에서 저장된 토큰 로드
    2. 만료되지 않았으면 그대로 반환
    3. 만료되었으면 Refresh Token으로 갱신 후 저장
    4. 토큰도 리프레시 토큰도 없으면 에러

    Returns:
        Bearer token string (access_token)
    """
    tokens = _load_tokens()

    # 토큰 없음
    if not tokens or not tokens.get("access_token"):
        raise RuntimeError(
            "xAI OAuth 토큰이 없습니다.\n"
            f"  python -m ticketlink_bot --setup\n"
            "  → OAuth 로그인을 먼저 실행하세요."
        )

    # 만료 확인 (5분 버퍼)
    now = int(time.time())
    expires_at = tokens.get("expires_at", 0)
    buffer = 300  # 5분

    if now < expires_at - buffer:
        # 유효함
        return tokens["access_token"]

    # 만료 → Refresh 시도
    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        raise RuntimeError(
            "xAI Access Token이 만료되었고 Refresh Token이 없습니다.\n"
            f"  python -m ticketlink_bot --setup\n"
            "  → 다시 OAuth 로그인하세요."
        )

    logger.info("🔄 xAI Access Token 만료, Refresh Token으로 갱신 중...")
    try:
        discovery = _xai_discover()
        token_endpoint = discovery["token_endpoint"]
        result = _refresh_token(refresh_token, token_endpoint)
        new_tokens = _normalize_tokens(result)

        # Refresh Token이 새로 발급되었으면 업데이트
        if result.get("refresh_token"):
            new_tokens["refresh_token"] = result["refresh_token"]
        else:
            # 기존 refresh_token 유지
            new_tokens["refresh_token"] = refresh_token

        _save_tokens(new_tokens)
        logger.info("✅ Access Token 갱신 완료!")
        return new_tokens["access_token"]

    except Exception as e:
        raise RuntimeError(
            f"❌ xAI Token 갱신 실패: {e}\n"
            f"  python -m ticketlink_bot --setup\n"
            "  → 다시 OAuth 로그인하세요."
        )


# ============================================================
# Device Authorization Flow (폰/원격 인증)
# ============================================================

def xai_device_login(
    timeout_seconds: float = 300.0,
) -> dict:
    """
    **Device Authorization Flow** — 폰으로도 OAuth 로그인 가능!

    사용법:
        1. CLI에 표시된 코드를 폰 브라우저에서 입력
        2. xAI 로그인
        3. 자동 토큰 수령

    Returns:
        {"access_token": str, "refresh_token": str, "expires_at": int, ...}
    """
    import urllib.error
    discovery = _xai_discover()

    device_endpoint = discovery.get("device_authorization_endpoint")
    if not device_endpoint:
        # OIDC discovery에 없으면 직접 입력
        device_endpoint = "https://auth.x.ai/oauth2/device/code"

    ctx = ssl.create_default_context()

    # 1. Device Code 요청
    logger.info("🔐 Device Authorization Flow 시작...")
    device_req = urllib.request.Request(
        device_endpoint,
        data=urllib.parse.urlencode({
            "client_id": XAI_OAUTH_CLIENT_ID,
            "scope": XAI_OAUTH_SCOPE,
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    device_resp = urllib.request.urlopen(device_req, context=ctx, timeout=15)
    device_data = json.loads(device_resp.read())

    user_code = device_data["user_code"]
    device_code = device_data["device_code"]
    verification_uri = device_data.get("verification_uri", "https://auth.x.ai/device")
    interval = device_data.get("interval", 5)

    print(f"""
╔══════════════════════════════════════════════════════╗
║   🔐 xAI OAuth — Device 인증                        ║
║                                                      ║
║   지금 폰/다른 기기에서 아래 주소로 접속해서         ║
║   인증 코드를 입력하세요.                            ║
║                                                      ║
║   📍 {verification_uri}
║                                                      ║
║   🔑 인증 코드:  {user_code}
║                                                      ║
║   {timeout_seconds:.0f}초 안에 인증해야 합니다.                  ║
║   (자동으로 폴링하며 기다립니다)                    ║
╚══════════════════════════════════════════════════════╝
""")

    # 2. 폴링: 토큰 교환 대기
    token_endpoint = discovery["token_endpoint"]
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        time.sleep(interval)

        try:
            token_req = urllib.request.Request(
                token_endpoint,
                data=urllib.parse.urlencode({
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                    "client_id": XAI_OAUTH_CLIENT_ID,
                }).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_resp = urllib.request.urlopen(token_req, context=ctx, timeout=15)
            token_data = json.loads(token_resp.read())

            # 성공!
            tokens = _normalize_tokens(token_data)
            if token_data.get("refresh_token"):
                tokens["refresh_token"] = token_data["refresh_token"]
            _save_tokens(tokens)
            print("\n✅ xAI OAuth 인증 완료! 토큰이 저장되었습니다.\n")
            return tokens

        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read())
                err = err_body.get("error", "")
            except Exception:
                err = str(e)

            if err in ("authorization_pending", "slow_down"):
                if err == "slow_down":
                    interval += 5  # 서버 요청: 간격 증가
                continue
            elif err == "access_denied":
                raise RuntimeError("❌ 사용자가 인증을 거절했습니다.")
            elif err == "expired_token":
                raise RuntimeError("❌ 인증 코드가 만료되었습니다. 다시 시도하세요.")
            else:
                raise RuntimeError(f"❌ Device 인증 오류: {err}")

    raise RuntimeError(
        "⏰ 인증 시간이 초과되었습니다. 다시 --setup을 실행하세요."
    )


# ============================================================
# Hermes auth.json 호환 — 기존 OAuth 토큰 읽기
# ============================================================

def migrate_from_hermes() -> bool:
    """
    Hermes auth.json에서 xAI OAuth 토큰을 가져와서
    ticketlink-bot auth.json으로 복사.

    모든 Hermes 프로필 검색 (mango, secretary, teacher, trading 등).

    Returns:
        성공 여부
    """
    hermes_home = Path.home() / ".hermes"

    # 모든 auth.json 수집
    auth_paths = []
    # 글로벌
    global_auth = hermes_home / "auth.json"
    if global_auth.exists():
        auth_paths.append(global_auth)
    # 모든 프로필
    profiles_dir = hermes_home / "profiles"
    if profiles_dir.exists():
        for p in sorted(profiles_dir.iterdir()):
            ap = p / "auth.json"
            if ap.exists():
                auth_paths.append(ap)

    for hp in auth_paths:
        try:
            with open(hp) as f:
                auth = json.load(f)
            for pool_name, entries in auth.get("credential_pool", {}).items():
                if "xai" not in pool_name.lower():
                    continue
                for entry in entries:
                    token = entry.get("access_token", "")
                    if token and token != "***":
                        tokens = {
                            "access_token": token,
                            "refresh_token": entry.get("refresh_token", ""),
                            "expires_at": entry.get("expires_at", 0) or (int(time.time()) + 21600),
                            "expires_in": entry.get("expires_in", 21600),
                            "token_type": entry.get("token_type", "Bearer"),
                            "scope": entry.get("scope", ""),
                            "saved_at": int(time.time()),
                            "migrated_from": str(hp),
                            "base_url": entry.get("base_url", XAI_API_BASE_URL),
                        }
                        _save_tokens(tokens)
                        logger.info(
                            "✅ Hermes %s에서 OAuth 토큰 마이그레이션 완료",
                            hp.parent.name if hp.parent.name != ".hermes" else "global",
                        )
                        return True
        except Exception:
            continue

    return False
