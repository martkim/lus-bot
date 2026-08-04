Set oWS = WScript.CreateObject("WScript.Shell")

' 1. Cloudflare 터널 바로가기
sLinkFile = oWS.SpecialFolders("Desktop") & "\PASSION_MATE_Cloudflare.lnk"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "C:\PASSION_MATE\start-cloudflared.bat"
oLink.WorkingDirectory = "C:\PASSION_MATE"
oLink.Description = "PASSION MATE Cloudflare Tunnel"
oLink.Save

' 2. Server 터널 바로가기
sLinkFile2 = oWS.SpecialFolders("Desktop") & "\PASSION_MATE_Server.lnk"
Set oLink2 = oWS.CreateShortcut(sLinkFile2)
oLink2.TargetPath = "C:\PASSION_MATE\start-server.bat"
oLink2.WorkingDirectory = "C:\PASSION_MATE"
oLink2.Description = "PASSION MATE Server"
oLink2.Save

' 3. 구형 Ngrok 아이콘 삭제 (존재할 경우)
sOldNgrok = oWS.SpecialFolders("Desktop") & "\PASSION_MATE_Ngrok.lnk"
Set fso = CreateObject("Scripting.FileSystemObject")
If fso.FileExists(sOldNgrok) Then
    fso.DeleteFile sOldNgrok
End If
