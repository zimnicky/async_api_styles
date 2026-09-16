@echo off
setlocal
cd /d "%~dp0"

python build_book.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Book build failed with exit code %errorlevel%.
    exit /b %errorlevel%
)
