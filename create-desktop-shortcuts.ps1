$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")

$CloudflareShortcutPath = Join-Path $DesktopPath "PASSION_MATE_Cloudflare.lnk"
$CloudflareShortcut = $WshShell.CreateShortcut($CloudflareShortcutPath)
$CloudflareShortcut.TargetPath = "C:\PASSION_MATE\start-cloudflared.bat"
$CloudflareShortcut.WorkingDirectory = "C:\PASSION_MATE"
$CloudflareShortcut.Save()

$ServerShortcutPath = Join-Path $DesktopPath "PASSION_MATE_Server.lnk"
$ServerShortcut = $WshShell.CreateShortcut($ServerShortcutPath)
$ServerShortcut.TargetPath = "C:\PASSION_MATE\start-server.bat"
$ServerShortcut.WorkingDirectory = "C:\PASSION_MATE"
$ServerShortcut.Save()

Write-Host "Desktop shortcuts created successfully!"
