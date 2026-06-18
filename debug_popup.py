#!/usr/bin/env python3.14
"""티켓링크 PAYCO 로그인 — 팝업 방식 테스트"""
import asyncio
import json
from playwright.async_api import async_playwright

EMAIL = "taehwanahn01@naver.com"
PASSWORD = "athath1206!"
BIRTH = "20011206"

async def test():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page(viewport={'width': 1280, 'height': 900})
    
    # 1. 메인 페이지 접속
    print("[1] 티켓링크 접속...")
    await page.goto('https://www.ticketlink.co.kr', wait_until='domcontentloaded')
    await asyncio.sleep(4)
    
    # 2. full_page_pop 제거 (클릭 방해 요소)
    print("[2] 오버레이 제거...")
    await page.evaluate("""() => {
        const pop = document.querySelector('.full_page_pop');
        if (pop) pop.remove();
        document.body.style.overflow = 'auto';
    }""")
    await asyncio.sleep(1)
    
    # 3. 팝업 대기 상태 설정 + 로그인 클릭
    print("[3] 로그인 버튼 클릭 + 팝업 대기...")
    
    async with page.expect_popup() as popup_info:
        # evaluate로 link.click() 실행 (href 기본동작 방지)
        await page.evaluate("""() => {
            const link = document.querySelector('a.header_util_link');
            if (!link) return;
            // React onClick 트리거 (link.click()으로)
            link.click();
        }""")
    
    # 4. 팝업 획득
    popup = await popup_info.value
    print(f"[4] 팝업 열림: {popup.url[:100]}")
    await asyncio.sleep(3)
    
    # 팝업 상태
    popup_info_data = await popup.evaluate("""() => {
        return JSON.stringify({
            url: location.href,
            title: document.title,
            inputs: Array.from(document.querySelectorAll('input')).map(i => i.type + ':' + (i.placeholder || '')),
            buttons: Array.from(document.querySelectorAll('button')).map(b => b.textContent.trim()).filter(t => t)
        });
    }""")
    print(f"   팝업 상태: {popup_info_data}")
    await popup.screenshot(path='/tmp/tl_popup.png')
    
    # 5. PAYCO 로그인 폼 입력
    popup_data = json.loads(popup_info_data)
    has_payco = any('이메일' in i or '아이디' in i for i in popup_data['inputs'])
    
    if has_payco:
        print("[5] PAYCO 로그인 폼 입력...")
        
        # 이메일
        await popup.evaluate(f"""(email) => {{
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {{
                if (inp.type === 'text' || inp.type === 'email') {{
                    const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    s.call(inp, email);
                    inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                    break;
                }}
            }}
        }}""", EMAIL)
        
        # 비밀번호
        await popup.evaluate(f"""(pw) => {{
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {{
                if (inp.type === 'password') {{
                    const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    s.call(inp, pw);
                    inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                    break;
                }}
            }}
        }}""", PASSWORD)
        
        await popup.screenshot(path='/tmp/tl_popup_filled.png')
        print("   ✓ 정보 입력 완료")
        
        # 로그인 버튼
        await popup.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '로그인' && !btn.disabled) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")
        print("   ✓ 로그인 버튼 클릭")
        await asyncio.sleep(3)
        
        # 팝업 상태 확인 (추가인증?)
        popup_html = await popup.content()
        if '새로운 기기' in popup_html or '생년월일' in popup_html:
            print("[6] 추가인증 처리...")
            await popup.evaluate(f"""(birth) => {{
                const inputs = document.querySelectorAll('input');
                for (const inp of inputs) {{
                    if (inp.type === 'tel') {{
                        const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                        s.call(inp, birth);
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        break;
                    }}
                }}
                const btns = document.querySelectorAll('button:not([disabled])');
                for (const btn of btns) {{
                    if (btn.textContent.trim() === '확인') {{
                        btn.click();
                        return true;
                    }}
                }}
                return false;
            }}""", BIRTH)
            await asyncio.sleep(3)
            print("   ✓ 추가인증 완료")
        
        await popup.screenshot(path='/tmp/tl_popup_auth.png')
        
        # 팝업 자동 닫힘 대기 + 메인 페이지 로그인 확인
        print("[7] 로그인 완료 대기...")
        
        # 팝업 최종 상태 확인
        try:
            popup_url = await popup.evaluate("location.href")
            popup_title = await popup.evaluate("document.title")
            popup_html_snippet = (await popup.content())[:500]
            print(f"   팝업 최종 URL: {popup_url[:120]}")
            print(f"   팝업 최종 Title: {popup_title}")
            if 'callback' in popup_url or 'error' in popup_url:
                print(f"   HTML: {popup_html_snippet[:200]}")
        except:
            print("   팝업 이미 닫힘")
        
        # 메인 페이지 대기
        for i in range(30):
            await asyncio.sleep(1)
            try:
                header = await page.evaluate("""() => 
                    Array.from(document.querySelectorAll('.header_util_link'))
                        .map(a => a.textContent.trim())
                """)
                if any('@' in h or '님' in h for h in header):
                    print(f"   🎉 로그인 성공! {header}")
                    break
            except:
                pass
        else:
            print("   ⚠️ 로그인 상태 확인 불가 (30초)")
        
        await page.screenshot(path='/tmp/tl_main_logged_in.png')
        print("   → /tmp/tl_main_logged_in.png")
    
    else:
        print(f"   ⚠️ PAYCO 폼 없음, 팝업 URL: {popup.url}")
    
    await asyncio.sleep(3)
    await browser.close()
    await p.stop()
    print("\n✅ 테스트 완료")

asyncio.run(test())
