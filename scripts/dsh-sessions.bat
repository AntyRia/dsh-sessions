@echo off
rem dsh-sessions CLI 启动器（无需安装，直接指向仓库 src）
setlocal
set "PYTHONPATH=%~dp0..\src"
python -m dsh_sessions.cli %*
endlocal
pause
