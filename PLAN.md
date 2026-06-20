# v0.4.0 — 시스템 매크로 + GUI 전환 계획

## 문제
1. 좌표가 Chrome CDP 탭 내 viewport에 한정 → 새 창/팝업에서 좌표 불일치
2. 터미널 인터페이스 → 사용성 한계

## 해결

### 1. SystemBot 시스템 레벨 매크로
- CDP `Input.dispatchMouseEvent` → `pyautogui` 시스템 클릭
- 좌표: viewport → screen 절대좌표
- 스크린샷: CDP → `pyautogui.screenshot()` (전체 화면)
- 픽셀 색상: CDP → `pyautogui.pixel()`

### 2. 글로벌 좌표 따기 (PickerOverlay)
- `pynput`으로 글로벌 마우스 리스너 (Chrome 밖에서도 감지)
- macOS: `Quartz` 이벤트 탭으로 전역 우클릭 캡처
- Windows: `win32api` SetWindowsHookEx
- 화면 전체에 반투명 오버레이 (macOS: NSScreen, Windows: pygetwindow)

### 3. GUI 애플리케이션 (tkinter + ttk)
통합매크로 스타일 레이아웃:
- 좌측: 프리셋 목록
- 중앙: 좌표 편집기 + 테스트 버튼 + 좌석 영역
- 하단: 로그 출력창 + 상태바
- 글로벌 핫키: F6 시작/중지, ESC 종료

## 새 파일
| 파일 | 내용 |
|------|------|
| `system_bot.py` | pyautogui 기반 시스템 마우스/스크린샷 |
| `picker.py` | 글로벌 좌표 따기 (pynput/Quartz) |
| `gui.py` | tkinter GUI 메인 윈도우 |
| `gui_picker.py` | GUI 통합 좌표 따기 버튼 |

## 수정 파일
| 파일 | 변경 |
|------|------|
| `booking.py` | CDP 클릭 + 시스템 클릭 선택 가능 |
| `__main__.py` | `--gui` 모드 추가, GUI 실행 |
| `config.py` | screen_coords 옵션 추가 |
| `pyproject.toml` | pyautogui, pynput 의존성 추가 |
| `build/build_exe.py` | GUI 모드 + 데이터 파일 포함 |
