Set oWS = WScript.CreateObject("WScript.Shell")
sStartup = oWS.SpecialFolders("Startup")

' 1. Cloudflare 터널 시작프로그램 등록
sLinkFile = sStartup & "\PASSION_MATE_Cloudflare_Startup.lnk"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "C:\PASSION_MATE\start-cloudflared.bat"
oLink.WorkingDirectory = "C:\PASSION_MATE"
oLink.WindowStyle = 7 ' Minimized
oLink.Description = "PASSION MATE Cloudflare Tunnel"
oLink.Save

' 2. Server 터널 시작프로그램 등록
sLinkFile2 = sStartup & "\PASSION_MATE_Server_Startup.lnk"
Set oLink2 = oWS.CreateShortcut(sLinkFile2)
oLink2.TargetPath = "C:\PASSION_MATE\start-server.bat"
oLink2.WorkingDirectory = "C:\PASSION_MATE"
oLink2.WindowStyle = 7 ' Minimized
oLink2.Description = "PASSION MATE Server"
oLink2.Save

' 3. System Service 독립 스케줄러 등록 (pythonw를 통해 숨김 실행)
sLinkFile3 = sStartup & "\PASSION_MATE_Service.lnk"
Set oLink3 = oWS.CreateShortcut(sLinkFile3)
oLink3.TargetPath = "pythonw.exe"
oLink3.Arguments = "C:\PASSION_MATE\system_service.py"
oLink3.WorkingDirectory = "C:\PASSION_MATE"
oLink3.WindowStyle = 0 ' Hidden
oLink3.Description = "PASSION MATE System Service"
oLink3.Save

WScript.Echo "Startup shortcuts created successfully in: " & sStartup
