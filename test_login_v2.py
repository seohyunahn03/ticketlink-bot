#!/usr/bin/env python3.14
"""
티켓링크 + 페이코 로그인 테스트 v2
팝업/딤드 처리 추가
"""
import asyncio
from playwright.async_api import async_playwright

EMAIL = "taehwanahn01@naver.com"
PASSWORD = "athath1206!"
BIRTH = "20011206"  # 추가인증

async def test_login():
    print("🚀 티켓링크 로그인 테스트 v2 시작...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,  # headless 모드
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--window-size=1280,900',
            ]
        )
        
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 900},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            locale='ko-KR'
        )
        
        # bot 탐지 우회
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko']});
        """)
        
        page = await context.new_page()
        
        # 1. 티켓링크 메인 접속
        print("📍 1. 티켓링크 접속...")
        await page.goto('https://www.ticketlink.co.kr', wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)
        await page.screenshot(path='/tmp/tl_01_main.png', full_page=True)
        print("   ✅ 메인 페이지 → /tmp/tl_01_main.png")
        
        # 2. 팝업/딤드 처리
        print("📍 2. 팝업/오버레이 처리...")
        
        # "닫기" 버튼 찾아서 클릭 (여러 개 있을 수 있음)
        close_btns = page.locator('button:has-text("닫기"), a:has-text("닫기"), .popup_close, .btn_close')
        close_count = await close_btns.count()
        print(f"   닫기 버튼 {close_count}개 발견")
        
        for i in range(close_count):
            try:
                await close_btns.nth(i).click(timeout=2000)
                await page.wait_for_timeout(500)
                print(f"   ✅ 닫기 버튼[{i}] 클릭 완료")
            except:
                print(f"   ⚠️ 닫기 버튼[{i}] 클릭 실패")
        
        await page.wait_for_timeout(1000)
        await page.screenshot(path='/tmp/tl_02_after_popup.png', full_page=True)
        print("   ✅ 팝업 처리 완료 → /tmp/tl_02_after_popup.png")
        
        # 3. HTML 확인
        html_preview = await page.content()
        with open('/tmp/tl_page.html', 'w', encoding='utf-8') as f:
            f.write(html_preview[:50000])
        print("   ✅ HTML 저장 → /tmp/tl_page.html")
        
        # 4. 로그인 / PAYCO 버튼 찾기
        print("📍 3. 로그인 버튼 찾기...")
        
        # 방법1: "로그인" 텍스트 링크
        login_btn = page.locator('a.header_util_link, a:has-text("로그인")')
        login_count = await login_btn.count()
        print(f"   로그인 버튼: {login_count}개")
        
        if login_count > 0:
            # JavaScript로 강제 클릭
            await page.evaluate("""
                () => {
                    const links = document.querySelectorAll('a');
                    for (const link of links) {
                        if (link.textContent.trim() === '로그인') {
                            link.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            print("   ✅ 로그인 링크 JS 클릭 완료")
            await page.wait_for_timeout(3000)
        else:
            print("   ⚠️ 로그인 버튼 미발견")
        
        await page.screenshot(path='/tmp/tl_03_after_login.png', full_page=True)
        print(f"   현재 URL: {page.url}")
        
        # 5. Payco 로그인 버튼
        print("📍 4. Payco 로그인 시도...")
        
        # Payco 버튼 찾기
        payco_found = await page.evaluate("""
            () => {
                const links = document.querySelectorAll('a, button');
                for (const el of links) {
                    if (el.textContent.includes('PAYCO') || el.textContent.includes('페이코')) {
                        el.click();
                        return el.textContent.trim();
                    }
                }
                return null;
            }
        """)
        print(f"   Payco 버튼: {payco_found if payco_found else '미발견'}")
        
        await page.wait_for_timeout(5000)
        await page.screenshot(path='/tmp/tl_04_payco_click.png', full_page=True)
        print(f"   현재 URL: {page.url}")
        
        # 6. iframe 확인
        print("📍 5. iframe 검사...")
        for i, frame in enumerate(page.frames):
            print(f"   [{i}] {frame.url[:100]}")
            if 'payco' in frame.url.lower():
                print(f"   ✅ Payco iframe 발견! [{i}]")
                await frame.screenshot(path=f'/tmp/tl_payco_iframe.png')
                
                # Payco 로그인
                await frame.fill('input[name="email"], input[type="email"]', EMAIL)
                print("   ✅ 이메일 입력")
                await frame.fill('input[type="password"]', PASSWORD)
                print("   ✅ 비밀번호 입력")
                await frame.screenshot(path=f'/tmp/tl_payco_filled.png')
                
                # 로그인 버튼
                btn = frame.locator('button[type="submit"]')
                if await btn.count() > 0:
                    await btn.click()
                    print("   ✅ 로그인 버튼 클릭")
                break
        
        await page.wait_for_timeout(5000)
        await page.screenshot(path='/tmp/tl_05_result.png', full_page=True)
        
        # 7. 최종 결과
        print(f"\n📍 최종 URL: {page.url}")
        print(f"📍 최종 타이틀: {await page.title()}")
        
        # 추가인증 확인
        html = await page.content()
        if 'birth' in html.lower() or '생년월일' in html or '추가인증' in html:
            print("⚠️ 추가인증 페이지 감지!")
            await page.screenshot(path='/tmp/tl_06_auth.png', full_page=True)
        
        if 'login' not in page.url.lower() and 'Login' not in page.url:
            print("🎉 로그인 성공!")
        else:
            print("⚠️ 로그인 페이지에 남아있음")
        
        await browser.close()
        print("\n🏁 테스트 종료")

if __name__ == "__main__":
    asyncio.run(test_login())
