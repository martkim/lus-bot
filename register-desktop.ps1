$WshShell = New-Object -ComObject WScript.Shell
$DesktopFolder = "C:\Users\Zion_2112\Desktop"
$ShortcutPath = Join-Path $DesktopFolder "PASSION_MATE_SERVER.lnk"

$TargetPath = "C:\Users\Zion_2112\.gemini\antigravity\scratch\study-tracker-app\start-server.bat"
$WorkDir = "C:\Users\Zion_2112\.gemini\antigravity\scratch\study-tracker-app"

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.WorkingDirectory = $WorkDir
$Shortcut.WindowStyle = 1 # Normal Window (대화형 실행 화면 강제 활성화)
$Shortcut.Description = "PASSION MATE 24h Server"
$Shortcut.Save()

Write-Host "[OK] Desktop shortcut created successfully!"
