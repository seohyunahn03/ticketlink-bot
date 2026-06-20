"""
🖥️ 티켓링크봇 GUI — 통합매크로 스타일

tkinter + ttk 기반 데스크탑 애플리케이션.
프리셋 관리, 좌표 편집, 좌석 영역 설정, 로그 출력, 시작/중지.
"""
import asyncio
import json
import logging
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Optional

from . import __version__
from .config import load_config, save_config, DEFAULT_CONFIG_PATH

logger = logging.getLogger("ticketlink_bot")

# ================================================================
#  스타일
# ================================================================

class _AppStyle:
    """통일된 UI 스타일"""
    BG = "#1e1e2e"          # 어두운 배경
    FG = "#cdd6f4"          # 밝은 텍스트
    ACCENT = "#89b4fa"      # 파란 강조
    SUCCESS = "#a6e3a1"     # 초록
    WARN = "#f9e2af"        # 노랑
    ERROR = "#f38ba8"       # 빨강
    SURFACE = "#313244"     # 카드 배경
    SURFACE2 = "#45475a"    # 경계선
    FONT = ("Segoe UI", 10)
    FONT_MONO = ("Menlo", 10)
    FONT_SMALL = ("Segoe UI", 9)
    FONT_TITLE = ("Segoe UI", 14, "bold")

    @classmethod
    def apply_theme(cls, root: tk.Tk):
        """다크 테마 적용"""
        root.configure(bg=cls.BG)
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TLabel", background=cls.BG, foreground=cls.FG, font=cls.FONT)
        style.configure("TFrame", background=cls.BG)
        style.configure("TButton", background=cls.SURFACE, foreground=cls.FG, font=cls.FONT, borderwidth=1)
        style.map("TButton", background=[("active", cls.ACCENT)])
        style.configure("TEntry", fieldbackground=cls.SURFACE2, foreground=cls.FG, font=cls.FONT_MONO)
        style.configure("TLabelframe", background=cls.BG, foreground=cls.FG)
        style.configure("TLabelframe.Label", background=cls.BG, foreground=cls.FG, font=cls.FONT)
        style.configure("TNotebook", background=cls.BG, foreground=cls.FG)
        style.configure("TNotebook.Tab", background=cls.SURFACE, foreground=cls.FG, padding=[10, 4])
        style.map("TNotebook.Tab", background=[("selected", cls.ACCENT)], foreground=[("selected", "#000")])
        style.configure("Vertical.TScrollbar", background=cls.SURFACE, troughcolor=cls.BG)
        style.configure("Accent.TButton", background=cls.ACCENT, foreground="#000", font=("Segoe UI", 11, "bold"))
        style.map("Accent.TButton", background=[("active", "#74c7ec")])
        style.configure("Success.TButton", background=cls.SUCCESS, foreground="#000", font=("Segoe UI", 11, "bold"))
        style.map("Success.TButton", background=[("active", "#94e2d5")])
        style.configure("Danger.TButton", background=cls.ERROR, foreground="#000", font=("Segoe UI", 11, "bold"))
        style.map("Danger.TButton", background=[("active", "#eba0ac")])


# ================================================================
#  로그 위젯 (Text + 스크롤)
# ================================================================

class _LogHandler(logging.Handler):
    """logging → tkinter Text 위젯"""
    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text = text_widget
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record):
        msg = self.format(record)
        try:
            self.text.after(0, self._append, msg)
        except Exception:
            pass

    def _append(self, msg: str):
        try:
            self.text.insert(tk.END, msg + "\n")
            self.text.see(tk.END)
        except Exception:
            pass


# ================================================================
#  메인 GUI
# ================================================================

