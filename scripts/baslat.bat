@echo off
chcp 65001 >nul
title LocalMinutes — Bot-Free Offline Meeting & Lecture Studio
cd /d "%~dp0.."

if exist "%~dp0..\dist\LocalMinutes\LocalMinutes.exe" (
    start "" "%~dp0..\dist\LocalMinutes\LocalMinutes.exe"
    exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Creating Python virtual environment (.venv)...
    py -3.11 -m venv .venv 2>nul || python -m venv .venv
)

if not exist ".venv\.deps_installed" (
    echo [2/2] Installing dependencies (PyQt6, faster-whisper, pyaudiowpatch, scipy)...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
    ".venv\Scripts\python.exe" -m pip install --prefer-binary -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to install Python dependencies.
        pause
        exit /b 1
    )
    type nul > ".venv\.deps_installed"
)

start "" ".venv\Scripts\pythonw.exe" main.py %*
