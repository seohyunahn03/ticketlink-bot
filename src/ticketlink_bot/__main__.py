#!/usr/bin/env python3
"""
🎫 티켓링크봇 CLI — python -m ticketlink_bot

사용법:
  python -m ticketlink_bot                      # 현재 페이지 스캔
  python -m ticketlink_bot --auto                # 자동 예매
  python -m ticketlink_bot --auto --team "KIA"   # 특정 팀
  python -m ticketlink_bot --config config.yaml  # 설정 파일
"""
import argparse
import asyncio
import logging
import sys

from .bot import Bot, discover_cdp_url
from .booking import scan_and_book, click_and_book, pick_coordinates, full_auto_book
from .config import load_config, save_config

# ── F6 토글 감시 모드 ──
import threading as _threading
import time as _time


async def _draw_zone_rect(
    bot: "Bot", x1: int, y1: int, x2: int, y2: int, zone_num: int = 1,
) -> None:
    """화면에 좌석 검색 영역 사각형 오버레이 표시 (통합매크로 스타일)"""
    colors = ["#00ff88", "#ff8800", "#4488ff"]
    color = colors[(zone_num - 1) % len(colors)]
    await bot.js(f"""
        (() => {{
            const old = document.getElementById('_zone_rect_{zone_num}');
            if (old) old.remove();

            const rect = document.createElement('div');
            rect.id = '_zone_rect_{zone_num}';
            rect.style.cssText = `
                position:fixed;
                left:{min(x1,x2)}px; top:{min(y1,y2)}px;
                width:{abs(x2-x1)}px; height:{abs(y2-y1)}px;
                border:3px solid {color};
                background:rgba({','.join(str(int(color[i:i+2],16)) for i in (1,3,5))},0.08);
                z-index:999990;
                pointer-events:none;
                box-shadow: 0 0 8px {color}44;
            `;
            // 레이블
            const label = document.createElement('div');
            label.style.cssText = `
                position:absolute; top:-28px; left:4px;
                background:{color}; color:#000;
                padding:2px 10px; border-radius:4px;
                font:bold 14px sans-serif;
            `;
            label.textContent = 'Zone {zone_num}';
            rect.appendChild(label);

            // 구석 표시 (↖ ↙ ↗ ↘)
            const corners = ['↖', '↗', '↙', '↘'];
            const positions = [
                {{left:'-4px', top:'-4px'}},
                {{right:'-4px', top:'-4px'}},
                {{left:'-4px', bottom:'-4px'}},
                {{right:'-4px', bottom:'-4px'}},
            ];
            for (let i = 0; i < 4; i++) {{
                const dot = document.createElement('div');
                dot.textContent = corners[i];
                dot.style.cssText = `
                    position:absolute; font:bold 16px sans-serif;
                    color:{color}; text-shadow: 0 0 4px #000;
                    ${{Object.entries(positions[i]).map(([k,v]) => k+':'+v).join(';')}};
                `;
                rect.appendChild(dot);
            }}

            document.body.appendChild(rect);
        }})()
    """)


def _coord_list_to_zones(macro: dict) -> list[dict]:
    """하위호환: 기존 seat_area/seat_color를 zone으로 변환"""
    zones = macro.get("seat_zones", [])
    if not zones:
        area = macro.get("seat_area", [0, 0, 0, 0])
        color = macro.get("seat_color", "C8C8C8")
        tol = macro.get("color_tolerance", 20)
        if any(area):
            zones = [{"area": area, "color": color, "tolerance": tol}]
    return zones


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stdout,
    )


