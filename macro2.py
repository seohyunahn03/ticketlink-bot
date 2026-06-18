#!/usr/bin/env python3.14
"""
🎫 티켓링크 LG 트윈스 예매 매크로 v2.0 — STEALTH MODE
- playwright-stealth 탑재 (자동화 탐지 우회)
- Chrome 쿠키 재사용 (로그인 불필요)
- SPA 로딩 안정화

사용법:
  python3.14 macro2.py                          # 대화형
  python3.14 macro2.py --auto                   # 자동 예매 시도
  python3.14 macro2.py --cookie-update           # 쿠키 새로고침
"""
import asyncio, json, os, sys, argparse
from datetime import datetime
from playwright.async_api import async_playwright

# ===== 설정 =====
COOKIE_PATH = '/Users/taehwan/.hermes/ticketing/cookies/ticketlink_cookies.json'
BASE_URL = 'https://www.ticketlink.co.kr'

def load_cookies():
    if not os.path.exists(COOKIE_PATH):
        print(f"❌ 쿠키 파일 없음: {COOKIE_PATH}")
        return None
    with open(COOKIE_PATH) as f:
        return json.load(f)

async def stealth_page(page):
    """playwright-stealth 적용"""
    try:
        import playwright_stealth
        await playwright_stealth.stealth_async(page)
        return True
    except Exception as e:
        print(f"  ⚠️ stealth 적용 실패: {e}")
        return False

async def wait_for_spa(page, keyword, timeout=25):
    """SPA 로딩 대기"""
    for i in range(timeout):
        await asyncio.sleep(1)
        try:
            text = await page.evaluate("document.body?.innerText || ''")
            if keyword in text:
                return True
        except:
            pass
    return False

async def run_macro(url=None, auto_book=False, headless=False):
    cookies = load_cookies()
    if not cookies:
        return 1

    target_url = url or f'{BASE_URL}/sports/137/59'

    print(f"🚀 티켓링크 매크로 v2.0")
    print(f"   대상: {target_url}")
    print(f"   모드: {'자동 예매' if auto_book else '대화형'}")
    print(f"   시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=headless,
        args=[
            '--no-sandbox',
            '--disable-blink-features=AutomationControlled',
            '--disable-features=ChromeWhatsNewUI,InterestFeedContentSuggestions',
        ]
    )

    context = await browser.new_context(
        viewport={'width': 1280, 'height': 900},
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36',
        locale='ko-KR',
        timezone_id='Asia/Seoul',
        device_scale_factor=2,
    )

    # stealth 적용
    page = await context.new_page()
    stealthed = await stealth_page(page)
    if stealthed:
        print("✅ stealth 모드 활성화")
    else:
        print("⚠️ stealth 미적용 — 수동 스크립트로 대체")

    # 추가 stealth 스크립트 (playwright-stealth 보강)
    await context.add_init_script("""
        // 추가 우회
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        if (window.chrome && window.chrome.runtime) {
            Object.defineProperty(window.chrome, 'runtime', {get: () => undefined});
        }
    """)

    # 쿠키 주입
    if cookies:
        try:
            await context.add_cookies(cookies)
            print("✅ 쿠키 로드 완료 (로그인 세션 복원)")
        except Exception as e:
            print(f"⚠️ 쿠키 주입 오류: {e}")

    # 1. 대상 페이지 접속
    print(f"\n📡 {target_url}")
    await page.goto(target_url, wait_until='domcontentloaded', timeout=30000)

    loaded = await wait_for_spa(page, '야구', timeout=20)
    if loaded:
        print("✅ 페이지 로딩 완료")
    else:
        print("⚠️ 페이지 로딩 상태 불확실")

    title = await page.title()
    print(f"\n📄 {title}")
    
    # 2. 로그인 상태 확인
    login_status = await page.evaluate("""() => {
        const text = document.body?.innerText || '';
        if (text.includes('로그아웃')) return '로그인 ✅';
        if (text.includes('@')) return '로그인 ✅';
        return '로그아웃 상태 ❌';
    }""")
    print(f"👤 {login_status}")

    # 3. 경기/예매 버튼 스캔
    print(f"\n🔍 페이지 스캔중...")
    
    data = await page.evaluate("""() => {
        const text = document.body?.innerText?.replace(/\\s+/g, ' ') || '';
        const allBtns = document.querySelectorAll('a, button, [role="button"], span[class*="btn"], div[class*="btn"]');
        const booking = [];
        for (const el of allBtns) {
            const t = el.textContent?.trim();
            if (t && (t.includes('예매') || t.includes('예약') || t.includes('구매'))) {
                booking.push({
                    text: t.substring(0, 40),
                    href: el.href || '',
                    tag: el.tagName,
                    id: (el.id || '').substring(0, 30),
                    cls: (el.className || '').substring(0, 50)
                });
            }
        }
        return JSON.stringify({
            preview: text.substring(0, 600),
            bookingBtns: booking
        });
    }""")
    
    result = json.loads(data)
    print(f"  페이지 미리보기: {result['preview'][:200]}")
    
    if result['bookingBtns']:
        print(f"\n🎯 예매 버튼 {len(result['bookingBtns'])}개 발견!")
        for i, b in enumerate(result['bookingBtns']):
            print(f"  [{i+1}] '{b['text']}' | {b['href'][:60] or '클릭가능'}")
        
        if auto_book:
            btn = result['bookingBtns'][0]
            print(f"\n🔄 자동 예매 진행...")
            if btn['href']:
                await page.goto(btn['href'], wait_until='domcontentloaded')
                print(f"  → 이동: {btn['href'][:60]}")
            else:
                clicked = await page.evaluate(f"""() => {{
                    const all = document.querySelectorAll('a, button, [role="button"]');
                    for (const el of all) {{
                        const t = el.textContent?.trim() || '';
                        if (t.includes('{btn['text'][:10]}')) {{
                            el.click();
                            return true;
                        }}
                    }}
                    return false;
                }}""")
                print(f"  → {'클릭 성공 ✅' if clicked else '클릭 실패 ❌'}")
            
            await asyncio.sleep(5)
            print(f"  📍 {page.url}")
    else:
        print("\n❌ 예매 버튼을 찾을 수 없습니다.")
        print("  → 직접 브라우저를 확인해주세요")

    print(f"\n{'='*50}")
    print(f"✅ 매크로 완료")
    
    if not headless and not auto_book:
        input("\n⏸️  Enter → 종료")
    
    await browser.close()
    await p.stop()
    return 0

def main():
    parser = argparse.ArgumentParser(description='🎫 티켓링크 매크로 v2')
    parser.add_argument('--url', default=f'{BASE_URL}/sports/137/59')
    parser.add_argument('--auto', action='store_true', help='자동 예매')
    parser.add_argument('--headless', action='store_true', help='헤드리스')
    args = parser.parse_args()
    asyncio.run(run_macro(url=args.url, auto_book=args.auto, headless=args.headless))

if __name__ == '__main__':
    main()
