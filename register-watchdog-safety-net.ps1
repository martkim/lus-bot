# ensure_watchdog.ps1을 Windows 작업 스케줄러에 등록한다: (1) 10분 주기 반복 트리거 +
# (2) 부팅 시(AtStartup) 트리거. 목적: system_service.py(파이썬 워치독)가 세션 도중
# 죽었을 때 최대 10분 안에 재기동되는 것("워치독의 워치독")에 더해, **크래시로 재부팅된 뒤
# 아무도 Windows에 로그인하지 않은 상태에서도** 워치독/서버/터널이 자동으로 살아나게 한다.
#
# 2026-09-20 감사에서 발견: 기존엔 LogonType이 Interactive였고 AtStartup 트리거도 없어서,
# 로그인된 세션 안에서만 동작했다 - 즉 BSOD 자동 재부팅 후 로그인 화면에서 멈추면(자동 로그인
# 미설정) 이 안전망도, register-startup.vbs의 시작프로그램 등록도 전혀 작동하지 않아 서버가
# 무한정 다운된 채로 남는 치명적 공백이 있었다(실제로 register-startup.vbs는 한 번도 적용된
# 적이 없어 시작프로그램 폴더가 비어 있었음). LogonType을 S4U로 바꾸면 비밀번호를 저장하지
# 않고도 "로그인 여부와 무관하게" 부팅 즉시 실행된다 - "서버는 절대 꺼지면 안 된다"는 요구사항
# 에 맞춰 이 안전망이 로그인 여부의 영향을 받지 않도록 하는 것이 핵심.

$taskName = "PassionMate_WatchdogSafetyNet"
$scriptPath = "C:\PASSION_MATE\ensure_watchdog.ps1"
$currentUser = "$env:USERDOMAIN\$env:USERNAME"

$actionArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs

$startupTrigger = New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Seconds 30)
$repeatTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)

# S4U: 비밀번호를 저장하지 않고도 로그인 여부와 무관하게 실행 (Interactive였던 기존 방식의
# 핵심 공백을 해소).
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType S4U -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$taskDescription = "PASSION MATE watchdog safety net - restarts system_service.py within 10 minutes if not running, and immediately at boot even if nobody is logged into Windows (S4U logon)"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[FAIL] Registering an S4U-logon task requires an elevated (Administrator) PowerShell window. Right-click PowerShell -> 'Run as Administrator' and re-run this script." -ForegroundColor Red
    exit 1
}

try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($startupTrigger, $repeatTrigger) -Principal $principal -Settings $settings -Description $taskDescription -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Host "[FAIL] Register-ScheduledTask failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$registered = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($registered -and $registered.Principal.LogonType -eq 'S4U') {
    Write-Host "[OK] Scheduled Task registered with S4U logon (works even without an interactive Windows login):" $taskName
} else {
    Write-Host "[FAIL] Task was not registered as expected (LogonType: $($registered.Principal.LogonType)). Re-check manually with Get-ScheduledTask." -ForegroundColor Red
    exit 1
}
