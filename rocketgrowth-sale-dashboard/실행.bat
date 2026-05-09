@echo off
cd /d "%~dp0"

:: Chrome 원격 디버깅 포트로 실행 (이미 실행 중이면 무시)
netstat -an | find "9222" >nul 2>&1
if errorlevel 1 (
    echo Chrome 실행 중...
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%TEMP%\wing_chrome_profile" "https://wing.coupang.com/tenants/rfm/settlements/status-new"
    timeout /t 2 /nobreak >nul
)

python app.py
pause
