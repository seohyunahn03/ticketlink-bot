#!/usr/bin/env python3.14
"""
티켓링크 + 페이코 로그인 테스트 v3
견고한 버전 - 각 단계별 안정적 처리
"""
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PwTimeout

EMAIL = "taehwanahn01@naver.com"
PASSWORD = "athath1206!"
BIRTH = "20011206"

async def safe_goto(page, url, timeout=30000):
    """안전한 페이지 이동"""
    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=timeout)
    except Exception as e:
        print(f"   ⚠️ goto 경고: {e}")
    await page.wait_for_timeout(3000)

async def safe_click(page, selector, timeout=5000):
    """안전한 클릭 (JS eval 우선)"""
    try:
        result = await page.evaluate(f"""
            (() => {{
                const el = document.querySelector('{selector}');
                if (el) {{ el.click(); return 'ok'; }}
                // 텍스트 매칭
                const byText = document.querySelector('[class*="close"], [class*="Close"], button');
                if (byText && byText.textContent.includes('닫기')) {{ byText.click(); return 'ok'; }}
                return 'not_found';
            }})()
        """)
        return result
    except Exception as e:
        return f'error: {e}'

async def test_login():
    print("🚀 티켓링크 v3 시작...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
        )
        
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 900},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='ko-KR'
        )
        
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko']});
        """)
        
        page = await context.new_page()
        
        # 1. 접속
        print("📍 1. 티켓링크 접속...")
        await safe_goto(page, 'https://www.ticketlink.co.kr')
        await page.screenshot(path='/tmp/tl_01_main.png', full_page=True)
        
        # 2. 팝업 닫기 (딤드 제거)
        print("📍 2. 오버레이/팝업 제거...")
        
        # JS로 모든 팝업/딤드 제거
        await page.evaluate("""
            () => {
                // 모든 딤드/팝업 요소 제거
                document.querySelectorAll('.dimmed, .popup, .modal, .full_page_pop, [class*="popup"], [class*="dim"]').forEach(el => {
                    if (el.style) el.style.display = 'none';
                    if (el.remove) el.remove();
                });
                // 닫기 버튼들 클릭
                document.querySelectorAll('button, a').forEach(el => {
                    if (el.textContent.trim() === '닫기' || el.textContent.trim() === 'close') {
                        el.click();
                    }
                });
                // overflow 복원
                document.body.style.overflow = 'auto';
            }
        """)
        await page.wait_for_timeout(2000)
        print("   ✅ 오버레이 제거 완료")
        await page.screenshot(path='/tmp/tl_02_clear.png', full_page=True)
        
        # 3. 로그인 페이지로 이동
        print("📍 3. 로그인 페이지 이동...")
        
        # 방법1: 직접 URL 이동
        await safe_goto(page, 'https://www.ticketlink.co.kr/login?returnUrl=%2Fhome')
        await page.screenshot(path='/tmp/tl_03_login_page.png', full_page=True)
        print(f"   URL: {page.url}")
        
        # 방법2: 안되면 메인에서 로그인 클릭
        if 'login' not in page.url.lower():
            print("   -> 메인에서 로그인 버튼 클릭 시도")
            await safe_goto(page, 'https://www.ticketlink.co.kr')
            await page.wait_for_timeout(2000)
            
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
            await page.wait_for_timeout(3000)
            await page.screenshot(path='/tmp/tl_03b_login_click.png', full_page=True)
            print(f"   URL: {page.url}")
        
        # 4. Payco 로그인 버튼 찾기
        print("📍 4. Payco 로그인 찾기...")
        
        await page.evaluate("""
            () => {
                const links = document.querySelectorAll('a, button, img');
                for (const el of links) {
                    const text = el.textContent || el.alt || '';
                    if (text.includes('PAYCO') || text.includes('페이코')) {
                        el.click();
                        return true;
                    }
                }
                // href로 찾기
                for (const el of document.querySelectorAll('a')) {
                    if (el.href && el.href.includes('payco')) {
                        window.open(el.href, '_self');
                        return true;
                    }
                }
                return false;
            }
        """)
        await page.wait_for_timeout(5000)
        await page.screenshot(path='/tmp/tl_04_payco_click.png', full_page=True)
        print(f"   URL: {page.url}")
        print(f"   Title: {await page.title()}")
        
        # 5. Payco 로그인 폼 (iframe 또는 새 페이지)
        print("📍 5. Payco 로그인 폼 확인...")
        
        # 모든 프레임 출력
        for i, frame in enumerate(page.frames):
            url = frame.url[:120]
            print(f"   프레임[{i}]: {url}")
            
            if 'payco' in url.lower():
                print(f"   ✅ Payco iframe 발견!")
                await frame.screenshot(path='/tmp/tl_05_payco_iframe.png')
                
                # Payco 로그인 폼 찾기
                for selector in ['input[name="email"]', 'input[type="email"]', 'input[id*="email"]', 'input[id*="userName"]', 'input[placeholder*="이메일"]', 'input[placeholder*="아이디"]']:
                    inp = frame.locator(selector)
                    if await inp.count() > 0:
                        await inp.first.fill(EMAIL)
                        print(f"   ✅ 이메일 입력 ({selector})")
                        break
                
                for selector in ['input[type="password"]', 'input[name*="pw"]', 'input[id*="pw"]', 'input[id*="password"]']:
                    inp = frame.locator(selector)
                    if await inp.count() > 0:
                        await inp.first.fill(PASSWORD)
                        print(f"   ✅ 비밀번호 입력 ({selector})")
                        break
                
                await frame.screenshot(path='/tmp/tl_05_filled.png')
                
                # 로그인 버튼
                for selector in ['button[type="submit"]', 'button:has-text("로그인")', 'a:has-text("로그인")', 'button:has-text("확인")']:
                    btn = frame.locator(selector)
                    if await btn.count() > 0:
                        await btn.first.click()
                        print(f"   ✅ 로그인 버튼 클릭 ({selector})")
                        break
        
        await page.wait_for_timeout(5000)
        await page.screenshot(path='/tmp/tl_06_after_login.png', full_page=True)
        print(f"   URL: {page.url}")
        print(f"   Title: {await page.title()}")
        
        # 6. 추가인증 처리
        print("📍 6. 추가인증 확인...")
        html = await page.content()
        
        if '생년월일' in html or 'birth' in html.lower() or '추가인증' in html:
            print("   ⚠️ 추가인증 필요!")
            for selector in ['input[placeholder*="생년월일"]', 'input[placeholder*="주민"]', 'input[name*="birth"]', 'input[type="tel"]']:
                inp = page.locator(selector)
                if await inp.count() > 0:
                    await inp.first.fill(BIRTH)
                    print(f"   ✅ 생년월일 입력 ({selector})")
                    break
            
            for selector in ['button:has-text("확인")', 'button:has-text("인증")', 'button:has-text("완료")']:
                btn = page.locator(selector)
                if await btn.count() > 0:
                    await btn.first.click()
                    print(f"   ✅ 인증 버튼 클릭")
                    break
            
            await page.wait_for_timeout(3000)
            await page.screenshot(path='/tmp/tl_07_auth_done.png', full_page=True)
        
        # 7. 최종 결과
        print(f"\n📍 최종 URL: {page.url}")
        print(f"📍 최종 Title: {await page.title()}")
        
        final_url = page.url
        if 'login' not in final_url.lower() and 'Login' not in final_url:
            print("🎉🎉🎉 로그인 성공!")
        else:
            print("⚠️ 로그인 페이지에 남아있음 (수동 확인 필요)")
        
        await page.screenshot(path='/tmp/tl_final.png', full_page=True)
        print("\n🏁 모든 스크린샷 저장 완료!")
        print("   /tmp/tl_01_main.png")
        print("   /tmp/tl_02_clear.png")
        print("   /tmp/tl_03_login_page.png")
        print("   /tmp/tl_04_payco_click.png")
        print("   /tmp/tl_06_after_login.png")
        print("   /tmp/tl_final.png")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_login())
