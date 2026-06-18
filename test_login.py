#!/usr/bin/env python3.14
"""
티켓링크 + 페이코 로그인 테스트
Playwright로 직접 브라우저 띄워서 확인
"""
import asyncio
import sys
from playwright.async_api import async_playwright

EMAIL = "taehwanahn01@naver.com"
PASSWORD = "athath1206!"
BIRTH = "20011206"  # 추가인증

async def test_login():
    print("🚀 티켓링크 로그인 테스트 시작...")
    
    async with async_playwright() as p:
        # Chrome 실행 옵션
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--window-size=1280,900',
            ]
        )
        
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 900},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
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
        await page.wait_for_timeout(3000)
        await page.screenshot(path='/tmp/tl_01_main.png')
        print("   ✅ 메인 페이지 로딩 완료 → /tmp/tl_01_main.png")
        
        # 2. 로그인 버튼 클릭
        print("📍 2. 로그인 버튼 클릭...")
        login_btn = page.locator('a:has-text("로그인")')
        if await login_btn.count() > 0:
            await login_btn.first.click()
            await page.wait_for_timeout(3000)
            await page.screenshot(path='/tmp/tl_02_login.png')
            print("   ✅ 로그인 페이지 이동 → /tmp/tl_02_login.png")
        else:
            print("   ❌ 로그인 버튼을 찾을 수 없음")
            await page.screenshot(path='/tmp/tl_02_error.png')
        
        # 3. Payco 로그인 버튼 찾기
        print("📍 3. Payco 로그인 버튼 찾기...")
        
        # iframe이나 팝업 형태일 수 있음
        payco_btn = page.locator('a:has-text("PAYCO"), button:has-text("PAYCO"), img[alt*="PAYCO"]')
        if await payco_btn.count() > 0:
            await payco_btn.first.click()
            await page.wait_for_timeout(5000)
            await page.screenshot(path='/tmp/tl_03_payco_click.png')
            print("   ✅ Payco 버튼 클릭 → /tmp/tl_03_payco_click.png")
        else:
            print("   ⚠️ Payco 버튼 미발견, 페이지 HTML 저장")
            html = await page.content()
            with open('/tmp/tl_page.html', 'w', encoding='utf-8') as f:
                f.write(html)
            print("   → /tmp/tl_page.html 저장됨")
        
        # 4. 현재 페이지 상태 확인
        print(f"\n📍 현재 URL: {page.url}")
        print(f"📍 페이지 타이틀: {await page.title()}")
        
        # 모든 iframe 확인
        iframes = page.frames
        print(f"📍 iframes: {len(iframes)}개")
        for i, f in enumerate(iframes):
            print(f"   [{i}] {f.url}")
        
        await page.screenshot(path='/tmp/tl_04_state.png')
        print("   → /tmp/tl_04_state.png")
        
        # 5. Payco 로그인 팝업 처리 (팝업이 열리면)
        print("\n📍 5. Payco 팝업 대기...")
        
        # 페이지 내 Payco 로그인 iframe 찾기
        for i, frame in enumerate(page.frames):
            if 'payco' in frame.url.lower():
                print(f"   ✅ Payco iframe 발견! [{i}] {frame.url}")
                await frame.screenshot(path=f'/tmp/tl_payco_iframe_{i}.png')
                
                # Payco 로그인 폼 찾기
                email_input = frame.locator('input[name="email"], input[type="email"], input[id*="email"], input[id*="user"], input[placeholder*="이메일"], input[placeholder*="아이디"]')
                if await email_input.count() > 0:
                    await email_input.first.fill(EMAIL)
                    print(f"   ✅ 이메일 입력 완료")
                
                pw_input = frame.locator('input[type="password"], input[name*="pw"], input[name*="pass"], input[id*="pw"], input[id*="pass"]')
                if await pw_input.count() > 0:
                    await pw_input.first.fill(PASSWORD)
                    print(f"   ✅ 비밀번호 입력 완료")
                
                await frame.screenshot(path=f'/tmp/tl_payco_filled.png')
                
                # 로그인 버튼
                login_submit = frame.locator('button[type="submit"], button:has-text("로그인"), a:has-text("로그인")')
                if await login_submit.count() > 0:
                    await login_submit.first.click()
                    print(f"   ✅ 로그인 버튼 클릭")
                    await page.wait_for_timeout(5000)
                    await page.screenshot(path='/tmp/tl_05_logged_in.png')
                    print(f"   → /tmp/tl_05_logged_in.png")
                break
        else:
            print("   ⚠️ Payco iframe 미발견 - 일반 로그인 시도")
            # 일반 로그인 폼 찾기
            email_input = page.locator('input[name="userId"], input[name="id"], input[placeholder*="아이디"]')
            if await email_input.count() > 0:
                await email_input.first.fill(EMAIL)
                print("   ✅ ID 입력 완료")
            
            pw_input = page.locator('input[type="password"]')
            if await pw_input.count() > 0:
                await pw_input.first.fill(PASSWORD)
                print("   ✅ PW 입력 완료")
            
            await page.screenshot(path='/tmp/tl_05_filled.png')
            
            submit_btn = page.locator('button[type="submit"], button:has-text("로그인"), a:has-text("로그인")')
            if await submit_btn.count() > 0:
                await submit_btn.first.click()
                print("   ✅ 로그인 버튼 클릭")
                await page.wait_for_timeout(5000)
                await page.screenshot(path='/tmp/tl_06_after_login.png')
        
        # 6. 추가인증 처리
        print("\n📍 6. 추가인증 확인...")
        
        # 생년월일 6자리 입력 필드 찾기
        birth_input = page.locator('input[placeholder*="생년월일"], input[placeholder*="주민"], input[name*="birth"], input[id*="birth"], input[type="tel"]')
        if await birth_input.count() > 0:
            await birth_input.first.fill(BIRTH)
            print("   ✅ 생년월일 입력 완료")
            
            confirm_btn = page.locator('button:has-text("확인"), button:has-text("인증"), button:has-text("완료")')
            if await confirm_btn.count() > 0:
                await confirm_btn.first.click()
                print("   ✅ 확인 버튼 클릭")
                await page.wait_for_timeout(3000)
        
        await page.screenshot(path='/tmp/tl_07_final.png')
        print(f"\n✅ 최종 상태 → /tmp/tl_07_final.png")
        print(f"✅ 최종 URL: {page.url}")
        print(f"✅ 최종 타이틀: {await page.title()}")
        
        # 7. 로그인 성공 여부 확인
        if "login" not in page.url.lower():
            print("🎉 로그인 성공!")
        else:
            print("⚠️ 로그인 페이지에 남아있음 - 수동 확인 필요")
        
        await page.wait_for_timeout(5000)
        await browser.close()
        print("\n🏁 테스트 종료")

if __name__ == "__main__":
    asyncio.run(test_login())
