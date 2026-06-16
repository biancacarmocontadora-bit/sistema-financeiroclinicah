@echo off
title Sistema Clinica Medica
echo.
echo ================================================
echo   Sistema de Clinica Medica - Iniciando...
echo ================================================
echo.

cd /d "%~dp0"

:: Verifica se Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado. Instale em https://python.org
    pause
    exit /b
)

:: Cria ambiente virtual se nao existir
if not exist "venv\" (
    echo Criando ambiente virtual...
    python -m venv venv
)

:: Ativa o ambiente virtual
call "%~dp0venv\Scripts\activate.bat"

:: Instala dependencias
echo Verificando dependencias...
pip install -r "%~dp0requirements.txt" -q

echo.
echo ================================================
echo   Acesse: http://localhost:5000
echo   Pressione CTRL+C para encerrar
echo ================================================
echo.

:: Migra o banco
python "%~dp0migrar_db.py"

:: Inicia o servidor
python "%~dp0app.py"

pause
