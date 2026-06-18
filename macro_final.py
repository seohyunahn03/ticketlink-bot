#!/usr/bin/env python3.14
"""
🎫 티켓링크 예매 매크로 v4 — 안심예매(캡차) 자동 인식
- Chrome CDP 직접 연결 (탐지 제로)
- xAI Grok Vision으로 캡차 자동 인식
- "예매" → "안심예매 캡차 입력" → "입력완료" → 좌석선택

사용법:
  python3.14 macro_final.py                # 현재 페이지 스캔
  python3.14 macro_final.py --auto         # 전체 자동 예매
"""
import asyncio, json, sys, argparse, base64, io, os, ssl, urllib.request, urllib.parse
import websockets

DOMAIN = 'ticketlink.co.kr'
AUTH_PATH = '/Users/taehwan/.hermes/profiles/secretary/auth.json'

def get_cdp_url():
    """로컬 Chrome CDP WebSocket URL 자동 탐지"""
    try:
        resp = urllib.request.urlopen('http://localhost:9222/json/version', timeout=3)
        data = json.loads(resp.read())
        return data['webSocketDebuggerUrl']
    except:
        try:
            resp = urllib.request.urlopen('http://localhost:9223/json/version', timeout=3)
            data = json.loads(resp.read())
            return data['webSocketDebuggerUrl']
        except:
            return None

# ===== xAI Vision (캡차 인식) =====
def xai_vision(image_bytes):
    """xAI Grok Vision으로 이미지 인식"""
    with open(AUTH_PATH) as f:
        auth = json.load(f)
    token = auth['credential_pool']['xai-oauth'][0]['access_token']
    
    # 이미지 리사이즈 (500px 제한)
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        if max(img.size) > 500:
            r = 500 / max(img.size)
            img = img.resize((int(img.width*r), int(img.height*r)))
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        image_bytes = buf.getvalue()
    except ImportError:
        pass  # PIL 없으면 원본 사용
    
    img_b64 = base64.b64encode(image_bytes).decode()
    
    data = json.dumps({
        'model': 'grok-4.20-0309-non-reasoning',
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': '이미지에 보이는 캡차 문자열이 무엇인가요? 문자만 정확히 알려주세요. 예: "ABC123"'},
            {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{img_b64}'}},
        ]}],
        'max_tokens': 50
    }).encode()
    
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        'https://api.x.ai/v1/chat/completions', data=data,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    )
    resp = urllib.request.urlopen(req, context=ctx, timeout=30)
    result = json.loads(resp.read())
    return result['choices'][0]['message']['content'].strip()

# ===== CDP 봇 =====
class Bot:
    def __init__(self):
        self.ws = None
        self.n = 0
        self.sid = None
    
    async def connect(self):
        cdp_url = get_cdp_url()
        if not cdp_url:
            raise Exception('Chrome CDP 연결 실패. Chrome이 --remote-debugging-port=9222로 실행중인지 확인')
        self.ws = await websockets.connect(cdp_url, max_size=10_000_000)
    
    async def cmd(self, method, params=None, sid=None):
        self.n += 1
        msg = {'id': self.n, 'method': method, 'params': params or {}}
        if sid or self.sid: msg['sessionId'] = sid or self.sid
        await self.ws.send(json.dumps(msg))
        while True:
            r = json.loads(await asyncio.wait_for(self.ws.recv(), 15))
            if r.get('id') == self.n:
                if 'error' in r:
                    # 세션 만료 시 재연결
                    if r['error'].get('code') == -32001:
                        raise ConnectionError('session_expired')
                    raise Exception(json.dumps(r['error']))
                return r.get('result')
    
    async def js(self, code):
        """sid 없이 self.sid 사용, 세션 만료 시 자동 재연결"""
        try:
            r = await self.cmd('Runtime.evaluate', {
                'expression': code, 'returnByValue': True, 'awaitPromise': True
            })
            return r.get('result', {}).get('value')
        except ConnectionError:
            # 세션 재연결
            targets = (await self.cmd('Target.getTargets')).get('targetInfos', [])
            for t in targets:
                if DOMAIN in t.get('url', '') or '야구' in t.get('title', ''):
                    r = await self.cmd('Target.attachToTarget', {'targetId': t['targetId'], 'flatten': True})
                    self.sid = r['sessionId']
                    r = await self.cmd('Runtime.evaluate', {
                        'expression': code, 'returnByValue': True, 'awaitPromise': True
                    })
                    return r.get('result', {}).get('value')
            raise
    
    async def screenshot(self):
        """현재 페이지 스크린샷 (base64)"""
        r = await self.cmd('Page.captureScreenshot', {'format': 'png', 'fromSurface': True})
        return base64.b64decode(r['data'])
    
    async def find_tab(self):
        targets = (await self.cmd('Target.getTargets')).get('targetInfos', [])
        for t in targets:
            url = t.get('url', '')
            if DOMAIN in url or '야구' in t.get('title', ''):
                return t
        return None
    
    async def attach(self, tid):
        r = await self.cmd('Target.attachToTarget', {'targetId': tid, 'flatten': True})
        self.sid = r['sessionId']
    
    async def close(self):
        if self.ws: await self.ws.close()

