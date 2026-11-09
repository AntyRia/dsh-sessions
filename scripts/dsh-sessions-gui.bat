@echo off
rem dsh-sessions GUI 启动器（无需安装，直接指向仓库 src）
setlocal
set "PYTHONPATH=%~dp0..\src"
start "" pythonw -m dsh_sessions.gui
endlocal
