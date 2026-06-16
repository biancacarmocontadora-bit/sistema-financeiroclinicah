Set oShell = CreateObject("WScript.Shell")
Set oFSO = CreateObject("Scripting.FileSystemObject")
pasta = oFSO.GetParentFolderName(WScript.ScriptFullName)
python = "C:\Users\Bem-vindo(a)\AppData\Local\Python\pythoncore-3.14-64\python.exe"
cmd = """" & python & """ -m streamlit run """ & pasta & "\app.py"" --server.port 8501 --browser.gatherUsageStats false --server.headless true"
oShell.Run "cmd /c " & cmd, 0, False
WScript.Sleep 8000
oShell.Run "http://localhost:8501"
