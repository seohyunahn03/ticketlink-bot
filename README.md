# 🎫 ticketlink-bot

**티켓링크 KBO 야구 예매 자동화 도구** — Chrome CDP + xAI Vision 기반

통합매크로 스타일의 좌표 설정 + 다중 구역 좌석 색상 검색 + 자동 캡차 해결.

---

## 📋 요구사항

| 항목 | 필수 | 비고 |
|------|------|------|
| Google Chrome | ✅ | `--remote-debugging-port=9222` 모드 실행 |
| Python 3.10+ | ✅ | EXE 버전은 불필요 |
| Tesseract OCR | ⬜ 선택 | 캡차 해결 시 필요 (선택) |
| xAI API 키 | ⬜ 선택 | 캡차 Vision 해결 시 필요 |
| 인터넷 연결 | ✅ | |

## ⚡ 빠른 시작

### Windows — EXE 설치
1. [Releases](https://github.com/taehwan/ticketlink-bot/releases)에서 `ticketlink-bot-setup-*.exe` 다운로드
2. 설치 후 Chrome을 CDP 모드로 실행:
   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.config\chrome-cdp"
   ```
3. 티켓링크 접속 후 실행:
   ```
   ticketlink-bot --pick    # 좌표 설정
   ticketlink-bot --full    # 전체 자동 예매
   ```

### pip 설치
```bash
git clone https://github.com/taehwan/ticketlink-bot.git
cd ticketlink-bot
pip install -r requirements.txt
python -m ticketlink_bot --help
```

## 🎯 사용법

### 1. 좌표 따기 (`--pick`)
```
python -m ticketlink_bot --pick
```
단계별로 Chrome에 오버레이가 표시됩니다. 클릭만 하면 됩니다:
1. **예매하기** 버튼 클릭
2. **확인** 버튼 클릭 (예매안내 모달)
3. **선택완료** 버튼 클릭
4. **결제하기** 버튼 (선택)
5. **날짜/회차** 선택 (선택)
6. **🏟️ 좌석 검색 영역** — 구역(zone)별로 ↖좌상단, ↘우하단 클릭

> 💡 다중 구역(zone) 지원: 1루측/3루측/외야 등 구역별로 다른 색상 설정 가능

### 2. 설정 마법사 (`--setup`)
```
python -m ticketlink_bot --setup
```
OAuth 로그인 + 좌표 + 색상까지 한번에 설정.

### 3. 전체 자동 예매 (`--full`)
```
python -m ticketlink_bot --full
```
설정된 좌표/색상으로 전체 파이프라인 실행:
```
① 예매하기 클릭 → ② 확인 클릭 → ③ 캡차 자동 해결 → ④ 좌석 검색 → ⑤ 연석 클릭 → ⑥ 선택완료 → ⑦ 결제
```

## ⚙️ 설정 파일

`~/.config/ticketlink-bot/config.yaml`에 저장됩니다:

```yaml
macro:
  click1: [800, 500]          # 예매하기 좌표
  click2: [900, 600]          # 확인 좌표
  click3: [100, 200]          # 선택완료 좌표
  click4: [300, 400]          # 결제하기 좌표
  seat_zones:                 # 좌석 검색 영역 (다중 구역)
    - area: [100, 200, 500, 800]
      color: "C8C8C8"
      tolerance: 20
    - area: [600, 200, 900, 800]
      color: "A0B0C0"
      tolerance: 20
  consecutive_seats: 2        # N연석
  color_tolerance: 20         # 색상 오차범위
```

## 🔧 빌드 방법

### Windows EXE
```bash
pip install pyinstaller
python build/build_exe.py
# 또는 Inno Setup 설치기:
iscc build/installer.iss
```

### GitHub Actions (자동 빌드)
`.github/workflows/build.yml` — push, tag, 수동 트리거로 Windows/macOS/Linux 자동 빌드

## 🏗️ 프로젝트 구조
```
ticketlink-bot/
├── src/ticketlink_bot/       # 소스 코드
│   ├── __main__.py           # CLI 진입점
│   ├── bot.py                # Chrome CDP 봇
│   ├── booking.py            # 예매 파이프라인 + 좌표 따기
│   ├── captcha.py            # 캡차 해결 (하이브리드)
│   ├── config.py             # 설정 관리
│   ├── oauth.py              # xAI OAuth 인증
│   └── seats.py              # 좌석 색상 검색
├── build/
│   ├── build_exe.py          # PyInstaller 빌드 스크립트
│   └── installer.iss         # Inno Setup 설치 스크립트
├── scripts/
│   └── install_deps.ps1      # Windows 설치 도우미
├── .github/workflows/build.yml  # CI/CD
├── pyproject.toml
└── requirements.txt
```

## 📝 라이선스
MIT
