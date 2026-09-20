@echo off
REM Puts a shortcut to the WLED Effects Studio on the desktop, pointing at the
REM exe in this folder. Ships in the packaged app (package.py copies it in); from
REM the tree it points at run_studio.cmd instead.
setlocal
set "HERE=%~dp0"
if exist "%HERE%WLED Effects Studio.exe" (
  set "TARGET=%HERE%WLED Effects Studio.exe"
  set "ICON=%HERE%WLED Effects Studio.exe,0"
) else (
  set "TARGET=%HERE%run_studio.cmd"
  set "ICON=%SystemRoot%\System32\shell32.dll,25"
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d = [Environment]::GetFolderPath('Desktop');" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($d + '\WLED Effects Studio.lnk');" ^
  "$s.TargetPath = $env:TARGET; $s.WorkingDirectory = $env:HERE; $s.IconLocation = $env:ICON;" ^
  "$s.Description = 'WLED Effects Studio'; $s.Save(); Write-Host ('shortcut made: ' + $d + '\WLED Effects Studio.lnk')"
pause
