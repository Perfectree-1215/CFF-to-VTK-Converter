@echo off
REM Script - one-click setup and run (spec section 7)
REM The project lives inside a Google Drive synced folder, so the virtualenv is
REM created OUTSIDE the project at %LOCALAPPDATA%\<Script>\venv to avoid
REM sync load and file locking. All paths are quoted (project path may contain
REM spaces / non-ASCII). This file itself uses ASCII only to dodge codepage issues.

REM "PROJECT_NAME"과 "SCRIPT_NAME"을 확인 및 변경 후 실행.

setlocal

set "PROJECT_NAME=CFF2VTK_venv"
set "SCRIPT_NAME=pv_export_gui.py"

set "VENV_DIR=D:\Venvs_collec\%PROJECT_NAME%\venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PYW=%VENV_DIR%\Scripts\pythonw.exe"

if not exist "%VENV_PY%" (
    echo [1/4] Creating virtual environment at "%VENV_DIR%" ...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo ERROR: could not create the virtual environment.
        echo Make sure Python 3.10+ is installed and available on PATH.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Virtual environment already exists.
)

echo [2/4] Installing / updating dependencies ...
"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo ERROR: dependency installation failed.
    pause
    exit /b 1
)

echo [3/4] Checking engine modules ...
"%VENV_PY%" -c "import PySide6, pyvista; print('  PySide6', PySide6.__version__); print('  pyvista', pyvista.__version__)"
if errorlevel 1 (
    echo WARNING: PySide6 or pyvista failed to import. The GUI or the PyVista engine may not work.
)
"%VENV_PY%" -c "import ansys.fluent.core as f; print('  ansys-fluent-core', f.__version__)"
if errorlevel 1 (
    echo WARNING: ansys-fluent-core failed to import.
    echo          The PyFluent tab will be disabled. Converter tab PyVista/ParaView still works.
)

:: echo [4/4] Launching Script ...
:: start "" "%VENV_PYW%" "%~dp0pv_export_gui.py"

echo [4/4] Launching %SCRIPT_NAME% ...
start "" "%VENV_PYW%" "%~dp0%SCRIPT_NAME%"

endlocal
