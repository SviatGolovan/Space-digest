@echo off
chcp 65001 >nul
rem Сборка установщика Space Digest на Windows.
rem Нужно один раз: Python 3.12 (python.org, галочка "Add to PATH") и Inno Setup 6 (jrsoftware.org).
rem Результат: dist\SpaceDigest-Setup-<версия>.exe
setlocal
cd /d "%~dp0\.."

if not exist .venv-build (
  py -3.12 -m venv .venv-build || python -m venv .venv-build || goto :err
)
call .venv-build\Scripts\activate.bat || goto :err
python -m pip install --upgrade pip
pip install -r requirements-build.txt || goto :err

pyinstaller packaging\SpaceDigest.spec --noconfirm --clean || goto :err

for /f %%v in ('python -c "from spacedigest import VERSION; print(VERSION)"') do set APPVER=%%v

set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo.
  echo Inno Setup не найден. Программа собрана в dist\SpaceDigest\SpaceDigest.exe
  echo Чтобы получить установщик, поставьте Inno Setup 6 и запустите этот файл снова.
  goto :end
)
%ISCC% /DAppVersion=%APPVER% packaging\windows\SpaceDigest.iss || goto :err
echo.
echo Готово: dist\SpaceDigest-Setup-%APPVER%.exe
goto :end

:err
echo.
echo ОШИБКА сборки — см. сообщения выше.
exit /b 1
:end
pause
