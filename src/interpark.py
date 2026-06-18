"""
인터파크/NOL 티켓 예매 자동화
"""
import re
import time
from typing import Optional

from playwright.sync_api import Page, expect

from .browser import BrowserManager
from .notifier import Notifier
from .config import load_config


class InterparkTicket:
    """인터파크 티켓 예매 매크로"""

    DOMAIN = "ticket.interpark.com"

    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = cfg or load_config()
        self.bm = BrowserManager(cfg)
        self.notifier = Notifier(cfg)
        self.page: Optional[Page] = None
        self._logged_in = False

    # ── 진입 ──────────────────────────────────────────────

    def start(self):
        """브라우저 실행 후 인터파크 메인 접속"""
        self.page = self.bm.start()
        self.page.goto("https://ticket.interpark.com", wait_until="load", timeout=30000)
        self.bm.screenshot("01_main")
        print("  ✅ 인터파크 메인 로딩 완료")
        return self

    def close(self):
        self.bm.close()

    # ── 로그인 ──────────────────────────────────────────────

    def login(self, user_id: str = "", password: str = ""):
        """인터파크 로그인"""
        uid = user_id or self.cfg["interpark"]["id"]
        pw = password or self.cfg["interpark"]["password"]
        if not uid or not pw:
            print("  ⚠️ 인터파크 ID/PW가 설정되지 않았습니다.")
            return self

        print("  🔑 인터파크 로그인 중...")
        self.page.goto(
            "https://ticket.interpark.com/Gate/TPLogin.asp",
            wait_until="domcontentloaded", timeout=20000
        )

        # ID 입력
        id_sel = self.page.locator("#user_id, input[name='user_id'], input[name='uid']")
        id_sel.first.fill(uid)

        # PW 입력
        pw_sel = self.page.locator("#user_pw, input[name='user_pw'], input[name='upw']")
        pw_sel.first.fill(pw)

        # 로그인 버튼 클릭
        login_btn = self.page.locator(
            "a:has-text('로그인'), button:has-text('로그인'), "
            "input[type='image'], .btnLogin, #loginBtn"
        )
        login_btn.first.click(timeout=5000)
        self.page.wait_for_timeout(3000)
        self.bm.screenshot("02_login")

        # 로그인 확인
        if "Login" in self.page.title() or "login" in self.page.url:
            print("  ⚠️ 로그인 실패. 수동 로그인 필요할 수 있음")
        else:
            self._logged_in = True
            print("  ✅ 로그인 성공!")

        return self

    # ── 콘서트 검색 ─────────────────────────────────────────

    def search(self, keyword: str):
        """공연/콘서트 검색"""
        print(f"  🔍 검색: '{keyword}'")
        search_box = self.page.locator(
            "#search_word, input[name='keyword'], input[name='search_word'], "
            ".search_input input[type='text'], input[placeholder*='검색']"
        )
        if search_box.count() > 0:
            search_box.first.fill(keyword)
            self.page.keyboard.press("Enter")
        else:
            # 검색창이 없으면 URL로 직접 이동
            encoded = keyword.replace(" ", "+")
            self.page.goto(
                f"https://ticket.interpark.com/Search/SearchResult.asp?keyword={encoded}",
                wait_until="domcontentloaded", timeout=15000
            )

        self.page.wait_for_timeout(3000)
        self.bm.screenshot("03_search")
        return self

    def select_product(self, index: int = 0):
        """검색 결과에서 상품 선택"""
        print(f"  🎯 검색 결과 중 #{index + 1} 선택")
        
        # 일반적인 검색 결과 링크 패턴
        links = self.page.locator(
            "a:has-text('예매'), a:has-text('티켓'), "
            ".prdTitle a, .productList a, .searchResult a, "
            "td a[href*='GoodsPlay']"
        )
        count = links.count()
        if count > 0:
            idx = min(index, count - 1)
            links.nth(idx).click(timeout=5000)
            self.page.wait_for_timeout(3000)
            self.bm.screenshot("04_product")
            print(f"  ✅ 상품 선택 완료")
        else:
            print("  ⚠️ 검색 결과를 찾을 수 없습니다")
        return self

    # ── 날짜/회차 선택 ──────────────────────────────────────

    def select_date(self, date_text: str = ""):
        """날짜/회차 선택"""
        print(f"  📅 날짜 선택: '{date_text or '첫번째'}'")
        
        # 1) iframe 전환 (인터파크는 iframe 다수)
        self._switch_to_content_iframe()

        # 2) 날짜 선택
        if date_text:
            day_btn = self.page.locator(
                f"a:has-text('{date_text}'), "
                f"td:has-text('{date_text}') a, "
                f".calendar a:has-text('{date_text}')"
            ).first
            if day_btn.count() > 0:
                day_btn.click(timeout=5000)
        else:
            # 첫 번째 예매 가능 날짜
            avail = self.page.locator(
                ".sticky a, .playDate a, .date a, "
                "td a[href*='PlaySeq'], td[class*='on'] a"
            ).first
            if avail.count() > 0:
                avail.click(timeout=5000)
                print("  ✅ 첫 번째 날짜 선택")

        self.page.wait_for_timeout(2000)
        self.bm.screenshot("05_date")
        return self

    def select_time(self, time_text: str = ""):
        """회차/시간 선택"""
        print(f"  🕐 회차 선택: '{time_text or '첫번째'}'")
        
        time_btns = self.page.locator(
            ".time a, .round a, .playTime a, "
            "a[href*='TimeSeq']"
        )
        if time_btns.count() > 0:
            if time_text:
                for i in range(time_btns.count()):
                    if time_text in time_btns.nth(i).text_content():
                        time_btns.nth(i).click(timeout=3000)
                        break
            else:
                time_btns.first.click(timeout=3000)
            self.page.wait_for_timeout(2000)
            print("  ✅ 회차 선택 완료")
        self.bm.screenshot("06_time")
        return self

    # ── 좌석 선택 ──────────────────────────────────────────

    def select_zone(self, zone_text: str = ""):
        """구역/등급 선택"""
        print(f"  💺 구역 선택: '{zone_text or '일반'}'")
        
        self._switch_to_seat_iframe()

        zones = self.page.locator(
            ".gradeTable a, .seatGrade a, .zone a, "
            "a[href*='Grade'], td a img[alt*='석']"
        )
        if zones.count() > 0:
            if zone_text:
                for i in range(zones.count()):
                    t = zones.nth(i).text_content() or zones.nth(i).get_attribute("alt") or ""
                    if zone_text in t:
                        zones.nth(i).click(timeout=3000)
                        break
            else:
                zones.first.click(timeout=3000)
            self.page.wait_for_timeout(2000)
            print("  ✅ 구역 선택 완료")
        self.bm.screenshot("07_zone")
        return self

    def auto_select_seats(self, count: int = 1):
        """자동 좌석 선택 (최고 우선)"""
        print(f"  🪑 좌석 {count}개 자동 선택...")
        
        self._switch_to_seat_iframe()

        # 좌석 선택 버튼
        auto_btn = self.page.locator(
            "a:has-text('자동배정'), a:has-text('자동선택'), "
            ".autoSeat a, #autoSeatBtn"
        )
        if auto_btn.count() > 0:
            auto_btn.first.click(timeout=5000)
            self.page.wait_for_timeout(2000)

        # 인원수 선택 (2인 이상)
        if count > 1:
            for btn_text in [str(count), f"{count}매", f"{count}석"]:
                qty_btn = self.page.locator(f"a:has-text('{btn_text}'), option:has-text('{btn_text}')")
                if qty_btn.count() > 0:
                    qty_btn.first.click(timeout=3000)
                    break

        # 좌선선택 완료 버튼
        confirm = self.page.locator(
            "a:has-text('선택완료'), a:has-text('좌석선택'), "
            ".btnSelect a, #btnSeatSelect"
        )
        if confirm.count() > 0:
            confirm.first.click(timeout=5000)

        self.page.wait_for_timeout(2000)
        self.bm.screenshot("08_seats")
        return self

    # ── 예매 진행 ───────────────────────────────────────────

    def go_to_payment(self):
        """결제 페이지로 이동 (사용자 확인)"""
        print("  💳 결제 페이지 이동...")
        self.page.wait_for_timeout(1000)

        # 메인 iframe으로 복귀 후 예매 버튼
        self.page.frame_locator("iframe[name*='Content'], iframe[name*='content']")
        
        book_btn = self.page.locator(
            "a:has-text('예매하기'), a:has-text('결제하기'), "
            ".btnBooking a, #btnBooking, .btnPayment a"
        )
        if book_btn.count() > 0:
            book_btn.first.click(timeout=5000)
            self.page.wait_for_timeout(3000)

        self.bm.screenshot("09_payment")
        print("  ✅ 결제 페이지 도착!")
        print("  ⚠️ 결제는 직접 진행해주세요 (보안 정책)")
        return self

    # ── 내부 헬퍼 ───────────────────────────────────────────

    def _switch_to_content_iframe(self):
        """콘텐츠 iframe으로 전환 시도"""
        for name_pattern in ["Content", "content", "main", "Main"]:
            frame = self.page.frame_locator(f"iframe[name*='{name_pattern}']")
            if frame.first.count() > 0:
                return frame
        return None

    def _switch_to_seat_iframe(self):
        """좌석 iframe으로 전환 시도"""
        for name_pattern in ["Seat", "seat", "Map"]:
            frame = self.page.frame_locator(f"iframe[name*='{name_pattern}']")
            if frame.first.count() > 0:
                return frame
        return None

    # ── 원클릭 예매 ─────────────────────────────────────────

    def quick_book(self, keyword: str, date: str = "", count: int = 1):
        """원클릭 예매: 로그인→검색→날짜→회차→좌석→결제"""
        try:
            self.start()
            self.login()
            self.search(keyword)
            self.page.wait_for_timeout(2000)
            self.select_product()
            self.page.wait_for_timeout(2000)
            self.select_date(date)
            self.page.wait_for_timeout(1000)
            self.select_time()
            self.page.wait_for_timeout(1000)
            self.auto_select_seats(count)
            self.page.wait_for_timeout(1000)
            self.go_to_payment()

            self.notifier.alert_reservation_done(
                "인터파크", keyword,
                f"날짜: {date or '자동'} | {count}매"
            )
        except Exception as e:
            print(f"  ❌ 오류: {e}")
            self.notifier.alert_error("인터파크", str(e))
            self.bm.screenshot("error")
