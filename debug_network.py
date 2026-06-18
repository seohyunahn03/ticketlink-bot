#!/usr/bin/env python3.14
"""네트워크 요청 트래킹 + 로그인 클릭"""
import asyncio
from playwright.async_api import async_playwright

async def debug_network():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page(viewport={'width': 1280, 'height': 900})
    
    # 네트워크 요청 트래킹
    requests = []
    page.on('request', lambda req: requests.append({
        'url': req.url[:120], 
        'method': req.method,
        'type': req.resource_type
    }))
    
    await page.goto('https://www.ticketlink.co.kr', wait_until='domcontentloaded')
    await asyncio.sleep(3)
    
    print(f"초기 로드 후 요청 수: {len(requests)}")
    
    # 로그인 클릭 전 요청 리셋
    requests.clear()
    
    # 오버레이 제거
    await page.evaluate("""
        () => {
            document.querySelectorAll('.dimmed, [class*="popup"]').forEach(el => el.remove());
            document.body.style.overflow = 'auto';
        }
    """)
    await asyncio.sleep(1)
    
    # 로그인 클릭 (dispatch_event로 React 이벤트 직접 트리거)
    link = page.locator('a.header_util_link').filter(has_text='로그인')
    print(f"로그인 링크 발견: {await link.count() > 0}")
    
    await link.first.dispatch_event('click')
    await asyncio.sleep(5)
    
    print(f"\n로그인 클릭 후 요청 ({len(requests)}개):")
    for req in requests[-20:]:
        print(f"  [{req['method']}] {req['url']}")
    
    # 페이지 상태
    has_payco = await page.evaluate("""
        () => {
            const html = document.body.innerHTML;
            const hasEmailInput = html.includes('이메일') || html.includes('email') || html.includes('Email');
            const hasPaycoText = html.includes('PAYCO') || html.includes('payco');
            const newInputs = document.querySelectorAll('input').length;
            return { hasEmailInput, hasPaycoText, newInputs, url: location.href };
        }
    """)
    print(f"\n페이지 상태: {has_payco}")
    
    await browser.close()
    await p.stop()

asyncio.run(debug_network())
