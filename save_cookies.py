#!/usr/bin/env python3.14
"""티켓링크 쿠키 저장 스크립트 — Chrome CDP에서 쿠키 추출"""
import json, sys

COOKIE_PATH = '/Users/taehwan/.hermes/ticketing/cookies/ticketlink_cookies.json'

CDP_WS = 'ws://localhost:9222/devtools/browser/3941751a-a76f'

async def fetch_and_save():
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    browser = await p.chromium.connect_over_cdp(CDP_WS)
    
    # 모든 쿠키 수집
    ctx = browser.contexts[0]
    cookies = await ctx.cookies()
    
    target_domains = ['ticketlink.co.kr', 'payco.com', 'nhnlink.co.kr', 'nhnace.com']
    filtered = [c for c in cookies if any(d in c.get('domain', '') for d in target_domains)]
    
    with open(COOKIE_PATH, 'w') as f:
        json.dump(filtered, f, indent=2)
    
    print(f"✅ {len(filtered)}개 쿠키 저장 완료 → {COOKIE_PATH}")
    await browser.close()
    await p.stop()

if __name__ == '__main__':
    import asyncio
    asyncio.run(fetch_and_save())
