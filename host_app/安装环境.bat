@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   第一次使用：正在安装运行环境（约几分钟）
echo ============================================
echo.

set "PYEXE="
for %%P in ("py -3" "python" "D:\Python313\python.exe") do (
  if not defined PYEXE (
    %%~P -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && set "PYEXE=%%~P"
  )
)

if not defined PYEXE (
  echo [出错] 没有找到 Python 3.10 或更高版本。
  echo 请先到 python.org 下载安装 Python（安装时勾选 Add to PATH），
  echo 装好后再双击本文件。
  echo.
  pause
  exit /b 1
)

echo 使用 Python: %PYEXE%
echo 正在创建独立运行环境……
%PYEXE% -m venv .venv
if errorlevel 1 (
  echo [出错] 创建运行环境失败。
  pause
  exit /b 1
)

set "VPIP=.venv\Scripts\python.exe -m pip"
echo 正在下载安装软件库（先用国内镜像，失败会自动换官方源）……
%VPIP% install --upgrade pip -q
%VPIP% install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo 镜像源安装失败，改用官方源重试……
  %VPIP% install -r requirements.txt
  if errorlevel 1 (
    echo [出错] 软件库安装失败，请检查网络后重新双击本文件。
    pause
    exit /b 1
  )
)

echo.
echo ============================================
echo   安装完成！以后双击「启动上位机.bat」即可使用
echo ============================================
pause