async def _main(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)

    _setup_logging(args.verbose)

    # CDP URL 확인
    cdp_url = discover_cdp_url(cfg.get("chrome", {}).get("cdp_ports", [9222, 9223]))
    if not cdp_url:
        from .bot import _chrome_launch_help
        print(
            "❌ Chrome CDP 연결 실패\n"
            "Chrome을 --remote-debugging-port=9222 로 실행해주세요:\n"
            + _chrome_launch_help()
        )
        return 1

    print(f"✅ Chrome CDP 연결")
    print(f"   {cdp_url[:60]}...")

    bot = Bot()
    await bot.connect(cdp_url)

    # 티켓링크 탭 찾기
    tab = await bot.find_tab("ticketlink")
    if not tab:
        tab = await bot.find_tab("야구")
    if not tab:
        print("❌ 티켓링크 탭 없음. Chrome에서 ticketlink.co.kr을 열어주세요!")
        await bot.close()
        return 1

    print(f"✅ 탭: {tab.get('title', '?')[:50]}")
    await bot.attach(tab["targetId"])

    if args.url:
        await bot.navigate(args.url)
        await asyncio.sleep(4)

    if args.pick:
        # ── 좌표 따기 모드 (통합매크로 방식, 다중 구역 지원) ──
        print("""
╔════════════════════════════════════════════════════════╗
║   🎯 티켓링크봇 — 좌표 따기 모드                      ║
║                                                        ║
║   통합매크로 방식으로 Chrome에서 직접 클릭하며          ║
║   좌표를 설정합니다.                                    ║
║                                                        ║
║   (각 단계: Chrome에서 해당 위치 클릭 → Enter)          ║
║   (건너뛰려면 그냥 Enter)                               ║
╚════════════════════════════════════════════════════════╝
        """)
        macro = cfg.setdefault("macro", {})

        # 1. 예매/확인/선택완료/결제 좌표
        steps = [
            ("click1",      "1/6 📌 예매하기 버튼을 클릭하세요"),
            ("click2",      "2/6 📌 확인 버튼 (예매안내 모달)"),
            ("section_click", "3/6 📌 구역선택 (없으면 엔터)"),
            ("click3",      "4/6 📌 선택완료 버튼"),
            ("click4",      "5/6 📌 결제하기 버튼 (없으면 엔터)"),
        ]
        for key, prompt in steps:
            print(f"\n{prompt}")
            input("    클릭 후 Enter → ")
            coord = await pick_coordinates(bot)
            if coord:
                macro[key] = [coord["x"], coord["y"]]
                print(f"    ✅ {key}: ({coord['x']}, {coord['y']})")
            else:
                print(f"    ⏭️ {key} 건너뜀")

        # 2. 날짜/회차 (선택)
        for key, prompt in [
            ("date_click", "6/6 📌 날짜 선택 (없으면 엔터)"),
            ("round_click", "7/6 📌 회차 선택 (없으면 엔터)"),
        ]:
            print(f"\n{prompt}")
            input("    클릭 후 Enter → ")
            coord = await pick_coordinates(bot)
            if coord:
                macro[key] = [coord["x"], coord["y"]]
                print(f"    ✅ {key}: ({coord['x']}, {coord['y']})")

        # 3. 좌석 검색 영역 — 다중 구역(zone) 설정
        print("""
╔════════════════════════════════════════════════════════╗
║   🏟️ 좌석 검색 영역 설정 (통합매크로 방식)             ║
║                                                        ║
║   여러 구역(zone)을 설정할 수 있습니다.                 ║
║   각 구역마다 ↖좌상단, ↘우하단 클릭 + 색상 설정.       ║
║   (예: 1루측, 3루측, 외야 등 구역별 색상이 다를 때)     ║
╚════════════════════════════════════════════════════════╝
        """)
        zone_count_str = input("    구역(zone) 개수 (기본 1, 최대 3): ").strip()
        try:
            zone_count = max(1, min(3, int(zone_count_str)))
        except ValueError:
            zone_count = 1

        seat_zones = []
        for zi in range(zone_count):
            print(f"\n─── Zone {zi + 1} ───")
            input(f"    {zi+1}-① ↖좌상단 클릭 → Enter ")
            p1 = await pick_coordinates(bot)
            input(f"    {zi+1}-② ↘우하단 클릭 → Enter ")
            p2 = await pick_coordinates(bot)

            if p1 and p2:
                # 사각형 오버레이 표시
                await _draw_zone_rect(bot, p1["x"], p1["y"], p2["x"], p2["y"], zi + 1)

                # 색상 설정
                print(f"    {zi+1}-③ 빈 좌석(밝은색) 클릭 → Enter")
                input("       ")
                color_coord = await pick_coordinates(bot)
                bgr = "C8C8C8"
                if color_coord:
                    from .seats import pick_color_at
                    try:
                        png = await bot.screenshot()
                        bgr = pick_color_at(png, color_coord["x"], color_coord["y"])
                        print(f"       ✅ 색상: #{bgr}")
                    except Exception as e:
                        print(f"       ⚠️ 색상 추출 실패: {e}")

                zone = {
                    "area": [p1["x"], p1["y"], p2["x"], p2["y"]],
                    "color": bgr,
                    "tolerance": macro.get("color_tolerance", 20),
                }
                seat_zones.append(zone)
                print(f"    ✅ Zone {zi+1} 등록: 영역={zone['area']}, 색상=#{bgr}")

        if seat_zones:
            macro["seat_zones"] = seat_zones
            # 하위호환: 첫 번째 zone의 값을 seat_area/seat_color에도 저장
            first = seat_zones[0]
            macro["seat_area"] = first["area"]
            macro["seat_color"] = first["color"]

        # 4. 연석 설정
        print(f"\n\n💺 몇 연석? (기본: {macro.get('consecutive_seats', 2)})")
        resp = input("    숫자 입력 (예: 2) → ").strip()
        if resp.isdigit() and int(resp) >= 1:
            macro["consecutive_seats"] = int(resp)
            print(f"    ✅ {macro['consecutive_seats']}연석")

        # 5. 오차범위
        print(f"\n🎨 색상 오차범위 (현재: {macro.get('color_tolerance', 20)})")
        print("    (통합매크로: 티켓링크 20~25, 인터파크 3)")
        resp = input("    숫자 입력 → ").strip()
        if resp.isdigit():
            macro["color_tolerance"] = int(resp)
            # 모든 zone에 오차범위 적용
            for z in macro.get("seat_zones", []):
                z["tolerance"] = int(resp)

        # 저장
        path = save_config(cfg)
        print(f"\n✅ 설정 저장 완료: {path}")
        print("\n🎯 이제 아래 명령어로 실행하세요:")
        print("    python -m ticketlink_bot --full")
        return 0

    if args.setup:
        # 대화형 설정 모드
        return await _interactive_setup(bot, cfg)

    if args.watch:
        return await _watch_loop(bot, cfg)

    if args.full:
        # 전체 자동 예매 (설정 기반)
        result = await full_auto_book(bot, cfg)
    elif args.click:
        # 좌표 클릭 모드
        parts = args.click.replace(" ", "").split(",")
        if len(parts) < 4:
            print("❌ --click 형식: x1,y1,x2,y2 (예: 800,500,900,600)")
            return 1
        x1, y1, x2, y2 = map(int, parts[:4])
        result = await click_and_book(
            bot,
            click1=(x1, y1),
            click2=(x2, y2),
            captcha_enabled=not args.no_captcha,
        )
    else:
        # 기존 자동/스캔 모드
        result = await scan_and_book(
            bot,
            auto=args.auto,
            team_keyword=args.team or cfg.get("booking", {}).get("team", "LG"),
            captcha_enabled=not args.no_captcha,
        )

    if result["success"]:
        print(f"\n✅ {result['message']}")
        print(f"📍 {result['url']}")
    else:
        print(f"\n⚠️ {result['message']}")

    await bot.close()
    return 0 if result["success"] else 1


