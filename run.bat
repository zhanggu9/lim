@echo off
@echo off
setlocal
set PYTHONDONTWRITEBYTECODE=1

set "ROOT=%~dp0"
cd /d "%ROOT%"
call C:\Users\L\anaconda3\Scripts\activate.bat
if errorlevel 1 goto error
call conda activate kw
if errorlevel 1 goto error
set "PYTHONPATH=%ROOT%src;%PYTHONPATH%"
python -m app.main
if errorlevel 1 goto error
endlocal
exit /b 0

:error
echo.
echo run.bat failed. See the error message above.
pause
endlocal
exit /b 1
