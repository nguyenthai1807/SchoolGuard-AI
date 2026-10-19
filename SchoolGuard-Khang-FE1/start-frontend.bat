@echo off
setlocal
cd /d "%~dp0"
echo SchoolGuard FE1: http://127.0.0.1:5500
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 -m http.server 5500 --bind 127.0.0.1 --directory minhkhangfe1
goto done
:use_python
python -m http.server 5500 --bind 127.0.0.1 --directory minhkhangfe1
:done
pause