# ================================================================
# 🔄 F6 토글 감시 모드 — 통합매크로 스타일
# ================================================================

class _ToggleController:
    """F6=토글, ESC=종료 키 리스너 (백그라운드 스레드)"""

    def __init__(self):
        self.enabled = True           # 시작 상태 = ON
        self.running = True           # 스레드 유지 플래그
        self._thread = None
        self._start_listener()

    def _start_listener(self):
        """OS별 키 리스너 시작"""
        if sys.platform == "win32":
            self._thread = _threading.Thread(target=self._win32_listen, daemon=True)
        else:
            self._thread = _threading.Thread(target=self._unix_listen, daemon=True)
        self._thread.start()

    def _win32_listen(self):
        """Windows: msvcrt (내장) — F6/ESC 감지"""
        import msvcrt
        while self.running:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch == b'\x00':  # 특수키 (F1-F12 등)
                    ch2 = msvcrt.getch()
                    if ch2 == b'\x75':  # VK_F6 = 117 = 0x75
                        self.enabled = not self.enabled
                        status = "🟢 실행" if self.enabled else "🔴 중지"
                        print(f"\n  [{status}] F6 토글")
                elif ch == b'\x1b':  # ESC
                    self.running = False
                    self.enabled = False
                    print("\n  ⏹️ ESC → 감시 종료")
            _time.sleep(0.05)

    def _unix_listen(self):
        """macOS/Linux: stdin 폴링 (fallback)"""
        import select
        while self.running:
            if select.select([sys.stdin], [], [], 0.05)[0]:
                try:
                    line = sys.stdin.readline().strip().lower()
                except (ValueError, OSError):
                    break
                if line in ("f6", "toggle"):
                    self.enabled = not self.enabled
                    status = "🟢 실행" if self.enabled else "🔴 중지"
                    print(f"\n  [{status}] 토글")
                elif line in ("esc", "exit", "quit"):
                    self.running = False
                    self.enabled = False
                    print("\n  ⏹️ 종료")

    def stop(self):
        self.running = False


