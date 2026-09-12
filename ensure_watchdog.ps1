# "워치독의 워치독" — system_service.py(파이썬 상시 워치독)는 Windows 로그인 시 1회만
# 시작되기 때문에, 세션 도중 이 프로세스 자체가 죽거나 강제 종료되면 재부팅/재로그인 전까지
# 아무것도 되살려주지 않는다. 이 스크립트를 Windows 작업 스케줄러에 10분 주기로 등록해서
# system_service.py가 안 떠 있으면 다시 띄운다 (register_watchdog_safety_net.ps1 참고).

$pythonwPath = "C:\Users\Zion_2112\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
$scriptPath = "C:\PASSION_MATE\system_service.py"
$logPath = "C:\PASSION_MATE\logs\needs_attention.log"

$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*system_service.py*" }

if (-not $running) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logPath -Value "[$ts] ensure_watchdog.ps1: system_service.py(watchdog) was not running - restarting it via Task Scheduler safety net."
    Start-Process -FilePath $pythonwPath -ArgumentList "`"$scriptPath`"" -WorkingDirectory "C:\PASSION_MATE"
}
