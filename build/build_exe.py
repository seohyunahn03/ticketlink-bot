#!/usr/bin/env python3
"""
📦 ticketlink-bot Windows EXE 빌드 스크립트 (PyInstaller)

사용법:
    python build/build_exe.py              # 기본 빌드
    python build/build_exe.py --upx-dir=..  # UPX 압축 지정
"""
import os
import sys
import site
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
OUTPUT_DIR = PROJECT_ROOT / "dist"
SPEC_DIR = PROJECT_ROOT / "build"


def build_exe(extra_args: list[str] | None = None) -> None:
    """PyInstaller로 단일 EXE 빌드"""
    try:
        import PyInstaller.__main__
    except ImportError:
        print("❌ PyInstaller가 설치되지 않았습니다.")
        print("   pip install pyinstaller")
        sys.exit(1)

    args = [
        "--onefile",              # 단일 EXE
        "--console",              # 콘솔 창 유지 (디버깅)
        "--noconfirm",            # 기존 dist 덮어쓰기
        f"--name=ticketlink-bot",
        f"--distpath={OUTPUT_DIR}",
        f"--workpath={SPEC_DIR / 'build'}",
        f"--specpath={SPEC_DIR}",

        # 데이터 파일 포함 (⚠️ OS별 separator: Windows=;, Linux/macOS=:)
        f"--add-data={SRC_DIR / 'ticketlink_bot'}{os.pathsep}ticketlink_bot",

        # 숨겨진 임포트 (PyInstaller가 자동 탐지 못하는 경우)
        "--hidden-import=websockets",
        "--hidden-import=websockets.__main__",
        "--hidden-import=websockets.speedups",
        "--hidden-import=yaml",
        "--hidden-import=_yaml",
        "--hidden-import=PIL",
        "--hidden-import=PIL._imaging",
        "--hidden-import=PIL.Image",
        "--hidden-import=numpy",
        "--hidden-import=pytesseract",
        "--hidden-import=requests",
        "--hidden-import=requests.utils",
        "--hidden-import=requests.packages.urllib3",

        # 런타임 훅 (Windows 콘솔 UTF-8)
        "--runtime-hook=rthooks/win_unicode.py" if os.name == "nt" else "",

        # 진입점
        str(SRC_DIR / "ticketlink_bot" / "__main__.py"),
    ]

    # extra args
    if extra_args:
        args.extend(extra_args)

    # 빈 문자열 제거
    args = [a for a in args if a]

    print(f"🔨 PyInstaller 빌드 시작...")
    print(f"   소스: {SRC_DIR / 'ticketlink_bot'}")
    print(f"   출력: {OUTPUT_DIR / 'ticketlink-bot.exe'}")
    print()

    PyInstaller.__main__.run(args)

    # 결과 확인
    exe_path = OUTPUT_DIR / "ticketlink-bot.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\n✅ 빌드 성공!")
        print(f"   📄 {exe_path}")
        print(f"   💾 {size_mb:.1f} MB")
    else:
        # Mac/Linux용 빌드
        alt = list(OUTPUT_DIR.glob("ticketlink-bot*"))
        if alt:
            size_mb = alt[0].stat().st_size / (1024 * 1024)
            print(f"\n✅ 빌드 성공!")
            print(f"   📄 {alt[0]}")
            print(f"   💾 {size_mb:.1f} MB")


def create_console_rthook() -> None:
    """Windows UTF-8 콘솔 런타임 훅 생성"""
    rthook_dir = SPEC_DIR / "rthooks"
    rthook_dir.mkdir(parents=True, exist_ok=True)
    hook = rthook_dir / "win_unicode.py"
    if not hook.exists():
        hook.write_text(
            "# Windows console UTF-8 setup\n"
            "import sys\n"
            "if sys.platform == 'win32':\n"
            "    import io\n"
            "    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')\n"
            "    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')\n"
            "    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')\n",
            encoding="utf-8"
        )


if __name__ == "__main__":
    create_console_rthook()
    build_exe(sys.argv[1:] if len(sys.argv) > 1 else None)