async def _watch_loop(bot, cfg):
    """
    🔄 F6 토글 감시 모드 — 설정한 좌표로 계속 예매 시도.

    - F6: 시작/중지 토글
    - ESC: 완전 종료
    - 내부: full_auto_book()을 계속 반복
    """
    macro = cfg.get("macro", {})
    delays = macro.get("delays", {})
    refresh_delay = delays.get("refresh", 500) / 1000.0

    # ── Chrome 페이지에 상태 오버레이 주입 ──
    await bot.js(r"""
        (() => {
            if (document.getElementById('_macro_status')) return;
            const el = document.createElement('div');
            el.id = '_macro_status';
            el.innerHTML = `
                <div id="_ms_bg" style="
                    position:fixed; top:80px; right:20px; z-index:999999;
                    background:rgba(0,0,0,0.85); backdrop-filter:blur(8px);
                    border-radius:12px; padding:16px 20px; min-width:200px;
                    border:2px solid #00ff88; box-shadow:0 4px 20px rgba(0,255,136,0.3);
                    font-family:'Segoe UI',system-ui,sans-serif;
                    pointer-events:none; user-select:none;
                ">
                    <div style="font-size:13px; color:#888; margin-bottom:6px;">
                        🎫 ticketlink-bot
                    </div>
                    <div id="_ms_status" style="
                        font-size:18px; font-weight:bold; color:#00ff88;
                    ">
                        🟢 실행중
                    </div>
                    <div id="_ms_sub" style="
                        font-size:12px; color:#aaa; margin-top:6px;
                    ">
                        #0 시도중 · F6:토글 · ESC:종료
                    </div>
                </div>
            `;
            // 드래그 가능하게 (마우스 다운 → 이동)
            const bg = el.querySelector('#_ms_bg');
            let isDragging = false, startX, startY, origX, origY;
            bg.style.cursor = 'move';
            bg.style.pointerEvents = 'auto';
            bg.addEventListener('mousedown', e => {
                isDragging = true;
                startX = e.clientX;
                startY = e.clientY;
                origX = bg.offsetLeft || parseInt(bg.style.right || '20');
                origY = bg.offsetTop || 80;
                // right→left 변환
                bg.style.right = 'auto';
                bg.style.left = (window.innerWidth - bg.offsetWidth - 20) + 'px';
                origX = parseInt(bg.style.left);
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
            });
            function onMove(e) {
                if (!isDragging) return;
                bg.style.left = (origX + e.clientX - startX) + 'px';
                bg.style.top = (origY + e.clientY - startY) + 'px';
            }
            function onUp() {
                isDragging = false;
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            }
            document.body.appendChild(el);
        })();
    """)

    async def _update_overlay(status_text: str, color: str, sub_text: str):
        """Chrome 오버레이 상태 업데이트"""
        await bot.js(f"""
            const s = document.getElementById('_ms_status');
            if (s) {{
                s.textContent = '{status_text}';
                s.style.color = '{color}';
            }}
            const sub = document.getElementById('_ms_sub');
            if (sub) sub.textContent = '{sub_text}';
            const bg = document.getElementById('_ms_bg');
            if (bg) bg.style.borderColor = '{color}';
        """)

    await _update_overlay("🟢 실행중", "#00ff88", "#0 준비중 · F6:토글 · ESC:종료")

    print(r"""
╔══════════════════════════════════════════════════════╗
║   🔄 티켓링크봇 — 감시 모드                         ║
║                                                      ║
║   설정된 좌표로 계속 예매를 시도합니다.              ║
║   빈 좌석이 생기면 자동으로 예매를 진행합니다.       ║
║                                                      ║
║   [F6]  실행/중지 토글                               ║
║   [ESC] 프로그램 종료                                ║
║                                                      ║
║   상태: 🟢 실행중                                    ║
╚══════════════════════════════════════════════════════╝""")

    toggle = _ToggleController()
    attempt = 0

    try:
        while toggle.running:
            # ── 중지 상태면 대기 ──
            if not toggle.enabled:
                await _update_overlay("🔴 일시정지", "#ff4444", f"#{attempt} · F6:재개 · ESC:종료")
                await asyncio.sleep(0.2)
                continue

            attempt += 1
            status = "🟢 실행" if toggle.enabled else "🔴 중지"
            await _update_overlay("🟢 실행중", "#00ff88", f"#{attempt} 시도중 · F6:중지 · ESC:종료")
            print(f"\n{'='*50}")
            print(f"  [{status}] #{attempt}번째 예매 시도...")
            print(f"{'='*50}")

            try:
                result = await full_auto_book(bot, cfg)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"  ⚠️ 예외 발생: {e}")
                print(f"  ↻ {refresh_delay}초 후 재시도 (F6로 중지 가능)")
                await asyncio.sleep(refresh_delay)
                continue

            if result and result.get("success"):
                await _update_overlay("✅ 예매 성공!", "#ffd700", "📍 자동 종료됩니다")
                print(f"\n{'='*50}")
                print(f"  ✅ 예매 성공! 감시 모드 종료")
                print(f"  📍 {result.get('url', '')}")
                print(f"{'='*50}")
                break

            print(f"  ↻ 실패, {refresh_delay}초 후 재시도 (F6로 중지, ESC로 종료)")
            await _update_overlay("🔄 재시도중", "#ffaa00", f"#{attempt} 실패 · {refresh_delay}초 후 재시도")
            await asyncio.sleep(refresh_delay)

    except KeyboardInterrupt:
        await _update_overlay("⏹️ 사용자 종료", "#ff4444", "Ctrl+C 감지됨")
        print("\n\n  ⏹️ Ctrl+C 감지 → 종료")
    finally:
        toggle.stop()
        # 오버레이 제거
        try:
            await bot.js("document.getElementById('_macro_status')?.remove()")
        except Exception:
            pass

    await bot.close()
    return 0