class TicketlinkGUI(tk.Tk):
    """
    티켓링크봇 메인 윈도우.

    레이아웃:
        좌측: 프리셋 목록 (Listbox + 버튼)
        중앙: 노트북 (좌표 / 좌석영역 / 설정)
        하단: 로그 + 시작/중지 버튼
    """

    def __init__(self):
        super().__init__()
        self.title(f"🎫 티켓링크봇 v{__version__}")
        self.geometry("1100x750")
        self.minsize(900, 600)

        # 설정
        self._cfg = load_config()
        self._preset_dir = Path.home() / ".config" / "ticketlink-bot" / "presets"
        self._preset_dir.mkdir(parents=True, exist_ok=True)
        self._presets: list[str] = []
        self._current_preset = "default"
        self._running = False
        self._bot_ref = None  # Bot 인스턴스 참조

        # 스타일
        _AppStyle.apply_theme(self)

        # 레이아웃
        self._build_menu()
        self._build_ui()

        # 프리셋 로드
        self._scan_presets()
        self._load_preset("default")

        # 종료 처리
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 글로벌 핫키 (pynput)
        self._hotkey_listener = None
        self._init_hotkeys()

        # 중지 이벤트 (매크로 강제 중지용)
        self._stop_event = threading.Event()

        # 상태바 초기화
        self._toggle_mode()

    # ── 메뉴 ──

    def _build_menu(self):
        menubar = tk.Menu(self, bg=_AppStyle.SURFACE, fg=_AppStyle.FG,
                          activebackground=_AppStyle.ACCENT, activeforeground="#000")
        self.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0, bg=_AppStyle.SURFACE, fg=_AppStyle.FG,
                            activebackground=_AppStyle.ACCENT, activeforeground="#000")
        file_menu.add_command(label="설정 불러오기...", command=self._load_config_dialog)
        file_menu.add_command(label="설정 저장하기...", command=self._save_config_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="종료", command=self._on_close)
        menubar.add_cascade(label="파일", menu=file_menu)

        tool_menu = tk.Menu(menubar, tearoff=0, bg=_AppStyle.SURFACE, fg=_AppStyle.FG,
                            activebackground=_AppStyle.ACCENT, activeforeground="#000")
        tool_menu.add_command(label="🎯 좌표 따기 (글로벌)", command=self._run_global_picker)
        menubar.add_cascade(label="도구", menu=tool_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg=_AppStyle.SURFACE, fg=_AppStyle.FG,
                            activebackground=_AppStyle.ACCENT, activeforeground="#000")
        help_menu.add_command(label="사용법", command=self._show_help)
        help_menu.add_command(label="버전 정보", command=self._show_about)
        menubar.add_cascade(label="도움말", menu=help_menu)

    # ── UI 빌드 ──

    def _build_ui(self):
        """전체 레이아웃 구성"""
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # ── 좌측: 프리셋 패널 ──
        left = ttk.Frame(self, width=200)
        left.grid(row=0, column=0, sticky="ns", padx=(8, 4), pady=8)
        left.grid_propagate(False)

        ttk.Label(left, text="📋 프리셋", font=_AppStyle.FONT_TITLE).pack(anchor="w", pady=(0, 8))

        self._preset_listbox = tk.Listbox(
            left, bg=_AppStyle.SURFACE, fg=_AppStyle.FG,
            selectbackground=_AppStyle.ACCENT, selectforeground="#000",
            font=_AppStyle.FONT, relief="flat", borderwidth=0,
            highlightthickness=0,
        )
        self._preset_listbox.pack(fill="both", expand=True)
        self._preset_listbox.bind("<<ListboxSelect>>", self._on_preset_select)

        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_frame, text="➕ 추가", command=self._add_preset).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_frame, text="🗑 삭제", command=self._delete_preset).pack(side="left", fill="x", expand=True, padx=(2, 0))

        # ── 중앙: 노트북 ──
        center = ttk.Frame(self)
        center.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        center.grid_rowconfigure(0, weight=1)
        center.grid_columnconfigure(0, weight=1)

        notebook = ttk.Notebook(center)
        notebook.grid(row=0, column=0, sticky="nsew")

        # 탭 1: 좌표
        self._coord_frame = ttk.Frame(notebook)
        notebook.add(self._coord_frame, text="📍 좌표")
        self._build_coord_tab()

        # 탭 2: 좌석 영역
        self._zone_frame = ttk.Frame(notebook)
        notebook.add(self._zone_frame, text="🏟️ 좌석 영역")
        self._build_zone_tab()

        # 탭 3: 설정
        self._settings_frame = ttk.Frame(notebook)
        notebook.add(self._settings_frame, text="⚙️ 설정")
        self._build_settings_tab()

        # ── 하단: 로그 + 버튼 ──
        bottom = ttk.Frame(self)
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        bottom.grid_columnconfigure(0, weight=1)

        # 로그
        log_frame = ttk.LabelFrame(bottom, text="📋 로그")
        log_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)

        self._log_text = tk.Text(
            log_frame, height=8, bg=_AppStyle.SURFACE, fg=_AppStyle.FG,
            font=_AppStyle.FONT_MONO, relief="flat", borderwidth=0,
            state="normal", wrap="word",
        )
        self._log_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self._log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._log_text.configure(yscrollcommand=scrollbar.set)

        # 로깅 핸들러 연결
        self._log_handler = _LogHandler(self._log_text)
        logging.getLogger("ticketlink_bot").addHandler(self._log_handler)

        # 제어 버튼
        btn_row = ttk.Frame(bottom)
        btn_row.grid(row=1, column=0, sticky="ew")
        btn_row.grid_columnconfigure(2, weight=1)

        self._start_btn = ttk.Button(
            btn_row, text="▶ 시작 (F6)", style="Success.TButton",
            command=self._start_macro,
        )
        self._start_btn.grid(row=0, column=0, padx=(0, 4))

        self._stop_btn = ttk.Button(
            btn_row, text="⏹ 중지", style="Danger.TButton",
            command=self._stop_macro, state="disabled",
        )
        self._stop_btn.grid(row=0, column=1, padx=(0, 8))

        self._status_label = ttk.Label(btn_row, text="⏸ 대기중", font=_AppStyle.FONT)
        self._status_label.grid(row=0, column=2, sticky="w")

        # 상태바
        self._statusbar = ttk.Label(
            bottom, text=" [F6] 실행/중지  |  [ESC] 종료",
            font=_AppStyle.FONT_SMALL, foreground=_AppStyle.SURFACE2,
        )
        self._statusbar.grid(row=2, column=0, sticky="ew", pady=(4, 0))

    # ── 좌표 탭 ──

    def _build_coord_tab(self):
        """좌표 편집기"""
        frame = self._coord_frame
        frame.grid_columnconfigure(1, weight=1)

        fields = [
            ("click1", "1️⃣ 예매하기"),
            ("click2", "2️⃣ 확인 (예매안내 모달)"),
            ("captcha_submit", "3️⃣ 보안문자 확인 버튼"),
            ("section_click", "4️⃣ 구역선택 (선택)"),
            ("click3", "5️⃣ 선택완료"),
            ("click4", "6️⃣ 결제하기 (선택)"),
            ("date_click", "7️⃣ 날짜 선택 (선택)"),
            ("round_click", "8️⃣ 회차 선택 (선택)"),
        ]

        self._coord_vars = {}
        for i, (key, label) in enumerate(fields):
            ttk.Label(frame, text=label, font=_AppStyle.FONT).grid(
                row=i, column=0, sticky="w", pady=4, padx=(8, 4)
            )
            var = tk.StringVar(value="0, 0")
            entry = ttk.Entry(frame, textvariable=var, width=18)
            entry.grid(row=i, column=1, sticky="ew", padx=4, pady=2)
            self._coord_vars[key] = var

            btn_f = ttk.Frame(frame)
            btn_f.grid(row=i, column=2, sticky="w", padx=4)
            ttk.Button(btn_f, text="🎯 따기",
                       command=lambda k=key: self._pick_coord(k, use_global=False)).pack(
                           side="left", padx=1)
            ttk.Button(btn_f, text="🌐 글로벌",
                       command=lambda k=key: self._pick_coord(k, use_global=True)).pack(
                           side="left", padx=1)
            ttk.Button(btn_f, text="테스트",
                       command=lambda k=key: self._test_coord(k)).pack(
                           side="left", padx=1)

        ttk.Label(frame, text="", font=_AppStyle.FONT_SMALL).grid(row=len(fields), column=0, pady=8)

    # ── 좌석 영역 탭 ──

    def _build_zone_tab(self):
        """좌석 검색 영역 + 색상 설정"""
        frame = self._zone_frame
        frame.grid_columnconfigure(1, weight=1)

        row = 0
        ttk.Label(frame, text="🏟️ 좌석 검색 영역 (통합매크로 방식)", font=_AppStyle.FONT_TITLE).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 12), padx=8
        )
        row += 1

        # Zone 프레임
        self._zone_container = ttk.Frame(frame)
        self._zone_container.grid(row=row, column=0, columnspan=3, sticky="nsew")
        frame.grid_rowconfigure(row, weight=1)

        self._zone_frames = []
        self._add_zone_ui()

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=row + 1, column=0, columnspan=3, pady=8)
        ttk.Button(btn_row, text="➕ 구역 추가", command=self._add_zone_ui).pack(side="left", padx=4)
        ttk.Button(btn_row, text="🎨 색상 자동추출", command=self._auto_pick_color).pack(side="left", padx=4)

        # 범용 설정
        row += 2
        ttk.Label(frame, text="연석:").grid(row=row, column=0, sticky="w", padx=8)
        self._consecutive_var = tk.StringVar(value="2")
        ttk.Entry(frame, textvariable=self._consecutive_var, width=6).grid(
            row=row, column=1, sticky="w", padx=4)

        row += 1
        ttk.Label(frame, text="색상 오차범위:").grid(row=row, column=0, sticky="w", padx=8)
        self._tolerance_var = tk.StringVar(value="20")
        ttk.Entry(frame, textvariable=self._tolerance_var, width=6).grid(
            row=row, column=1, sticky="w", padx=4)

    def _add_zone_ui(self, area=None, color=None, tolerance=None):
        """Zone 편집 UI 추가"""
        idx = len(self._zone_frames)
        frame = ttk.LabelFrame(self._zone_container, text=f"Zone {idx + 1}")
        frame.pack(fill="x", pady=4, padx=4)

        vars = {
            "x1": tk.StringVar(value=str(area[0]) if area else "0"),
            "y1": tk.StringVar(value=str(area[1]) if area else "0"),
            "x2": tk.StringVar(value=str(area[2]) if area else "0"),
            "y2": tk.StringVar(value=str(area[3]) if area else "0"),
            "color": tk.StringVar(value=color or "C8C8C8"),
            "tolerance": tk.StringVar(value=str(tolerance or "20")),
        }

        ttk.Label(frame, text="↖좌상단:").grid(row=0, column=0, padx=4)
        ttk.Entry(frame, textvariable=vars["x1"], width=6).grid(row=0, column=1)
        ttk.Entry(frame, textvariable=vars["y1"], width=6).grid(row=0, column=2)
        ttk.Button(frame, text="🎯", width=3,
                   command=lambda: self._quick_pick(vars["x1"], vars["y1"])).grid(row=0, column=3, padx=2)

        ttk.Label(frame, text="↘우하단:").grid(row=1, column=0, padx=4)
        ttk.Entry(frame, textvariable=vars["x2"], width=6).grid(row=1, column=1)
        ttk.Entry(frame, textvariable=vars["y2"], width=6).grid(row=1, column=2)
        ttk.Button(frame, text="🎯", width=3,
                   command=lambda: self._quick_pick(vars["x2"], vars["y2"])).grid(row=1, column=3, padx=2)

        ttk.Label(frame, text="색상:").grid(row=2, column=0, padx=4)
        ttk.Entry(frame, textvariable=vars["color"], width=8).grid(row=2, column=1)
        ttk.Button(frame, text="🎨", width=3,
                   command=lambda: self._quick_pick_color(vars["color"])).grid(row=2, column=3, padx=2)

        ttk.Button(frame, text="❌", width=3,
                   command=lambda: (frame.destroy(), self._zone_frames.remove(vars))).grid(
                       row=0, column=4, rowspan=3, padx=8)

        self._zone_frames.append(vars)

    # ── 설정 탭 ──

    def _build_settings_tab(self):
        """설정 편집기"""
        frame = self._settings_frame
        frame.grid_columnconfigure(1, weight=1)

        fields = [
            ("team", "응원 팀:", self._cfg.get("booking", {}).get("team", "LG")),
            ("ticket_count", "매수:", str(self._cfg.get("booking", {}).get("ticket_count", 2))),
            ("click_wait", "클릭 후 대기(초):", "3"),
            ("seat_click", "좌석 딜레이(ms):", "10"),
            ("refresh", "새로고침 간격(ms):", "500"),
        ]

        self._settings_vars = {}
        for i, (key, label, default) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            var = tk.StringVar(value=default)
            entry = ttk.Entry(frame, textvariable=var, width=20)
            entry.grid(row=i, column=1, sticky="w", padx=4, pady=2)
            self._settings_vars[key] = var

        ttk.Label(frame, text="").grid(row=len(fields), column=0, pady=8)

        # 사용 모드
        self._standalone_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame, text="✅ 독립형 모드 (Chrome 불필요, pyautogui 시스템 클릭)",
            variable=self._standalone_var,
            command=self._toggle_mode,
        ).grid(row=len(fields) + 1, column=0, columnspan=2, sticky="w", padx=8)

        ttk.Label(
            frame, text="⚠️ Chrome 없이 모든 화면에서 동작. 좌표는 절대화면 좌표 사용.",
            font=_AppStyle.FONT_SMALL, foreground=_AppStyle.SUCCESS,
        ).grid(row=len(fields) + 2, column=0, columnspan=2, sticky="w", padx=16)

    # ── 좌표 따기 ──

    def _pick_coord(self, key: str, use_global: bool = False):
        """좌표 따기 실행"""
        threading.Thread(target=self._do_pick_coord, args=(key, use_global), daemon=True).start()

    def _do_pick_coord(self, key: str, use_global: bool):
        """별도 스레드에서 좌표 따기"""
        try:
            coord = self._run_picker_sync(use_global)
            if coord:
                x, y = coord["x"], coord["y"]
                self.after(0, lambda: self._coord_vars[key].set(f"{x}, {y}"))
                logger.info("✅ %s = (%d, %d)", key, x, y)
            else:
                logger.info("  ⏭️ 좌표 따기 취소")
        except Exception as e:
            logger.error("❌ 좌표 따기 실패: %s", e)

    def _run_picker_sync(self, use_global: bool):
        """동기식 좌표 따기 실행"""
        if use_global:
            from .picker import GlobalPicker
            picker = GlobalPicker()
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(picker.pick(timeout=60))
            finally:
                picker.close()
        else:
            # CDP picker (기존 pick_coordinates)
            try:
                from .booking import pick_coordinates
                from .bot import Bot
                bot = Bot()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(bot.connect(auto_launch=True))
                tab = loop.run_until_complete(bot.find_tab("ticketlink"))
                if not tab:
                    tab = loop.run_until_complete(bot.find_tab("야구"))
                if tab:
                    loop.run_until_complete(bot.attach(tab["targetId"]))
                result = loop.run_until_complete(pick_coordinates(bot, click_timeout=60))
                loop.run_until_complete(bot.close())
                return result
            except Exception as e:
                logger.error("❌ CDP picker 오류: %s", e)
                return None

    def _quick_pick(self, x_var, y_var):
        """빠른 좌표 따기 (zone용)"""
        coord = self._run_picker_sync(use_global=True)
        if coord:
            x_var.set(str(coord["x"]))
            y_var.set(str(coord["y"]))

    def _quick_pick_color(self, color_var):
        """색상 자동 추출"""
        coord = self._run_picker_sync(use_global=True)
        if coord:
            try:
                from .system_bot import SystemBot
                bgr = SystemBot.pixel(coord["x"], coord["y"])
                color_var.set(bgr)
                logger.info("  ✅ 색상: #%s", bgr)
            except Exception as e:
                logger.error("  ⚠️ 색상 추출 실패: %s", e)

    def _auto_pick_color(self):
        """Zone 영역에서 색상 자동 추출 (여러 좌표 평균)"""
        logger.info("🎨 빈 좌석(밝은색) 우클릭 → 색상 저장")
        coord = self._run_picker_sync(use_global=True)
        if coord:
            try:
                from .system_bot import SystemBot
                bgr = SystemBot.pixel(coord["x"], coord["y"])
                # 모든 zone에 적용
                for zv in self._zone_frames:
                    zv["color"].set(bgr)
                logger.info("  ✅ 모든 Zone 색상: #%s", bgr)
            except Exception as e:
                logger.error("  ⚠️ 색상 추출 실패: %s", e)

    def _test_coord(self, key: str):
        """좌표 테스트 클릭"""
        try:
            val = self._coord_vars[key].get()
            x, y = map(int, val.replace(" ", "").split(","))
            from .system_bot import SystemBot
            if SystemBot.available():
                SystemBot.click(x, y)
                logger.info("🖱️ 테스트 클릭 %s = (%d, %d)", key, x, y)
            else:
                logger.warning("⚠️ pyautogui 미설치")
        except Exception as e:
            logger.error("❌ 테스트 실패: %s", e)

    # ── 프리셋 관리 ──

    def _scan_presets(self):
        """프리셋 파일 목록 스캔"""
        self._presets = ["default"]
        if self._preset_dir.exists():
            for f in sorted(self._preset_dir.glob("*.yaml")):
                name = f.stem
                if name != "default":
                    self._presets.append(name)
        self._preset_listbox.delete(0, tk.END)
        for p in self._presets:
            self._preset_listbox.insert(tk.END, p)

    def _load_preset(self, name: str):
        """프리셋 로드"""
        self._current_preset = name
        path = self._preset_dir / f"{name}.yaml" if name != "default" else None
        self._cfg = load_config(path)
        self._apply_cfg_to_ui()

    def _save_preset(self, name: str):
        """프리셋 저장"""
        self._collect_ui_to_cfg()
        if name == "default":
            save_config(self._cfg)
        else:
            path = self._preset_dir / f"{name}.yaml"
            save_config(self._cfg, path)
        logger.info("✅ 프리셋 저장: %s", name)

    def _add_preset(self):
        """새 프리셋 추가"""
        name = self._simple_input("새 프리셋 이름", "프리셋 이름을 입력하세요:")
        if name and name.strip():
            name = name.strip()
            if name not in self._presets:
                self._presets.append(name)
                self._preset_listbox.insert(tk.END, name)
                self._load_preset(name)
                self._save_preset(name)

    def _delete_preset(self):
        """프리셋 삭제"""
        sel = self._preset_listbox.curselection()
        if not sel:
            return
        name = self._presets[sel[0]]
        if name == "default":
            messagebox.showwarning("⚠️", "기본 프리셋은 삭제할 수 없습니다.")
            return
        if messagebox.askyesno("삭제 확인", f"'{name}' 프리셋을 삭제할까요?"):
            path = self._preset_dir / f"{name}.yaml"
            if path.exists():
                path.unlink()
            self._presets.remove(name)
            self._scan_presets()

    def _on_preset_select(self, event):
        """프리셋 선택"""
        sel = self._preset_listbox.curselection()
        if sel:
            name = self._presets[sel[0]]
            self._load_preset(name)

    def _load_config_dialog(self):
        """외부 설정 파일 불러오기"""
        path = filedialog.askopenfilename(
            title="설정 파일 선택",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")]
        )
        if path:
            self._cfg = load_config(path)
            self._apply_cfg_to_ui()
            logger.info("✅ 설정 로드: %s", path)

    def _save_config_dialog(self):
        """설정 파일 저장"""
        self._collect_ui_to_cfg()
        path = filedialog.asksaveasfilename(
            title="설정 저장",
            defaultextension=".yaml",
            filetypes=[("YAML files", "*.yaml"), ("All files", "*.*")]
        )
        if path:
            save_config(self._cfg, path)
            logger.info("✅ 설정 저장: %s", path)

    def _simple_input(self, title: str, prompt: str) -> str:
        """간단 입력 대화상자"""
        return messagebox.askquestion(title, prompt)  # fallback

    # ── UI ↔ 설정 변환 ──

    def _apply_cfg_to_ui(self):
        """설정 → UI 위젯"""
        macro = self._cfg.get("macro", {})
        for key, var in self._coord_vars.items():
            val = macro.get(key, [0, 0])
            var.set(f"{val[0]}, {val[1]}")

        # Zone
        for f in self._zone_frames:
            f["frame"].destroy()
        self._zone_frames.clear()
        zones = macro.get("seat_zones", [])
        if not zones:
            area = macro.get("seat_area", [0, 0, 0, 0])
            if any(area):
                zones = [{"area": area, "color": macro.get("seat_color", "C8C8C8"),
                          "tolerance": macro.get("color_tolerance", 20)}]
        for z in zones:
            a = z.get("area", [0, 0, 0, 0])
            self._add_zone_ui(area=a, color=z.get("color", "C8C8C8"),
                              tolerance=z.get("tolerance", 20))

        self._consecutive_var.set(str(macro.get("consecutive_seats", 2)))
        self._tolerance_var.set(str(macro.get("color_tolerance", 20)))

        # Settings
        booking = self._cfg.get("booking", {})
        self._settings_vars["team"].set(booking.get("team", "LG"))
        self._settings_vars["ticket_count"].set(str(booking.get("ticket_count", 2)))
        delays = macro.get("delays", {})
        self._settings_vars["click_wait"].set(str(delays.get("click_wait", 3)))
        self._settings_vars["seat_click"].set(str(delays.get("seat_click", 10)))
        self._settings_vars["refresh"].set(str(delays.get("refresh", 500)))

    def _collect_ui_to_cfg(self):
        """UI → 설정"""
        macro = self._cfg.setdefault("macro", {})
        for key, var in self._coord_vars.items():
            try:
                parts = var.get().replace(" ", "").split(",")
                macro[key] = [int(parts[0]), int(parts[1])]
            except (ValueError, IndexError):
                macro[key] = [0, 0]

        # Zone
        zones = []
        for zv in self._zone_frames:
            try:
                zone = {
                    "area": [
                        int(zv["x1"].get()), int(zv["y1"].get()),
                        int(zv["x2"].get()), int(zv["y2"].get()),
                    ],
                    "color": zv["color"].get().strip() or "C8C8C8",
                    "tolerance": int(zv["tolerance"].get() or "20"),
                }
                zones.append(zone)
            except (ValueError, KeyError):
                pass
        if zones:
            macro["seat_zones"] = zones
            macro["seat_area"] = zones[0]["area"]
            macro["seat_color"] = zones[0]["color"]

        try:
            macro["consecutive_seats"] = int(self._consecutive_var.get())
        except ValueError:
            macro["consecutive_seats"] = 2
        try:
            macro["color_tolerance"] = int(self._tolerance_var.get())
        except ValueError:
            macro["color_tolerance"] = 20

        # Settings
        booking = self._cfg.setdefault("booking", {})
        booking["team"] = self._settings_vars["team"].get()
        try:
            booking["ticket_count"] = int(self._settings_vars["ticket_count"].get())
        except ValueError:
            booking["ticket_count"] = 2

        delays = macro.setdefault("delays", {})
        for k in ("click_wait", "seat_click", "refresh"):
            try:
                delays[k] = int(self._settings_vars.get(k, tk.StringVar(value="0")).get())
            except ValueError:
                delays[k] = {"click_wait": 3, "seat_click": 10, "refresh": 500}.get(k, 0)

    def _toggle_mode(self):
        """독립형/CDP 모드 전환 시 UI 업데이트"""
        mode = "독립형" if self._standalone_var.get() else "CDP 하이브리드"
        self._statusbar.configure(text=f" [F6] 실행/중지  |  [ESC] 종료  |  모드: {mode}")

    # ── 매크로 실행 ──

    def _start_macro(self):
        """매크로 시작"""
        self._collect_ui_to_cfg()
        self._running = True
        self._stop_event.clear()
        self._start_btn.configure(state="disabled", text="▶ 실행중...")
        self._stop_btn.configure(state="normal")
        self._status_label.configure(text="🟢 실행중", foreground=_AppStyle.SUCCESS)

        standalone = self._standalone_var.get()
        threading.Thread(target=self._run_macro, args=(standalone,), daemon=True).start()

    def _stop_macro(self):
        """매크로 중지"""
        self._running = False
        self._stop_event.set()
        self._start_btn.configure(state="normal", text="▶ 시작 (F6)")
        self._stop_btn.configure(state="disabled")
        self._status_label.configure(text="⏸ 중지됨", foreground=_AppStyle.WARN)

    def _run_macro(self, standalone_mode: bool):
        """별도 스레드에서 매크로 실행"""
        try:
            if standalone_mode:
                # ── 독립형 모드 (Chrome/CDP 불필요) ──
                logger.info("🚀 독립형 매크로 시작 (Chrome 불필요)")
                from .standalone import standalone_book
                result = standalone_book(self._cfg, stop_event=self._stop_event)
            else:
                # ── CDP 하이브리드 모드 ──
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    from .bot import Bot
                    bot = Bot()
                    loop.run_until_complete(bot.connect(auto_launch=True))

                    tab = loop.run_until_complete(bot.find_tab("ticketlink"))
                    if not tab:
                        tab = loop.run_until_complete(bot.find_tab("야구"))
                    if not tab:
                        default_url = self._cfg.get("booking", {}).get(
                            "default_url", "https://www.ticketlink.co.kr/sports/137/59"
                        )
                        result = loop.run_until_complete(
                            bot.cmd("Target.createTarget", {"url": default_url})
                        )
                        tab = result

                    if tab:
                        loop.run_until_complete(bot.attach(tab["targetId"]))
                        logger.info("✅ Chrome 연결 완료")

                    from .booking import full_auto_book
                    result = loop.run_until_complete(
                        full_auto_book(bot, self._cfg, use_system_click=True)
                    )
                    loop.run_until_complete(bot.close())
                finally:
                    loop.close()

            if result.get("success"):
                self.after(0, lambda: self._status_label.configure(
                    text="✅ 성공!", foreground=_AppStyle.SUCCESS))
                logger.info("🎉 %s", result.get("message", ""))
            else:
                self.after(0, lambda: self._status_label.configure(
                    text="⚠️ 실패", foreground=_AppStyle.ERROR))
                logger.warning("⚠️ %s", result.get("message", ""))
        except Exception as e:
            logger.error("❌ 매크로 오류: %s", e)
            import traceback
            traceback.print_exc()
        finally:
            self.after(0, self._stop_macro)

    # ── 도구 메뉴 ──

    def _run_global_picker(self):
        """글로벌 좌표 따기 도구"""
        logger.info("🌐 글로벌 좌표 따기 시작...")
        threading.Thread(target=self._do_global_pick, daemon=True).start()

    def _do_global_pick(self):
        coord = self._run_picker_sync(use_global=True)
        if coord:
            self.after(0, lambda: messagebox.showinfo(
                "좌표", f"📌 ({coord['x']}, {coord['y']})\n클립보드에 복사됨"))
            self.clipboard_clear()
            self.clipboard_append(f"{coord['x']}, {coord['y']}")

    def _run_cdp_picker(self):
        """CDP 좌표 따기 도구"""
        logger.info("🔍 Chrome 좌표 따기 시작...")
        threading.Thread(target=self._do_cdp_pick, daemon=True).start()

    def _do_cdp_pick(self):
        coord = self._run_picker_sync(use_global=False)
        if coord:
            self.after(0, lambda: messagebox.showinfo(
                "좌표", f"📌 ({coord['x']}, {coord['y']})"))

    # ── 도움말 ──

    def _show_help(self):
        messagebox.showinfo(
            "📖 사용법",
            "🎫 티켓링크봇 — KBO 야구 예매 자동화\n\n"
            "1. 좌표 설정: 각 버튼의 위치를 '따기' 버튼으로 설정\n"
            "2. 좌석 영역: 빈 좌석의 색상과 검색 영역 설정\n"
            "3. '시작' 버튼 또는 F6 키로 매크로 실행\n\n"
            "🎯 좌표 따기:\n"
            "  - '따기' 버튼 → Chrome에서 우클릭\n"
            "  - '글로벌' 버튼 → 화면 어디서나 우클릭\n\n"
            "⌨️ 단축키:\n"
            "  F6: 실행/중지 토글\n"
            "  ESC: 종료"
        )

    def _show_about(self):
        messagebox.showinfo(
            "ℹ️ 버전 정보",
            f"🎫 티켓링크봇 v{__version__}\n\n"
            "KBO 야구 예매 자동화 프로그램\n"
            "Chrome CDP + 시스템 매크로 하이브리드\n\n"
            "© 2026 ticketlink-bot"
        )

    # ── 글로벌 핫키 ──

    def _init_hotkeys(self):
        """pynput 글로벌 키보드 리스너 (F6/ESC)"""
        try:
            from pynput import keyboard as _kb
            def _on_press(key):
                try:
                    if key == _kb.Key.f6:
                        self.after(0, self._toggle_start_stop)
                    elif key == _kb.Key.esc:
                        self.after(0, self._on_close)
                except Exception:
                    pass
            self._hotkey_listener = _kb.Listener(on_press=_on_press)
            self._hotkey_listener.daemon = True
            self._hotkey_listener.start()
            logger.info("⌨️ 글로벌 핫키: F6=시작/중지, ESC=종료")
        except ImportError:
            logger.info("  pynput 미설치 — 글로벌 핫키 미지원")
        except Exception as e:
            logger.debug("  핫키 초기화 실패: %s", e)

    def _toggle_start_stop(self):
        """F6 핫키: 실행중이면 중지, 중지면 시작"""
        if self._running:
            self._stop_macro()
        else:
            self._start_macro()

    # ── 종료 ──

    def _on_close(self):
        """프로그램 종료"""
        if self._running:
            if not messagebox.askyesno("종료 확인", "매크로가 실행 중입니다. 종료할까요?"):
                return
        self._save_preset(self._current_preset)
        logging.getLogger("ticketlink_bot").removeHandler(self._log_handler)
        self.destroy()


# ================================================================
#  실행 진입점
# ================================================================

def run_gui():
    """GUI 실행 (메인 스레드에서 호출)"""
    app = TicketlinkGUI()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
