#!/usr/bin/env python3.14
"""테스트: preventDefault + click"""
import asyncio
from playwright.async_api import async_playwright

async def test():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page(viewport={'width': 1280, 'height': 900})
    
    await page.goto('https://www.ticketlink.co.kr', wait_until='domcontentloaded')
    await asyncio.sleep(3)
    
    # 오버레이 제거
    await page.evaluate("""
        () => document.querySelectorAll('.full_page_pop, .dimmed').forEach(el => el.remove());
    """)
    await asyncio.sleep(1)
    
    # 로그인 버튼 찾아서 제대로 클릭
    result = await page.evaluate("""
        () => {
            const link = document.querySelector('a.header_util_link');
            if (!link) return 'link_not_found';
            
            // 1) React 이벤트 핸들러 확인
            const handlers = Object.keys(link).filter(k => k.startsWith('__react'));
            
            // 2) Native click 이벤트 생성 (preventDefault 포함)
            const event = new MouseEvent('click', {
                bubbles: true,
                cancelable: true,
                view: window,
                button: 0,
                buttons: 1
            });
            
            // 3) href 기본동작 방지
            link.addEventListener('click', e => e.preventDefault(), {once: true});
            
            // 4) 클릭 이벤트 dispatch
            const result = link.dispatchEvent(event);
            
            return JSON.stringify({
                reactHandlers: handlers,
                dispatchResult: result,
                defaultPrevented: event.defaultPrevented,
                href: link.href
            });
        }
    """)
    
    print("클릭 결과:", result)
    await asyncio.sleep(4)
    
    # PAYCO 모달 확인
    html = await page.content()
    has_payco_form = '이메일' in html and ('password' in html or '비밀번호' in html)
    inputs = await page.evaluate("""
        () => Array.from(document.querySelectorAll('input'))
            .map(i => i.placeholder || i.type)
    """)
    print(f"PAYCO 폼: {has_payco_form}")
    print(f"Inputs: {inputs}")
    
    # 스크린샷
    await page.screenshot(path='/tmp/tl_payco_test.png', full_page=True)
    print("스크린샷: /tmp/tl_payco_test.png")
    
    await browser.close()
    await p.stop()

asyncio.run(test())
