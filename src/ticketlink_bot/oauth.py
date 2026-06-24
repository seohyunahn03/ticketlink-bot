"""
🔐 OAuth 인증 모듈 — xAI + OpenAI (Codex)

Device Code Flow (RFC 8628) 기반 OAuth 인증.
xAI와 OpenAI(Codex) OAuth를 지원하며, 각각의 토큰은
~/.config/ticketlink-bot/auth.json에 중첩된 형태로 저장됩니다.

사용법:
    from .oauth import xai_oauth_login, get_xai_token, openai_oauth_login, get_openai_token

    # xAI
    token = xai_oauth_login()
    token = get_xai_token()

    # OpenAI (Codex)
    token = openai_oauth_login()
    token = get_openai_token()
"""
import json
import logging
import os
import ssl
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
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
XAI_API_BASE_URL = "https://api.x.ai/v1"

# ============================================================
# OpenAI (Codex) OAuth 설정
# ============================================================
OPENAI_OAUTH_ISSUER = "https://auth0.openai.com"
OPENAI_OAUTH_DISCOVERY_URL = f"{OPENAI_OAUTH_ISSUER}/.well-known/openid-configuration"
OPENAI_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_OAUTH_SCOPE = "openid profile email offline_access"

# 토큰 저장 경로
TOKEN_PATH = Path.home() / ".config" / "ticketlink-bot" / "auth.json"


# ============================================================
# OIDC Discovery
# ============================================================

def _discover(discovery_url: str, provider_name: str = "OIDC",
              timeout: float = 15.0) -> dict:
    """Generic OIDC discovery — 인증/토큰/device 엔드포인트 조회"""
    req = urllib.request.Request(
        discovery_url,
        headers={"Accept": "application/json"},
    )
    ctx = ssl.create_default_context()
    resp = urllib.request.urlopen(req, context=ctx, timeout=timeout)
    data = json.loads(resp.read())

    auth_endpoint = (data.get("authorization_endpoint") or "").strip()
    token_endpoint = (data.get("token_endpoint") or "").strip()
    device_endpoint = (data.get("device_authorization_endpoint") or "").strip()

    if not auth_endpoint or not token_endpoint:
        raise RuntimeError(
            f"{provider_name} OIDC discovery 응답에 authorization_endpoint 또는 "
            f"token_endpoint가 없습니다."
        )
    if not device_endpoint:
        raise RuntimeError(
            f"{provider_name} OIDC에 device_authorization_endpoint 없음"
        )
    return {
        "authorization_endpoint": auth_endpoint,
        "token_endpoint": token_endpoint,
        "device_authorization_endpoint": device_endpoint,
    }


def _xai_discover(timeout: float = 15.0) -> dict:
    """xAI OIDC Discovery"""
    return _discover(XAI_OAUTH_DISCOVERY_URL, "xAI", timeout)


def _openai_discover(timeout: float = 15.0) -> dict:
    """OpenAI (Codex) OIDC Discovery"""
    return _discover(OPENAI_OAUTH_DISCOVERY_URL, "OpenAI", timeout)


# ============================================================
# Device Code Flow (RFC 8628)
# ============================================================