async def solve_captcha(bot):
    """안심예매(캡차) 인식 및 입력"""
    print('\n🔍 안심예매(캡차) 감지중...')
    
    # 페이지 내용 확인
    text = await bot.js("document.body?.innerText?.substring(0, 1000) || ''") or ''
    
    if '안심' not in text and '클린' not in text and '문자' not in text and '입력' not in text:
        print('  → 안심예매 화면 아님')
        return False
    
    print('  ✅ 안심예매 캡차 발견!')
    
    # 캡차 이미지 영역 스크린샷 (가능하면 특정 영역만)
    # 전체 페이지 스크린샷
    png_data = await bot.screenshot()
    
    # xAI Vision으로 문자열 인식
    print('  🤖 xAI Vision으로 문자열 인식중...')
    try:
        captcha_text = xai_vision(png_data)
        print(f'  ✅ 인식 결과: "{captcha_text}"')
    except Exception as e:
        print(f'  ❌ 인식 실패: {e}')
        return False
    
    # 입력 필드에 문자열 입력
    inputted = await bot.js(f"""
    (() => {{
        const inputs = document.querySelectorAll('input');
        for (const inp of inputs) {{
            if (inp.type === 'text' || inp.type === 'tel' || !inp.type) {{
                const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                s.call(inp, '{captcha_text}');
                inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }}
        }}
        return false;
    }})()
    """)
    
    if inputted:
        print('  ✅ 캡차 문자열 입력 완료!')
    else:
        print('  ⚠️ 입력 필드를 못 찾음, 직접 입력해주세요')
        return False
    
    # "입력 완료" 버튼 클릭
    clicked = await bot.js("""() => {
        const all = document.querySelectorAll('a, button, [role="button"]');
        for (const el of all) {
            const t = (el.textContent||'').trim();
            if (t.includes('입력 완료') || t.includes('확인') || t.includes('완료')) {
                el.click(); return true;
            }
        }
        return false;
    }""")
    
    if clicked:
        print('  ✅ "입력 완료" 버튼 클릭!')
    else:
        print('  ⚠️ 버튼 클릭 실패')
    
    await asyncio.sleep(3)
    return True

