#!/usr/bin/env python3.14
"""
티켓링크 (PAYCO) 자동 예매 매크로 v3
- POPUP 방식 로그인 (expect_popup)
- PAYCO 로그인 자동 입력
- SMS 문자인증은 사용자 확인 (반자동)
"""
import asyncio, json, os, sys
import yaml
from playwright.async_api import async_playwright, TimeoutError as PwTimeout

CONFIG_PATH = '/Users/taehwan/.hermes/ticketing/config/config.yaml'

def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}
def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(cfg, f, allow_unicode=True)

JS_SET_VALUE = """
(val) => {
    const inputs = document.querySelectorAll('input');
    for (const inp of inputs) {
        if (inp.type === '{type}') {
            const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            s.call(inp, val);
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            return true;
        }
    }
    return false;
}
"""

async def init_browser(headless=False):
    p = await async_playwright().start()
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
    return p, browser, context, await context.new_page()


async def login_ticketlink(page, email, password, birth=None):
    """티켓링크 PAYCO 로그인 (팝업 방식)"""
    
    # 1. 접속
    print("[1/7] 티켓링크 접속...")
    await page.goto('https://www.ticketlink.co.kr', wait_until='domcontentloaded', timeout=30000)
    await asyncio.sleep(3)  # SPA 초기 렌더링 대기
    for i in range(15):
        await asyncio.sleep(1)
        try:
            ok = await page.evaluate("document.querySelector('.header_util_list') !== null")
            if ok:
                print(f"  ✓ 로딩 완료 ({i+1}초)")
                break
        except:
            pass  # 네비게이션 무시
    
    # 2. 오버레이 제거
    print("[2/7] 오버레이 제거...")
    try:
        await page.evaluate("""() => {
            const p = document.querySelector('.full_page_pop');
            if (p) p.style.display = 'none';
            document.body.style.overflow = 'auto';
        }""")
    except:
        pass
    await asyncio.sleep(2)
    
    # 3. 로그인 → 팝업
    print("[3/7] 로그인 팝업 오픈...")
    async with page.expect_popup() as popup_info:
        await page.evaluate("""() => {
            const links = document.querySelectorAll('a');
            for (const l of links) {
                if (l.textContent.trim() === '로그인') { l.click(); return; }
            }
        }""")
    
    popup = await popup_info.value
    print(f"  ✓ 팝업 열림")
    await asyncio.sleep(3)
    
    # 4. PAYCO 로그인
    print("[4/7] PAYCO 로그인...")
    
    # 이메일 입력
    email_input = popup.locator('input[type="text"]')
    await email_input.first.click()
    await popup.keyboard.type(email, delay=30)
    print("  ✓ 이메일 입력")
    
    # 비밀번호 입력 (force=True로 오버레이 우회)
    pw_input = popup.locator('input[type="password"]')
    await pw_input.first.click(force=True, timeout=5000)
    await popup.keyboard.type(password, delay=20)
    print("  ✓ 비밀번호 입력")
    
    # 로그인 버튼
    await popup.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if (b.textContent.trim() === '로그인') { b.click(); return; }
        }
    }""")
    print("  ✓ 로그인 버튼 클릭")
    await asyncio.sleep(3)
    
    # 5. 추가인증 (생년월일)
    popup_html = await popup.content()
    if '새로운 기기' in popup_html or '생년월일' in popup_html:
        print("[5/7] 추가인증 (생년월일)...")
        if birth:
            # JS value setter로 입력
            await popup.evaluate(f"""((b) => {{
                const inputs = document.querySelectorAll('input');
                for (const inp of inputs) {{
                    if (inp.type === 'tel') {{
                        const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                        s.call(inp, b);
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        return;
                    }}
                }}
            }})(""" + f'"{birth}"' + ")")
            await asyncio.sleep(1)
            
            await popup.evaluate("""() => {
                const btns = document.querySelectorAll('button:not([disabled])');
                for (const b of btns) {
                    if (b.textContent.trim() === '확인') { b.click(); return; }
                }
            }""")
            await asyncio.sleep(2)
            print("  ✓ 생년월일 인증 완료")
    
    # 6. SMS 문자인증 대기 (반자동)
    print("[6/7] 문자인증 대기중...")
    popup_url = await popup.evaluate("location.href")
    
    if 'certify' in popup_url or '문자' in (await popup.evaluate("document.title")):
        print("  ⏳ SMS 문자인증 필요!")
        print("  📱 폰에서 문자 확인 후 인증번호를 입력해주세요")
        print("  ⏰ 최대 120초 대기...")
        
        # 팝업이 닫힐 때까지 대기 (SMS 인증 완료 → OAuth 콜백 → 팝업 종료)
        for i in range(120):
            await asyncio.sleep(1)
            # 팝업이 닫혔는지 확인
            try:
                url = await popup.evaluate("location.href")
                if 'callback' in url or 'ticketlink.co.kr/auth' in url:
                    print(f"  ✓ OAuth 콜백 진행중...")
                    await asyncio.sleep(3)
                    continue
                if 'success' in url.lower() or url == 'about:blank':
                    await asyncio.sleep(2)
                    break
            except:
                print("  ✓ 팝업 닫힘")
                await asyncio.sleep(2)
                break
            
            if i % 10 == 0 and i > 0:
                print(f"  ... {i}초 대기중")
        
        print("  ✓ 문자인증 대기 완료")
    else:
        print("  ✓ 추가인증 불필요")
        await asyncio.sleep(3)
    
    # 7. 로그인 결과 확인
    print("[7/7] 로그인 확인...")
    for i in range(15):
        await asyncio.sleep(1)
        try:
            header = await page.evaluate("""() => 
                Array.from(document.querySelectorAll('.header_util_link'))
                    .map(a => a.textContent.trim())
            """)
            if any('@' in h or '님' in h for h in header):
                print(f"  🎉 로그인 성공! {header[0]}")
                return True
        except:
            pass
    
    print("  ⚠️ 로그인 상태 미확인 (직접 확인 필요)")
    return False


async def search_and_book(page, keyword):
    """검색 + 예매 페이지 진입"""
    print(f"\n🔍 '{keyword}' 검색중...")
    
    # 검색어 입력
    await page.evaluate(f"""(kw) => {{
        const inputs = document.querySelectorAll('input');
        for (const inp of inputs) {{
            if (inp.placeholder && inp.placeholder.includes('검색')) {{
                const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                s.call(inp, kw);
                inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                // Enter
                const e = new KeyboardEvent('keydown', {{
                    key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
                }});
                inp.dispatchEvent(e);
                return true;
            }}
        }}
        return false;
    }}""", keyword)
    await asyncio.sleep(5)
    print(f"  URL: {page.url[:80]}")
    
    # 첫 결과 클릭
    clicked = await page.evaluate("""() => {
        const items = document.querySelectorAll('[class*="product"] a, li a');
        for (const item of items) {
            if (item.href && item.href.includes('product') && !item.href.includes('home')) {
                item.click(); return item.href;
            }
        }
        return null;
    }""")
    if clicked:
        print(f"  ✓ 상품 선택: {clicked[:60]}")
        await asyncio.sleep(5)
        
        # 예매하기
        booking = await page.evaluate("""() => {
            const btns = document.querySelectorAll('a, button, span');
            for (const b of btns) {
                const t = b.textContent.trim();
                if (t.includes('예매하기') || t === '예매') { b.click(); return t; }
            }
            return null;
        }""")
        if booking:
            print(f"  ✓ '{booking}' 클릭")
            await asyncio.sleep(5)
            return f"✅ 예매페이지 진입! URL: {page.url[:60]}"
    
    return f"✅ 로그인+검색 완료 (키워드: {keyword})"


async def reserve_ticket(keyword, count=2, payment=False):
    cfg = load_config()
    email = cfg.get('payco_id') or os.environ.get('PAYCO_ID')
    password = cfg.get('payco_pw') or os.environ.get('PAYCO_PW')
    birth = cfg.get('payco_birth') or os.environ.get('PAYCO_BIRTH')
    if not email or not password:
        return "❌ 설정 필요: ticket.py config"
    
    p, browser, context, page = await init_browser(headless=False)
    try:
        ok = await login_ticketlink(page, email, password, birth)
        if not ok:
            return "❌ 로그인 실패"
        return await search_and_book(page, keyword)
    except Exception as e:
        return f"❌ 오류: {e}"
    finally:
        await browser.close()
        await p.stop()


async def search_only(keyword):
    cfg = load_config()
    p, browser, context, page = await init_browser(headless=False)
    try:
        ok = await login_ticketlink(page, cfg['payco_id'], cfg['payco_pw'], cfg.get('payco_birth'))
        if not ok:
            return "❌ 로그인 실패"
        return await search_and_book(page, keyword)
    except Exception as e:
        return f"❌ 오류: {e}"
    finally:
        await browser.close()
        await p.stop()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'help'
    if cmd == 'config':
        e = input("PAYCO 아이디: ").strip()
        p = input("PAYCO 비밀번호: ").strip()
        b = input("생년월일 8자리 (선택): ").strip()
        save_config({'payco_id': e, 'payco_pw': p, 'payco_birth': b or None})
        print("✅ 저장 완료")
    elif cmd == 'search':
        kw = sys.argv[2] if len(sys.argv) > 2 else input("검색어: ")
        print(asyncio.run(search_only(kw)))
    elif cmd == 'book':
        kw = sys.argv[2] if len(sys.argv) > 2 else input("검색어: ")
        print(asyncio.run(reserve_ticket(kw)))
    else:
        print("사용법: config | search <검색어> | book <검색어>")
