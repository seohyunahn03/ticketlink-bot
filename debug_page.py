#!/usr/bin/env python3.14
"""로그인 클릭 후 페이지 상태 덤프"""
import asyncio, json
from playwright.async_api import async_playwright

async def debug():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page(viewport={'width': 1280, 'height': 900})
    
    await page.goto('https://www.ticketlink.co.kr', wait_until='domcontentloaded')
    await asyncio.sleep(3)
    
    # remove overlays
    await page.evaluate("""
        () => {
            const b = document.querySelector('.gnb_banner');
            if (b) b.style.display = 'none';
            document.querySelectorAll('.dimmed, [class*="popup"]').forEach(el => el.remove());
        }
    """)
    await asyncio.sleep(1)
    
    # click login
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
    await asyncio.sleep(4)
    
    # dump page info
    info = await page.evaluate("""
        () => {
            const allText = document.body.innerText.substring(0, 3000);
            const inputs = Array.from(document.querySelectorAll('input')).map(i => ({
                type: i.type, placeholder: i.placeholder, id: i.id, name: i.name, className: i.className.substring(0,60)
            }));
            const buttons = Array.from(document.querySelectorAll('button')).map(b => ({
                text: b.textContent.trim().substring(0,30), disabled: b.disabled
            }));
            const forms = document.querySelectorAll('form').length;
            const iframes = document.querySelectorAll('iframe').length;
            const visibleInputs = inputs.filter(i => {
                const style = document.querySelector(i.id ? '#'+i.id : 'input[type="'+i.type+'"]');
                return style && style.offsetParent !== null;
            });
            return JSON.stringify({
                url: location.href,
                title: document.title,
                inputs, buttons, forms, iframes,
                visibleInputCount: visibleInputs.length,
                textSample: allText.substring(0, 2000),
                htmlSample: document.body.innerHTML.substring(0, 3000)
            }, null, 2);
        }
    """)
    print(info)
    
    await browser.close()
    await p.stop()

asyncio.run(debug())
