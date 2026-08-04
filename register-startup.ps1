# 윈도우 시작프로그램(Startup) 바로가기 등록 자동화 스크립트
# 이 스크립트는 start-server.bat를 최소화 창(WindowStyle = 7)으로 시작프로그램에 등록합니다.

$WshShell = New-Object -ComObject WScript.Shell

# 1. 윈도우 시작프로그램 폴더 내 바로가기 경로 설정
$StartupFolder = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$ShortcutPath = Join-Path $StartupFolder "PassionMateServer.lnk"

# 2. 원본 배치 파일 경로 설정
$TargetPath = "C:\Users\Zion_2112\.gemini\antigravity-ide\scratch\study-tracker-app\start-server.bat"
$WorkDir = "C:\Users\Zion_2112\.gemini\antigravity-ide\scratch\study-tracker-app"

# 3. 바로가기 객체 생성 및 속성 정의
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.WorkingDirectory = $WorkDir
$Shortcut.WindowStyle = 7  # 7: 최소화된 창으로 실행 (바탕화면에 뜨지 않고 작업표시줄 뒤로 숨김)
$Shortcut.Description = "Passion Mate 24h Auto-Restart Server"

# 4. 바로가기 저장
$Shortcut.Save()

Write-Host "=========================================================="
Write-Host "[OK] 윈도우 시작프로그램에 Passion Mate 서버가 등록되었습니다!"
Write-Host "[Info] 등록 경로: $ShortcutPath"
Write-Host "[Info] 이제 컴퓨터 전원을 켜고 로그인하면 서버가 백그라운드에서 자동으로 가동됩니다."
Write-Host "=========================================================="
