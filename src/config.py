"""
티켓팅 매크로 설정 관리
"""
import os
import yaml
from pathlib import Path

DEFAULT_CONFIG = {
    "browser": {
        "headless": False,
        "channel": "chrome",  # chrome, msedge, chromium
        "user_data_dir": None,
        "slow_mo": 50,  # ms between actions (anti-bot)
        "timeout": 30000,
        "viewport": {"width": 1280, "height": 900},
    },
    "interpark": {
        "id": "",
        "password": "",
        "login_url": "https://ticket.interpark.com/Gate/TPLogin.asp",
        "domain": "ticket.interpark.com",
    },
    "ticketlink": {
        "id": "",
        "password": "",
        "login_url": "https://www.ticketlink.co.kr/login",
        "domain": "www.ticketlink.co.kr",
    },
    "telegram": {
        "token": "",
        "chat_id": "",
        "enabled": False,
    },
    "paths": {
        "download": "./downloads",
        "screenshot": "./screenshots",
    },
}


def get_config_dir() -> Path:
    """설정 파일 디렉토리"""
    return Path(os.path.expanduser("~/.hermes/ticketing/config"))


def get_config_path() -> Path:
    return get_config_dir() / "config.yaml"


def load_config() -> dict:
    """설정 로드"""
    path = get_config_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return {**DEFAULT_CONFIG, **yaml.safe_load(f)}
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    """설정 저장"""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)


def setup_interactive():
    """대화형 설정 마법사"""
    cfg = load_config()
    print("=== 티켓팅 매크로 설정 ===\n")

    print("[인터파크/NOL 티켓]")
    cfg["interpark"]["id"] = input(f"  ID ({cfg['interpark']['id'] or '없음'}): ") or cfg["interpark"]["id"]
    cfg["interpark"]["password"] = input(f"  PW ({'*' * len(cfg['interpark']['password']) if cfg['interpark']['password'] else '없음'}): ") or cfg["interpark"]["password"]

    print("\n[티켓링크]")
    cfg["ticketlink"]["id"] = input(f"  ID ({cfg['ticketlink']['id'] or '없음'}): ") or cfg["ticketlink"]["id"]
    cfg["ticketlink"]["password"] = input(f"  PW ({'*' * len(cfg['ticketlink']['password']) if cfg['ticketlink']['password'] else '없음'}): ") or cfg["ticketlink"]["password"]

    print("\n[알림 (선택)]")
    yn = input("  텔레그램 알림 사용? (y/n): ").lower()
    if yn == "y":
        cfg["telegram"]["enabled"] = True
        cfg["telegram"]["token"] = input("  Bot Token: ") or cfg["telegram"]["token"]
        cfg["telegram"]["chat_id"] = input("  Chat ID: ") or cfg["telegram"]["chat_id"]

    save_config(cfg)
    print("\n✅ 설정 저장 완료!")
