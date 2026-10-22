# Recovery for the interrupted NEW installation created by AgentLab.
# Run in an elevated PowerShell. Never resets an installed/working distribution.
$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Ejecuta este script desde PowerShell como administrador para reiniciar WslService.'
}
if (Get-Process -Name vmmemWSL -ErrorAction SilentlyContinue) {
    throw 'Hay una VM WSL activa. Cierra sus trabajos antes de reiniciar el servicio.'
}
$expected = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'AgentLab\WSL\AgentLab-Repair'))
$entries = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' | Get-ItemProperty | Where-Object { $_.DistributionName -eq 'AgentLab-Repair' })
if ($entries.Count -ne 1 -or $entries[0].BasePath -ne $expected -or $entries[0].State -ne 3) {
    throw 'No coincide la instalación incompleta de AgentLab-Repair; no se reinició ni eliminó nada.'
}
$recordPath = Join-Path (Split-Path -Parent $expected) 'AgentLab-Repair.agentlab.json'
if (-not (Test-Path -LiteralPath $recordPath)) { throw 'Falta el registro de instalación de AgentLab.' }
$record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
if ($record.kind -ne 'agentlab-repair-install-v1' -or $record.location -ne $expected -or $record.status -ne 'installing') {
    throw 'El registro no corresponde a esta instalación incompleta.'
}
$service = Get-Service -Name WslService
if ($service.Status -ne 'Stopped') {
    if ($service.Status -eq 'Running') { $service.Stop() }
    try { $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(20)) }
    catch {
        if (Get-Process -Name vmmemWSL -ErrorAction SilentlyContinue) { throw 'Apareció una VM WSL; no se forzará el cierre.' }
        $serviceInfo = Get-CimInstance Win32_Service -Filter "Name='WslService'"
        if ($serviceInfo.ProcessId -gt 0) { Stop-Process -Id $serviceInfo.ProcessId -Force }
        $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(15))
    }
}
Start-Service -Name WslService
& wsl.exe --unregister AgentLab-Repair
if ($LASTEXITCODE -ne 0) { throw 'No se pudo retirar la instalación incompleta.' }
& (Join-Path $PSScriptRoot 'setup_repair_wsl.ps1') -Name AgentLab-Repair -Location $expected
