@echo off
REM ===================================================================
REM  Hardmine - CFTC + ICE COT weekly update
REM  CFTC releases Friday 15:30 ET; ICE publishes Friday 18:30 London.
REM  Schedule this for Friday ~23:30 IST so both are out.
REM ===================================================================

setlocal
set ROOT=%~dp0..
set LOG=%~dp0run_log.txt

echo. >> "%LOG%"
echo ================================================== >> "%LOG%"
echo Run started %DATE% %TIME% >> "%LOG%"

python "%ROOT%\Code\cftc_ingest.py" >> "%LOG%" 2>&1
set RC_CFTC=%ERRORLEVEL%
if not "%RC_CFTC%"=="0" echo [WARN] cftc_ingest exited %RC_CFTC% >> "%LOG%"

python "%ROOT%\Code\ice_ingest.py" >> "%LOG%" 2>&1
set RC_ICE=%ERRORLEVEL%
if not "%RC_ICE%"=="0" echo [WARN] ice_ingest exited %RC_ICE% >> "%LOG%"

echo Run finished %DATE% %TIME%  (cftc=%RC_CFTC% ice=%RC_ICE%) >> "%LOG%"

if not "%RC_CFTC%"=="0" exit /b %RC_CFTC%
if not "%RC_ICE%"=="0" exit /b %RC_ICE%
exit /b 0
