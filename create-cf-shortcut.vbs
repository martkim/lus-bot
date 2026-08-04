Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = oWS.SpecialFolders("Desktop") & "\PASSION_MATE_Cloudflare.lnk"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "C:\Users\Zion_2112\.gemini\antigravity-ide\scratch\study-tracker-app\start-cloudflared.bat"
oLink.WorkingDirectory = "C:\Users\Zion_2112\.gemini\antigravity-ide\scratch\study-tracker-app"
oLink.Save
