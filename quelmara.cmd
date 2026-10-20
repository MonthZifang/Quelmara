@echo off
rem Quelmara 工具链入口（Windows）
rem   用法: quelmara <build|run|test|fmt|bench|version> [参数]
rem   tools\stage0\ = stage-0 引导层（Python），最终由 bootstrap\ 自举实现替换
setlocal
set "HERE=%~dp0"
python "%HERE%tools\stage0\qlm_cli.py" %*
exit /b %ERRORLEVEL%
