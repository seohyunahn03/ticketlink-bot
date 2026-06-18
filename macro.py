#!/usr/bin/env python3.14
"""
🎫 티켓링크 LG 트윈스 예매 매크로 v1.0
- Chrome 세션 쿠키 재사용 (로그인 불필요)
- 특정 구단 페이지 → 예매 가능 경기 확인 → 자동 예매

사용법:
  python3.14 macro.py                  # 대화형 모드
  python3.14 macro.py --help           # 도움말
  python3.14 macro.py --url https://www.ticketlink.co.kr/sports/137/59
  python3.14 macro.py --auto           # 첫 번째 예매가능 경기 자동 예매
"""
import asyncio, json, os, sys, argparse
from datetime import datetime
from playwright.async_api import async_playwright

# ===== 설정 =====
COOKIE_PATH = '/Users/taehwan/.hermes/ticketing/cookies/ticketlink_cookies.json'
BASE_URL = 'https://www.ticketlink.co.kr'

# ===== 유틸 =====
def load_cookies():
    if not os.path.exists(COOKIE_PATH):
        print(f"❌ 쿠키 파일 없음: {COOKIE_PATH}")
        print("   Chrome에서 티켓링크 로그인 후 cookie-update 명령을 실행하세요")
        return None
    with open(COOKIE_PATH) as f:
        return json.load(f)

