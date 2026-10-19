@echo off
rem Rosoto 工具链入口（Windows）
rem   用法: rosoto <build|run|test|fmt|bench|version> [参数]
setlocal
set "HERE=%~dp0"
python "%HERE%tools\rosoto_cli.py" %*
exit /b %ERRORLEVEL%
