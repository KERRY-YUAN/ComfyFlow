@echo off

set "python_exec=python.exe"
set "requirements_txt=%~dp0\requirements.txt"

echo Installing with ComfyUI Portable
echo .
echo Install requirement.txt...
for /f "delims=" %%i in (%requirements_txt%) do (
    %python_exec% -s -m pip install "%%i"
    )

echo .
echo Install Finish!
pause
