#!/usr/bin/env python3.14
"""
🎫 티켓팅 매크로 v3.0 — 티켓링크
"""
import sys, asyncio
from src.ticketlink import load_config, save_config, reserve_ticket, search_only

def main():
    if len(sys.argv) < 2:
        print("🎫 티켓팅 매크로 v3.0")
        print("=" * 30)
        print("  config              PAYCO 로그인 설정")
        print("  search <검색어>     로그인 + 검색")
        print("  book <검색어>       예매시도 (브라우저 오픈)")
        return
    
    cmd = sys.argv[1]
    if cmd == 'config':
        e = input("PAYCO 아이디: ").strip()
        p = input("PAYCO 비밀번호: ").strip()
        b = input("생년월일 8자리: ").strip()
        save_config({'payco_id': e, 'payco_pw': p, 'payco_birth': b or None})
        print("✅ 저장 완료!")
    elif cmd == 'search':
        kw = sys.argv[2] if len(sys.argv) > 2 else input("검색어: ")
        print(asyncio.run(search_only(kw)))
    elif cmd == 'book':
        kw = sys.argv[2] if len(sys.argv) > 2 else input("검색어: ")
        print(asyncio.run(reserve_ticket(kw)))
    else:
        print(f"알 수 없는 명령: {cmd}")

if __name__ == "__main__":
    main()
