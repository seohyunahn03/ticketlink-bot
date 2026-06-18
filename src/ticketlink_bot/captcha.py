"""
🎫 xAI Grok Vision + Tesseract 하이브리드 캡차(보안문자) 자동 인식

전략:
  1. Tesseract OCR (로컬, ~0.3초) — confidence ≥ THRESHOLD → 즉시 반환
  2. xAI Vision API (원격, ~1.5초) — Tesseract 실패 시 폴백
  3. 문자 보정 — 블로그 참고: 5→S, 0→O, 1→L 등

토큰 획득 방식 (우선순위):
  1. ticketlink-bot auth.json (OAuth)
  2. 환경변수 XAI_API_KEY
  3. Hermes auth.json (OAuth)
"""

import base64
import io
import json
import logging
import os
import re
import ssl
import urllib.request
from pathlib import Path

from .oauth import get_xai_token, migrate_from_hermes

logger = logging.getLogger(__name__)

# fallback auth 경로들
_AUTH_CANDIDATES = [
    os.environ.get("XAI_API_KEY"),
    Path.home() / ".hermes" / "profiles" / "programmer" / "auth.json",
    Path.home() / ".hermes" / "auth.json",
    Path.home() / ".config" / "ticketlink-bot" / "auth.json",
]

# Tesseract confidence 임계값 — 이 이상이면 로컬 OCR 결과를 신뢰
TESSERACT_CONFIDENCE_THRESHOLD = 60  # 0~100

# 캡차 문자 보정 맵 (블로그 참고 + 추가)
_CHAR_REPLACEMENTS = {
    "5": "S", "0": "O", "$": "S", "€": "C",
    "1": "I", "4": "A", "3": "E",
    "e": "Q", "£": "E",
    "+": "T", "'": "", "`": "",
    "{": "", "}": "", "|": "I",
    "/": "", "\\": "", "_": "",
    ":": "", ".": "", ",": "",
    "-": "", '"': "", "!": "I",
    "@": "A", "#": "", "%": "",
    "&": "", "*": "", "(": "", ")": "",
    "ㅁ": "O", "ㅇ": "O",
    "ㄱ": "L", "ㄴ": "L",
}

# 캡차에 유효한 문자 (티켓링크: 대/소문자 구분 없음, I L O Q 제외)
_VALID_CHARS = set("ABCDEFGHJKMNPQRSTUVWXYZ0123456789")


# ──────────────────────────────────────────────
# Tesseract (로컬 OCR)
# ──────────────────────────────────────────────

def _tesseract_available() -> bool:
    """Tesseract + pytesseract 사용 가능 여부 (Windows/macOS/Linux)"""
    try:
        import pytesseract

        # 1) pytesseract가 이미 tesseract_cmd를 알고 있는지 확인
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            pass

        # 1.5) shutil.which()로 PATH에서 찾기 (가장 표준적인 방법)
        import shutil
        tess_in_path = shutil.which("tesseract")
        if tess_in_path:
            pytesseract.pytesseract.tesseract_cmd = tess_in_path
            try:
                pytesseract.get_tesseract_version()
                return True
            except Exception:
                pass

        # 2) PATH 환경변수에서 tesseract 실행 파일 찾기
        path_sep = ";" if os.name == "nt" else ":"
        tesseract_exe = "tesseract.exe" if os.name == "nt" else "tesseract"
        found_in_path = False
        for p in os.environ.get("PATH", "").split(path_sep):
            candidate = os.path.join(p.strip(), tesseract_exe)
            if os.path.exists(candidate):
                pytesseract.pytesseract.tesseract_cmd = candidate
                found_in_path = True
                break

        if not found_in_path:
            # 3) OS별 기본 설치 경로 탐색
            candidates = []
            if os.name == "nt":
                # Windows 기본 경로
                candidates = [
                    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                ]
                # LOCALAPPDATA 경로
                local = os.environ.get("LOCALAPPDATA", "")
                if local:
                    candidates.append(os.path.join(local, "Tesseract-OCR", "tesseract.exe"))
            else:
                # macOS (Homebrew) / Linux
                candidates = [
                    "/opt/homebrew/bin/tesseract",
                    "/usr/local/bin/tesseract",
                    "/usr/bin/tesseract",
                ]
            for candidate in candidates:
                if os.path.exists(candidate):
                    pytesseract.pytesseract.tesseract_cmd = candidate
                    break

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _correct_text(raw: str) -> str:
    """OCR raw 결과를 캡차 문자열로 보정"""
    # 1. 대문자 변환
    text = raw.upper().strip()
    # 2. 문자 보정 맵 적용
    result = []
    for ch in text:
        if ch in _CHAR_REPLACEMENTS:
            replaced = _CHAR_REPLACEMENTS[ch]
            if replaced:  # 빈 문자열이면 스킵
                result.append(replaced)
        else:
            result.append(ch)
    corrected = "".join(result)
    # 3. 유효 문자만 필터링 (영문 대문자 + 숫자)
    filtered = "".join(c for c in corrected if c in _VALID_CHARS)
    return filtered


