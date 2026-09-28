' Double-click to start voiceinput silently in the background (tray icon only, no console window).
Option Explicit
Dim fso, sh, base, pyw
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base
pyw = base & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then
    MsgBox "Cannot find .venv\Scripts\pythonw.exe." & vbCrLf & "Please run setup.bat first.", vbExclamation, "voiceinput"
    WScript.Quit 1
End If
sh.Run """" & pyw & """ -m voiceinput", 0, False
