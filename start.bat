@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul

rem 用 pushd 规范化脚本目录，避免 ~dp0 末尾反斜杠与引号转义的坑。
pushd "%~dp0" 2>nul
if errorlevel 1 goto :no_dir
set "ROOT=%CD%"
popd
set "PORT=8080"
if defined PRAGENT_PORT set "PORT=%PRAGENT_PORT%"
set "URL=http://127.0.0.1:%PORT%/"

title PRAgent 一键启动
echo.
echo   PRAgent 一键启动
echo   ----------------------------------------
echo   运行目录: %ROOT%
echo.

rem 工作目录固定到脚本所在位置，避免通过快捷方式启动时把数据写到别处。
cd /d "%ROOT%" 2>nul
if errorlevel 1 goto :no_dir

rem --- 1. 定位 Python：随包运行时优先，其次系统安装 ---
rem 所有分支只负责设置变量，回显放到块外，否则 %VAR% 会在块解析时被提前展开成空值。
set "PY_EXE="
set "PY_LABEL="

if exist "%ROOT%\runtime\python\python.exe" (
  set "PY_EXE="%ROOT%\runtime\python\python.exe""
  set "PY_LABEL=随包 Python 运行时"
)

if not defined PY_EXE (
  for /f "delims=" %%i in ('where python 2^>nul') do (
    if not defined PY_EXE set "PY_EXE="%%i""
  )
)

if not defined PY_EXE (
  where py >nul 2>nul
  if not errorlevel 1 set "PY_EXE=py -3.11"
)

if defined PY_EXE if not defined PY_LABEL set "PY_LABEL=系统 Python"
if not defined PY_EXE goto :no_python
echo   [1/3] 使用 %PY_LABEL%

%PY_EXE% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto :old_python

rem --- 2. 检查是否已经在运行 ---
set "PORT_BUSY="
for /f "tokens=*" %%a in ('netstat -ano ^| findstr /c:"LISTENING" ^| findstr /c:":%PORT% "') do set "PORT_BUSY=1"
if defined PORT_BUSY (
  echo   [2/3] 端口 %PORT% 上已有服务在运行
  echo   [3/3] 直接打开控制台: %URL%
  echo.
  echo   如果这不是 PRAgent，请先关闭占用该端口的程序。
  start "" "%URL%"
  goto :end
)
echo   [2/3] 端口 %PORT% 空闲

rem --- 3. 先排一个延迟任务打开浏览器，再前台启动服务 ---
echo   [3/3] 正在启动服务，浏览器将自动打开...
echo.
start "PRAgent 浏览器" /min cmd /c "timeout /t 4 /nobreak >nul & rundll32 url.dll,FileProtocolHandler %URL%"

%PY_EXE% -m pragent
if errorlevel 1 goto :crashed

echo.
echo   服务已停止。
goto :end

:no_python
echo.
echo   [错误] 没有找到 Python 3.11 或更高版本。
echo.
echo   请选择一种方式后重新双击 start.bat：
echo     1. 安装 Python 3.11+，安装时勾选 "Add Python to PATH"
echo        https://www.python.org/downloads/
echo     2. 把便携版 Python 解压到 runtime\python 目录，确保
echo        runtime\python\python.exe 存在
echo.
goto :failed

:old_python
echo.
echo   [错误] 当前 Python 版本低于 3.11，PRAgent 无法运行。
echo.
echo   请安装 Python 3.11 或更高版本，或把便携版放到 runtime\python。
echo   当前版本：
%PY_EXE% -V
echo.
goto :failed

:no_dir
echo.
echo   [错误] 无法进入运行目录：%ROOT%
echo   可能该目录已被移动或没有访问权限。
echo.
goto :failed

:crashed
echo.
echo   [错误] 服务异常退出，请查看上方的错误信息。
echo   常见原因：依赖未安装。可在本目录执行：
echo     %PY_EXE% -m pip install -r requirements.txt
echo.
goto :failed

:failed
echo   按任意键关闭窗口。
pause >nul
endlocal
exit /b 1

:end
endlocal
exit /b 0
