@echo off
REM ============================================================
REM 日次プリフェッチタスクをWindows Task Schedulerに登録
REM 管理者権限で実行してください
REM ============================================================

echo 日次プリフェッチタスクを登録します...

for /f "tokens=*" %%i in ('where python') do set PYTHON_PATH=%%i
set SCRIPT_PATH=E:\dev\Cusor\dlogic-agent\scripts\daily_prefetch.py

echo Python: %PYTHON_PATH%
echo Script: %SCRIPT_PATH%

REM 既存タスクがあれば削除
schtasks /delete /tn "DlogicDailyPrefetch" /f >nul 2>&1

REM 毎日18:00に実行
schtasks /create ^
    /tn "DlogicDailyPrefetch" ^
    /tr "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\"" ^
    /sc daily ^
    /st 18:00 ^
    /rl HIGHEST ^
    /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================================
    echo 登録成功！
    echo タスク名: DlogicDailyPrefetch
    echo スケジュール: 毎日 18:00
    echo ============================================================
    echo.
    echo 確認: schtasks /query /tn "DlogicDailyPrefetch" /v
    echo 手動実行: schtasks /run /tn "DlogicDailyPrefetch"
    echo 削除: schtasks /delete /tn "DlogicDailyPrefetch" /f
) else (
    echo.
    echo ERROR: タスク登録に失敗しました
    echo 管理者権限で再実行してください
)

pause
