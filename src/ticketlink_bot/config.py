"""
설정 관리 — YAML/환경변수/CLI args
"""
import copy
import json
import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "ticketlink-bot" / "config.yaml"

DEFAULT_CONFIG = {
    # Chrome
    "chrome": {
        "cdp_ports": [9222, 9223],
        "user_data_dir": str(Path.home() / ".config" / "chrome-cdp"),
    },
    # 예매 설정
    "booking": {
        "team": "LG 트윈스",
        "ticket_count": 2,
        "prefer_seat": "",
        "auto_captcha": True,
        "server_time": "",  # "10:00:00" 형식 — 새로고침 봇용
        "default_url": "https://www.ticketlink.co.kr/sports/137/59",
    },
    # xAI (캡차)
    "xai": {
        "api_type": "oauth",  # "vision" | "oauth"
        "api_key": "",         # 직접 API 키 (선택사항)
        "model": "grok-4.20-0309-non-reasoning",
    },
    # ===== 매크로 좌표 설정 =====
    "macro": {
        "click1": [0, 0],       # 예매하기 좌표
        "click2": [0, 0],       # 확인 좌표 (예매안내 모달)
        "click3": [0, 0],       # 선택완료 좌표
        "click4": [0, 0],       # 결제하기 좌표
        "captcha_submit": [0, 0],  # 보안문자 입력 확인 버튼 좌표
        "captcha_input": [0, 0],   # 보안문자 입력창 좌표 (매크로봇용)
        "date_click": [0, 0],   # 날짜 좌표 (선택)
        "round_click": [0, 0],  # 회차 좌표 (선택)
        "section_click": [0, 0],# 구역선택 좌표 (선택)
        "direct_select": [0, 0],# 직접선택 좌표 (선택, 구역선택→안내창 확인 사이)
        "click_guide": [0, 0],  # 안내창 확인 좌표 (선택, 구역선택→선택완료 사이)
        "captcha_area": [0, 0, 0, 0],  # 캡차 영역 [x1,y1,x2,y2] (선택, OCR 영역 제한)
        # ── 좌석 검색 영역 (다중 구역) ──
        # 통합매크로 방식: 여러 구역(zone) 각각 영역+색상 설정
        # 각 zone: {area: [↖x, ↖y, ↘x, ↘y], color: "BGR색상", tolerance: 오차범위}
        "seat_zones": [
            # {"area": [0, 0, 0, 0], "color": "C8C8C8", "tolerance": 20},  # 예시: 1구역
        ],
        # 하위호환: 단일 영역/색상 (zones가 비어있으면 이 값 사용)
        "seat_area": [0, 0, 0, 0],
        "seat_color": "C8C8C8",
        "color_tolerance": 20,
        "consecutive_seats": 2, # 몇 연석? (1=개별, 2=2연석...)
        "delays": {
            "click_wait": 3,    # 클릭 후 대기(초)
            "seat_click": 10,   # 좌석 잡는 순간 딜레이(ms)
            "section_move": 200,# 구역 이동 딜레이(ms)
            "refresh": 500,     # 새로고침 간격(ms)
            "captcha_typing_delay": 80,  # 캡차 글자간 입력 간격(ms), 비정상 빠른입력 방지
        },
        # ── 매크로 제어값 (하드코딩 대신 설정 가능) ──
        "max_retries": 30,        # 좌석 검색 최대 재시도 횟수
        "max_screenshot_fails": 5,# 스크린샷 연속 실패 허용 횟수
        "seat_search": {
            "row_tolerance": 30,     # 같은 열 판정 픽셀 오차
            "gap_tolerance": 40,     # 연속 좌석 간격 픽셀 오차
            "max_results_per_zone": 20,  # 구역당 최대 좌석 후보
        },
    },
    # 알림
    "notify": {
        "enabled": False,
        "webhook_url": "",
    },
    # 타임아웃
    "timeout": {
        "page_load": 10,
        "captcha": 30,
        "click_wait": 3,
    },
}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """
    설정 파일 로드. 없으면 기본값 사용.
    CLI args로 오버라이드 가능한 값들은 별도 처리.
    """
    cfg = copy.deepcopy(DEFAULT_CONFIG)  # deep copy — 내부 dict 독립 보장

    if path:
        config_path = Path(path)
    else:
        # 우선순위: CLI 지정 > XDG > 기본
        config_path = DEFAULT_CONFIG_PATH
        if not config_path.exists():
            # 현재 디렉토리 config.yaml (또는 실행파일 위치)
            local = Path("config.yaml")
            exe_local = None
            try:
                # PyInstaller --onefile: EXE 위치 기준
                import sys
                exe_dir = Path(sys.executable).parent
                exe_local = exe_dir / "config.yaml"
            except Exception:
                pass
            if local.exists():
                config_path = local
            elif exe_local and exe_local.exists():
                config_path = exe_local
            else:
                return cfg  # 기본값 사용

    if config_path.exists():
        with open(config_path) as f:
            if config_path.suffix in (".yaml", ".yml"):
                loaded = yaml.safe_load(f) or {}
            elif config_path.suffix == ".json":
                loaded = json.load(f)
            else:
                loaded = {}
        _deep_merge(cfg, loaded)

    # 환경변수 오버라이드 — (nesting_keys..., converter) 형식
    # converter가 None이면 str 그대로 사용
    env_overrides = [
        ("XAI_API_KEY", "xai", "api_key", None),
        ("XAI_API_TYPE", "xai", "api_type", None),
        ("TICKET_TEAM", "booking", "team", None),
        ("TICKET_COUNT", "booking", "ticket_count", int),
    ]
    for env_var, *keys_and_conv in env_overrides:
        val = os.environ.get(env_var)
        if val:
            *keys, converter = keys_and_conv
            if converter is None:
                _set_nested(cfg, keys, val)
            else:
                _set_nested(cfg, keys, converter(val))  # pylint: disable=not-callable

    return cfg


def _deep_merge(base: dict, override: dict) -> None:
    """딕셔너리 deep merge"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _set_nested(d: dict, keys: tuple, value: Any) -> None:
    """중첩 키에 값 설정"""
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


def save_config(cfg: dict, path: str | Path | None = None) -> Path:
    """설정 저장"""
    if path is None:
        path = DEFAULT_CONFIG_PATH
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        if path.suffix in (".yaml", ".yml"):
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
        else:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    return path
