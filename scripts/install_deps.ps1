# 🎫 ticketlink-bot Windows 설치 도우미
# PowerShell 5.1+ 필요. 관리자 권한으로 실행 권장.
# 사용법: powershell -ExecutionPolicy Bypass -File scripts\install_deps.ps1

Write-Host "🎫 ticketlink-bot Windows 설치 도우미" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# 1. Python 확인
Write-Host "[1/4] Python 확인 중..." -ForegroundColor Cyan
try {
    $pyVersion = python --version 2>&1
    Write-Host "  ✅ $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "  ❌ Python이 설치되지 않았습니다." -ForegroundColor Red
    Write-Host "     https://www.python.org/downloads/ 에서 Python 3.11+ 설치 후 다시 실행하세요." -ForegroundColor Yellow
    exit 1
}

# 2. Tesseract OCR 설치 확인
Write-Host ""
Write-Host "[2/4] Tesseract OCR 확인 중..." -ForegroundColor Cyan
$tesseractPaths = @(
    "C:\Program Files\Tesseract-OCR\tesseract.exe",
    "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
)
$tesseractFound = $false
foreach ($tp in $tesseractPaths) {
    if (Test-Path $tp) {
        Write-Host "  ✅ Tesseract 발견: $tp" -ForegroundColor Green
        $tesseractFound = $true
        break
    }
}

if (-not $tesseractFound) {
    Write-Host "  ⚠️ Tesseract OCR이 설치되지 않았습니다." -ForegroundColor Yellow
    Write-Host "     (선택사항: 캡차 해결에 필요)" -ForegroundColor Yellow
    Write-Host "     다운로드: https://github.com/UB-Mannheim/tesseract/wiki" -ForegroundColor Yellow
    $installTesseract = Read-Host "     지금 설치하시겠습니까? (y/N)"
    if ($installTesseract -eq "y") {
        Write-Host "     https://github.com/UB-Mannheim/tesseract/wiki 에서 다운로드 후 설치하세요." -ForegroundColor Yellow
        Write-Host "     설치 옵션에서 '한국어 언어팩'도 같이 설치하세요." -ForegroundColor Yellow
    }
}

# 3. Python 패키지 설치
Write-Host ""
Write-Host "[3/4] Python 패키지 설치 중..." -ForegroundColor Cyan
$packages = @(
    "websockets>=12.0",
    "pyyaml>=6.0",
    "Pillow>=10.0",
    "numpy>=1.24",
    "pytesseract>=0.3",
    "requests>=2.31"
)

foreach ($pkg in $packages) {
    Write-Host "  ⏳ 설치 중: $pkg" -ForegroundColor Gray
    pip install $pkg --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✅ $pkg" -ForegroundColor Green
    } else {
        Write-Host "  ❌ $pkg 설치 실패" -ForegroundColor Red
    }
}

# 4. Chrome 설정 안내
Write-Host ""
Write-Host "[4/4] Chrome 설정" -ForegroundColor Cyan
Write-Host "  ticketlink-bot은 Chrome CDP 모드가 필요합니다." -ForegroundColor Yellow
Write-Host "" -ForegroundColor Yellow
Write-Host "  Chrome 바로가기 속성 → 대상(T)에 아래 추가:" -ForegroundColor Yellow
Write-Host '  --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.config\chrome-cdp"' -ForegroundColor White
Write-Host "" -ForegroundColor Yellow
Write-Host "  예시:" -ForegroundColor Yellow
Write-Host '  "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.config\chrome-cdp"' -ForegroundColor White

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "✅ 설치 완료!" -ForegroundColor Green
Write-Host "  ticketlink-bot --pick    (좌표 설정)" -ForegroundColor White
Write-Host "  ticketlink-bot --setup   (설정 마법사)" -ForegroundColor White
Write-Host "  ticketlink-bot --full    (자동 예매)" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Green