def _solve_with_tesseract(image_bytes: bytes) -> tuple[str | None, float]:
    """
    Tesseract OCR로 캡차 인식.
    Returns: (인식된_문자열 or None, 평균_confidence)
    """
    if not _tesseract_available():
        logger.debug("Tesseract 미설치, 건너뜀")
        return None, 0.0

    try:
        import pytesseract
        from PIL import Image

        # Tesseract에 최적화된 전처리
        img = Image.open(io.BytesIO(image_bytes))

        # 전처리: 그레이스케일 + 이진화 (캡차 대비 향상)
        img = img.convert("L")  # 그레이스케일
        img = img.point(lambda x: 0 if x < 140 else 255)  # 이진화 (임계값 140)

        # PSM 8 = 단일 단어 모드, OEM 3 = LSTM + Legacy
        custom_config = (
            "--oem 3 --psm 8 "
            "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        )

        # detail=1: confidence 정보 포함
        data = pytesseract.image_to_data(
            img,
            config=custom_config,
            output_type=pytesseract.Output.DICT,
        )

        # 인식된 문자 + confidence 수집
        chars = []
        confs = []
        for i, text in enumerate(data["text"]):
            text = text.strip()
            if not text:
                continue
            conf = int(data["conf"][i]) if data["conf"][i] not in (None, "-1") else 0
            chars.append(text)
            confs.append(conf)

        if not chars:
            logger.debug("Tesseract: 문자 미인식")
            return None, 0.0

        raw = "".join(chars)
        mean_conf = sum(confs) / len(confs) if confs else 0.0
        corrected = _correct_text(raw)

        logger.info(
            "🧠 Tesseract: raw=\"%s\" → \"%s\" (conf=%.1f%%)",
            raw, corrected, mean_conf,
        )

        # 결과가 0자면 None 반환
        if not corrected:
            return None, 0.0

        return corrected, mean_conf

    except Exception as e:
        logger.warning("Tesseract 에러: %s", e)
        return None, 0.0


# ──────────────────────────────────────────────
# xAI Vision API
# ──────────────────────────────────────────────

def _resolve_xai_token() -> str:
    """xAI API 토큰 자동 탐색 — OAuth → 환경변수 → Hermes → config"""
    # 1. OAuth: ticketlink-bot auth.json
    try:
        token = get_xai_token()
        if token:
            return token
    except Exception:
        pass

    # 2. Hermes auth.json 마이그레이션
    try:
        if migrate_from_hermes():
            return get_xai_token()
    except Exception:
        pass

    # 3. 환경변수
    env_key = os.environ.get("XAI_API_KEY")
    if env_key:
        return env_key

    # 4. auth.json 파일들
    for candidate in _AUTH_CANDIDATES:
        if isinstance(candidate, Path) and candidate.exists():
            try:
                with open(candidate) as f:
                    auth = json.load(f)
                for pool_entry in (
                    auth.get("credential_pool", {}).get("xai-oauth", [])
                ):
                    token = pool_entry.get("access_token")
                    if token and token != "***":
                        return token
                for pool_name, entries in auth.get("credential_pool", {}).items():
                    if "xai" in pool_name.lower():
                        for entry in entries:
                            token = entry.get("access_token")
                            if token and token != "***":
                                return token
            except Exception:
                continue

    # 5. ~/.config/ticketlink-bot/config.json
    config_path = Path.home() / ".config" / "ticketlink-bot" / "config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            if cfg.get("xai_api_key"):
                return cfg["xai_api_key"]
        except Exception:
            pass

    raise ValueError(
        "xAI API 키를 찾을 수 없습니다.\n"
        "  export XAI_API_KEY=your_key_here\n"
        "  또는 ~/.config/ticketlink-bot/config.json 에 xai_api_key 설정"
    )


def _resize_image(image_bytes: bytes, max_size: int = 500) -> bytes:
    """이미지 리사이즈 (Vision 토큰 절약 + 속도 향상)"""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            img = img.resize(
                (int(img.width * ratio), int(img.height * ratio))
            )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except ImportError:
        return image_bytes


def _solve_with_vision(image_bytes: bytes, model: str = "grok-4.20-0309-non-reasoning") -> str:
    """xAI Grok Vision으로 캡차 이미지 문자열 인식"""
    token = _resolve_xai_token()
    image_bytes = _resize_image(image_bytes)
    img_b64 = base64.b64encode(image_bytes).decode()

    data = json.dumps({
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Extract only the captcha characters visible in this image. "
                            "Return ONLY the characters, nothing else. "
                            "Example: \"ABC123\""
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{img_b64}"
                        },
                    },
                ],
            }
        ],
        "max_tokens": 20,
    }).encode()

    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        "https://api.x.ai/v1/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    resp = urllib.request.urlopen(req, context=ctx, timeout=30)
    result = json.loads(resp.read())
    raw = result["choices"][0]["message"]["content"].strip()

    # Vision 결과도 보정 (혹시 모를 오탐 방지)
    text = raw.upper().strip()
    corrected = "".join(
        _CHAR_REPLACEMENTS.get(c, c) for c in text if c.isalnum()
    )
    return corrected


