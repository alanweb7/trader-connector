@echo off
chcp 65001 >nul
title Broker Gateway - Menu

:MENU
cls
echo ============================================================
echo           BROKER GATEWAY - MENU PRINCIPAL
echo ============================================================
echo.
echo   [1] Iniciar Servidor (porta 8000)
echo   [2] Rodar Testes da API
echo   [3] Testar Conexao IQ Option
echo   [4] Abrir Docs da API (navegador)
echo   [5] Instalar Dependencias
echo   [6] Parar Servidor
echo   [0] Sair
echo.
echo ============================================================
set /p opcao="Escolha uma opcao: "

if "%opcao%"=="1" goto INICIAR_SERVIDOR
if "%opcao%"=="2" goto RODAR_TESTES
if "%opcao%"=="3" goto TESTAR_IQOPTION
if "%opcao%"=="4" goto ABRIR_DOCS
if "%opcao%"=="5" goto INSTALAR
if "%opcao%"=="6" goto PARAR_SERVIDOR
if "%opcao%"=="0" goto SAIR

echo Opcao invalida!
timeout /t 2 >nul
goto MENU

:INICIAR_SERVIDOR
cls
echo Iniciando servidor...
cd /d "%~dp0"
call venv\Scripts\activate.bat
start "Broker Gateway" cmd /k "python -m src.server"
timeout /t 3 >nul
echo Servidor iniciado em http://localhost:8000
echo.
pause
goto MENU

:RODAR_TESTES
cls
echo Rodando testes da API...
cd /d "%~dp0"
call venv\Scripts\activate.bat
python scripts\test_api.py
echo.
pause
goto MENU

:TESTAR_IQOPTION
cls
echo Testando conexao com IQ Option...
cd /d "%~dp0"
call venv\Scripts\activate.bat
python scripts\test_iqoption_connection.py
echo.
pause
goto MENU

:ABRIR_DOCS
echo Abrindo documentacao...
start http://localhost:8000/docs
timeout /t 2 >nul
goto MENU

:INSTALAR
cls
echo Instalando dependencias...
cd /d "%~dp0"
python -m venv venv
call venv\Scripts\activate.bat
pip install -e .
echo.
echo Dependencias instaladas!
echo Copie o arquivo .env.example para .env e configure suas credenciais.
echo.
pause
goto MENU

:PARAR_SERVIDOR
echo Parando servidor...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Broker Gateway*" >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
echo Servidor parado.
timeout /t 2 >nul
goto MENU

:SAIR
exit