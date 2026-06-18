"""
설정 관리 — YAML/환경변수/CLI args
"""
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
    },
    # xAI Vision (캡차)
    "xai": {
        "model": "grok-4.20-0309-non-reasoning",
    },
    # ===== 매크로 좌표 설정 =====
    "macro": {
        "click1": [0, 0],       # 예매하기 좌표
        "click2": [0, 0],       # 확인 좌표 (예매안내 모달)
        "click3": [0, 0],       # 선택완료 좌표
        "click4": [0, 0],       # 결제하기 좌표
        "date_click": [0, 0],   # 날짜 좌표 (선택)
        "round_click": [0, 0],  # 회차 좌표 (선택)
        "section_click": [0, 0],# 구역선택 좌표 (선택)
        # ── 좌석 검색 영역 (다중 구역) ──
        # 통합매크로 방식: 여러 구역(zone) 각각 영역+색상 설정
        # 각 zone: [↖x, ↖y, ↘x, ↘y, "BGR색상", 오차범위]
        "seat_zones": [
            # [0, 0, 0, 0, "C8C8C8", 20],  # 예시: 1구역
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
    cfg = dict(DEFAULT_CONFIG)  # shallow copy

    if path:
        config_path = Path(path)
    else:
        # 우선순위: CLI 지정 > XDG > 기본
        config_path = DEFAULT_CONFIG_PATH
        if not config_path.exists():
            # 현재 디렉토리 config.yaml
            local = Path("config.yaml")
            if local.exists():
                config_path = local
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

    # 환경변수 오버라이드
    env_overrides = {
        "XAI_API_KEY": ("xai", "api_key"),
        "TICKET_TEAM": ("booking", "team"),
        "TICKET_COUNT": ("booking", "ticket_count"),
    }
    for env_var, keys in env_overrides.items():
        val = os.environ.get(env_var)
        if val:
            _set_nested(cfg, keys, val)

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