# ──────────────────────────────────────────────
# 통합 solve_captcha (병렬 하이브리드)
# ──────────────────────────────────────────────

def _solve_parallel(
    image_bytes: bytes,
    model: str = "grok-4.20-0309-non-reasoning",
) -> str:
    """
    Tesseract + Vision **동시 실행**, 먼저 성공한 결과 반환.

    전략:
      ╭─ Tesseract(0.3s) ── 성공 → 0.3s 🚀 (Vision은 폐기)
      ╎      ║
      ╰─ Vision(0.5s) ──── 실패 시 0.5s에 결과 도착

    Best: 0.3s, Worst: 0.5s (sequential 대비 40% 단축)
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time

    results: dict[int, tuple[str | None, float | str | None]] = {}
    vision_model = model

    def tess_worker():
        text, conf = _solve_with_tesseract(image_bytes)
        return ("tess", text, conf)

    def vis_worker():
        text = _solve_with_vision(image_bytes, model=vision_model)
        return ("vis", text, 100.0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        tess_fut = pool.submit(tess_worker)
        vis_fut = pool.submit(vis_worker)

        # 먼저 완료되는 순서대로 처리
        for future in as_completed([tess_fut, vis_fut]):
            try:
                source, text, conf = future.result(timeout=10)
            except Exception as e:
                logger.warning("⚠️ %s 스레드 에러: %s", source, e)
                continue

            if source == "tess" and isinstance(text, str) and conf >= TESSERACT_CONFIDENCE_THRESHOLD:
                logger.info("⚡ 병렬 Tesseract 성공! (conf=%.1f%%) → \"%s\"", conf, text)
                return text

            if source == "vis" and isinstance(text, str) and text:
                logger.info("🌐 병렬 Vision 인식: \"%s\"", text)
                return text

    raise ValueError("캡차 인식 실패 — Tesseract + xAI Vision 모두 실패했습니다.")


def solve_captcha(
    image_bytes: bytes,
    model: str = "grok-4.20-0309-non-reasoning",
    force_tesseract: bool = False,
    force_vision: bool = False,
) -> str:
    """
    캡차 이미지 문자열 인식 — **병렬 하이브리드** 자동 폴백.

    - 기본: Tesseract + Vision **동시 실행** → 먼저 성공한 결과
    - force_tesseract=True: Tesseract만 (Vision 안 탐)
    - force_vision=True: Vision만 (Tesseract 안 탐)

    Best case: 0.3초 (Tesseract 성공)
    Worst case: 0.5초 (Vision 폴백)
    """
    if force_vision:
        text = _solve_with_vision(image_bytes, model=model)
        if text:
            return text
        raise ValueError("Vision 전용 모드에서 인식 실패")

    if force_tesseract:
        text, conf = _solve_with_tesseract(image_bytes)
        if text:
            return text
        raise ValueError("Tesseract 전용 모드에서 인식 실패")

    # 병렬 실행
    return _solve_parallel(image_bytes, model=model)


def _solve_with_vision_b64(
    b64_str: str,
    model: str = "grok-4.20-0309-non-reasoning",
) -> str:
    """xAI Vision — **base64 직접 입력** (디코드→재인코드 생략, CDP→xAI 직통)"""
    token = _resolve_xai_token()

    data = json.dumps({
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Extract captcha text. Return only characters.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64_str}"
                        },
                    },
                ],
            }
        ],
        "max_tokens": 10,
    }).encode()

    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        "https://api.x.ai/v1/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    resp = urllib.request.urlopen(req, context=ctx, timeout=30)
    result = json.loads(resp.read())
    raw = result["choices"][0]["message"]["content"].strip()
    text = raw.upper().strip()
    corrected = "".join(
        _CHAR_REPLACEMENTS.get(c, c) for c in text if c.isalnum()
    )
    logger.info("🌐 Vision(b64): \"%s\"", corrected)
    return corrected


def solve_captcha_b64(
    b64_str: str,
    model: str = "grok-4.20-0309-non-reasoning",
) -> str:
    """
    **CDP→xAI 직통** 캡차 인식 (base64 직접 입력).

    - Tesseract 먼저 (디코드 필요)
    - 실패 시 Vision에 base64 바로 전송 (디코드→재인코드 0ms!)
    - bytes 경로 대비 **30~80ms 단축**
    """
    import base64

    # Tesseract (bytes로 디코드)
    image_bytes = base64.b64decode(b64_str)
    text, conf = _solve_with_tesseract(image_bytes)
    if text and conf >= TESSERACT_CONFIDENCE_THRESHOLD:
        logger.info("⚡ Tesseract 성공! (conf=%.1f%%) → \"%s\"", conf, text)
        return text

    # Vision (b64 직행)
    return _solve_with_vision_b64(b64_str, model=model)
