#!/usr/bin/env python3
"""
🎫 ticketlink-bot — 안전한 진입점 (PyInstaller --onefile EXE 대응)

이 파일은 ticketlink_bot 패키지에 의존하지 않습니다.
모든 import를 try/except로 감싸서 EXE 크래시 시 traceback 출력 후 Enter 대기.
"""

import sys


def _print_crash_help() -> None:
    print()
    print("⚠️  EXE가 시작하자마자 꺼지는 경우:")
    print("   1. Tesseract OCR이 설치되지 않았거나 DLL 누락")
    print("   2. VC++ 재배포 가능 패키지 누락 (https://aka.ms/vs/17/release/vc_redist.x64.exe)")
    print("   3. Windows Defender가 차단 → '추가 정보' → '실행'")
    print("   4. Chrome이 --remote-debugging-port=9222 모드로 실행 안 됨")
    print()
    print("   위 traceback을 확인하거나 개발자에게 문의하세요.")


def _safe_entry() -> None:
    """Import + 실행을 try로 감싸서 모든 예외를 캐치"""
    try:
        import ticketlink_bot.__main__
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"\n❌ 모듈 로딩 실패: {exc}")
        _print_crash_help()
        input("\n   엔터를 누르면 종료합니다...")
        sys.exit(1)

    try:
        ticketlink_bot.__main__.main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"\n❌ 실행 중 오류: {exc}")
        print()
        print("   Chrome이 --remote-debugging-port=9222 인지 확인하세요.")
        print("   위 traceback을 확인하세요.")
        input("\n   엔터를 누르면 종료합니다...")
        sys.exit(1)


if __name__ == "__main__":
    _safe_entry()