# ================================================================
# 🎯 대화형 메뉴
# ================================================================

def _print_menu(cfg: dict) -> None:
    """메뉴 화면 출력"""
    from . import __version__
    macro = cfg.get("macro", {})
    zones = macro.get("seat_zones", [])
    has_zones = bool(zones) or any(macro.get("seat_area", [0]*4))
    has_coords = any([macro.get(k, [0])[0] for k in ("click1","click2")])
    
    # pre-compute values for f-string (avoid backslash issues)
    z_str = f"✅ {len(zones)}개 구역" if zones else (f"✅ 1개 영역" if any(macro.get("seat_area",[0]*4)) else "❌ 미설정")
    seat_str = macro.get("seat_color","C8C8C8")
    tol_str = macro.get("color_tolerance",20)
    con_str = f"{macro.get('consecutive_seats',2)}연석" if macro.get('consecutive_seats',2)>1 else f"{macro.get('consecutive_seats',2)}석"
    
    print(f"""
╔══════════════════════════════════════════════════════╗
║        🎫 티켓링크봇 - KBO 야구 예매 자동화          ║
║                    v{__version__}                               ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║  1️⃣  🎯 좌표 설정하기                               ║
║     (Chrome에서 직접 클릭해서 좌표+색상 저장)        ║
║                                                      ║
║  2️⃣  🔄 자동 예매 시작                              ║
║     (F6 시작/중지 · Chrome 오버레이 표시)            ║
║                                                      ║
║  3️⃣  ⚡ 한 번만 실행                                ║
║     (저장된 설정으로 1회 예매 시도)                  ║
║                                                      ║
║  4️⃣  🔐 xAI OAuth 로그인                            ║
║     (캡차 자동 인식용 - 폰 인증 가능)                ║
║                                                      ║
║  5️⃣  📋 설정 상태 보기                              ║
║     (저장된 좌표/색상/영역 확인)                     ║
║                                                      ║
╠══════════════════════════════════════════════════════╣
║  📌 예매 버튼: {_coord_status(macro, 'click1')} {"✅" if has_coords else "❌"}      ║
║     예매하기({_coord_str(macro,'click1')}) · 확인({_coord_str(macro,'click2')})      ║
║     선택완료({_coord_str(macro,'click3')}) · 결제({_coord_str(macro,'click4')})    ║
║     날짜({_coord_str(macro,'date_click')}) · 회차({_coord_str(macro,'round_click')})   ║
║  🏟️ 좌석영역: {z_str}     ║
║  🎨 색상: #{seat_str}  오차:{tol_str}  {con_str}  ║
╚══════════════════════════════════════════════════════╝
번호 입력 (1~5) 또는 q(종료) > """)


def _coord_str(macro: dict, key: str) -> str:
    v = macro.get(key, [0, 0])
    return f"({v[0]},{v[1]})" if v[0] or v[1] else "___"

