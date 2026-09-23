@echo off
chcp 65001 >nul
title Broker Gateway - Menu

:MENU
cls
echo ============================================================
echo           BROKER GATEWAY - MENU PRINCIPAL
echo ============================================================
echo.
echo   [1] Iniciar Servidor (segundo plano)
echo   [2] Reiniciar Servidor
echo   [3] Rodar Testes da API
echo   [4] Testar Conexao IQ Option
echo   [5] Abrir Docs da API (navegador)
echo   [6] Instalar Dependencias
echo   [7] Parar Servidor
echo   [0] Sair
echo.
echo ============================================================
set /p opcao="Escolha uma opcao: "

if "%opcao%"=="1" goto INICIAR_SERVIDOR
if "%opcao%"=="2" goto REINICIAR_SERVIDOR
if "%opcao%"=="3" goto RODAR_TESTES
if "%opcao%"=="4" goto TESTAR_IQOPTION
if "%opcao%"=="5" goto ABRIR_DOCS
if "%opcao%"=="6" goto INSTALAR
if "%opcao%"=="7" goto PARAR_SERVIDOR
if "%opcao%"=="0" goto SAIR

echo Opcao invalida!
timeout /t 2 >nul
goto MENU

:INICIAR_SERVIDOR
cls
echo Verificando se ja esta rodando...
tasklist /FI "WINDOWTITLE eq Broker Gateway*" 2>nul | find /I "python.exe" >nul
if %errorlevel%==0 (
    echo Servidor ja esta rodando!
    echo Acesse: http://localhost:8000
) else (
    echo Iniciando servidor em segundo plano...
    cd /d "%~dp0"
    call venv\Scripts\activate.bat
    start /B "Broker Gateway" python -m src.server >nul 2>&1
    timeout /t 3 >nul
    echo Servidor iniciado em http://localhost:8000
)
echo.
pause
goto MENU

:REINICIAR_SERVIDOR
cls
echo Reiniciando servidor...
cd /d "%~dp0"

echo [1/2] Parando servidor existente...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Broker Gateway*" >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
timeout /t 2 >nul

echo [2/2] Iniciando servidor...
call venv\Scripts\activate.bat
start /B "Broker Gateway" python -m src.server >nul 2>&1
timeout /t 3 >nul

echo Servidor reiniciado em http://localhost:8000
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