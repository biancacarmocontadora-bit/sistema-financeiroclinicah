$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $pasta

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Sistema de Clinica Medica - Iniciando..." -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# Migra banco
& "$pasta\venv\Scripts\python.exe" migrar_db.py

Write-Host ""
Write-Host "  Acesse: http://localhost:5000" -ForegroundColor Green
Write-Host "  Pressione CTRL+C para encerrar" -ForegroundColor Green
Write-Host ""

# Inicia servidor
& "$pasta\venv\Scripts\python.exe" app.py