def _coord_status(macro: dict, key: str) -> str:
    v = macro.get(key, [0, 0])
    return "✅" if v[0] or v[1] else "⭕"


async def _interactive_menu() -> None:
    """대화형 메뉴 — Chrome 연결 전에 표시"""
    cfg = load_config()
    _setup_logging()

    while True:
        _print_menu(cfg)
        choice = input().strip()

        if choice == "1":
            # ── 좌표 설정 (--pick) ──
            result = await _menu_connect_and_run(cfg, "pick")
            if result == 0:
                cfg = load_config()  # 설정 갱신
                input("\n✅ 좌표 설정 완료! 엔터 → 메뉴로...")
            else:
                input("\n❌ Chrome 연결 실패! 엔터 → 메뉴로...")

        elif choice == "2":
            # ── 감시 모드 (--watch) ──
            await _menu_connect_and_run(cfg, "watch")
            input("\n감시 모드 종료. 엔터 → 메뉴로...")

        elif choice == "3":
            # ── 한 번 실행 (--full) ──
            await _menu_connect_and_run(cfg, "full")
            input("\n실행 완료. 엔터 → 메뉴로...")

        elif choice == "4":
            # ── xAI OAuth 로그인 (CDP 불필요) ──
            try:
                from .oauth import xai_oauth_login, get_xai_token
                try:
                    token = get_xai_token()
                    if token:
                        print("✅ 이미 로그인되어 있습니다.")
                except Exception:
                    print("\n1: 로컬 브라우저 로그인")
                    print("2: 폰/원격 Device 인증")
                    resp = input("선택 (1/2/Enter=취소): ").strip()
                    if resp == "2":
                        from .oauth import xai_device_login
                        xai_device_login()
                    elif resp == "1":
                        xai_oauth_login()
            except Exception as e:
                print(f"❌ OAuth 로그인 실패: {e}")
            input("\n엔터 → 메뉴로...")

        elif choice == "5":
            # ── 설정 상태 보기 ──
            _show_config_status(cfg)
            input("\n엔터 → 메뉴로...")

        elif choice.lower() in ("q", "quit", "exit", "esc"):
            print("👋 종료합니다.")
            break

        else:
            print("⚠️ 1~5 또는 q를 입력하세요.")
            _time.sleep(1)


async def _menu_connect_and_run(cfg: dict, mode: str) -> int:
    """메뉴에서 Chrome CDP 연결 후 모드 실행"""
    # Chrome CDP 연결
    cdp_url = discover_cdp_url(cfg.get("chrome", {}).get("cdp_ports", [9222, 9223]))
    if not cdp_url:
        from .bot import _chrome_launch_help
        print("\n❌ Chrome CDP 연결 실패")
        print("Chrome을 --remote-debugging-port=9222 로 실행해주세요:")
        print(_chrome_launch_help())
        return 1

    print(f"✅ Chrome CDP 연결")
    bot = Bot()
    await bot.connect(cdp_url)

    # 티켓링크 탭 찾기
    tab = await bot.find_tab("ticketlink")
    if not tab:
        tab = await bot.find_tab("야구")
    if not tab:
        print("❌ 티켓링크 탭 없음. Chrome에서 ticketlink.co.kr을 열어주세요!")
        await bot.close()
        return 1

    print(f"✅ 탭: {tab.get('title', '?')[:50]}")
    await bot.attach(tab["targetId"])

    if mode == "pick":
        # 좌표 설정은 _main()이 Chrome 연결도 직접 하므로, 재사용
        import argparse
        dummy_args = argparse.Namespace(pick=True, setup=False, url=None,
            config=None, verbose=False, full=False, click=None, auto=False,
            team="", no_captcha=False, version=False, watch=False)
        await bot.close()
        return await _main(dummy_args)
    
    elif mode == "watch":
        return await _watch_loop(bot, cfg)

    elif mode == "full":
        from .booking import full_auto_book
        result = await full_auto_book(bot, cfg)
        if result.get("success"):
            print(f"\n✅ {result['message']}")
            print(f"📍 {result['url']}")
        else:
            print(f"\n⚠️ {result['message']}")
        await bot.close()
        return 0 if result.get("success") else 1

    return 0


