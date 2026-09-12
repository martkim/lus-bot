# ensure_watchdog.ps1을 Windows 작업 스케줄러에 10분 주기 반복 작업으로 등록한다.
# 목적: system_service.py(파이썬 워치독)가 세션 도중 죽었을 때, 다음 로그인까지 기다리지 않고
# 최대 10분 안에 자동으로 재기동되게 한다 ("워치독의 워치독").
#
# 이미 로그인된 사용자 세션에서만 동작(비밀번호 저장 불필요) - 기존 Startup 폴더 방식과
# 동일한 전제(PC가 로그인된 채로 계속 켜져 있음)라 새로운 요구사항을 추가하지 않는다.

$taskName = "PassionMate_WatchdogSafetyNet"
$scriptPath = "C:\PASSION_MATE\ensure_watchdog.ps1"

$actionArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs

$repeatInterval = New-TimeSpan -Minutes 10
$repeatDuration = New-TimeSpan -Days 3650
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval $repeatInterval -RepetitionDuration $repeatDuration

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$taskDescription = "PASSION MATE watchdog safety net - restarts system_service.py within 10 minutes if it is not running"

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description $taskDescription -Force

Write-Host "[OK] Scheduled Task registered:" $taskName
