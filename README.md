# 🎫 ticketlink-bot

**티켓링크 KBO 야구 예매 자동화 도구** — Chrome/CDP 불필요, 시스템 매크로 기반

통합매크로 스타일의 좌표 설정 + 다중 구역 좌석 색상 검색 + xAI Vision 캡차 자동 해결.

**Chrome이 필요 없습니다.** pyautogui가 모든 클릭을 처리하고, 전체화면 스크린샷으로 좌석/캡차를 인식합니다.

---

## 📋 요구사항

| 항목 | 필수 | 비고 |
|------|:----:|------|
| Tesseract OCR | ⬜ 선택 | 캡차 해결 시 필요 (로컬 OCR, ~0.3초) |
| xAI API 키 | ⬜ 선택 | 캡차 Vision 해결 시 필요 (Tesseract 실패 시 폴백) |
| 인터넷 연결 | ✅ | |
| Chrome | ❌ **불필요** | CDP/Playwright 완전 제거됨 |

## ⚡ 빠른 시작

### GUI 실행 (기본)
```bash
python -m ticketlink_bot
```
tkinter 기반 GUI가 실행됩니다. 모든 설정을 GUI에서 관리할 수 있습니다.

### CLI 독립형 모드
```bash
python -m ticketlink_bot --standalone
```
설정 파일 기준으로 콘솔에서 바로 예매를 실행합니다.

## 🎯 사용법

### GUI 모드 (기본)
1. **설정 탭** — 각 버튼의 좌표를 '따기' 버튼으로 설정
2. **좌석 탭** — 빈 좌석의 검색 영역과 색상 설정 (다중 구역 지원)
3. **시작 버튼** 또는 **F6** 키로 매크로 실행
4. **ESC** 키로 종료

### 단축키
- **F6**: 실행/중지 토글
- **ESC**: 프로그램 종료

### 좌표 따기
- **'따기' 버튼** → 화면에서 우클릭하면 좌표가 자동 저장됩니다
- **'글로벌' 버튼** → 시스템 전체 화면 어디서나 우클릭 가능

## ⚙️ 설정 파일

`~/.config/ticketlink-bot/config.yaml`에 저장됩니다:

```yaml
macro:
  click1: [800, 500]          # 예매하기 좌표
  click2: [900, 600]          # 확인 좌표
  click3: [100, 200]          # 선택완료 좌표
  click4: [300, 400]          # 결제하기 좌표
  date_click: [400, 300]      # 날짜 선택 (선택)
  round_click: [500, 300]     # 회차 선택 (선택)
  section_click: [200, 400]   # 구역선택 (선택)
  captcha_submit: [500, 600]  # 보안문자 확인 버튼 (선택)
  seat_zones:                 # 좌석 검색 영역 (다중 구역)
    - area: [100, 200, 500, 800]
      color: "C8C8C8"
      tolerance: 20
    - area: [600, 200, 900, 800]
      color: "A0B0C0"
      tolerance: 20
  consecutive_seats: 2        # N연석
  color_tolerance: 20         # 색상 오차범위
  delays:
    click_wait: 3             # 클릭 후 대기시간 (초)
    seat_click: 500           # 좌석 간 클릭 간격 (ms)
    refresh: 2000             # 새로고침 후 대기시간 (ms)
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
push 또는 tag 시 Windows/macOS/Linux 자동 빌드됩니다.

## 🏗️ 프로젝트 구조
```
ticketlink-bot/
├── src/ticketlink_bot/       # 소스 코드
│   ├── __main__.py           # CLI 진입점
│   ├── gui.py                # tkinter GUI
│   ├── standalone.py         # 독립형 매크로 파이프라인
│   ├── system_bot.py         # 시스템 매크로 (pyautogui 래퍼)
│   ├── captcha.py            # 캡차 해결 (Tesseract + xAI Vision)
│   ├── config.py             # 설정 파일 관리
│   ├── oauth.py              # xAI OAuth 인증
│   ├── picker.py             # 글로벌 좌표 따기 (pynput)
│   └── seats.py              # 좌석 색상 검색
├── build/
│   ├── build_exe.py          # PyInstaller 빌드 스크립트
│   └── installer.iss         # Inno Setup 설치 스크립트
├── entry_point.py            # PyInstaller 진입점
├── .github/workflows/build.yml  # CI/CD
└── pyproject.toml
```

## 📝 라이선스
MIT