def _show_config_status(cfg: dict) -> None:
    """저장된 설정 상태 출력"""
    macro = cfg.get("macro", {})
    print(f"""
╔══════════════════════════════════════════════════════╗
║                 📋 설정 상태                          ║
╠══════════════════════════════════════════════════════╣""")
    
    # 좌표 상태
    coord_keys = [("click1", "예매하기"), ("click2", "확인"), 
                  ("click3", "선택완료"), ("click4", "결제하기"),
                  ("date_click", "날짜선택"), ("round_click", "회차선택"),
                  ("section_click", "구역선택")]
    
    for key, label in coord_keys:
        val = macro.get(key, [0, 0])
        status = f"({val[0]}, {val[1]})" if val[0] != 0 or val[1] != 0 else "❌ 미설정"
        print(f"║  {label}: {status}")

    # 구역 상태
    zones = macro.get("seat_zones", [])
    if zones:
        print(f"║")
        for i, z in enumerate(zones):
            area = z.get("area", [0]*4)
            color = z.get("color", "?")
            tol = z.get("tolerance", 20)
            print(f"║  Zone {i+1}: 영역={area} 색상=#{color} 오차={tol}")
    else:
        area = macro.get("seat_area", [0]*4)
        if any(area):
            print(f"║  영역: {area} / 색상: #{macro.get('seat_color','?')} / 오차: {macro.get('color_tolerance',20)}")

    print(f"""║
║  연석: {macro.get('consecutive_seats', 2)}연석
║  새로고침: {macro.get('delays', {}).get('refresh', 500)}ms
╚══════════════════════════════════════════════════════╝""")


