<#
  Controle do processo do CONNECTOR (Broker Gateway).

  Uso:
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\srv_ctl.ps1 -Action status
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\srv_ctl.ps1 -Action stop

  status -> exit 0 se o gateway estiver rodando, 1 se estiver parado
  stop   -> encerra SOMENTE os processos do connector:
             1) o reloader "python -m src.server";
             2) o dono da porta 8000 (o filho do uvicorn --reload nao tem
                "src.server" na command line).
           NUNCA mata os outros python.exe da maquina.
#>
param(
    [ValidateSet('status', 'stop')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'SilentlyContinue'

function Get-GatewayProcesses {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'python.exe' -and $_.CommandLine -like '*-m src.server*'
    })
}

function Get-PortOwners {
    @(Get-NetTCPConnection -LocalPort 8000 -State Listen |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

switch ($Action) {
    'status' {
        $procs = Get-GatewayProcesses
        $owners = Get-PortOwners
        if ($procs.Count -gt 0 -or $owners.Count -gt 0) {
            Write-Output ("RUNNING gateway={0} porta8000={1}" -f $procs.Count, $owners.Count)
            exit 0
        }
        Write-Output 'STOPPED'
        exit 1
    }

    'stop' {
        # 1) o reloader primeiro - se ele ficar vivo, ele respawna o filho
        foreach ($proc in Get-GatewayProcesses) {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        }
        # 2) dono da porta 8000 (filho do uvicorn --reload)
        foreach ($procId in Get-PortOwners) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 900
        $left = @(Get-PortOwners)
        if ($left.Count -gt 0) {
            Write-Output ("WARN ainda ouvindo na 8000: {0}" -f ($left -join ','))
            exit 2
        }
        Write-Output 'STOPPED'
        exit 0
    }
}
