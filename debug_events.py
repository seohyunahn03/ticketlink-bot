#!/usr/bin/env python3.14
"""로그인 링크의 React 이벤트 핸들러 확인"""
import asyncio
from playwright.async_api import async_playwright

async def test():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page(viewport={'width': 1280, 'height': 900})
    
    await page.goto('https://www.ticketlink.co.kr', wait_until='domcontentloaded')
    await asyncio.sleep(4)
    
    # React props 확인 (이벤트 핸들러)
    info = await page.evaluate("""() => {
        const link = document.querySelector('a.header_util_link');
        if (!link) return 'no_link';
        const keys = Object.keys(link).filter(k => k.startsWith('__reactProps'));
        const props = {};
        for (const key of keys) {
            const p = link[key];
            for (const k in p) {
                if (k.startsWith('on')) props[k] = p[k] ? p[k].toString().substring(0,200) : null;
            }
        }
        return JSON.stringify(props);
    }""")
    print("React event handlers:", info)
    
    await browser.close()
    await p.stop()

asyncio.run(test())