async def _interactive_setup(bot: Bot, cfg: dict) -> int:
    """대화형 설정 마법사 — OAuth 로그인 + 좌표/색상 설정"""
    import json as _json
    from .seats import pick_color_at
    from .oauth import xai_oauth_login, get_xai_token

    print("""
╔════════════════════════════════════════╗
║   🎫 티켓링크봇 설정 마법사           ║
║                                        ║
║   단계별로 Chrome에서 클릭하여         ║
║   좌표와 색상을 설정합니다.            ║
╚════════════════════════════════════════╝
    """)

    # ===== 0. xAI OAuth 로그인 =====
    try:
        token = get_xai_token()
        if token:
            print("✅ xAI OAuth: 이미 로그인됨")
    except Exception:
        print("\n📌 xAI OAuth 로그인이 필요합니다.")
        print("   1) 로컬 브라우저 로그인 (컴퓨터 앞에 있을 때)")
        print("   2) Device 인증 (폰/태블릿으로도 가능!)")
        print("   그냥 Enter → 건너뛰기")
        resp = input("   선택 (1/2): ").strip()
        try:
            if resp == "2":
                from .oauth import xai_device_login
                xai_device_login()
                print("✅ Device 인증 완료!")
            elif resp != "":
                from .oauth import xai_oauth_login
                xai_oauth_login()
        except Exception as e:
            print(f"   ⚠️ OAuth 로그인 실패: {e}")
            print("   건너뜁니다. --setup을 다시 실행하거나")
            print('   환경변수 XAI_API_KEY를 설정하세요.')

    macro = cfg.setdefault("macro", {})

    steps = [
        ("click1", "1/8 📌 예매하기 버튼을 클릭하세요"),
        ("click2", "2/8 📌 확인 버튼을 클릭하세요 (예매안내 모달)"),
        ("section_click", "3/8 📌 구역선택 버튼 (없으면 엔터)"),
        ("click3", "4/8 📌 선택완료 버튼을 클릭하세요"),
        ("click4", "5/8 📌 결제하기 버튼 (없으면 엔터)"),
        ("date_click", "6/8 📌 날짜 선택 버튼을 클릭 (없으면 엔터)"),
        ("round_click", "7/8 📌 회차 선택 버튼을 클릭 (없으면 엔터)"),
    ]

    for key, prompt in steps:
        input(f"\n{prompt}\n    준비되면 Enter → ")
        coord = await pick_coordinates(bot)
        if coord:
            macro[key] = [coord["x"], coord["y"]]
            print(f"    ✅ {key} = ({coord['x']}, {coord['y']})")
        else:
            print("    ⏭️ 건너뜀")

    # 좌석 범위 설정 — 다중 구역(zone) 지원
    print("""
╔════════════════════════════════════════════════════════╗
║   🏟️ 좌석 검색 영역 설정                             ║
║                                                        ║
║   여러 구역(zone)을 설정할 수 있습니다.                ║
║   zone 2+는 선택사항 (없으면 엔터로 건너뛰기).         ║
╚════════════════════════════════════════════════════════╝
    """)

    zone_count_str = input("    구역(zone) 개수 (기본 1, 최대 3): ").strip()
    try:
        zone_count = max(1, min(3, int(zone_count_str)))
    except ValueError:
        zone_count = 1

    seat_zones = []
    for zi in range(zone_count):
        print(f"\n─── Zone {zi + 1} ───")
        input(f"    {zi+1}-① ↖좌상단 클릭 → Enter ")
        p1 = await pick_coordinates(bot)
        input(f"    {zi+1}-② ↘우하단 클릭 → Enter ")
        p2 = await pick_coordinates(bot)

        if p1 and p2:
            await _draw_zone_rect(bot, p1["x"], p1["y"], p2["x"], p2["y"], zi + 1)

            print(f"    {zi+1}-③ 빈 좌석(밝은색) 클릭 → Enter")
            input("       ")
            color_coord = await pick_coordinates(bot)
            bgr = "C8C8C8"
            if color_coord:
                try:
                    png = await bot.screenshot()
                    bgr = pick_color_at(png, color_coord["x"], color_coord["y"])
                    print(f"       ✅ 색상: #{bgr}")
                except Exception as e:
                    print(f"       ⚠️ 색상 추출 실패: {e}")

            zone = {
                "area": [p1["x"], p1["y"], p2["x"], p2["y"]],
                "color": bgr,
                "tolerance": macro.get("color_tolerance", 20),
            }
            seat_zones.append(zone)
            print(f"    ✅ Zone {zi+1} 등록")

    if seat_zones:
        macro["seat_zones"] = seat_zones
        first = seat_zones[0]
        macro["seat_area"] = first["area"]
        macro["seat_color"] = first["color"]

    print(f"\n🎨 색상 오차범위 (현재: {macro.get('color_tolerance', 20)})")
    print("   (통합매크로: 티켓링크 20~25, 인터파크 3)")
    resp = input("   숫자 입력 → ").strip()
    if resp.isdigit():
        macro["color_tolerance"] = int(resp)
        for z in macro.get("seat_zones", []):
            z["tolerance"] = int(resp)

    # 연석 설정
    print(f"\n💺 몇 연석? (현재: {macro.get('consecutive_seats', 2)})")
    resp = input("   숫자 입력 (예: 2) → ").strip()
    if resp.isdigit() and int(resp) >= 1:
        macro["consecutive_seats"] = int(resp)
        print(f"   ✅ {macro['consecutive_seats']}연석")

    # 저장
    path = save_config(cfg)
    print(f"\n✅ 설정 저장 완료: {path}")
    print("\n🎯 이제 아래 명령어로 실행하세요:")
    print("    python -m ticketlink_bot --full")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        description="🎫 티켓링크봇 — KBO 야구 예매 자동화"
    )
    p.add_argument("--auto", action="store_true", help="전체 자동 예매")
    p.add_argument("--full", action="store_true", help="전체 자동 예매 (설정파일 기반 매크로)")
    p.add_argument("--pick", action="store_true", help="좌표 따기 모드")
    p.add_argument("--setup", action="store_true", help="대화형 설정 마법사")
    p.add_argument("--watch", action="store_true", help="감시 모드 (F6 시작/중지, ESC 종료)")
    p.add_argument("--click", help="좌표 클릭 모드: x1,y1,x2,y2 (예매하기, 확인)")
    p.add_argument("--team", default="", help="응원 팀명 (예: LG, KIA, 두산)")
    p.add_argument("--url", help="시작 페이지 URL")
    p.add_argument("--config", help="설정 파일 경로")
    p.add_argument("--no-captcha", action="store_true", help="캡차 자동 입력 비활성화")
    p.add_argument("-v", "--verbose", action="store_true", help="상세 로그")
    p.add_argument("--version", action="store_true", help="버전 정보")

    args = p.parse_args()

    if args.version:
        from . import __version__
        print(f"ticketlink-bot v{__version__}")
        return

    # 플래그가 하나도 없으면 → 대화형 메뉴 표시
    has_action = any([args.auto, args.full, args.pick, args.setup, args.watch, args.click])
    if not has_action:
        asyncio.run(_interactive_menu())
        return

    exit_code = asyncio.run(_main(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n❌ 치명적 오류: {e}")
        print("\n⚠️  EXE가 시작하자마자 꺼지면: DLL 누락 또는 import 실패입니다.")
        print("   위 traceback을 보고하거나, 관리자에게 문의하세요.")
        print("\n   엔터를 누르면 종료합니다...")
        input()
        sys.exit(1)
