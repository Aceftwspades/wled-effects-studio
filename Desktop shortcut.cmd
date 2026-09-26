@echo off
REM Puts a shortcut to the WLED Effects Studio on the desktop, pointing at the
REM exe in this folder. Ships in the packaged app (package.py copies it in); from
REM the tree it points at run_studio.pyw run by pythonw - no console window (the
REM launcher says in a message box if the studio does not start) - or, with no
REM pythonw on the path, at run_studio.cmd.
setlocal
set "HERE=%~dp0"
set "ARGS="
set "PYW="
if exist "%HERE%WLED Effects Studio.exe" (
  set "TARGET=%HERE%WLED Effects Studio.exe"
  set "ICON=%HERE%WLED Effects Studio.exe,0"
  goto make
)
set "TARGET=%HERE%run_studio.cmd"
set "ICON=%SystemRoot%\System32\shell32.dll,25"
for /f "delims=" %%P in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%P"
if defined PYW (
  set "TARGET=%PYW%"
  set "ARGS=%HERE%run_studio.pyw"
)
if exist "%HERE%build\app.ico" set "ICON=%HERE%build\app.ico"
:make
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d = [Environment]::GetFolderPath('Desktop');" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($d + '\WLED Effects Studio.lnk');" ^
  "$s.TargetPath = $env:TARGET; $s.WorkingDirectory = $env:HERE; $s.IconLocation = $env:ICON;" ^
  "if ($env:ARGS) { $s.Arguments = [char]34 + $env:ARGS + [char]34 };" ^
  "$s.Description = 'WLED Effects Studio'; $s.Save(); Write-Host ('shortcut made: ' + $d + '\WLED Effects Studio.lnk')"
pause