async def run_macro(url=None, auto_book=False, headless=False):
    """메인 매크로 함수"""
    
    cookies = load_cookies()
    if not cookies:
        return 1
    
    target_url = url or f'{BASE_URL}/sports/137/59'
    
    print(f"🚀 티켓링크 매크로 시작")
    print(f"   대상: {target_url}")
    print(f"   모드: {'자동 예매' if auto_book else '대화형'}")
    print(f"   시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    p = await async_playwright().start()
    
    # 기존 크롬 프로필 사용 (로그인 세션 유지)
    import platform
    is_mac = platform.system() == 'Darwin'
    chrome_paths = [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',  # Mac
    ]
    chrome_path = None
    for cp in chrome_paths:
        if os.path.exists(cp):
            chrome_path = cp
            break
    
    user_data_dir = os.path.expanduser('~/Library/Application Support/Google/Chrome')
    
    if chrome_path and os.path.exists(user_data_dir):
        # 실제 Chrome + 기존 프로필 사용
        browser = await p.chromium.launch(
            headless=headless,
            executable_path=chrome_path,
            args=[
                f'--user-data-dir={user_data_dir}',
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--no-first-run',
                '--no-default-browser-check',
            ]
        )
        print("✅ 실제 Chrome + 기존 프로필 사용")
    else:
        # 기본 Playwright Chrome
        browser = await p.chromium.launch(
            headless=headless,
            args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
        )
        print("✅ Playwright Chrome 사용")
    
    context = await browser.new_context(
        viewport={'width': 1280, 'height': 900},
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36',
        locale='ko-KR',
        timezone_id='Asia/Seoul'
    )
    
    # 강력한 stealth 스크립트
    await context.add_init_script("""
        // webdriver 속성 제거
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        
        // Chrome 자동화 플래그 제거
        Object.defineProperty(navigator, '__webdriver_evaluate', {get: () => undefined});
        Object.defineProperty(navigator, '__selenium_evaluate', {get: () => undefined});
        Object.defineProperty(navigator, '__fxdriver_evaluate', {get: () => undefined});
        Object.defineProperty(navigator, '__driver_evaluate', {get: () => undefined});
        Object.defineProperty(navigator, '__webdriver_script_fn', {get: () => undefined});
        
        // plugins, languages 정상화
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US', 'en']});
        
        // chrome.runtime 제거 (Playwright 흔적)
        if (window.chrome && window.chrome.runtime) {
            Object.defineProperty(window.chrome, 'runtime', {get: () => undefined});
        }
        
        // permissions 정상화
        const originalQuery = window.navigator.permissions?.query;
        if (originalQuery) {
            window.navigator.permissions.query = (params) => (
                params.name === 'notifications' ?
                Promise.resolve({state: Notification.permission}) :
                originalQuery(params)
            );
        }
    """)
    
    # 쿠키 주입 (로그인 세션 복원)
    if cookies:
        await context.add_cookies(cookies)
        print("✅ 쿠키 로드 완료 (로그인 세션 복원)")
    else:
        print("⚠️ 쿠키 없음 — Chrome에 직접 로그인 필요")
    
    page = await context.new_page()
    
    # 1. 대상 페이지 접속
    print(f"\n📡 페이지 접속중...")
    await page.goto(target_url, wait_until='domcontentloaded', timeout=30000)
    
    # SPA 로딩 대기
    for i in range(20):
        await asyncio.sleep(1)
        try:
            body = await page.evaluate("document.body?.innerText?.substring(0, 500) || ''")
            if '야구' in body or '경기' in body or 'LG' in body or '예매' in body:
                print(f"  ✓ 페이지 로딩 완료 ({i+1}초)")
                break
        except:
            pass
    else:
        print("  ⚠️ 페이지 로딩이 느립니다 (계속 진행)")
    
    # 2. 페이지 정보 출력
    title = await page.title()
    print(f"\n📄 페이지 제목: {title}")
    print(f"   URL: {page.url}")
    
    # 3. 경기 목록 확인
    print(f"\n🏟️ 경기 목록 스캔중...")
    
    # 다양한 셀렉터로 경기 항목 찾기
    games = await page.evaluate("""() => {
        const results = [];
        
        // 방법 1: 상품 리스트
        const items = document.querySelectorAll('[class*="product"], [class*="card"], [class*="item"], li, .list_item, [class*="schedule"], [class*="match"], [class*="game"]');
        
        for (const item of items) {
            const text = item.textContent.trim().replace(/\\s+/g, ' ').substring(0, 200);
            if (!text || text.length < 5) continue;
            
            // 경기 관련 키워드 포함 확인
            const hasGame = /경기|vs|LG|트윈스|야구|예매|대|match/i.test(text);
            const hasButton = item.querySelector('a, button, [class*="btn"]');
            
            if (hasGame) {
                results.push({
                    text: text.substring(0, 150),
                    hasButton: !!hasButton,
                    buttons: Array.from(item.querySelectorAll('a, button')).map(b => ({
                        text: b.textContent.trim().substring(0, 30),
                        href: b.href || ''
                    }))
                });
            }
        }
        
        // 방법 2: 모든 버튼/링크에서 '예매' 찾기
        const bookingBtns = [];
        const allLinks = document.querySelectorAll('a, button');
        for (const el of allLinks) {
            const t = el.textContent.trim();
            if (t.includes('예매') || t.includes('예약')) {
                bookingBtns.push({
                    text: t.substring(0, 30),
                    href: el.href || '',
                    tag: el.tagName,
                    id: el.id || '',
                    class: (el.className || '').substring(0, 60)
                });
            }
        }
        
        return JSON.stringify({games: results.slice(0, 10), bookingBtns: bookingBtns.slice(0, 10)});
    }""")
    
    data = json.loads(games)
    
    print(f"\n  📋 찾은 경기: {len(data['games'])}개")
    for i, g in enumerate(data['games']):
        print(f"     [{i+1}] {g['text'][:80]}...")
        if g['buttons']:
            for b in g['buttons']:
                print(f"         → {b['text']}")
    
    print(f"\n  🎯 '예매' 버튼: {len(data['bookingBtns'])}개")
    for i, b in enumerate(data['bookingBtns']):
        print(f"     [{i+1}] '{b['text']}' | 링크: {b['href'][:60] or '없음'} | 태그: {b['tag']}")
    
    # 4. 자동 예매 모드
    if auto_book and data['bookingBtns']:
        btn = data['bookingBtns'][0]
        print(f"\n🔄 자동 예매 진행중...")
        
        if btn['href']:
            await page.goto(btn['href'], wait_until='domcontentloaded')
            print(f"  → 예매 페이지 이동: {btn['href'][:60]}")
        else:
            # 버튼 클릭
            clicked = await page.evaluate("""(targetText) => {
                const all = document.querySelectorAll('a, button');
                for (const el of all) {
                    if (el.textContent.trim().includes(targetText)) {
                        el.click();
                        return el.textContent.trim();
                    }
                }
                return null;
            }""", btn['text'])
            print(f"  → '{clicked}' 버튼 클릭")
        
        await asyncio.sleep(5)
        print(f"\n✅ 예매 페이지 진입!")
        print(f"   URL: {page.url}")
        
        # 좌석 선택 페이지 확인
        page_text = await page.evaluate("document.body?.innerText?.substring(0, 1000) || ''")
        print(f"\n📄 페이지 내용 (일부):")
        print(f"   {page_text[:500].replace(chr(10), ' ')}")
    
    print(f"\n{'='*50}")
    print(f"✅ 매크로 실행 완료!")
    print(f"👉 브라우저가 열려 있으니 직접 확인해보세요")
    
    if not headless and not auto_book:
        # 대화형 모드: 브라우저 유지
        input("\n⏸️  Enter 누르면 브라우저를 닫습니다...")
    
    await browser.close()
    await p.stop()
    return 0

def main():
    parser = argparse.ArgumentParser(description='🎫 티켓링크 LG 트윈스 예매 매크로')
    parser.add_argument('--url', default=f'{BASE_URL}/sports/137/59',
                       help='대상 페이지 URL')
    parser.add_argument('--auto', action='store_true',
                       help='자동 예매 모드 (첫 번째 예매가능 경기)')
    parser.add_argument('--headless', action='store_true',
                       help='헤드리스 모드 (브라우저 안 띄움)')
    parser.add_argument('--cookie-update', action='store_true',
                       help='Chrome에서 쿠키 다시 가져오기')
    
    args = parser.parse_args()
    
    if args.cookie_update:
        # CDP로 쿠키 가져오기
        print("🔄 Chrome에서 쿠키 업데이트중...")
        print("   (별도 스크립트: python3 save_cookies.py)")
        return
    
    asyncio.run(run_macro(
        url=args.url,
        auto_book=args.auto,
        headless=args.headless
    ))

if __name__ == '__main__':
    main()
