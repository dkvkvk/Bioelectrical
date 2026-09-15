@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 第一次使用请先双击「安装环境.bat」安装运行环境。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" app.py
if errorlevel 1 (
  echo.
  echo 程序异常退出了。请把上面显示的错误信息截图反馈。
  pause
)
