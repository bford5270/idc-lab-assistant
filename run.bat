@echo off
REM Launch the IDC Lab Assistant locally on Windows.
REM Double-click this file or run from a Command Prompt.

cd /d "%~dp0"

where streamlit >nul 2>nul
if errorlevel 1 (
    echo Streamlit not found. Installing dependencies...
    python -m pip install -r requirements.txt
)

REM Streamlit opens the browser to http://localhost:8501 on first boot.
streamlit run app.py
