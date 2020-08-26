@ECHO OFF

CALL :CASE_%1 2>NUL
IF ERRORLEVEL 1 ECHO []

EXIT /B 0

:CASE_db
    ECHO ["db:1"]
    EXIT /B

:CASE_mon
    ECHO ["mon:2"]
    EXIT /B

:CASE_db1
    ECHO ["db1:4"]
    EXIT /B

:CASE_db2
    ECHO ["db2:5", "db2:6"]
    EXIT /B