async def main():
    p = argparse.ArgumentParser()
    p.add_argument('--auto', action='store_true', help='전체 자동 예매')
    p.add_argument('--url', help='페이지 URL')
    args = p.parse_args()
    
    bot = Bot()
    await bot.connect()
    print('✅ Chrome CDP 연결')
    
    tab = await bot.find_tab()
    if not tab:
        print('❌ 티켓링크 탭 없음. Chrome에서 ticketlink.co.kr 열어주세요!')
        await bot.close()
        return 1
    
    print(f'✅ 탭: {tab["title"][:40]}')
    await bot.attach(tab['targetId'])
    
    if args.url:
        await bot.cmd('Page.navigate', {'url': args.url})
        await asyncio.sleep(4)
    
    # 페이지 정보 출력
    info = await bot.js("document.title + '\\n' + (document.body?.innerText?.substring(0,600) || '')") or ''
    print(f'\n📄 {info[:300]}')
    
    # 안심예매/예매 버튼 찾기
    btns = json.loads(await bot.js("""JSON.stringify(
        Array.from(document.querySelectorAll('a, button, [role="button"], span, div, label')).filter(el => {
            const t = (el.textContent||'').trim();
            return t.includes('예매') || t.includes('안심');
        }).map(el => ({
            text: (el.textContent||'').trim().substring(0,40),
            tag: el.tagName,
            visible: el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0,
            href: el.href || ''
        }))
    )""") or '[]')
    
    if btns:
        print(f'\n🎯 버튼 {len(btns)}개')
        for i, b in enumerate(btns):
            vis = '👁️' if b.get('visible') else '🚫'
            print(f'  {vis} [{i+1}] {b["text"]}')
        
        if args.auto:
            # "예매하기" 정확히 매칭되는 visible 버튼 찾기 (우선순위)
            target = None
            for b in btns:
                t = b['text'].strip()
                if b.get('visible') and ('예매하기' in t and len(t) < 20):
                    target = b; break
            
            # 없으면 "예매" 포함 visible 버튼 (20자 이하)
            if not target:
                for b in btns:
                    t = b['text'].strip()
                    if b.get('visible') and '예매' in t and len(t) < 15:
                        target = b; break
            
            # 없으면 "클린예매 visible"
            if not target:
                for b in btns:
                    t = b['text'].strip()
                    if b.get('visible') and '클린' in t and len(t) < 15:
                        target = b; break
            
            if not target: target = btns[0] if btns else None
            
            if target:
                print(f'\n🔄 "{target["text"]}" 클릭...')
                if target.get('href'):
                    await bot.cmd('Page.navigate', {'url': target['href']})
                else:
                    # dispatchEvent로 정확한 클릭 이벤트 전달
                    await bot.js(f"""(() => {{
                        const all = document.querySelectorAll('a, button, [role="button"], span, div, label');
                        for (const el of all) {{
                            if ((el.textContent||'').trim().includes('{target["text"][:10]}')) {{
                                el.dispatchEvent(new MouseEvent('click', {{bubbles: true, cancelable: true, view: window}}));
                                return true;
                            }}
                        }}
                        return false;
                    }})()""")
                
                await asyncio.sleep(5)
                new_url = await bot.js('document.location.href')
                print(f'  📍 {new_url}')
                
                # 캡차 확인 (URL 변경 감지)
                if new_url and 'sports/137/59' not in new_url.split('?')[0]:
                    # 캡차 화면으로 이동됨
                    solved = await solve_captcha(bot)
                else:
                    # 페이지가 안 바뀜 → 다른 버튼 시도
                    print('  ⚠️ 페이지 전환 없음, 다른 경기 시도...')
                    # 실제 경기 항목의 "예매하기" 찾아서 다시 클릭
                    clicked_another = await bot.js(f"""() => {{
                        const items = document.querySelectorAll('[class*="product"], [class*="card"], li, [class*="item"]');
                        for (const item of items) {{
                            if (item.textContent.includes('LG') && item.textContent.includes('예매하기')) {{
                                const btn = item.querySelector('a, button');
                                if (btn && btn.textContent.includes('예매')) {{
                                    btn.dispatchEvent(new MouseEvent('click', {{bubbles: true, cancelable: true, view: window}}));
                                    return btn.textContent.trim();
                                }}
                            }}
                        }}
                        return null;
                    }}""")
                    print(f'  → "{clicked_another}" 클릭')
                    await asyncio.sleep(5)
                    print(f'  📍 {await bot.js("document.location.href")}')
                    solved = await solve_captcha(bot)
                
                if solved:
                    await asyncio.sleep(3)
                    # 좌석 선택 페이지 확인
                    url = await bot.js('document.location.href')
                    page_text = await bot.js("document.body?.innerText?.substring(0,500) || ''")
                    print(f'\n💺 현재 페이지: {url}')
                    print(f'  {page_text[:200]}')
                    print(f'\n✅ 예매 자동화 완료! 브라우저를 확인해주세요.')
                else:
                    print(f'\n⚠️ 안심예매 해결 실패. 직접 브라우저를 확인해주세요.')
    else:
        print('\n❌ 예매/안심 버튼 없음')
    
    await bot.close()

if __name__ == '__main__':
    asyncio.run(main())
