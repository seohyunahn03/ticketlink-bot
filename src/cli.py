"""
티켓팅 매크로 CLI
"""
import argparse
import sys
import os

# 프로젝트 루트를 path에 추가
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)


def cmd_config(args):
    """설정 마법사 실행"""
    from src.config import setup_interactive
    setup_interactive()


def cmd_interpark(args):
    """인터파크 예매"""
    from src.interpark import InterparkTicket

    bot = InterparkTicket()
    try:
        bot.start()
        bot.login()
        if args.search:
            bot.search(args.search)
            bot.page.wait_for_timeout(2000)
            bot.select_product(args.index)
            bot.page.wait_for_timeout(2000)
            bot.select_date(args.date)
            bot.page.wait_for_timeout(1000)
            bot.select_time(args.time)
            bot.page.wait_for_timeout(1000)
            bot.auto_select_seats(args.count)
            bot.page.wait_for_timeout(1000)
            if args.payment:
                bot.go_to_payment()
        print("\n✅ 작업 완료! 브라우저는 열려 있습니다.")
        print("ℹ️  종료하려면 Ctrl+C")
        try:
            import time
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
    finally:
        if not args.keep:
            bot.close()


def cmd_ticketlink(args):
    """티켓링크 예매"""
    from src.ticketlink import TicketlinkTicket

    bot = TicketlinkTicket()
    try:
        bot.start()
        bot.login()
        if args.search:
            bot.search_game(args.search)
            bot.page.wait_for_timeout(2000)
            bot.select_game()
            bot.page.wait_for_timeout(2000)
            bot.book_ticket(args.date)
            bot.page.wait_for_timeout(1500)
            bot.select_seats(args.count)
            bot.page.wait_for_timeout(1000)
            if args.payment:
                bot.go_to_payment()
        print("\n✅ 작업 완료! 브라우저는 열려 있습니다.")
        print("ℹ️  종료하려면 Ctrl+C")
        try:
            import time
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
    finally:
        if not args.keep:
            bot.close()


def cmd_cancel_sniper(args):
    """취소표 스나이퍼 (watchdog)"""
    from src.interpark import InterparkTicket
    from src.notifier import Notifier
    import time

    notifier = Notifier()
    print(f"🔍 취소표 감시 시작: '{args.search}' (30초 간격)")
    print("   발견 시 알림 + 자동 예매 시도")

    bot = InterparkTicket()
    bot.start()
    bot.login()

    checked_urls = set()

    try:
        while True:
            try:
                bot.search(args.search)
                bot.page.wait_for_timeout(2000)

                # 잔여석 확인 (사이트별 로직에 따라 조정)
                page_text = bot.page.locator("body").inner_text(timeout=5000)
                
                if "예매" in page_text and ("취소" in page_text or "잔여" in page_text):
                    # 취소표 발견!
                    msg = f"🎯 취소표 발견! '{args.search}'"
                    print(f"\n  {msg}")
                    notifier.alert_ticket_open("인터파크", args.search, bot.page.url)
                    
                    # 자동 예매 시도
                    bot.select_product()
                    bot.page.wait_for_timeout(1500)
                    bot.select_date(args.date)
                    bot.page.wait_for_timeout(1000)
                    bot.auto_select_seats(args.count)
                    bot.page.wait_for_timeout(1000)
                    bot.go_to_payment()
                    break

                print(f"  ⏳ 대기중... ({time.strftime('%H:%M:%S')})", end="\r")
                time.sleep(30)

            except Exception as e:
                print(f"\n  ⚠️ {e}")
                time.sleep(30)
    except KeyboardInterrupt:
        print("\n  👋 감시 종료")
    finally:
        bot.close()


def main():
    parser = argparse.ArgumentParser(
        description="🎫 티켓팅 매크로 — 인터파크/NOL + 티켓링크",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예:
  # 설정
  python3 cli.py config

  # 인터파크 콘서트 예매
  python3 cli.py interpark --search "김범수" --count 2 --payment

  # 티켓링크 야구 예매
  python3 cli.py ticketlink --search "LG 트윈스" --count 2 --payment

  # 취소표 감시
  python3 cli.py cancel-sniper --search "임영웅" --date "7월 20일"
        """
    )
    sub = parser.add_subparsers(dest="command")

    # config
    p_conf = sub.add_parser("config", help="설정 마법사")

    # interpark
    p_ip = sub.add_parser("interpark", help="인터파크 예매")
    p_ip.add_argument("--search", "-s", help="검색어 (공연명)")
    p_ip.add_argument("--date", "-d", default="", help="날짜/회차")
    p_ip.add_argument("--time", "-t", default="", help="시간")
    p_ip.add_argument("--count", "-c", type=int, default=1, help="매수")
    p_ip.add_argument("--index", "-i", type=int, default=0, help="검색결과 인덱스")
    p_ip.add_argument("--payment", "-p", action="store_true", help="결제페이지까지 이동")
    p_ip.add_argument("--keep", "-k", action="store_true", help="브라우저 유지")

    # ticketlink
    p_tl = sub.add_parser("ticketlink", help="티켓링크 예매")
    p_tl.add_argument("--search", "-s", help="검색어 (팀명/경기명)")
    p_tl.add_argument("--date", "-d", default="", help="날짜")
    p_tl.add_argument("--count", "-c", type=int, default=1, help="매수")
    p_tl.add_argument("--payment", "-p", action="store_true", help="결제페이지까지 이동")
    p_tl.add_argument("--keep", "-k", action="store_true", help="브라우저 유지")

    # cancel sniper
    p_cs = sub.add_parser("cancel-sniper", help="취소표 감시")
    p_cs.add_argument("--search", "-s", required=True, help="검색어")
    p_cs.add_argument("--date", "-d", default="", help="날짜")
    p_cs.add_argument("--count", "-c", type=int, default=1, help="매수")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    runners = {
        "config": cmd_config,
        "interpark": cmd_interpark,
        "ticketlink": cmd_ticketlink,
        "cancel-sniper": cmd_cancel_sniper,
    }
    runners[args.command](args)


if __name__ == "__main__":
    main()
