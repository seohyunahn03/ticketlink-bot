#!/usr/bin/env python3.14
"""
🎫 티켓링크 CDP 매크로 v3 — Chrome 다이렉트 연결
- Playwright 사용 안 함 → 탐지 제로
- "안심예매" 버튼 찾아서 자동 클릭 + 좌석선택
  
사용법:
  python3.14 macro_cdp.py              # 현재 페이지 스캔
  python3.14 macro_cdp.py --auto       # 안심예매 → 좌석 자동
"""
import asyncio, json, sys, argparse, time
import websockets

CDP = 'ws://localhost:9222/devtools/browser/3941751a-a76f'
DOMAIN = 'ticketlink.co.kr'

class Bot:
    def __init__(self):
        self.ws = None
        self.n = 0
        self.sid = None  # session id
    
    async def connect(self):
        self.ws = await websockets.connect(CDP, max_size=10_000_000)
    
    async def cmd(self, method, params=None, sid=None):
        self.n += 1
        msg = {'id': self.n, 'method': method, 'params': params or {}}
        if sid or self.sid:
            msg['sessionId'] = sid or self.sid
        await self.ws.send(json.dumps(msg))
        while True:
            r = json.loads(await asyncio.wait_for(self.ws.recv(), 15))
            if r.get('id') == self.n:
                if 'error' in r:
                    raise Exception(json.dumps(r['error']))
                return r.get('result')
    
    async def js(self, code, sid=None):
        r = await self.cmd('Runtime.evaluate', {
            'expression': code, 'returnByValue': True, 'awaitPromise': True
        }, sid=sid)
        return r.get('result', {}).get('value')
    
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

async def main():
    p = argparse.ArgumentParser()
    p.add_argument('--auto', action='store_true')
    p.add_argument('--url')
    args = p.parse_args()
    
    bot = Bot()
    await bot.connect()
    print('✅ Chrome CDP 연결')
    
    tab = await bot.find_tab()
    if not tab:
        print('❌ 티켓링크 탭 없음. Chrome에서 열어주세요!')
        await bot.close()
        return 1
    
    print(f'✅ 탭: {tab["title"][:40]}')
    await bot.attach(tab['targetId'])
    
    if args.url:
        await bot.cmd('Page.navigate', {'url': args.url})
        await asyncio.sleep(4)
    
    # 페이지 스캔
    info = await bot.js("document.title + '\\n' + (document.body?.innerText?.substring(0,800) || '')")
    print(f'\n📄 {info[:300]}')
    
    # 안심예매 찾기
    btns_json = await bot.js("""JSON.stringify(
        Array.from(document.querySelectorAll('a, button, [role="button"], span, div, label')).filter(el => {
            const t = (el.textContent||'').trim();
            return t.includes('안심예매') || t.includes('안심') || t.includes('예매하기') || t.includes('바로예매');
        }).map(el => ({
            text: (el.textContent||'').trim().substring(0,40),
            tag: el.tagName,
            visible: el.getBoundingClientRect().width > 0,
            href: el.href || ''
        }))
    )""")
    
    btns = json.loads(btns_json) if btns_json else []
    
    if btns:
        print(f'\n🎯 안심예매 버튼 {len(btns)}개')
        for i, b in enumerate(btns):
            vis = '👁️' if b.get('visible') else '🚫'
            print(f'  {vis} [{i+1}] {b["text"]}')
        
        if args.auto:
            # visible 버튼 찾아 클릭
            target = None
            for b in btns:
                if b.get('visible'):
                    target = b
                    break
            if not target:
                target = btns[0]
            
            print(f'\n🔄 "{target["text"]}" 클릭...')
            
            if target.get('href'):
                await bot.cmd('Page.navigate', {'url': target['href']})
            else:
                await bot.js(f"""(() => {{
                    for (const el of document.querySelectorAll('a, button, [role="button"], span, div, label')) {{
                        if ((el.textContent||'').trim().includes('{target["text"][:10]}')) {{
                            el.click(); return true;
                        }}
                    }}
                    return false;
                }})()""")
            
            await asyncio.sleep(5)
            url = await bot.js('document.location.href')
            print(f'  📍 {url}')
            
            # 좌석선택 페이지 확인
            seat_info = await bot.js("""JSON.stringify({
                hasSeat: (document.body?.innerText||'').includes('좌석'),
                nextBtns: Array.from(document.querySelectorAll('a, button')).filter(el => {
                    const t = (el.textContent||'').trim();
                    return t.includes('다음') || t.includes('확인') || t.includes('선택') || t.includes('결제');
                }).map(el => (el.textContent||'').trim().substring(0,20)),
                preview: (document.body?.innerText||'').substring(0, 400)
            })""")
            
            si = json.loads(seat_info) if seat_info else {}
            if si.get('hasSeat'):
                print('\n💺 좌석 선택 페이지 도착!')
            if si.get('nextBtns'):
                print(f'   버튼: {si["nextBtns"]}')
            print(f'\n{si.get("preview", "")[:300]}')
    else:
        print('\n❌ 안심예매 버튼 없음')
        print('  LG 트윈스 경기 선택 페이지에서 실행해주세요')
        print('  또는 --url 옵션으로 페이지 이동 가능')
    
    await bot.close()

if __name__ == '__main__':
    asyncio.run(main())
