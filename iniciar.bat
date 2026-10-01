@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :error
.venv\Scripts\python.exe run.py
pause
exit /b
:error
echo No se pudo preparar el entorno. Instala Python 3.12 o superior y vuelve a intentarlo.
pause
exit /b 1
