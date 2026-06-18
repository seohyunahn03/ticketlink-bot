#!/usr/bin/env python3.14
"""
티켓링크 + PAYCO 로그인 v4 (심플 버전)
JS evaluate로 value 직접 설정 (keyboard/fill 우회)
"""
import asyncio
import json
import yaml
from playwright.async_api import async_playwright

async def login_and_search(keyword, headless=True):
    """로그인 + 검색"""
    
    with open('/Users/taehwan/.hermes/ticketing/config/config.yaml') as f:
        cfg = yaml.safe_load(f)
    
    email = cfg['payco_id']
    password = cfg['payco_pw']
    birth = cfg.get('payco_birth', '')
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
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
        
        # 1. 접속 (SPA 완전 로딩 대기)
        print("1. 티켓링크 접속...")
        await page.goto('https://www.ticketlink.co.kr', wait_until='domcontentloaded', timeout=30000)
        # SPA가 완전히 렌더링될 때까지 충분히 대기
        for i in range(10):
            await page.wait_for_timeout(1000)
            has_header = await page.evaluate("document.querySelector('.header_util_list') !== null")
            if has_header:
                print(f"   SPA 로딩 완료 ({i+1}초)")
                break
        
        # 2. 로그인 시도 (네비게이션 안정화 후)
        print("2. 로그인 시도...")
        
        # 페이지 안정화 대기
        await page.wait_for_timeout(3000)
        
        # 재시도 루프
        clicked = False
        for attempt in range(5):
            try:
                # evaluate 전에 page가 안정적인지 확인
                await page.evaluate("1+1")  # 간단한 sanity check
                
                clicked = await page.evaluate("""
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
                if clicked:
                    print(f"   로그인 버튼 클릭 성공 (시도 {attempt+1})")
                    break
            except Exception as e:
                print(f"   ⚠️ 시도 {attempt+1} 실패: {str(e)[:60]}")
                await page.wait_for_timeout(2000)
        
        if not clicked:
            print("   ❌ 로그인 버튼을 찾을 수 없음")
            await page.screenshot(path='/tmp/tl_no_login_btn.png')
            await browser.close()
            return "로그인 버튼 없음"
        
        await page.wait_for_timeout(3000)
        
        # PAYCO 모달 확인
        modal_info = await page.evaluate("""
            () => {
                const inputs = Array.from(document.querySelectorAll('input'));
                const types = inputs.map(i => i.type + ':' + (i.placeholder || ''));
                const btns = Array.from(document.querySelectorAll('button'))
                    .map(b => b.textContent.trim()).filter(t => t);
                return JSON.stringify({inputs: types, buttons: btns});
            }
        """)
        info = json.loads(modal_info)
        print(f"   입력창: {info['inputs']}")
        print(f"   버튼: {info['buttons']}")
        
        # 4. PAYCO 로그인
        payco_found = any('이메일' in i or 'email' in i or '휴대폰' in i for i in info['inputs'])
        
        if payco_found:
            print("4. PAYCO 로그인 폼 입력...")
            
            # JS로 value 직접 설정
            set_value_js = """
(email, pw) => {
    const inputs = document.querySelectorAll('input');
    let emailSet = false, pwSet = false;
    for (const inp of inputs) {
        if ((inp.type === 'text' || inp.type === 'email') && !emailSet) {
            const nativeSetter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'value'
            ).set;
            nativeSetter.call(inp, email);
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            emailSet = true;
        } else if (inp.type === 'password' && !pwSet) {
            const nativeSetter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'value'
            ).set;
            nativeSetter.call(inp, pw);
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            pwSet = true;
        }
    }
    return JSON.stringify({emailSet, pwSet});
}
"""
            result = await page.evaluate(set_value_js, email, password)
            print(f"   입력 결과: {result}")
            await page.wait_for_timeout(500)
            
            # 로그인 버튼 클릭
            print("5. 로그인 버튼 클릭...")
            await page.evaluate("""
                () => {
                    const btns = document.querySelectorAll('button');
                    for (const btn of btns) {
                        if (btn.textContent.trim() === '로그인') {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            await page.wait_for_timeout(3000)
            
            # 5. 추가인증
            html = await page.content()
            if '새로운 기기' in html or '생년월일' in html:
                print("6. 추가인증 처리...")
                
                set_birth_js = f"""
(birth) => {{
    const inputs = document.querySelectorAll('input');
    let set = false;
    for (const inp of inputs) {{
        if (inp.type === 'tel' || inp.type === 'text') {{
            const nativeSetter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'value'
            ).set;
            nativeSetter.call(inp, birth);
            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
            set = true;
            break;
        }}
    }}
    return set;
}}
"""
                await page.evaluate(set_birth_js, birth)
                await page.wait_for_timeout(500)
                
                # 확인 버튼
                clicked = await page.evaluate("""
                    () => {
                        const btns = document.querySelectorAll('button');
                        for (const btn of btns) {
                            if (btn.textContent.trim() === '확인' && !btn.disabled) {
                                btn.click();
                                return true;
                            }
                        }
                        // disabled 체크 없이 시도
                        for (const btn of btns) {
                            if (btn.textContent.trim() === '확인') {
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                print(f"   확인 버튼 클릭: {clicked}")
                await page.wait_for_timeout(3000)
            
            # 6. 로그인 결과 대기
            print("7. 로그인 결과 대기...")
            logged_in = False
            for i in range(15):
                await page.wait_for_timeout(1000)
                header = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('.header_util_link'))
                        .map(a => a.textContent.trim())
                """)
                if any('@' in link or '님' in link for link in header):
                    print(f"   ✅ 로그인 성공! {header}")
                    logged_in = True
                    break
            
            if not logged_in:
                print("   ⚠️ 로그인 실패 또는 확인 불가")
                await page.screenshot(path='/tmp/tl_fail.png')
                await browser.close()
                return "로그인 실패"
        else:
            print("   ⚠️ PAYCO 로그인 폼 없음")
            await page.screenshot(path='/tmp/tl_no_form.png')
            await browser.close()
            return "PAYCO 폼 없음"
        
        # 7. 검색
        print(f"8. '{keyword}' 검색...")
        
        search_js = """
(keyword) => {
    const inputs = document.querySelectorAll('input');
    for (const inp of inputs) {
        if (inp.placeholder && inp.placeholder.includes('검색')) {
            const nativeSetter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'value'
            ).set;
            nativeSetter.call(inp, keyword);
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            
            // Enter 키 이벤트
            const enterEvent = new KeyboardEvent('keydown', {
                key: 'Enter', code: 'Enter', keyCode: 13, which: 13,
                bubbles: true, cancelable: true
            });
            inp.dispatchEvent(enterEvent);
            return true;
        }
    }
    return false;
}
"""
        searched = await page.evaluate(search_js, keyword)
        print(f"   검색 실행: {searched}")
        
        await page.wait_for_timeout(5000)
        print(f"   URL: {page.url}")
        
        await page.screenshot(path='/tmp/tl_search_final.png')
        print("   → /tmp/tl_search_final.png")
        
        await browser.close()
        return f"✅ 성공! 로그인 + '{keyword}' 검색 완료"


if __name__ == "__main__":
    import sys
    keyword = sys.argv[1] if len(sys.argv) > 1 else "워터밤"
    result = asyncio.run(login_and_search(keyword, headless=True))
    print(result)
