@echo off
setlocal
cd /d "%~dp0.."

echo === SC2 ChatBot portable build (Windows) ===
echo.

python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
python -m pip install "pyinstaller>=6.0"
if errorlevel 1 exit /b 1

echo.
echo Building with PyInstaller...
pyinstaller --noconfirm SC2ChatBot.spec
if errorlevel 1 exit /b 1

REM Ensure editable config sits NEXT TO the exe (not only inside _internal)
if not exist "dist\SC2ChatBot\config" mkdir "dist\SC2ChatBot\config"
copy /Y "config\config.example.yaml" "dist\SC2ChatBot\config\config.example.yaml" >nul
if not exist "dist\SC2ChatBot\config\config.yaml" (
  copy /Y "config\config.yaml" "dist\SC2ChatBot\config\config.yaml" >nul
)

if not exist "dist\SC2ChatBot\tools" mkdir "dist\SC2ChatBot\tools"
copy /Y "tools\measure_chat_region.py" "dist\SC2ChatBot\tools\measure_chat_region.py" >nul
copy /Y "portable\README_PORTABLE.txt" "dist\SC2ChatBot\README_PORTABLE.txt" >nul
copy /Y "portable\SWITCH_MODES.txt" "dist\SC2ChatBot\SWITCH_MODES.txt" >nul

echo.
echo Done.
echo Portable folder: dist\SC2ChatBot\
echo   - Run:  dist\SC2ChatBot\SC2ChatBot.exe
echo   - Edit: dist\SC2ChatBot\config\config.yaml
echo   - Switch simulated / OCR via chat_backend in that file
endlocal
