Set oShell = CreateObject("WScript.Shell")
oShell.Run "cmd /k ""cd /d """ & Chr(34) & "C:\Users\Bem-vindo(a)\Documents\Claude\Projects\SISTEMA FINANCEIRO" & Chr(34) & " && python -m streamlit run app.py --server.port 8501 --browser.gatherUsageStats false""", 1, False
