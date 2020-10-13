@ECHO OFF

CALL :CASE_%2 %* 2>NUL
IF ERRORLEVEL 1 CALL :CASE_3 %*
EXIT /B %ERRORLEVEL%

:CASE_1
:CASE_2
    ECHO ["remote/0"]
    EXIT /B 0

:CASE_3
    ECHO ERROR invalid value "%2" for option -r: relation not found >&2
    EXIT /B 2

:CASE_4
:CASE_5
    ECHO ["remoteapp1/0"]
    EXIT /B 0

:CASE_6
    ECHO ["remoteapp2/0"]
    EXIT /B 0
