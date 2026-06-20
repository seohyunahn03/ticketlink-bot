#!/usr/bin/env python3
"""🎫 티켓링크봇 CLI — python -m ticketlink_bot

사용법:
  python -m ticketlink_bot              # GUI 실행 (기본)
  python -m ticketlink_bot --standalone # CLI 독립형 매크로
  python -m ticketlink_bot --config config.yaml
"""
import argparse
import logging
import sys

from .config import load_config


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stdout,
    )


def main() -> None:
    p = argparse.ArgumentParser(
        prog="ticketlink-bot",
        description="🎫 티켓링크 KBO 야구 예매 자동화 — 시스템 매크로",
    )

    p.add_argument("--standalone", action="store_true", help="CLI 독립형 매크로 (Chrome 불필요)")
    p.add_argument("--config", type=str, default=None, help="설정 파일 경로")
    p.add_argument("--verbose", action="store_true", help="디버그 로그 출력")
    p.add_argument("--version", action="store_true", help="버전 정보")

    args = p.parse_args()

    if args.version:
        from . import __version__
        print(f"ticketlink-bot v{__version__}")
        return

    _setup_logging(args.verbose)

    # --standalone → CLI 독립형 모드 (Chrome/CDP 불필요)
    if args.standalone:
        cfg = load_config(args.config)
        from .standalone import standalone_book
        print("🎫 티켓링크봇 — 독립형 모드 (Chrome 불필요)")
        print("=" * 50)
        result = standalone_book(cfg)
        print()
        if result["success"]:
            print(f"✅ {result['message']}")
        else:
            print(f"⚠️ {result['message']}")
        return

    # 기본: GUI 모드
    try:
        from .gui import run_gui
        run_gui()
        # EXE(--onefile)로 실행 시 종료 전 대기 (터미널 바로 꺼짐 방지)
        if getattr(sys, "frozen", False):
            print()
            input("   엔터를 누르면 종료합니다...")
    except ImportError as e:
        print(f"❌ GUI 실행 불가: {e}")
        print("   tkinter가 설치되어 있는지 확인하세요.")
        print("   CLI 모드: python -m ticketlink_bot --standalone")
        print()
        input("   엔터를 누르면 종료합니다...")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n❌ 치명적 오류: {e}")
        print("\n⚠️  EXE가 시작하자마자 꺼지면: DLL 누락 또는 import 실패입니다.")
        print("   위 traceback을 참고하거나 개발자에게 문의하세요.")
        print("\n   엔터를 누르면 종료합니다...")
        input()
        sys.exit(1)
