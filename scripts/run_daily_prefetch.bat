@echo off
REM 手動でプリフェッチを実行
echo 日次プリフェッチを手動実行します...
cd /d E:\dev\Cusor\dlogic-agent\scripts
python daily_prefetch.py
echo.
echo 完了！ログは logs\ フォルダを確認してください。
pause
