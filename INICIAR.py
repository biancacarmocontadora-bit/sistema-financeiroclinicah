import subprocess
import webbrowser
import time
import os
import sys

pasta = os.path.dirname(os.path.abspath(__file__))
app = os.path.join(pasta, "app.py")

print("Iniciando Sistema Financeiro...")
proc = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", app,
     "--server.port", "8501",
     "--browser.gatherUsageStats", "false"],
    cwd=pasta
)

time.sleep(5)
webbrowser.open("http://localhost:8501")
print("Sistema aberto no navegador!")
print("Mantenha esta janela aberta.")
proc.wait()