def _request_device_code(discovery: dict,
                         client_id: str = XAI_OAUTH_CLIENT_ID,
                         scope: str = XAI_OAUTH_SCOPE) -> dict:
    """Device Code 요청 → user_code + device_code + verification_uri"""
    device_endpoint = discovery.get("device_authorization_endpoint")
    if not device_endpoint:
        raise RuntimeError("OIDC에 device_authorization_endpoint 없음")
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "scope": scope,
    }).encode()
    req = urllib.request.Request(
        device_endpoint, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    ctx = ssl.create_default_context()
    resp = urllib.request.urlopen(req, context=ctx, timeout=15)
    return json.loads(resp.read())


def _poll_device_token(device_code: str, token_endpoint: str,
                       client_id: str = XAI_OAUTH_CLIENT_ID,
                       interval: int = 5,
                       timeout: float = 300.0) -> dict:
    """Device Code → Access Token 폴링"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "client_id": client_id,
        }).encode()
        req = urllib.request.Request(
            token_endpoint, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        ctx = ssl.create_default_context()
        try:
            resp = urllib.request.urlopen(req, context=ctx, timeout=10)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                err_json = json.loads(body)
            except json.JSONDecodeError:
                err_json = {}
            err = err_json.get("error", "unknown")
            if err == "authorization_pending":
                time.sleep(interval)
                continue
            elif err == "slow_down":
                interval += 5
                time.sleep(interval)
                continue
            elif err == "expired_token":
                raise TimeoutError("⏱️ Device Code 만료 — 다시 시도하세요.")
            else:
                raise RuntimeError(f"❌ Device Code 폴링 오류: {err}")
    raise TimeoutError(f"⏱️ OAuth 인증 타임아웃 ({timeout:.0f}초)")


def _cleanup_old_token():
    """로그인 전 이전 토큰 제거 (깨끗한 상태에서 재시도)"""
    if TOKEN_PATH.exists():
        try:
            TOKEN_PATH.unlink()
            logger.info("   이전 토큰 삭제: %s", TOKEN_PATH)
        except Exception as e:
            logger.debug("   이전 토큰 삭제 실패: %s", e)


# ============================================================
# 토큰 갱신
# ============================================================

def _refresh_token(refresh_token: str, token_endpoint: str,
                   client_id: str = XAI_OAUTH_CLIENT_ID,
                   timeout: float = 20.0) -> dict:
    """Refresh Token으로 Access Token 갱신"""
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": client_id,
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
# 토큰 저장/로드 — 다중 프로바이더 지원
# ============================================================

def _migrate_if_needed(data: dict) -> dict:
    """
    이전 단일 제공자 형식(flat)을 신규 중첩 형식으로 마이그레이션.

    이전 형식:
        {"access_token": "...", "refresh_token": "...", ...}
    신규 형식:
        {"xai": {...}, "openai": {...}}

    감지: 최상위에 "access_token" 키가 있고 "xai"/"openai" 키가 없으면
          이전 형식으로 간주하고 "xai" 하위로 이동.
    """
    if "access_token" in data and "xai" not in data and "openai" not in data:
        migrated = {"xai": data}
        try:
            with open(TOKEN_PATH, "w") as f:
                json.dump(migrated, f, indent=2)
            logger.info("   🔄 auth.json 마이그레이션 완료 (flat → nested)")
        except Exception:
            pass
        return migrated
    return data


def _save_tokens(tokens: dict, provider: str = "xai") -> Path:
    """특정 프로바이더의 토큰을 auth.json에 저장"""
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 기존 데이터 로드
    all_tokens = {}
    if TOKEN_PATH.exists():
        try:
            with open(TOKEN_PATH) as f:
                all_tokens = json.load(f)
            all_tokens = _migrate_if_needed(all_tokens)
        except (json.JSONDecodeError, OSError):
            all_tokens = {}

    all_tokens[provider] = tokens

    with open(TOKEN_PATH, "w") as f:
        json.dump(all_tokens, f, indent=2)
    logger.info("🔐 %s 토큰 저장 완료: %s", provider.upper(), TOKEN_PATH)
    return TOKEN_PATH


def _load_tokens(provider: Optional[str] = None) -> Optional[dict]:
    """
    auth.json에서 토큰 로드.

    Args:
        provider: None이면 모든 프로바이더의 중첩 dict 반환.
                  "xai" 또는 "openai"면 해당 프로바이더의 flat dict 반환.

    Returns:
        프로바이더 지정 시: {"access_token": str, ...} or None
        프로바이더 미지정 시: {"xai": {...}, "openai": {...}} or None
    """
    if not TOKEN_PATH.exists():
        return None
    try:
        with open(TOKEN_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # 이전 형식(flat) → 신규 형식(nested) 마이그레이션
    data = _migrate_if_needed(data)

    if provider is not None:
        return data.get(provider)
    return data


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
# xAI OAuth 로그인 (Device Code)
# ============================================================

def xai_oauth_login(
    timeout_seconds: float = 120.0,
    open_browser: bool = True,
) -> dict:
    """
    xAI OAuth Device Code 로그인 플로우 실행.

    1. OIDC Discovery
    2. Device Code 요청 (user_code + verification_uri)
    3. 브라우저에서 verification_uri 열기
    4. 사용자가 user_code 입력 후 인증
    5. Polling → Access/Refresh Token 획득
    6. 저장된 토큰 반환

    Returns:
        {"access_token": str, "refresh_token": str, "expires_at": int, ...}
    """
    logger.info("🔐 xAI OAuth 로그인 시작...")

    # 1. Discovery
    logger.info("   OIDC discovery 중...")
    discovery = _xai_discover()
    token_endpoint = discovery["token_endpoint"]

    # 2. 기존 토큰 정리 (싱크 맞춤)
    _cleanup_old_token()

    # 3. Device Code 요청
    logger.info("   Device Code 요청 중...")
    device_resp = _request_device_code(discovery, client_id=XAI_OAUTH_CLIENT_ID,
                                       scope=XAI_OAUTH_SCOPE)
    device_code = device_resp["device_code"]
    user_code = device_resp["user_code"]
    verification_uri = device_resp.get("verification_uri",
                                        device_resp.get("verification_uri_complete",
                                                        "https://auth.x.ai/device"))
    interval = device_resp.get("interval", 5)

    # 4. 사용자에게 코드 표시 + 브라우저 열기
    logger.info("")
    logger.info("=" * 50)
    logger.info("  🔐 xAI OAuth 인증")
    logger.info("=" * 50)
    logger.info("  브라우저가 열리면 xAI 계정으로 로그인한 뒤,")
    logger.info("  아래 코드를 입력하세요:")
    logger.info("")
    logger.info("  ┌──────────────────────────────┐")
    logger.info("  │                              │")
    logger.info("  │      인증 코드: %s     │", user_code)
    logger.info("  │                              │")
    logger.info("  └──────────────────────────────┘")
    logger.info("")
    logger.info("  또는 브라우저에서 직접 접속: %s", verification_uri)
    logger.info("  (타임아웃: %d초)", timeout_seconds)
    logger.info("=" * 50)
    logger.info("")

    # 5. 브라우저 열기 (verification_uri)
    if open_browser:
        try:
            webbrowser.open(verification_uri)
        except Exception:
            pass

    # 6. Polling → Token
    logger.info("   인증 완료 대기 중... (브라우저에서 코드를 입력하세요)")
    token_result = _poll_device_token(
        device_code, token_endpoint,
        client_id=XAI_OAUTH_CLIENT_ID,
        interval=interval, timeout=timeout_seconds,
    )

    # 7. 토큰 정리 및 저장
    tokens = _normalize_tokens(token_result)
    _save_tokens(tokens, provider="xai")

    expires_in = tokens.get("expires_in", 0)
    logger.info(
        "✅ OAuth 로그인 완료! (Access Token: %d자, %d초 유효)",
        len(tokens.get("access_token", "")),
        expires_in,
    )

    return tokens


# ============================================================
# xAI 토큰 획득 (저장된 토큰 → 만료 시 자동 갱신)
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
    tokens = _load_tokens(provider="xai")

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
        result = _refresh_token(refresh_token, token_endpoint, client_id=XAI_OAUTH_CLIENT_ID)
        new_tokens = _normalize_tokens(result)

        # Refresh Token이 새로 발급되었으면 업데이트
        if result.get("refresh_token"):
            new_tokens["refresh_token"] = result["refresh_token"]
        else:
            # 기존 refresh_token 유지
            new_tokens["refresh_token"] = refresh_token

        _save_tokens(new_tokens, provider="xai")
        logger.info("✅ Access Token 갱신 완료!")
        return new_tokens["access_token"]

    except Exception as e:
        raise RuntimeError(
            f"❌ xAI Token 갱신 실패: {e}\n"
            f"  python -m ticketlink_bot --setup\n"
            "  → 다시 OAuth 로그인하세요."
        )


# ============================================================
# Device Authorization Flow (폰/원격 인증) — xAI
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
            _save_tokens(tokens, provider="xai")
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
# OpenAI (Codex) OAuth 로그인 — Codex CLI --device-auth 활용
# ============================================================

def openai_oauth_login(timeout_seconds=120):
    """
    OpenAI/Codex OAuth 로그인 — Codex CLI의 --device-auth 활용.

    Codex CLI가 Cloudflare challenge를 처리하므로 직접 HTTP 요청보다 안정적.
    """
    logger.info("🔐 OpenAI (Codex) OAuth 로그인 시작...")

    # 1) 이미 auth 파일이 있으면 바로 읽기
    codex_auth_path = Path.home() / ".codex" / "auth.json"
    if codex_auth_path.exists():
        logger.info("   ✅ 기존 Codex OAuth 토큰 발견: %s", codex_auth_path)
        return _import_codex_tokens(codex_auth_path)

    # 2) npx 찾기 (PATH + 일반적인 설치 경로)
    import shutil
    npx_path = shutil.which("npx")
    if not npx_path:
        # Hermes/node 경로 fallback
        hermes_npx = os.path.expanduser("~/.hermes/node/bin/npx")
        if os.path.isfile(hermes_npx):
            npx_path = hermes_npx
        else:
            raise RuntimeError(
                "npx를 찾을 수 없습니다. Node.js가 설치되어 있는지 확인하세요.\n"
                "  설치: https://nodejs.org/\n"
                "  또는: brew install node"
            )
    logger.info("   🔑 Codex CLI 로그인 실행 중... (브라우저가 열립니다)")
    logger.info("   (처음이면 npm/npx 패키지 다운로드에 시간이 소요될 수 있음)")

    try:
        result = subprocess.run(
            [npx_path, "@openai/codex", "login", "--device-auth"],
            capture_output=True, text=True,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Codex CLI 로그인 실패 (exit={result.returncode}):\n"
                f"{result.stderr.strip()}"
            )
    except FileNotFoundError:
        raise RuntimeError(
            "npx를 찾을 수 없습니다. Node.js가 설치되어 있는지 확인하세요."
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(
            f"Codex OAuth 로그인 시간 초과 ({timeout_seconds}초)"
        )

    # 3) 로그인 후 auth.json 읽기
    if not codex_auth_path.exists():
        raise RuntimeError(
            "Codex CLI 로그인은 완료되었지만 auth.json을 찾을 수 없습니다.\n"
            f"  예상 경로: {codex_auth_path}"
        )

    return _import_codex_tokens(codex_auth_path)


def _import_codex_tokens(codex_auth_path: Path) -> dict:
    """Codex auth.json을 읽어 ticketlink-bot 형식으로 변환"""
    with open(codex_auth_path) as f:
        codex_tokens = json.load(f)

    # Codex auth.json 구조 확인 (일반적으로 access_token, refresh_token 등)
    access_token = codex_tokens.get("access_token") or ""
    refresh_token = codex_tokens.get("refresh_token") or ""
    expires_in = int(codex_tokens.get("expires_in", 21600))
    expires_at = codex_tokens.get("expires_at") or int(time.time()) + expires_in

    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "expires_in": expires_in,
        "token_type": "Bearer",
        "scope": "openid profile email offline_access",
        "saved_at": int(time.time()),
    }

    # 우리 auth.json에 저장
    _save_tokens(tokens, provider="openai")
    logger.info("✅ OpenAI OAuth 토큰 가져오기 완료! (Access Token: %d자)", len(access_token))
    return tokens


# ============================================================
# OpenAI (Codex) 토큰 획득 (저장된 토큰 → 만료 시 자동 갱신)
# ============================================================

def get_openai_token() -> str:
    """
    사용 가능한 OpenAI (Codex) Access Token 반환.

    1. auth.json에서 openai 키의 저장된 토큰 로드
    2. 만료되지 않았으면 그대로 반환
    3. 만료되었으면 Refresh Token으로 갱신 후 저장
    4. 토큰도 리프레시 토큰도 없으면 에러

    Returns:
        Bearer token string (access_token)
    """
    tokens = _load_tokens(provider="openai")

    # 토큰 없음
    if not tokens or not tokens.get("access_token"):
        raise RuntimeError(
            "OpenAI (Codex) OAuth 토큰이 없습니다.\n"
            "  GUI → 설정 → 🤖 Codex OAuth 로그인을 먼저 실행하세요."
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
            "OpenAI Access Token이 만료되었고 Refresh Token이 없습니다.\n"
            "  GUI → 설정 → 🤖 Codex OAuth 로그인을 다시 실행하세요."
        )

    logger.info("🔄 OpenAI Access Token 만료, Refresh Token으로 갱신 중...")
    try:
        discovery = _openai_discover()
        token_endpoint = discovery["token_endpoint"]
        result = _refresh_token(refresh_token, token_endpoint,
                                client_id=OPENAI_OAUTH_CLIENT_ID)
        new_tokens = _normalize_tokens(result)

        # Refresh Token이 새로 발급되었으면 업데이트
        if result.get("refresh_token"):
            new_tokens["refresh_token"] = result["refresh_token"]
        else:
            # 기존 refresh_token 유지
            new_tokens["refresh_token"] = refresh_token

        _save_tokens(new_tokens, provider="openai")
        logger.info("✅ OpenAI Access Token 갱신 완료!")
        return new_tokens["access_token"]

    except Exception as e:
        raise RuntimeError(
            f"❌ OpenAI Token 갱신 실패: {e}\n"
            "  GUI → 설정 → 🤖 Codex OAuth 로그인을 다시 실행하세요."
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
                        _save_tokens(tokens, provider="xai")
                        logger.info(
                            "✅ Hermes %s에서 OAuth 토큰 마이그레이션 완료",
                            hp.parent.name if hp.parent.name != ".hermes" else "global",
                        )
                        return True
        except Exception:
            continue

    return False
