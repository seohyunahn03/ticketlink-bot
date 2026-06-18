#!/usr/bin/env python3.14
"""최종 테스트: Playwright click vs evaluate click"""
import asyncio
from playwright.async_api import async_playwright

async def test():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=False)  # 실제 창
    page = await browser.new_page(viewport={'width': 1280, 'height': 900})
    
    await page.goto('https://www.ticketlink.co.kr')
    await asyncio.sleep(4)
    
    # full_page_pop만 제거 (dimmed는 남김 - 클릭을 막지만 React 이벤트는 통과)
    await page.evaluate("""() => {
        const pop = document.querySelector('.full_page_pop');
        if (pop) pop.remove();
    }""")
    await asyncio.sleep(1)
    
    # Playwright 진짜 click 시도 (force=False지만 dimmed가 없으니 통과)
    print("Playwright click 시도...")
    try:
        await page.locator('a.header_util_link').filter(has_text='로그인').first.click(timeout=10000)
        print("  click 성공!")
    except Exception as e:
        print(f"  click 실패: {str(e)[:80]}")
        # fallback: scroll into view + force
        await page.locator('a.header_util_link').filter(has_text='로그인').first.click(force=True, timeout=5000)
        print("  force click 시도")
    
    await asyncio.sleep(5)
    
    # 결과
    info = await page.evaluate("""() => {
        const inputs = Array.from(document.querySelectorAll('input')).map(i => i.placeholder || i.type);
        const hasPayco = document.body.innerHTML.includes('이메일') && document.body.innerHTML.includes('비밀번호');
        return JSON.stringify({inputs, hasPayco, url: location.href, title: document.title});
    }""")
    print(f"\n결과: {info}")
    
    await page.screenshot(path='/tmp/tl_final_test.png')
    print("\n스크린샷: /tmp/tl_final_test.png")
    print("\n5초 후 종료됩니다 (직접 확인 가능)")
    await asyncio.sleep(10)
    await browser.close()
    await p.stop()

asyncio.run(test())
