param(
    [ValidatePattern('^AgentLab-[A-Za-z0-9_-]+$')][string]$Name = 'AgentLab-Repair',
    [string]$Location = ''
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw 'WSL no está instalado.' }
if (-not $Location) { $Location = Join-Path $env:LOCALAPPDATA "AgentLab\WSL\$Name" }
$Location = [IO.Path]::GetFullPath($Location)
$recordPath = Join-Path (Split-Path -Parent $Location) "$Name.agentlab.json"
$resume = $false
$installed = @(& wsl.exe --list --quiet) | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ }
if ($LASTEXITCODE -ne 0) { throw 'No se pudo listar WSL.' }
if ($installed -contains $Name) {
    & wsl.exe --distribution $Name --user root --cd / --exec cat /etc/agentlab-repair.json
    $hasMarker = $LASTEXITCODE -eq 0
    if (Test-Path -LiteralPath $recordPath) {
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        $resume = ($record.kind -eq 'agentlab-repair-install-v1' -and $record.name -eq $Name -and $record.location -eq $Location -and $record.status -eq 'installing')
    }
    if ($hasMarker -and -not $resume) {
        Write-Host 'El WSL dedicado ya existe. Usa repair.py wsl para validar su configuración.'
        exit 0
    }
    if (-not $resume) { throw "$Name existe pero no fue preparado por este instalador. No se modificó." }
    Write-Host "Retomando la preparación incompleta de $Name..."
}
$targetDrive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Location))
if ($targetDrive.AvailableFreeSpace -lt 4GB) { throw "Se necesitan al menos 4 GB libres en $($targetDrive.Name). Elige otra -Location." }
if (-not $resume) {
    if (Test-Path -LiteralPath $Location) { throw "La ubicación ya existe; elige una carpeta nueva: $Location" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Location) | Out-Null
    @{kind='agentlab-repair-install-v1'; name=$Name; location=$Location; status='installing'} | ConvertTo-Json | Set-Content -LiteralPath $recordPath -Encoding utf8
    Write-Host "Instalando Debian limpio como $Name en $Location..."
    & wsl.exe --install Debian --name $Name --location $Location --no-launch --web-download
    if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación. No se modificaron las otras distribuciones.' }
}

$provision = @'
set -eu
export DEBIAN_FRONTEND=noninteractive
dpkg --configure -a </dev/null || true
apt-get update </dev/null
apt-get -f install -y </dev/null
apt-get install -y python3 python3-venv python3-pip git ca-certificates curl build-essential procps </dev/null
mkdir -p /workspace
cat > /etc/wsl.conf <<'CONF'
[automount]
enabled=false
mountFsTab=false
[interop]
enabled=false
appendWindowsPath=false
[user]
default=root
CONF
printf '%s\n' '{"kind":"agentlab-repair-v1","purpose":"shared coding workspace"}' > /etc/agentlab-repair.json
chmod 644 /etc/agentlab-repair.json /etc/wsl.conf
'@
$provision = $provision -replace "`r", ''
$provision | & wsl.exe --distribution $Name --user root --cd / --exec bash -c 'tr -d "\r" | bash -s'
if ($LASTEXITCODE -ne 0) { throw "Falló la preparación de $Name; se conserva para diagnóstico." }
& wsl.exe --terminate $Name
if ($LASTEXITCODE -ne 0) { throw "No se pudo reiniciar $Name para aplicar wsl.conf." }
Push-Location $PSScriptRoot
try {
    python -c "from repair_workspace import WSLWorkspace; WSLWorkspace('$Name'); print('Configuración WSL validada.')"
    if ($LASTEXITCODE -ne 0) { throw 'El entorno no pasó la validación de WSL.' }
} finally { Pop-Location }
@{kind='agentlab-repair-install-v1'; name=$Name; location=$Location; status='ready'} | ConvertTo-Json | Set-Content -LiteralPath $recordPath -Encoding utf8
Write-Host "Listo: $Name. Acceso completo como root, sin automount ni interop Windows."
Write-Host "  wsl.exe -d $Name -u root --cd /workspace"
Write-Host 'WSL con root no es una frontera de seguridad frente a código hostil; no equivale a una VM independiente.'
