"""
🖥️ 티켓링크봇 GUI — 통합매크로 스타일

tkinter + ttk 기반 데스크탑 애플리케이션.
프리셋 관리, 좌표 편집, 좌석 영역 설정, 로그 출력, 시작/중지.
"""
import asyncio
import logging
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from pathlib import Path
from typing import Optional

from . import __version__
from .config import load_config, save_config

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

        # 이중봇 상태 (F6=새로고침, F8=매크로)
        self._refresh_running = False
        self._macro_running = False
        self._hybrid_running = False  # F9=하이브리드 새로고침
        self._refresh_stop_event = threading.Event()
        self._macro_stop_event = threading.Event()
        self._hybrid_stop_event = threading.Event()

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

        # 서버시간 오프셋 (HTTP Date 헤더 측정값, 초 단위)
        self._server_offset = 0.0

        # 상태바 초기화
        self._statusbar.configure(text=' [F6] 새로고침봇  |  [F8] 매크로봇  |  [F9] 하이브리드  |  [ESC] 종료')

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

        # 탭 3: 설정 (스크롤 가능)
        _settings_outer = ttk.Frame(notebook)
        notebook.add(_settings_outer, text="⚙️ 설정")
        _settings_outer.grid_rowconfigure(0, weight=1)
        _settings_outer.grid_rowconfigure(1, weight=0)
        _settings_outer.grid_columnconfigure(0, weight=1)

        _canvas = tk.Canvas(_settings_outer, bg=_AppStyle.BG, highlightthickness=0)
        _vscroll = ttk.Scrollbar(_settings_outer, orient="vertical", command=_canvas.yview)
        _hscroll = ttk.Scrollbar(_settings_outer, orient="horizontal", command=_canvas.xview)
        self._settings_frame = ttk.Frame(_canvas)
        self._settings_frame.bind(
            "<Configure>",
            lambda e: _canvas.configure(scrollregion=_canvas.bbox("all")),
        )
        _canvas.create_window((0, 0), window=self._settings_frame, anchor="nw")
        _canvas.configure(yscrollcommand=_vscroll.set, xscrollcommand=_hscroll.set)

        _canvas.grid(row=0, column=0, sticky="nsew")
        _vscroll.grid(row=0, column=1, sticky="ns")
        _hscroll.grid(row=1, column=0, sticky="ew")

        # 마우스 휠 스크롤 (Canvas 영역 진입/이탈)
        def _on_mousewheel(event):
            _canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _on_shift_mousewheel(event):
            _canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        _canvas.bind("<Enter>", lambda e: (
            _canvas.bind_all("<MouseWheel>", _on_mousewheel),
            _canvas.bind_all("<Shift-MouseWheel>", _on_shift_mousewheel),
        ))
        _canvas.bind("<Leave>", lambda e: (
            _canvas.unbind_all("<MouseWheel>"),
            _canvas.unbind_all("<Shift-MouseWheel>"),
        ))
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

        # 제어 버튼 (이중봇: F6=새로고침, F7=매크로)
        btn_row = ttk.Frame(bottom)
        btn_row.grid(row=1, column=0, sticky="ew")
        btn_row.grid_columnconfigure(4, weight=1)

        # 새로고침 봇 (F6)
        self._refresh_btn = ttk.Button(
            btn_row, text="🔄 새로고침 (F6)", style="Success.TButton",
            command=self._toggle_refresh,
        )
        self._refresh_btn.grid(row=0, column=0, padx=(0, 4))

        # 매크로 봇 (F8)
        self._macro_btn = ttk.Button(
            btn_row, text="⚡ 매크로 (F8)", style="Accent.TButton",
            command=self._toggle_macro,
        )
        self._macro_btn.grid(row=0, column=1, padx=(0, 4))

        # 하이브리드 새로고침 (F9)
        self._hybrid_btn = ttk.Button(
            btn_row, text="🔄 하이브리드 (F9)", style="Accent.TButton",
            command=self._toggle_hybrid,
        )
        self._hybrid_btn.grid(row=0, column=2, padx=(0, 4))

        # 전체 중지
        self._stop_all_btn = ttk.Button(
            btn_row, text="⏹ 전체 중지", style="Danger.TButton",
            command=self._stop_all,
        )
        self._stop_all_btn.grid(row=0, column=3, padx=(0, 8))

        # 상태 레이블
        self._status_label = ttk.Label(btn_row, text="⏸ 대기중", font=_AppStyle.FONT)
        self._status_label.grid(row=0, column=3, sticky="w", padx=(0, 4))

        # 개별 상태 표시 (작은 텍스트)
        self._refresh_status_label = ttk.Label(btn_row, text="", font=_AppStyle.FONT_SMALL, foreground=_AppStyle.SURFACE2)
        self._refresh_status_label.grid(row=0, column=4, sticky="w")

        # 상태바
        self._statusbar = ttk.Label(
            bottom, text=" [F6] 새로고침봇  |  [F8] 매크로봇  |  [ESC] 종료",
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
            ("captcha_input", "3️⃣ 보안문자 입력창 (매크로봇용)"),
            ("captcha_submit", "4️⃣ 보안문자 확인 버튼"),
            ("section_click", "5️⃣ 구역선택 (선택)"),
            ("direct_select", "🆕 직접선택 (선택)"),
            ("click_guide", "🔟 안내창 확인 (선택)"),
            ("click3", "6️⃣ 선택완료"),
            ("click4", "7️⃣ 결제하기 (선택)"),
            ("date_click", "8️⃣ 날짜 선택 (선택)"),
            ("round_click", "9️⃣ 회차 선택 (선택)"),
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

        # ── 좌표 전체 초기화 버튼 ──
        reset_frame = ttk.Frame(frame)
        reset_frame.grid(row=len(fields) + 1, column=0, columnspan=3, pady=4)
        ttk.Button(
            reset_frame, text="🗑️ 좌표 전체 초기화",
            command=self._reset_all_coords,
            style="Danger.TButton",
        ).pack(side="left", padx=4)
        ttk.Label(
            reset_frame, text="모든 좌표를 (0, 0)으로 리셋",
            font=_AppStyle.FONT_SMALL, foreground=_AppStyle.SURFACE2,
        ).pack(side="left", padx=4)

    # ── 좌표 초기화 ──
    def _reset_all_coords(self):
        """모든 좌표를 (0, 0)으로 초기화"""
        if not messagebox.askyesno("좌표 초기화",
                                    "모든 좌표를 (0, 0)으로 초기화할까요?",
                                    parent=self):
            return
        for key, var in self._coord_vars.items():
            var.set("0, 0")
        logger.info("🗑️ 모든 좌표가 (0, 0)으로 초기화되었습니다")

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
        # tolerance var는 _add_zone_ui()보다 먼저 초기화
        self._tolerance_var = tk.StringVar(value="20")
        self._add_zone_ui()

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=row + 1, column=0, columnspan=3, pady=8)
        ttk.Button(btn_row, text="➕ 구역 추가", command=self._add_zone_ui).pack(side="left", padx=4)
        ttk.Button(btn_row, text="🎨 좌석 클릭해서 색상추출", command=self._auto_pick_color).pack(side="left", padx=4)

        # 범용 설정
        row += 2
        ttk.Label(frame, text="연석:").grid(row=row, column=0, sticky="w", padx=8)
        self._consecutive_var = tk.StringVar(value="2")
        ttk.Entry(frame, textvariable=self._consecutive_var, width=6).grid(
            row=row, column=1, sticky="w", padx=4)

        row += 1
        ttk.Label(frame, text="색상 오차범위:").grid(row=row, column=0, sticky="w", padx=8)
        ttk.Entry(frame, textvariable=self._tolerance_var, width=6).grid(
            row=row, column=1, sticky="w", padx=4)

        # ── 좌석 검색 파라미터 ──
        row += 1
        ttk.Label(frame, text="", font=_AppStyle.FONT_SMALL).grid(row=row, column=0, pady=4)
        row += 1
        ttk.Label(frame, text="⚙️ 좌석 검색 파라미터", font=("", 10, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))

        seat_search_params = [
            ("row_tolerance", "같은열 오차(px):", str(
                self._cfg.get("macro", {}).get("seat_search", {}).get("row_tolerance", 30))),
            ("gap_tolerance", "좌석간격 오차(px):", str(
                self._cfg.get("macro", {}).get("seat_search", {}).get("gap_tolerance", 40))),
            ("max_results_per_zone", "구역당 최대후보:", str(
                self._cfg.get("macro", {}).get("seat_search", {}).get("max_results_per_zone", 20))),
        ]
        self._seat_search_vars = {}
        for key, label, default in seat_search_params:
            row += 1
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=3)
            var = tk.StringVar(value=default)
            ttk.Entry(frame, textvariable=var, width=8).grid(
                row=row, column=1, sticky="w", padx=4)
            self._seat_search_vars[key] = var

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
            "tolerance": tk.StringVar(value=str(tolerance) if tolerance is not None else self._tolerance_var.get()),
            "frame": frame,
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
                   command=lambda v=vars, f=frame: (f.destroy(), self._zone_frames.remove(v) if v in self._zone_frames else None)).grid(
                       row=0, column=4, rowspan=3, padx=8)

        self._zone_frames.append(vars)

    # ── 설정 탭 ──

    def _build_settings_tab(self):
        """설정 편집기"""
        frame = self._settings_frame
        frame.grid_columnconfigure(1, weight=1)
        self._settings_vars = {}

        row = 0

        # ── 예매 기본 ──
        ttk.Label(frame, text="📋 예매 기본", font=("", 10, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        row += 1

        # team, ticket_count (loop)
        simple_fields = [
            ("team", "응원 팀:", self._cfg.get("booking", {}).get("team", "LG 트윈스")),
            ("ticket_count", "매수:", str(self._cfg.get("booking", {}).get("ticket_count", 2))),
        ]
        for key, label, default in simple_fields:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
            var = tk.StringVar(value=default)
            ttk.Entry(frame, textvariable=var, width=20).grid(
                row=row, column=1, sticky="w", padx=4, pady=2)
            self._settings_vars[key] = var
            row += 1

        # server_time + "불러오기" 버튼
        ttk.Label(frame, text="서버시간 (HH:MM:SS):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        self._server_time_var = tk.StringVar(
            value=self._cfg.get("booking", {}).get("server_time", ""))
        ttk.Entry(frame, textvariable=self._server_time_var, width=12).grid(
            row=row, column=1, sticky="w", padx=4, pady=2)
        ttk.Button(frame, text="🔍 서버시간 불러오기",
                   command=self._fetch_server_time).grid(
            row=row, column=2, sticky="w", padx=4)
        row += 1

        # default_url + "열기" 버튼
        ttk.Label(frame, text="예매 URL:").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        self._default_url_var = tk.StringVar(
            value=self._cfg.get("booking", {}).get("default_url",
                  "https://www.ticketlink.co.kr/sports/137/59"))
        url_entry = ttk.Entry(frame, textvariable=self._default_url_var, width=40)
        url_entry.grid(row=row, column=1, sticky="ew", padx=4, pady=2)
        ttk.Button(frame, text="🌐 열기",
                   command=lambda: self._open_url(self._default_url_var.get())).grid(
            row=row, column=2, sticky="w", padx=4)
        row += 1

        # prefer_seat
        ttk.Label(frame, text="선호 좌석:").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        self._prefer_seat_var = tk.StringVar(
            value=self._cfg.get("booking", {}).get("prefer_seat", ""))
        ttk.Entry(frame, textvariable=self._prefer_seat_var, width=20).grid(
            row=row, column=1, sticky="w", padx=4, pady=2)
        row += 1

        # ── 딜레이/제어값 ──
        ttk.Label(frame, text="⏱️ 딜레이 & 제어값", font=("", 10, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))
        row += 1

        delay_fields = [
            ('click_wait', '클릭 후 대기(ms):', '1500'),
            ('seat_click', '좌석 딜레이(ms):', '80'),
            ('section_move', '구역 이동 딜레이(ms):', '100'),
            ('refresh', '새로고침 간격(ms):', '300'),
            ('captcha_typing_delay', '캡차 입력 간격(ms):', '50'),
            ("max_retries", "최대 재시도 횟수:", "30"),
            ("max_screenshot_fails", "최대 스크린샷 실패:", "5"),
        ]
        for key, label, default in delay_fields:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
            var = tk.StringVar(value=default)
            ttk.Entry(frame, textvariable=var, width=12).grid(
                row=row, column=1, sticky="w", padx=4, pady=2)
            self._settings_vars[key] = var
            row += 1

        # ── 캡차 설정 ──
        row += 1
        lbl = ttk.Label(frame, text="🤖 캡차 (xAI Grok Vision)", font=("", 10, "bold"))
        lbl.grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        row += 1

        # auto_captcha 체크박스
        self._auto_captcha_var = tk.BooleanVar(
            value=self._cfg.get("booking", {}).get("auto_captcha", True))
        ttk.Checkbutton(frame, text="자동 캡차 해제 사용",
                        variable=self._auto_captcha_var).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=8, pady=2)
        row += 1

        # xai_api_type 선택 (vision | oauth)
        ttk.Label(frame, text="xAI 인증 방식:").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        api_types = ["oauth", "vision"]
        self._xai_api_type_var = tk.StringVar(
            value=self._cfg.get("xai", {}).get("api_type", "oauth"))
        api_type_combo = ttk.Combobox(frame, textvariable=self._xai_api_type_var,
                                      values=api_types, width=10, state="readonly")
        api_type_combo.grid(row=row, column=1, sticky="w", padx=4, pady=2)
        # OAuth 로그인 버튼 (api_type 바로 옆에 배치)
        self._xai_oauth_btn = ttk.Button(frame, text="🔐 xAI OAuth 로그인",
                                         command=self._start_xai_oauth)
        self._xai_oauth_btn.grid(row=row, column=2, sticky="w", padx=4, pady=2)
        # Codex OAuth 로그인 버튼 (xAI 옆에)
        self._codex_oauth_btn = ttk.Button(frame, text="🤖 Codex OAuth 로그인",
                                           command=self._start_codex_oauth)
        self._codex_oauth_btn.grid(row=row, column=3, sticky="w", padx=4, pady=2)
        ttk.Label(frame, text="oauth=PKCE 인증 (추천) / vision=API 키 직접",
                  font=("", 8), foreground="gray").grid(
            row=row, column=4, sticky="w", padx=4, pady=2)
        row += 1

        # xai_api_key (선택, 감춰진 입력)
        ttk.Label(frame, text="xAI API 키 (선택):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        self._xai_api_key_var = tk.StringVar(
            value=self._cfg.get("xai", {}).get("api_key", ""))
        api_entry = ttk.Entry(frame, textvariable=self._xai_api_key_var,
                              width=20, show="*")
        api_entry.grid(row=row, column=1, sticky="w", padx=4, pady=2)
        row += 1

        # xai_model 선택
        ttk.Label(frame, text="Vision 모델:").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        models = [
            "grok-4.20-0309-non-reasoning",
            "grok-3.9-latest",
            "grok-3.5-latest",
        ]
        self._xai_model_var = tk.StringVar(
            value=self._cfg.get("xai", {}).get("model", models[0]))
        model_combo = ttk.Combobox(frame, textvariable=self._xai_model_var,
                                   values=models, width=20, state="readonly")
        model_combo.grid(row=row, column=1, sticky="w", padx=4, pady=2)
        row += 1

        ttk.Label(frame, text="vision 모드: XAI_API_KEY 환경변수 또는 위 API 키 필드 사용",
                  font=("", 8), foreground="gray").grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))
        row += 1

        # ── 캡차 영역 (선택) ──
        sep = ttk.Separator(frame, orient="horizontal")
        sep.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
        row += 1
        ttk.Label(frame, text="📐 캡차 영역 (선택 — 비우면 전체화면 OCR)", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))
        row += 1

        ca = self._cfg.get("macro", {}).get("captcha_area", [0, 0, 0, 0])
        cap_area_labels = [("x1", "↖x"), ("y1", "↖y"), ("x2", "↘x"), ("y2", "↘y")]
        self._captcha_area_vars = {}
        for ci, (ckey, clabel) in enumerate(cap_area_labels):
            ttk.Label(frame, text=f"{clabel}:").grid(
                row=row, column=ci * 2, sticky="w", padx=(8 if ci == 0 else 2))
            var = tk.StringVar(value=str(ca[ci]) if len(ca) > ci else "0")
            e = ttk.Entry(frame, textvariable=var, width=7)
            e.grid(row=row, column=ci * 2 + 1, sticky="w", padx=2)
            self._captcha_area_vars[ckey] = var

        # 🎯 따기 버튼 (x1,y1 쌍 / x2,y2 쌍)
        ttk.Button(frame, text="🎯 ↖",
                   command=lambda: self._quick_pick(
                       self._captcha_area_vars["x1"], self._captcha_area_vars["y1"])
                   ).grid(row=row, column=8, padx=4)
        ttk.Button(frame, text="🎯 ↘",
                   command=lambda: self._quick_pick(
                       self._captcha_area_vars["x2"], self._captcha_area_vars["y2"])
                   ).grid(row=row, column=9, padx=2)
        row += 1

        # ── CDP 폼 하이재킹 ──
        sep2 = ttk.Separator(frame, orient="horizontal")
        sep2.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
        row += 1
        ttk.Label(frame, text="💉 CDP 폼 하이재킹", font=("", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))
        row += 1

        hijack = self._cfg.get("macro", {}).get("cdp_hijack", {})
        self._cdp_enabled_var = tk.BooleanVar(value=hijack.get("enabled", False))
        ttk.Checkbutton(frame, text="CDP 하이재킹 활성화", variable=self._cdp_enabled_var).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=8, pady=2)
        row += 1

        # CDP port
        port_frame = ttk.Frame(frame)
        port_frame.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        ttk.Label(port_frame, text="CDP 포트:").pack(side="left")
        self._cdp_port_var = tk.StringVar(value=str(hijack.get("port", 9222)))
        ttk.Entry(port_frame, textvariable=self._cdp_port_var, width=8).pack(side="left", padx=4)
        ttk.Button(port_frame, text="🚀 Chrome 실행 (CDP)",
                   command=self._launch_cdp_chrome).pack(side="left", padx=(10, 0))
        row += 1

        # product_id
        ttk.Label(frame, text="Product ID (구단코드):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        self._cdp_product_id_var = tk.StringVar(value=hijack.get("product_id", ""))
        ttk.Entry(frame, textvariable=self._cdp_product_id_var, width=20).grid(
            row=row, column=1, sticky="w", padx=4, pady=2)
        row += 1

        # schedule_id
        ttk.Label(frame, text="Schedule ID (경기코드):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        self._cdp_schedule_id_var = tk.StringVar(value=hijack.get("schedule_id", ""))
        ttk.Entry(frame, textvariable=self._cdp_schedule_id_var, width=30).grid(
            row=row, column=1, sticky="w", padx=4, pady=2)
        btn_sched = ttk.Frame(frame)
        btn_sched.grid(row=row, column=2, sticky="w", padx=4)
        ttk.Button(btn_sched, text="🎯 경기 불러오기",
                   command=self._fetch_cdp_games).pack(side="left", padx=(0, 4))
        ttk.Button(btn_sched, text="📋 URL에서 읽기",
                   command=self._read_cdp_url).pack(side="left")
        row += 1

        # 설명
        ttk.Label(frame,
                  text="필수: Chrome --remote-debugging-port=9222 로 실행",
                  font=("", 8), foreground="gray").grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8)
        row += 1
        ttk.Label(frame,
                  text="[경기 불러오기] = 구단목록 / [URL에서 읽기] = 현재 예매페이지 URL 파싱",
                  font=("", 8), foreground="gray").grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))
        row += 1

        # ── 하이브리드 새로고침 (CDP DOM 폴링) ──
        sep3 = ttk.Separator(frame, orient="horizontal")
        sep3.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
        row += 1
        ttk.Label(frame, text="🔄 하이브리드 새로고침 (CDP DOM 폴링)", font=("", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))
        row += 1

        hr = self._cfg.get("booking", {}).get("hybrid_refresh", {})
        self._hybrid_enabled_var = tk.BooleanVar(value=hr.get("enabled", False))
        ttk.Checkbutton(frame, text="하이브리드 새로고침 활성화", variable=self._hybrid_enabled_var).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=8, pady=2)
        row += 1

        ttk.Label(frame, text="Source Product ID (BEFORE 구단):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        self._hybrid_source_pid_var = tk.StringVar(value=hr.get("source_product_id", ""))
        ttk.Entry(frame, textvariable=self._hybrid_source_pid_var, width=20).grid(
            row=row, column=1, sticky="w", padx=4, pady=2)
        row += 1

        ttk.Label(frame, text="Source Schedule ID (BEFORE 경기):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        self._hybrid_source_sid_var = tk.StringVar(value=hr.get("source_schedule_id", ""))
        ttk.Entry(frame, textvariable=self._hybrid_source_sid_var, width=30).grid(
            row=row, column=1, sticky="w", padx=4, pady=2)
        row += 1

        ttk.Label(frame, text="Target Product ID (타겟, 선택):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        self._hybrid_target_pid_var = tk.StringVar(value=hr.get("target_product_id", ""))
        ttk.Entry(frame, textvariable=self._hybrid_target_pid_var, width=20).grid(
            row=row, column=1, sticky="w", padx=4, pady=2)
        row += 1

        ttk.Label(frame, text="Target Schedule ID (타겟, 선택):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        self._hybrid_target_sid_var = tk.StringVar(value=hr.get("target_schedule_id", ""))
        ttk.Entry(frame, textvariable=self._hybrid_target_sid_var, width=30).grid(
            row=row, column=1, sticky="w", padx=4, pady=2)
        row += 1

        ttk.Label(frame, text="폴링 간격(초):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        self._hybrid_poll_var = tk.StringVar(value=str(hr.get("poll_interval", 0.5)))
        ttk.Entry(frame, textvariable=self._hybrid_poll_var, width=8).grid(
            row=row, column=1, sticky="w", padx=4, pady=2)
        row += 1

        ttk.Label(frame, text="최대 대기(분):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        self._hybrid_max_wait_var = tk.StringVar(value=str(hr.get("max_wait_minutes", 60)))
        ttk.Entry(frame, textvariable=self._hybrid_max_wait_var, width=8).grid(
            row=row, column=1, sticky="w", padx=4, pady=2)
        row += 1

        ttk.Label(frame,
                  text="Source=BEFORE 게임에서 예매하기 활성 감시 / Target=빈 값이면 동일 경기",
                  font=("", 8), foreground="gray").grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))
        row += 1

    # ── xAI OAuth 로그인 ──

    def _start_xai_oauth(self):
        """xAI OAuth PKCE 로그인 (별도 스레드)"""
        threading.Thread(target=self._do_xai_oauth, daemon=True).start()

    def _do_xai_oauth(self):
        """백그라운드에서 xAI OAuth 로그인 실행"""
        try:
            from .oauth import xai_oauth_login
            logger.info("🔐 xAI OAuth 로그인 시작... (브라우저가 열립니다)")
            tokens = xai_oauth_login(timeout_seconds=120.0, open_browser=True)
            if tokens and tokens.get("access_token"):
                logger.info("✅ xAI OAuth 로그인 완료! (%d자 토큰)",
                            len(tokens["access_token"]))
                # 자동으로 api_type = oauth 로 전환
                self.after(0, lambda: self._xai_api_type_var.set("oauth"))
                # cfg에도 반영
                self.after(0, self._save_preset, self._current_preset)
            else:
                logger.error("❌ xAI OAuth 로그인 실패 — 토큰을 받지 못했습니다.")
        except Exception as e:
            logger.error("❌ xAI OAuth 로그인 오류: %s", e)
            import traceback
            traceback.print_exc()

    # ── Codex OAuth 로그인 ──

    def _start_codex_oauth(self):
        """Codex OAuth Device Code 로그인 (별도 스레드)"""
        threading.Thread(target=self._do_codex_oauth, daemon=True).start()

    def _do_codex_oauth(self):
        """백그라운드에서 OpenAI (Codex) OAuth 로그인 실행"""
        try:
            from .oauth import openai_oauth_login
            logger.info("🤖 Codex OAuth 로그인 시작... (브라우저가 열립니다)")
            tokens = openai_oauth_login(timeout_seconds=120.0)
            if tokens and tokens.get("access_token"):
                logger.info("✅ Codex OAuth 로그인 완료! (%d자 토큰)",
                            len(tokens["access_token"]))
                self.after(0, self._save_preset, self._current_preset)
            else:
                logger.error("❌ Codex OAuth 로그인 실패 — 토큰을 받지 못했습니다.")
        except Exception as e:
            logger.error("❌ Codex OAuth 로그인 오류: %s", e)
            import traceback
            traceback.print_exc()

    # ── URL/서버시간 도구 ──

    def _open_url(self, url: str):
        """브라우저에서 URL 열기"""
        import webbrowser
        if url and url.startswith("http"):
            webbrowser.open(url)
            logger.info("🌐 브라우저 열기: %s", url)
        else:
            logger.warning("⚠️ 올바른 URL이 아닙니다: %s", url)

    def _fetch_server_time(self):
        """URL에서 서버시간(예매오픈시간) 추출 (별도 스레드)"""
        threading.Thread(target=self._do_fetch_server_time, daemon=True).start()

    def _do_fetch_server_time(self):
        """백그라운드에서 HTTP Date 헤더 기반 서버시간 동기화

        1) URL에 GET/HEAD 요청 → Date 헤더로 서버시간 측정
        2) RTT 고려해 offset 보정 (다중 요청)
        3) 필요시 HTML에서 예매시작시간 파싱 시도 (fallback)
        """
        url = self._default_url_var.get().strip()
        if not url or not url.startswith("http"):
            logger.warning("⚠️ 올바른 예매 URL을 먼저 입력하세요.")
            return

        logger.info("🔍 서버시간 측정 중: %s", url)
        try:
            import time as _time
            import urllib.request
            import re
            from datetime import datetime, timedelta, timezone

            # ── 1단계: HTTP Date 헤더로 서버시간 오프셋 측정 ──
            def _get_server_date_epoch(req_url: str) -> tuple[float, float]:
                """HEAD 요청 → 서버 Date 헤더 epoch + RTT 반환"""
                t0 = _time.time()
                req = urllib.request.Request(
                    req_url, method="HEAD",
                    headers={
                        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                       "AppleWebKit/537.36"),
                        "Accept": "*/*",
                    },
                )
                resp = urllib.request.urlopen(req, timeout=10)
                rtt = _time.time() - t0
                date_str = resp.headers.get("Date")
                if not date_str:
                    raise RuntimeError("Date 헤더 없음")
                # "Thu, 25 Jun 2026 10:00:00 GMT"
                dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %Z")
                server_epoch = dt.replace(tzinfo=timezone.utc).timestamp()
                return server_epoch, rtt

            # 다중 요청 → 최소 RTT 기준 offset 채택
            offsets: list[tuple[float, float]] = []  # (offset, rtt)
            for i in range(5):
                try:
                    srv_epoch, rtt = _get_server_date_epoch(url)
                    local_epoch = _time.time()
                    offset = srv_epoch - local_epoch
                    offsets.append((offset, rtt))
                    logger.debug("  📡 #%d: offset=%.3fs  rtt=%.1fms", i+1, offset, rtt*1000)
                except Exception as e:
                    logger.debug("  📡 #%d 실패: %s", i+1, e)
                _time.sleep(0.3)

            if not offsets:
                raise RuntimeError("서버 응답 없음 (Date 헤더를 받지 못함)")

            # 최소 RTT(가장 정확한) offset 사용
            best_offset = min(offsets, key=lambda x: x[1])[0]
            server_now_epoch = _time.time() + best_offset

            # ── 2단계: HTML에서 예매시작시간 파싱 시도 ──
            found_booking_time = None
            try:
                html_req = urllib.request.Request(
                    url, method="GET",
                    headers={
                        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                       "AppleWebKit/537.36"),
                        "Accept": "text/html,application/json,*/*",
                    },
                )
                html_resp = urllib.request.urlopen(html_req, timeout=10)
                html = html_resp.read().decode("utf-8", errors="replace")

                # a) JSON-LD bookingPeriod
                m = re.search(r'"bookingPeriod"\s*:\s*"([^"]+)"', html)
                if m:
                    found_booking_time = m.group(1)
                # b) 날짜+시간 패턴
                if not found_booking_time:
                    m = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2})\s+(\d{2}:\d{2})', html)
                    if m:
                        found_booking_time = f"{m.group(2)}:00"
                # c) 키워드 근접 시간
                if not found_booking_time:
                    for kw in ["예매", "오픈", "시작", "open", "booking"]:
                        idx = html.lower().find(kw)
                        if idx >= 0:
                            m = re.search(r'(\d{2}:\d{2}(?::\d{2})?)', html[idx:idx+200])
                            if m:
                                found_booking_time = m.group(1)
                                break
            except Exception:
                pass  # HTML 파싱 실패 → 무시

            # ── 3단계: 오프셋 저장 + 결과 표시 ──
            # 오프셋 저장 (bot이 사용)
            self._server_offset = best_offset
            self._cfg.setdefault("booking", {})["server_time_offset"] = round(best_offset, 3)

            # 현재 서버시간 표시
            server_dt = datetime.fromtimestamp(server_now_epoch)
            server_hhmmss = server_dt.strftime("%H:%M:%S")
            logger.info("🕐 현재 서버시간: %s (offset=%.0fms, RTT=%.1fms)",
                        server_hhmmss,
                        best_offset * 1000,
                        min(o[1] for o in offsets) * 1000)

            if found_booking_time:
                # T포함 처리
                if "T" in found_booking_time:
                    found_booking_time = found_booking_time.split("T")[1]
                if found_booking_time.count(":") == 1:
                    found_booking_time = f"{found_booking_time}:00"
                self.after(0, lambda: self._server_time_var.set(found_booking_time))
                logger.info("✅ 예매시작시간 발견: %s", found_booking_time)
            else:
                logger.info(
                    "✅ 서버 연결 OK (현재 서버시간: %s) — 예매시작시간을 수동 입력하세요.\n"
                    "  (예: 10:00:00 → F5 봇이 09:59:57부터 자동 스팸)",
                    server_hhmmss,
                )

        except Exception as e:
            logger.error("❌ 서버시간 측정 실패: %s", e)

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

    def _run_picker_sync(self, use_global: bool = True):
        """동기식 좌표 따기 실행 (시스템 글로벌 픽커, Chrome 불필요)"""
        from .picker import GlobalPicker
        picker = GlobalPicker()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(picker.pick(timeout=60))
        finally:
            picker.close()
            loop.close()

    def _quick_pick(self, x_var, y_var):
        """빠른 좌표 따기 (zone용) — 백그라운드 스레드"""
        threading.Thread(target=self._do_quick_pick, args=(x_var, y_var), daemon=True).start()

    def _do_quick_pick(self, x_var, y_var):
        coord = self._run_picker_sync(use_global=True)
        if coord:
            self.after(0, lambda: x_var.set(str(coord["x"])))
            self.after(0, lambda: y_var.set(str(coord["y"])))

    def _quick_pick_color(self, color_var):
        """색상 자동 추출 — 백그라운드 스레드"""
        threading.Thread(target=self._do_quick_pick_color, args=(color_var,), daemon=True).start()

    def _do_quick_pick_color(self, color_var):
        coord = self._run_picker_sync(use_global=True)
        if coord:
            try:
                from .system_bot import SystemBot
                bgr = SystemBot.pixel(coord["x"], coord["y"])
                self.after(0, lambda: color_var.set(bgr))
                logger.info("  ✅ 색상: #%s", bgr)
            except Exception as e:
                logger.error("  ⚠️ 색상 추출 실패: %s", e)

    def _auto_pick_color(self):
        """Zone 영역에서 색상 자동 추출 — 백그라운드 스레드"""
        threading.Thread(target=self._do_auto_pick_color, daemon=True).start()

    def _do_auto_pick_color(self):
        logger.info("🎨 빈 좌석 클릭 → 자동 색상 추출")
        logger.info("   (좌석표에서 빈 좌석을 좌클릭 또는 우클릭하세요)")
        coord = self._run_picker_sync(use_global=True)
        if coord:
            try:
                from .system_bot import SystemBot
                bgr = SystemBot.pixel(coord["x"], coord["y"])
                # 모든 zone에 적용 (복사본으로 순회 — thread-safe)
                for zv in list(self._zone_frames):
                    self.after(0, lambda z=zv: z["color"].set(bgr))
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
                self._current_preset = name
                self._collect_ui_to_cfg()
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
        return simpledialog.askstring(title, prompt) or ""

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

        # Seat search vars
        ss = macro.get("seat_search", {})
        if hasattr(self, "_seat_search_vars"):
            self._seat_search_vars["row_tolerance"].set(str(ss.get("row_tolerance", 30)))
            self._seat_search_vars["gap_tolerance"].set(str(ss.get("gap_tolerance", 40)))
            self._seat_search_vars["max_results_per_zone"].set(str(ss.get("max_results_per_zone", 20)))

        # Settings
        booking = self._cfg.get("booking", {})
        self._settings_vars["team"].set(booking.get("team", "LG 트윈스"))
        self._settings_vars["ticket_count"].set(str(booking.get("ticket_count", 2)))
        self._server_time_var.set(booking.get("server_time", ""))
        self._default_url_var.set(booking.get("default_url", "https://www.ticketlink.co.kr/sports/137/59"))
        self._prefer_seat_var.set(booking.get("prefer_seat", ""))
        delays = macro.get("delays", {})
        self._settings_vars["click_wait"].set(str(delays.get("click_wait", 1500)))
        self._settings_vars["seat_click"].set(str(delays.get("seat_click", 80)))
        self._settings_vars["section_move"].set(str(delays.get("section_move", 100)))
        self._settings_vars["refresh"].set(str(delays.get("refresh", 300)))
        self._settings_vars["captcha_typing_delay"].set(str(delays.get("captcha_typing_delay", 50)))
        self._settings_vars["max_retries"].set(str(macro.get("max_retries", 30)))
        self._settings_vars["max_screenshot_fails"].set(str(macro.get("max_screenshot_fails", 5)))

        # xAI / captcha — cfg → UI 읽기
        xai_cfg = self._cfg.get("xai", {})
        self._xai_api_type_var.set(xai_cfg.get("api_type", "oauth"))
        self._xai_api_key_var.set(xai_cfg.get("api_key", ""))
        self._xai_model_var.set(xai_cfg.get("model", "grok-4.20-0309-non-reasoning"))
        self._auto_captcha_var.set(
            self._cfg.get("booking", {}).get("auto_captcha", True))

        # Captcha area
        if hasattr(self, "_captcha_area_vars"):
            ca = macro.get("captcha_area", [0, 0, 0, 0])
            for i, ck in enumerate(["x1", "y1", "x2", "y2"]):
                self._captcha_area_vars[ck].set(str(ca[i]) if len(ca) > i else "0")

        # CDP hijack
        hijack = macro.get("cdp_hijack", {})
        if hasattr(self, "_cdp_enabled_var"):
            self._cdp_enabled_var.set(hijack.get("enabled", False))
            self._cdp_port_var.set(str(hijack.get("port", 9222)))
            self._cdp_product_id_var.set(hijack.get("product_id", ""))
            self._cdp_schedule_id_var.set(hijack.get("schedule_id", ""))

        # Hybrid refresh
        hr = booking.get("hybrid_refresh", {})
        if hasattr(self, "_hybrid_enabled_var"):
            self._hybrid_enabled_var.set(hr.get("enabled", False))
            self._hybrid_source_pid_var.set(hr.get("source_product_id", ""))
            self._hybrid_source_sid_var.set(hr.get("source_schedule_id", ""))
            self._hybrid_target_pid_var.set(hr.get("target_product_id", ""))
            self._hybrid_target_sid_var.set(hr.get("target_schedule_id", ""))
            self._hybrid_poll_var.set(str(hr.get("poll_interval", 0.5)))
            self._hybrid_max_wait_var.set(str(hr.get("max_wait_minutes", 60)))

    def _collect_ui_to_cfg(self):
        """UI → 설정"""
        macro = self._cfg.setdefault("macro", {})
        for key, var in self._coord_vars.items():
            try:
                parts = var.get().replace(" ", "").split(",")
                macro[key] = [int(parts[0]), int(parts[1])]
            except (ValueError, IndexError):
                macro[key] = [0, 0]
                logger.warning("⚠️ 좌표 '%s' 파싱 실패 — [0,0] 사용", key)

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
        else:
            macro.pop("seat_zones", None)
            macro.pop("seat_area", None)
            macro.pop("seat_color", None)
            macro.pop("color_tolerance", None)  # zone 삭제 시 잔류 방지

        try:
            macro["consecutive_seats"] = int(self._consecutive_var.get())
        except ValueError:
            macro["consecutive_seats"] = 2
        try:
            macro["color_tolerance"] = int(self._tolerance_var.get())
        except ValueError:
            macro["color_tolerance"] = 20

        # Seat search vars
        ss = macro.setdefault("seat_search", {})
        if hasattr(self, "_seat_search_vars"):
            for k in ("row_tolerance", "gap_tolerance", "max_results_per_zone"):
                try:
                    ss[k] = int(self._seat_search_vars[k].get())
                except (ValueError, KeyError):
                    ss[k] = {"row_tolerance": 30, "gap_tolerance": 40, "max_results_per_zone": 20}.get(k, 0)

        # Settings
        booking = self._cfg.setdefault("booking", {})
        booking["team"] = self._settings_vars["team"].get()
        try:
            booking["ticket_count"] = int(self._settings_vars["ticket_count"].get())
        except ValueError:
            booking["ticket_count"] = 2
        booking["server_time"] = self._server_time_var.get().strip()
        booking["default_url"] = self._default_url_var.get().strip()
        booking["prefer_seat"] = self._prefer_seat_var.get().strip()

        delays = macro.setdefault("delays", {})
        for k in ("click_wait", "seat_click", "section_move", "refresh", "captcha_typing_delay"):
            try:
                delays[k] = int(self._settings_vars[k].get())
            except (ValueError, KeyError):
                delays[k] = {"click_wait": 1500, "seat_click": 80, "section_move": 100, "refresh": 300, "captcha_typing_delay": 50}.get(k, 0)

        for k in ("max_retries", "max_screenshot_fails"):
            try:
                macro[k] = int(self._settings_vars[k].get())
            except (ValueError, KeyError):
                macro[k] = {"max_retries": 30, "max_screenshot_fails": 5}.get(k, 0)

        # xAI / captcha — UI -> cfg 저장
        xai_cfg = self._cfg.setdefault("xai", {})
        xai_cfg["api_type"] = self._xai_api_type_var.get()
        xai_cfg["api_key"] = self._xai_api_key_var.get()
        xai_cfg["model"] = self._xai_model_var.get()
        booking["auto_captcha"] = self._auto_captcha_var.get()

        # Captcha area
        if hasattr(self, "_captcha_area_vars"):
            try:
                macro["captcha_area"] = [
                    int(self._captcha_area_vars["x1"].get() or "0"),
                    int(self._captcha_area_vars["y1"].get() or "0"),
                    int(self._captcha_area_vars["x2"].get() or "0"),
                    int(self._captcha_area_vars["y2"].get() or "0"),
                ]
            except (ValueError, KeyError):
                macro.pop("captcha_area", None)

        # CDP hijack — UI → cfg
        if hasattr(self, "_cdp_enabled_var"):
            macro["cdp_hijack"] = {
                "enabled": self._cdp_enabled_var.get(),
                "port": int(self._cdp_port_var.get() or "9222"),
                "product_id": self._cdp_product_id_var.get().strip(),
                "schedule_id": self._cdp_schedule_id_var.get().strip(),
            }

        # Hybrid refresh — UI → cfg
        if hasattr(self, "_hybrid_enabled_var"):
            booking["hybrid_refresh"] = {
                "enabled": self._hybrid_enabled_var.get(),
                "source_product_id": self._hybrid_source_pid_var.get().strip(),
                "source_schedule_id": self._hybrid_source_sid_var.get().strip(),
                "target_product_id": self._hybrid_target_pid_var.get().strip(),
                "target_schedule_id": self._hybrid_target_sid_var.get().strip(),
                "poll_interval": float(self._hybrid_poll_var.get() or "0.5"),
                "max_wait_minutes": float(self._hybrid_max_wait_var.get() or "60"),
            }

    # ── CDP 경기 불러오기 ──

    def _fetch_cdp_games(self):
        """CDP로 구단 페이지에서 경기 목록 스크래핑 → 선택 UI"""
        product_id = self._cdp_product_id_var.get().strip()
        cdp_port = int(self._cdp_port_var.get() or "9222")
        threading.Thread(target=self._do_fetch_cdp_games,
                         args=(product_id, cdp_port), daemon=True).start()

    def _do_fetch_cdp_games(self, product_id: str, cdp_port: int):
        """백그라운드에서 CDP 경기 스크래핑 실행"""
        try:
            # 1) 먼저 Network capture 방식 시도 (product_id 불필요)
            from .cdp_hijack import fetch_games_via_network
            logger.info("🔍 CDP Network capture로 경기 목록 불러오는 중... (포트 %d)",
                        cdp_port)
            games = fetch_games_via_network(cdp_port=cdp_port)

            # Network capture 성공 여부 확인
            if games and any(g.get("scheduleId") and g.get("productId")
                             for g in games):
                logger.info("✅ Network capture 성공: %d개 경기 발견", len(games))
            else:
                # 2) 실패 시 DOM 방식 fallback (product_id 필요)
                if not product_id:
                    self.after(0, lambda: logger.warning(
                        "⚠️ 경기 목록을 불러올 수 없습니다.\n"
                        "1) Network capture 실패\n"
                        "2) 구단코드(Product ID) 미입력 → DOM 방식 fallback 불가\n"
                        "Chrome CDP(--remote-debugging-port=%d) 실행 상태 확인", cdp_port))
                    return
                from .standalone import _fetch_games_from_cdp
                logger.info("↩️ DOM 방식 fallback (구단 %s)", product_id)
                games = _fetch_games_from_cdp(product_id, cdp_port=cdp_port)

            if not games:
                self.after(0, lambda: logger.warning(
                    "⚠️ 경기 목록을 찾을 수 없습니다.\n"
                    "Chrome CDP 연결 확인: --remote-debugging-port=%d", cdp_port))
                return

            # 실제 경기만 필터링 (data-* 또는 URL에서 추출된 것)
            real_games = [g for g in games
                          if g.get("scheduleId") and not g.get("_strategy")]
            if not real_games:
                self.after(0, lambda: logger.warning(
                    "⚠️ 경기 데이터를 페이지에서 찾을 수 없습니다.\n"
                    "티켓링크 페이지가 정상 로딩되었는지 확인하세요."))
                return

            # 경기 선택 다이얼로그 표시
            self.after(0, self._show_game_selector, real_games)

        except Exception as e:
            logger.error("❌ 경기 목록 스크래핑 오류: %s", e)
            self.after(0, lambda: logger.warning(
                "⚠️ 오류: %s\nChrome CDP(--remote-debugging-port)가 실행 중인지 확인",
                e))

    def _show_game_selector(self, games: list[dict]):
        """경기 선택 팝업"""
        import tkinter as tk
        from tkinter import ttk

        win = tk.Toplevel(self)
        win.title("⚾ 경기 선택")
        win.geometry("550x400")
        win.resizable(True, True)
        win.transient(self)
        win.grab_set()

        ttk.Label(win, text="경기를 선택하면 Schedule ID가 자동 입력됩니다",
                  font=("", 10)).pack(pady=(10, 5))

        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=10, pady=5)

        cols = ("scheduleId", "productId", "team", "detail")
        tree = ttk.Treeview(frame, columns=cols, show="headings",
                            height=12, selectmode="browse")
        tree.heading("scheduleId", text="경기코드")
        tree.heading("productId", text="구단코드")
        tree.heading("team", text="구분")
        tree.heading("detail", text="상세")
        tree.column("scheduleId", width=120)
        tree.column("productId", width=0, minwidth=0, stretch=False)  # 숨김
        tree.column("team", width=100)
        tree.column("detail", width=280)

        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        for g in games:
            sid = g.get("scheduleId", "")
            pid = g.get("productId", "")
            text = g.get("text", "")
            href = g.get("href", "")
            # productId로 팀명 찾기
            from .cdp_hijack import PRODUCT_ID_TO_TEAM
            team = PRODUCT_ID_TO_TEAM.get(pid, f"구단({pid})")
            detail = text or href or f"scheduleId={sid}"
            tree.insert("", "end", values=(sid, pid, team, detail))

        def on_select():
            sel = tree.selection()
            if not sel:
                return
            values = tree.item(sel[0], "values")
            if values:
                self._cdp_schedule_id_var.set(values[0])
                self._cdp_product_id_var.set(values[1])
                logger.info("✅ Schedule ID=%s / Product ID=%s 선택",
                            values[0], values[1])
            win.destroy()

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill="x", pady=10)
        ttk.Button(btn_frame, text="✅ 선택 완료", command=on_select).pack(
            side="right", padx=10)
        ttk.Button(btn_frame, text="취소",
                   command=win.destroy).pack(side="right", padx=5)

    # ── CDP URL 읽기 ──

    def _read_cdp_url(self):
        """현재 Chrome 페이지 URL/폼에서 경기코드 읽기"""
        cdp_port = int(self._cdp_port_var.get() or "9222")
        threading.Thread(target=self._do_read_cdp_url,
                         args=(cdp_port,), daemon=True).start()

    def _do_read_cdp_url(self, cdp_port: int):
        """백그라운드에서 CDP URL 읽기 실행"""
        try:
            from .standalone import _read_ids_from_cdp
            logger.info("📋 Chrome 페이지 URL 읽는 중... (포트 %d)", cdp_port)
            result = _read_ids_from_cdp(cdp_port=cdp_port)

            if not result:
                self.after(0, lambda: logger.warning(
                    "⚠️ URL에서 경기코드를 찾을 수 없습니다.\n"
                    "Chrome CDP(--remote-debugging-port=%d)가 실행 중이고\n"
                    "예매 팝업(새 창)이 열려있는지 확인하세요.\n"
                    "※ 모든 탭/팝업을 자동 스캔합니다.", cdp_port))
                return

            pid = result.get("productId", "")
            sid = result.get("scheduleId", "")
            url = result.get("url", "")

            # UI 업데이트
            if pid:
                self._cdp_product_id_var.set(pid)
            if sid:
                self._cdp_schedule_id_var.set(sid)

            msg = f"✅ URL 읽기 완료: productId={pid}, scheduleId={sid}"
            if "예매 가능한 경기가 없습니다" in url or "예매" not in url:
                msg += "\n  ⚠️ 예매 페이지가 맞는지 확인하세요"
            self.after(0, lambda: logger.info(msg))

        except Exception as e:
            logger.error("❌ URL 읽기 오류: %s", e)
            self.after(0, lambda: logger.warning(
                "⚠️ 오류: %s\nChrome CDP(--remote-debugging-port)가 실행 중인지 확인", e))

    # ── CDP Chrome 실행 ──

    def _launch_cdp_chrome(self):
        """Chrome을 CDP(--remote-debugging-port) 모드로 실행 (macOS/Windows)"""
        import subprocess
        import sys
        import os

        port = self._cdp_port_var.get().strip() or "9222"
        chrome_path = None

        # OS별 Chrome 경로 찾기
        if sys.platform == "win32":
            candidates = [
                os.environ.get("LOCALAPPDATA", "") + r"\Google\Chrome\Application\chrome.exe",
                os.environ.get("PROGRAMFILES", "") + r"\Google\Chrome\Application\chrome.exe",
                os.environ.get("PROGRAMFILES(X86)", "") + r"\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
        elif sys.platform == "darwin":
            candidates = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ]
        else:  # Linux
            candidates = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium-browser",
                "/usr/bin/chromium",
            ]

        for p in candidates:
            if os.path.isfile(p):
                chrome_path = p
                break

        if not chrome_path:
            self.after(0, lambda: logger.warning(
                "⚠️ Chrome을 찾을 수 없습니다.\n직접 실행: Chrome --remote-debugging-port=%s", port))
            return

        # 이미 실행 중인지 확인
        try:
            import urllib.request
            import json
            req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            ver = json.loads(req.read()).get("Browser", "?")
            self.after(0, lambda: logger.info(
                "✅ Chrome CDP 이미 실행 중 (포트 %s, %s)", port, ver))
            return
        except Exception:
            pass

        # Chrome 실행
        udir = os.path.join(os.path.expanduser("~"), ".config", "chrome-cdp-profile")
        args = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={udir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
        ]
        try:
            if sys.platform == "win32":
                subprocess.Popen(args, shell=False)
            else:
                subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.after(0, lambda: logger.info(
                "🚀 Chrome 실행 중... (포트 %s)\nCDP 연결 준비: [📋 URL에서 읽기] 클릭", port))
        except Exception as e:
            self.after(0, lambda: logger.error("❌ Chrome 실행 실패: %s", e))

    # ── 이중봇 실행 ──

    def _update_bot_status(self):
        """세 봇의 상태를 종합하여 UI 업데이트"""
        running_parts = []
        refresh_indicator = ""
        macro_indicator = ""
        hybrid_indicator = ""

        if self._refresh_running:
            running_parts.append("🔄새로고침")
            refresh_indicator = "[F6] 🔄"
        if self._macro_running:
            running_parts.append("⚡매크로")
            macro_indicator = "[F8] ⚡"
        if self._hybrid_running:
            running_parts.append("🔄하이브리드")
            hybrid_indicator = "[F9] 🔄"

        if running_parts:
            self._status_label.configure(
                text=f"🟢 {'+'.join(running_parts)}", foreground=_AppStyle.SUCCESS)
        else:
            self._status_label.configure(text="⏸ 대기중", foreground=_AppStyle.FG)

        combined = "  ".join(p for p in (refresh_indicator, macro_indicator, hybrid_indicator) if p)
        self._refresh_status_label.configure(text=combined)

    def _toggle_refresh(self):
        """F6: 새로고침 봇 시작/중지"""
        if self._refresh_running:
            self._stop_refresh()
        else:
            self._start_refresh()

    def _start_refresh(self):
        """새로고침 봇 시작"""
        self._collect_ui_to_cfg()
        self._refresh_running = True
        self._refresh_stop_event.clear()
        self._refresh_btn.configure(state="disabled", text="🔄 새로고침중...")
        self._update_bot_status()
        threading.Thread(target=self._run_refresh_bot, daemon=True).start()

    def _stop_refresh(self):
        """새로고침 봇 중지"""
        self._refresh_running = False
        self._refresh_stop_event.set()
        self._refresh_btn.configure(state="normal", text="🔄 새로고침 (F6)")
        self._update_bot_status()

    def _toggle_macro(self):
        """F8: 매크로 봇 시작/중지"""
        if self._macro_running:
            self._stop_macro_bot()
        else:
            self._start_macro_bot()

    def _start_macro_bot(self):
        """매크로 봇 시작"""
        self._collect_ui_to_cfg()
        self._macro_running = True
        self._macro_stop_event.clear()
        self._macro_btn.configure(state="disabled", text="⚡ 매크로중...")
        self._update_bot_status()
        threading.Thread(target=self._run_macro_bot, daemon=True).start()

    def _stop_macro_bot(self):
        """매크로 봇 중지"""
        self._macro_running = False
        self._macro_stop_event.set()
        self._macro_btn.configure(state="normal", text="⚡ 매크로 (F8)")
        self._update_bot_status()

    def _stop_all(self):
        """전체 중지"""
        self._stop_refresh()
        self._stop_macro_bot()
        self._stop_hybrid()

    def _run_refresh_bot(self):
        """별도 스레드: 새로고침 봇"""
        try:
            from .standalone import refresh_bot
            result = refresh_bot(self._cfg, stop_event=self._refresh_stop_event)
            if result.get("success"):
                logger.info("✅ 새로고침 봇 완료: %s", result.get("message", ""))
            else:
                logger.warning("⚠️ 새로고침 봇: %s", result.get("message", ""))
        except Exception as e:
            logger.error("❌ 새로고침 봇 오류: %s", e)
            import traceback
            traceback.print_exc()
        finally:
            self.after(0, self._stop_refresh)

    def _run_macro_bot(self):
        """별도 스레드: 매크로 봇"""
        try:
            from .standalone import macro_bot
            result = macro_bot(self._cfg, stop_event=self._macro_stop_event)
            if result.get("success"):
                logger.info("🎉 매크로 봇 완료: %s", result.get("message", ""))
            else:
                logger.warning("⚠️ 매크로 봇: %s", result.get("message", ""))
        except Exception as e:
            logger.error("❌ 매크로 봇 오류: %s", e)
            import traceback
            traceback.print_exc()
        finally:
            self.after(0, self._stop_macro_bot)

    # ── 하이브리드 새로고침 ──

    def _toggle_hybrid(self):
        """F9: 하이브리드 새로고침 봇 시작/중지"""
        if self._hybrid_running:
            self._stop_hybrid()
        else:
            self._start_hybrid()

    def _start_hybrid(self):
        """하이브리드 새로고침 봇 시작"""
        self._collect_ui_to_cfg()
        self._hybrid_running = True
        self._hybrid_stop_event.clear()
        self._hybrid_btn.configure(state="disabled", text="🔄 하이브리드중...")
        self._update_bot_status()
        threading.Thread(target=self._run_hybrid_bot, daemon=True).start()

    def _stop_hybrid(self):
        """하이브리드 새로고침 봇 중지"""
        self._hybrid_running = False
        self._hybrid_stop_event.set()
        self._hybrid_btn.configure(state="normal", text="🔄 하이브리드 (F9)")
        self._update_bot_status()

    def _run_hybrid_bot(self):
        """별도 스레드: 하이브리드 새로고침 + 예매 봇"""
        try:
            from .standalone import hybrid_book
            result = hybrid_book(self._cfg, stop_event=self._hybrid_stop_event)
            if result.get("success"):
                logger.info("✅ 하이브리드 예매 완료: %s", result.get("message", ""))
            else:
                logger.warning("⚠️ 하이브리드 예매 실패: %s", result.get("message", ""))
        except Exception as e:
            logger.error("❌ 하이브리드 새로고침 오류: %s", e)
            import traceback
            traceback.print_exc()
        finally:
            self.after(0, self._stop_hybrid)

    # ── 도구 메뉴 ──

    def _run_global_picker(self):
        """글로벌 좌표 따기 도구"""
        logger.info("🌐 글로벌 좌표 따기 시작...")
        threading.Thread(target=self._do_global_pick, daemon=True).start()

    def _do_global_pick(self):
        coord = self._run_picker_sync(use_global=True)
        if coord:
            x, y = coord["x"], coord["y"]
            # 먼저 클립보드에 복사 후 메시지 표시
            self.after(0, lambda: (
                self.clipboard_clear(),
                self.clipboard_append(f"{x}, {y}"),
            ))
            self.after(50, lambda: messagebox.showinfo(
                "좌표", f"📌 ({x}, {y})\n클립보드에 복사됨"))

    # ── 도움말 ──

    def _show_help(self):
        messagebox.showinfo(
            "📖 사용법",
            "🎫 티켓링크봇 — KBO 야구 예매 자동화\n\n"
            "1. 좌표 설정: 각 버튼의 위치를 '따기' 버튼으로 설정\n"
            "2. 좌석 영역: 빈 좌석의 색상과 검색 영역 설정\n"
            "3. 새로고침봇(F6) → 예매하기 + 확인까지 자동\n"
            "4. 매크로봇(F8) → 캡차 + 좌석검색 + 결제까지 자동\n"
            "5. 하이브리드봇(F9) → CDP 폴링 + 예매하기 자동클릭\n\n"
            "🎯 좌표 따기:\n"
            "  - '글로벌' 버튼 → 화면 어디서나 우클릭\n\n"
            "⌨️ 단축키:\n"
            "  F6: 새로고침 봇 시작/중지\n"
            "  F8: 매크로 봇 시작/중지\n"
            "  F9: 하이브리드 새로고침\n"
            "  ESC: 종료"
        )

    def _show_about(self):
        messagebox.showinfo(
            "ℹ️ 버전 정보",
            f"🎫 티켓링크봇 v{__version__}\n\n"
            "KBO 야구 예매 자동화 프로그램\n"
            "시스템 매크로 모드 (Chrome 불필요)\n\n"
            "© 2026 ticketlink-bot"
        )

    # ── 글로벌 핫키 ──

    def _init_hotkeys(self):
        """pynput 글로벌 키보드 리스너 (F6/F7/ESC)"""
        try:
            from pynput import keyboard as _kb
            def _on_press(key):
                try:
                    if key == _kb.Key.f6:
                        self.after(0, self._toggle_refresh)
                    elif key == _kb.Key.f8:
                        self.after(0, self._toggle_macro)
                    elif key == _kb.Key.f9:
                        self.after(0, self._toggle_hybrid)
                    elif key == _kb.Key.esc:
                        self.after(0, self._on_close)
                except Exception:
                    pass
            self._hotkey_listener = _kb.Listener(on_press=_on_press)
            self._hotkey_listener.daemon = True
            self._hotkey_listener.start()
            logger.info("⌨️ 글로벌 핫키: F6=새로고침봇, F8=매크로봇, F9=하이브리드, ESC=종료")
        except ImportError:
            logger.info("  pynput 미설치 — 글로벌 핫키 미지원")
        except Exception as e:
            logger.debug("  핫키 초기화 실패: %s", e)

    def _toggle_start_stop(self):
        """(deprecated) F6 핫키 → _toggle_refresh 로 대체"""
        self._toggle_refresh()

    # ── 종료 ──

    def _on_close(self):
        """프로그램 종료"""
        if self._refresh_running or self._macro_running:
            if not messagebox.askyesno("종료 확인", "봇이 실행 중입니다. 종료할까요?"):
                return
        self._stop_all()
        if self._hotkey_listener:
            self._hotkey_listener.stop()
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
