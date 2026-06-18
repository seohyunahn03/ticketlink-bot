#!/usr/bin/env python3
"""macOS .app 번들 + DMG 빌드 스크립트"""
import os, sys, shutil, subprocess, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
APP_NAME = "ticketlink-bot"
APP_DIR = ROOT / "dist" / f"{APP_NAME}.app"

def build_app():
    """PyInstaller --onedir로 .app 번들 생성"""
    import PyInstaller.__main__
    args = [
        "--windowed",             # GUI 앱 (터미널 없이)
        "--noconfirm",
        f"--name={APP_NAME}",
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={ROOT / 'build' / 'pyi-build'}",
        f"--specpath={ROOT / 'build'}",

        # 아이콘 (있는 경우)
        # "--icon=build/icon.icns",

        # 임포트
        "--hidden-import=websockets",
        "--hidden-import=websockets.speedups",
        "--hidden-import=yaml",
        "--hidden-import=_yaml",
        "--hidden-import=PIL",
        "--hidden-import=PIL._imaging",
        "--hidden-import=numpy",
        "--hidden-import=pytesseract",
        "--hidden-import=requests",

        # 진입점
        str(SRC / "ticketlink_bot" / "__main__.py"),
    ]

    print("🔨 macOS .app 빌드 중...")
    PyInstaller.__main__.run(args)

def create_launcher():
    """원클릭 런처 .command 생성"""
    launcher = ROOT / "dist" / "ticketlink-bot.command"
    launcher.write_text(
        '#!/bin/bash\n'
        f'cd "$(dirname "$0")"\n'
        f'open "{APP_NAME}.app" --args --pick\n'
    )
    launcher.chmod(0o755)
    print(f"  ✅ 런처: {launcher}")

def create_dmg():
    """DMG 생성 (create-dmi 없으면 간단히 폴더로)"""
    dmg_name = f"{APP_NAME}-macos.dmg"
    dmg_path = ROOT / "dist" / dmg_name
    
    # create-dmi 확인
    if shutil.which("create-dmg"):
        print("  📀 DMG 생성 중...")
        subprocess.run([
            "create-dmg",
            "--volname", f"{APP_NAME} v0.1.0",
            "--window-pos", "200", "200",
            "--window-size", "600", "400",
            "--icon", APP_NAME, "200", "170",
            "--app-drop-link", "400", "170",
            str(dmg_path),
            str(APP_DIR),
        ], check=True)
        print(f"  ✅ DMG: {dmg_path}")
        return dmg_path
    else:
        # 대안: .app를 zip으로
        zip_path = ROOT / "dist" / f"{APP_NAME}-macos.zip"
        if zip_path.exists():
            zip_path.unlink()
        shutil.make_archive(
            str(zip_path.with_suffix("")), "zip",
            ROOT / "dist", APP_NAME
        )
        print(f"  ✅ ZIP: {zip_path}")
        return zip_path

if __name__ == "__main__":
    build_app()
    create_launcher()
    dmg = create_dmg()
    print(f"\n✅ 빌드 완료!")
    print(f"   📦 {dmg}")
    print(f"   🖱️  더블클릭으로 실행!")
