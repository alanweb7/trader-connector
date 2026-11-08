@echo off
title Broker Gateway - Menu

REM ===========================================================================
REM  BROKER GATEWAY - MENU PRINCIPAL
REM
REM  ORDEM DOS BLOCOS (importante):
REM    - o fluxo principal (:MENU) fica no TOPO do arquivo, porque o cmd
REM      comeca a executar pela primeira linha;
REM    - as sub-rotinas (:START_SERVER, :IS_RUNNING, ...) ficam no FIM.
REM
REM  BUG CORRIGIDO 1: :IS_RUNNING estava no TOPO - o cmd caia direto nela ao
REM  abrir o .bat e o "exit /b" da sub-rotina encerrava o script ANTES do menu
REM  aparecer (a tela ficava limpa e o menu nunca era mostrado).
REM
REM  BUG CORRIGIDO 2: o "chcp 65001" foi REMOVIDO de proposito. O chcp troca o
REM  codepage do console e QUEBRA a leitura de stdin redirecionado (o set /p
REM  volta com EOF / erro 1), alem de deixar acentos quebrados em consoles
REM  cp850. O menu e 100% ASCII, entao nao depende de codepage.
REM
REM  O venv NAO e "ativado" (call activate.bat) de proposito: isso muda o
REM  PROMPT do console do usuario para "(venv) ...". O menu chama o python do
REM  venv pelo caminho completo, sem sujar o prompt.
REM ===========================================================================

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
set "opcao="
set /p opcao="Escolha uma opcao: "
if errorlevel 1 goto SAIR

if "%opcao%"=="1" goto INICIAR_SERVIDOR
if "%opcao%"=="2" goto REINICIAR_SERVIDOR
if "%opcao%"=="3" goto RODAR_TESTES
if "%opcao%"=="4" goto TESTAR_IQOPTION
if "%opcao%"=="5" goto ABRIR_DOCS
if "%opcao%"=="6" goto INSTALAR
if "%opcao%"=="7" goto PARAR_SERVIDOR
if "%opcao%"=="0" goto SAIR

echo Opcao invalida!
call :WAIT 2
goto MENU

:INICIAR_SERVIDOR
cls
echo Verificando se ja esta rodando...
call :IS_RUNNING
if not errorlevel 1 (
    echo Servidor ja esta rodando!
    echo Acesse: http://localhost:8000
    goto MENU_AFTER
)
echo Iniciando servidor em segundo plano...
call :START_SERVER
if errorlevel 1 (
    echo ERRO ao iniciar o servidor.
    goto MENU_AFTER
)
echo Servidor iniciado em http://localhost:8000
goto MENU_AFTER

:MENU_AFTER
echo.
call :PAUSE
goto MENU

:REINICIAR_SERVIDOR
cls
echo Reiniciando servidor...
echo [1/2] Parando servidor existente...
call :STOP_SERVER
call :WAIT 2
echo [2/2] Iniciando servidor...
call :START_SERVER
if errorlevel 1 (
    echo ERRO ao iniciar o servidor.
    goto MENU_AFTER
)
echo Servidor reiniciado em http://localhost:8000
goto MENU_AFTER

:RODAR_TESTES
cls
echo Rodando testes da API...
cd /d "%~dp0"
call :GET_PY
if errorlevel 1 (
    echo ERRO: Python nao encontrado.
    goto MENU_AFTER
)
"%PY%" scripts\test_api.py
goto MENU_AFTER

:TESTAR_IQOPTION
cls
echo Testando conexao com IQ Option...
cd /d "%~dp0"
call :GET_PY
if errorlevel 1 (
    echo ERRO: Python nao encontrado.
    goto MENU_AFTER
)
"%PY%" scripts\test_iqoption_connection.py
goto MENU_AFTER

:ABRIR_DOCS
echo Abrindo documentacao...
start "" http://localhost:8000/docs
call :WAIT 2
goto MENU

:INSTALAR
cls
echo Instalando dependencias...
cd /d "%~dp0"
call :GET_PY
if errorlevel 1 (
    echo ERRO: Python nao encontrado.
    goto MENU_AFTER
)
if not exist "venv\Scripts\python.exe" (
    echo Criando venv...
    "%PY%" -m venv venv
)
if not exist "venv\Scripts\python.exe" (
    echo ERRO ao criar o venv.
    goto MENU_AFTER
)
echo Instalando pacotes...
"venv\Scripts\python.exe" -m pip install --upgrade pip
"venv\Scripts\python.exe" -m pip install -e .
echo.
echo Dependencias instaladas!
echo Copie o arquivo .env.example para .env e configure suas credenciais.
goto MENU_AFTER

:PARAR_SERVIDOR
cls
echo Parando servidor...
call :STOP_SERVER
echo Servidor parado.
goto MENU_AFTER

:SAIR
exit /b 0

REM ===========================================================================
REM  SUB-ROTINAS
REM ===========================================================================

REM --- python do venv (self-contained) ou fallback para o PATH --------------
:GET_PY
set "PY="
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
if not defined PY exit /b 1
exit /b 0

REM --- sobe o gateway em segundo plano ---------------------------------------
:START_SERVER
cd /d "%~dp0"
call :GET_PY
if errorlevel 1 (
    echo ERRO: Python nao encontrado - nem no venv nem no PATH.
    exit /b 1
)
if not exist "logs" mkdir "logs" >nul 2>&1
REM start "titulo" /B -> processo na MESMA janela (sem abrir outra), com o
REM titulo "Broker Gateway" para identificar; saida vai para os logs.
start "Broker Gateway" /B "%PY%" -m src.server >>"logs\server.out.log" 2>>"logs\server.err.log"
call :WAIT 3
exit /b 0

REM --- o gateway esta rodando? (exit 0 = sim) --------------------------------
:IS_RUNNING
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\srv_ctl.ps1" -Action status >nul 2>&1
if not errorlevel 1 exit /b 0
exit /b 1

REM --- encerra SOMENTE o gateway (nunca os outros python.exe do PC) ---------
:STOP_SERVER
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\srv_ctl.ps1" -Action stop >nul 2>&1
exit /b 0

REM --- espera N segundos (funciona mesmo com stdin redirecionado) ------------
:WAIT
set /a _wait_n=%~1+1
ping -n %_wait_n% 127.0.0.1 >nul 2>&1
exit /b 0

REM --- "pressione uma tecla" (skip com MENU_NO_PAUSE=1, p/ execucao auto) --
:PAUSE
if defined MENU_NO_PAUSE exit /b 0
pause
exit /b 0
