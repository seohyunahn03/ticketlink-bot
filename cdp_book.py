#!/usr/bin/env python3.14
"""
🎫 티켓링크 CDP 모드 — 이미 로그인된 Chrome 세션 활용
"""
import asyncio, sys
from playwright.async_api import async_playwright

CDP_URL = 'http://localhost:9222'

async def cdp_book(keyword):
    p = await async_playwright().start()
    
    # 이미 로그인된 Chrome에 연결
    browser = await p.chromium.connect_over_cdp(CDP_URL)
    print(f"✅ Chrome CDP 연결 완료 (버전: {await browser.version})")
    
    # 기존 탭들 확인
    contexts = browser.contexts
    if contexts:
        pages = contexts[0].pages
        for pg in pages:
            url = pg.url
            if 'ticketlink' in url:
                print(f"  📌 티켓링크 탭 발견: {url[:60]}")
                page = pg
                break
        else:
            # 새 탭 열기
            page = await contexts[0].new_page()
            print("  📌 새 탭 오픈")
    else:
        page = await browser.new_page()
        print("  📌 새 페이지 생성")
    
    # 티켓링크 접속 (이미 쿠키 있음 → 로그인 상태)
    if 'ticketlink' not in page.url:
        print("\n[1/4] 티켓링크 접속...")
        await page.goto('https://www.ticketlink.co.kr', wait_until='domcontentloaded', timeout=30000)
        
        # SPA 로딩 대기
        for i in range(15):
            await asyncio.sleep(1)
            try:
                ok = await page.evaluate("document.querySelector('.header_util_list') !== null")
                if ok:
                    print(f"  ✓ 로딩 완료 ({i+1}초)")
                    break
            except:
                pass
        
        # 오버레이 제거
        try:
            await page.evaluate("""() => {
                const p = document.querySelector('.full_page_pop');
                if (p) p.style.display = 'none';
                document.body.style.overflow = 'auto';
            }""")
        except:
            pass
        await asyncio.sleep(2)
    
    # 로그인 상태 확인
    header = await page.evaluate("""() => 
        Array.from(document.querySelectorAll('.header_util_link, .header_util_list a, .member_info'))
            .map(a => a.textContent.trim())
    """)
    print(f"  👤 헤더: {header}")
    
    logged_in = any('@' in h or '님' in h or '로그아웃' in h for h in header)
    if logged_in:
        print("  🎉 이미 로그인 상태!")
    else:
        print("  ⚠️ 로그인 필요 → 직접 Chrome에서 로그인해주세요")
        # 그냥 진행 (사용자가 로그인했다고 했으니)
    
    # 검색
    print(f"\n[2/4] '{keyword}' 검색중...")
    
    # 검색창 찾아서 입력
    found = await page.evaluate(f"""(kw) => {{
        const inputs = document.querySelectorAll('input');
        for (const inp of inputs) {{
            if (inp.placeholder && inp.placeholder.includes('검색')) {{
                const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                s.call(inp, kw);
                inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                const e = new KeyboardEvent('keydown', {{
                    key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
                }});
                inp.dispatchEvent(e);
                return true;
            }}
        }}
        return false;
    }}""", keyword)
    
    if found:
        print("  ✓ 검색어 입력 완료")
    else:
        # 직접 URL로 이동
        search_url = f"https://www.ticketlink.co.kr/search?keyword={keyword}"
        await page.goto(search_url, wait_until='domcontentloaded')
        print(f"  → 검색 URL로 이동")
    
    await asyncio.sleep(5)
    print(f"  📍 현재 URL: {page.url[:80]}")
    
    # 상품 클릭
    print(f"\n[3/4] 상품 선택중...")
    clicked = await page.evaluate("""() => {
        const items = document.querySelectorAll('a[href*="product"], li a');
        for (const item of items) {
            if (item.href && item.href.includes('product') && !item.href.includes('home')) {
                item.click(); return item.href;
            }
        }
        return null;
    }""")
    
    if clicked:
        print(f"  ✓ 상품 선택: {clicked[:60]}")
    else:
        print("  ⚠️ 자동 선택 실패 — 브라우저에서 직접 선택해주세요")
        print(f"  🔗 {page.url}")
    
    await asyncio.sleep(5)
    
    # 예매하기 버튼
    print(f"\n[4/4] 예매 시도...")
    booking = await page.evaluate("""() => {
        const btns = document.querySelectorAll('a, button, span');
        for (const b of btns) {
            const t = b.textContent.trim();
            if (t.includes('예매하기') || t === '예매') { b.click(); return t; }
        }
        return null;
    }""")
    
    if booking:
        print(f"  ✓ '{booking}' 클릭!")
    else:
        print("  ⚠️ 예매 버튼 미발견 — 직접 클릭해주세요")
    
    await asyncio.sleep(3)
    print(f"\n✅ 완료! URL: {page.url}")
    print("👉 브라우저가 열려 있으니 직접 확인해보세요!")
    
    # 브라우저는 닫지 않음 (사용자 Chrome이므로)
    # p.stop()도 하지 않음

async def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else input("검색어: ")
    await cdp_book(keyword)

if __name__ == "__main__":
    asyncio.run(main())
