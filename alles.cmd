@echo off
rem prefer 'python' — it's the interpreter people pip-install into.
rem 'py -3' can resolve to a different install with no packages.
where python >nul 2>nul
if %errorlevel%==0 (
  python "%~dp0cli.py" %*
) else (
  py -3 "%~dp0cli.py" %*
)
