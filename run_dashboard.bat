@echo off
REM Launches the GaN HEMT Digital Twin Streamlit dashboard.
REM Regenerates the Stage 2 artefacts first so the dashboard never shows stale numbers.
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%dashboard"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] python was not found on PATH.
    exit /b 1
)

python -c "import streamlit, plotly" >nul 2>&1
if errorlevel 1 (
    echo Installing dashboard dependencies from requirements.txt ...
    python -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        exit /b 1
    )
)

echo Regenerating Stage 2 artefacts ...
pushd "%ROOT%stage2"
python -m ganstage2.run
if errorlevel 1 (
    echo [ERROR] Stage 2 pipeline failed. Dashboard not started.
    popd
    exit /b 1
)
popd

echo Starting dashboard at http://localhost:8501
python -m streamlit run app.py --server.port 8501 --browser.gatherUsageStats false
endlocal
