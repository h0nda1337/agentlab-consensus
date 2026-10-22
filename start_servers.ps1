param(
    [string]$LlamaServerPath = "",
    [switch]$Restart,
    [switch]$LowMemory,
    [ValidateSet('Dars','Rade','Miso')][string[]]$Agents = @('Dars','Rade','Miso'),
    [switch]$Stop,
    [string]$OwnerToken = '',
    [ValidateRange(2048, 32768)][int]$DarsCtx = 8192,
    [ValidateRange(2048, 8192)][int]$MisoCtx = 8192,
    [ValidateRange(2048, 32768)][int]$RadeCtx = 8192,
    [ValidatePattern('^(auto|all|[0-9]+)$')][string]$DarsGpuLayers = 'auto',
    [ValidatePattern('^(auto|all|[0-9]+)$')][string]$RadeGpuLayers = 'auto',
    [ValidatePattern('^(auto|all|[0-9]+)$')][string]$MisoGpuLayers = 'auto'
)

$ErrorActionPreference = 'Stop'
$logRoot = Join-Path $PSScriptRoot 'work\serverlogs'
if ($Stop) {
    if (-not $OwnerToken) { throw '-Stop requiere el token del proceso que inició estos servidores.' }
    foreach ($agentName in $Agents) {
        $manifestPath = Join-Path $logRoot "$agentName.process.json"
        if (-not (Test-Path -LiteralPath $manifestPath)) { continue }
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if ($manifest.owner -ne $OwnerToken) { continue }
        $ownedProcess = Get-Process -Id $manifest.pid -ErrorAction SilentlyContinue
        if ($ownedProcess) {
            if ($ownedProcess.ProcessName -notlike 'llama-server*' -or $ownedProcess.StartTime.ToUniversalTime().Ticks -ne $manifest.startedTicks) {
                throw 'El PID cambió de propietario; no se detendrá.'
            }
            Stop-Process -Id $ownedProcess.Id -Force
            $ownedProcess.WaitForExit(15000) | Out-Null
        }
        Remove-Item -LiteralPath $manifestPath
    }
    exit 0
}

# GPU allocations also consume Windows commit. Leave unrelated models running
# and use mapped CPU weights when there is not enough commit for all three.
$availableMemory = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
if ($LowMemory -or ($availableMemory -and $availableMemory.FreeVirtualMemory -lt 18*1024*1024)) {
    $conservativeLayers = '0'
    if ($OwnerToken -and $availableMemory -and $availableMemory.FreeVirtualMemory -gt 6*1024*1024) {
        # A managed session keeps only one model resident. A small GPU offload
        # speeds prompt processing while leaving commit for Linux and tools.
        $conservativeLayers = '8'
    }
    foreach ($setting in @('DarsGpuLayers', 'RadeGpuLayers', 'MisoGpuLayers')) {
        if (-not $PSBoundParameters.ContainsKey($setting)) { Set-Variable -Name $setting -Value $conservativeLayers }
    }
    Write-Host "Perfil de memoria reducida: $conservativeLayers capas GPU para agentes sin ajuste explícito."
}

if ([string]::IsNullOrWhiteSpace($LlamaServerPath)) {
    $found = Get-Command llama-server.exe -ErrorAction SilentlyContinue
    if (-not $found) { $found = Get-Command llama-server -ErrorAction SilentlyContinue }
    if ($found) { $LlamaServerPath = $found.Source }
    if ([string]::IsNullOrWhiteSpace($LlamaServerPath)) {
        $packageRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
        foreach ($package in (Get-ChildItem -LiteralPath $packageRoot -Directory -Filter 'ggml.llamacpp_*' -ErrorAction SilentlyContinue)) {
            $candidate = Join-Path $package.FullName 'llama-server.exe'
            if (Test-Path -LiteralPath $candidate) { $LlamaServerPath = $candidate; break }
        }
    }
    if ([string]::IsNullOrWhiteSpace($LlamaServerPath)) {
        throw "No encontre llama-server.exe. Ejecuta: .\start_servers.ps1 -LlamaServerPath 'C:\ruta\llama-server.exe'"
    }
}
if (-not (Test-Path -LiteralPath $LlamaServerPath)) { throw "No existe: $LlamaServerPath" }

$profilesPath = Join-Path $PSScriptRoot 'server_profiles.json'
if (-not (Test-Path -LiteralPath $profilesPath)) { throw 'Copy server_profiles.example.json to server_profiles.json and set your model paths and devices.' }
$modelProfiles = Get-Content -LiteralPath $profilesPath -Raw | ConvertFrom-Json
foreach ($slot in @('Dars','Rade','Miso')) {
    $modelPath = [string]$modelProfiles.$slot.model
    if (-not [IO.Path]::IsPathRooted($modelPath)) { $modelPath = Join-Path $PSScriptRoot $modelPath }
    $modelProfiles.$slot.model = $modelPath
}

$servers = @(
    @{
        Name = 'Dars'; Model = $modelProfiles.Dars.model
        Port = 8081; Device = $modelProfiles.Dars.device; Ctx = $DarsCtx; Layers = $DarsGpuLayers
        TemplateArgs = @($modelProfiles.Dars.template_args)
    },
    @{
        Name = 'Rade'; Model = $modelProfiles.Rade.model
        Port = 8082; Device = $modelProfiles.Rade.device; Ctx = $RadeCtx; Layers = $RadeGpuLayers
        TemplateArgs = @($modelProfiles.Rade.template_args)
    },
    @{
        Name = 'Miso'; Model = $modelProfiles.Miso.model
        Port = 8083; Device = $modelProfiles.Miso.device; Ctx = $MisoCtx; Layers = $MisoGpuLayers
        # Gemma 2 does not have a separate native system role.
        # llama.cpp's built-in gemma chat template merges system into user.
        TemplateArgs = @($modelProfiles.Miso.template_args)
    }
)
$servers = @($servers | Where-Object { $_.Name -in $Agents })

foreach ($s in $servers) {
    if (-not (Test-Path -LiteralPath $s.Model)) { throw "Falta el GGUF de $($s.Name): $($s.Model)" }
}

function Get-ServerOwner([int]$port) {
    $conn = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -eq '127.0.0.1' -or $_.LocalAddress -eq '0.0.0.0' -or $_.LocalAddress -eq '::1' -or $_.LocalAddress -eq '::' } |
        Select-Object -First 1)
    if ($conn.Count -eq 0) { return $null }
    return Get-Process -Id $conn[0].OwningProcess -ErrorAction SilentlyContinue
}

function Get-ServerProps([int]$port) {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$port/props" -TimeoutSec 3 -ErrorAction Stop
    } catch {
        return $null
    }
}

if ($Restart) {
    foreach ($s in $servers) {
        $owner = Get-ServerOwner $s.Port
        if (-not $owner) { continue }
        if ($owner.ProcessName -notlike 'llama-server*') {
            throw "Puerto $($s.Port) ocupado por proceso ajeno ($($owner.ProcessName), PID $($owner.Id)). No lo cerrare."
        }
        Write-Host "Deteniendo $($s.Name): PID $($owner.Id), puerto $($s.Port)"
        Stop-Process -Id $owner.Id -ErrorAction Stop
        $deadline = (Get-Date).AddSeconds(25)
        while ((Get-ServerOwner $s.Port) -and ((Get-Date) -lt $deadline)) { Start-Sleep -Milliseconds 350 }
        if (Get-ServerOwner $s.Port) { throw "Puerto $($s.Port) no se libero tras detener el servidor." }
    }
}

New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
foreach ($s in $servers) {
    $owner = Get-ServerOwner $s.Port
    if ($owner) {
        $props = Get-ServerProps $s.Port
        if ($owner.ProcessName -notlike 'llama-server*') {
            throw "Puerto $($s.Port) ocupado por $($owner.ProcessName). No se reemplazara."
        }
        $loadedPath = if ($props) { [string]$props.model_path } else { '' }
        if ($loadedPath -ieq $s.Model) {
            Write-Host "$($s.Name) ya esta cargado en $($s.Port) con el GGUF nuevo."
            continue
        }
        throw "Puerto $($s.Port) ocupado por otro modelo o aun cargando: '$loadedPath'. Cierra los antiguos usando .\start_servers.ps1 -Restart"
    }

    $argParts = @(
        '-m', ('"' + $s.Model + '"'),
        '--host', '127.0.0.1',
        '--port', [string]$s.Port,
        '--device', $s.Device,
        '--split-mode', 'none',
        '--gpu-layers', $s.Layers,
        '--cache-type-k', 'q8_0',
        '--cache-type-v', 'q8_0',
        '--batch-size', '512',
        '--ubatch-size', '128',
        '--ctx-size', [string]$s.Ctx,
        '--parallel', '1',
        '--flash-attn', 'auto',
        '--no-context-shift'
    ) + $s.TemplateArgs

    $stdoutPath = Join-Path $logRoot "$($s.Name).stdout.log"
    $stderrPath = Join-Path $logRoot "$($s.Name).stderr.log"
    $process = Start-Process -FilePath $LlamaServerPath -ArgumentList ($argParts -join ' ') `
        -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
    @{pid=$process.Id; startedTicks=$process.StartTime.ToUniversalTime().Ticks; owner=$OwnerToken; model=$s.Model; port=$s.Port} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot "$($s.Name).process.json") -Encoding utf8
    Write-Host "Cargando $($s.Name): $($s.Device), contexto=$($s.Ctx), puerto=$($s.Port), PID=$($process.Id)..."

    $deadline = (Get-Date).AddMinutes(4)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $process.Refresh()
        if ($process.HasExited) { break }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$($s.Port)/health" -TimeoutSec 2 -ErrorAction Stop
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) {
        $process.Refresh()
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
        Write-Warning "$($s.Name) no llego a estado OK. Ultimas lineas de stderr:"
        if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Tail 35 }
        throw "No se pudo cargar $($s.Name). Revisa: $stderrPath"
    }
    Write-Host "$($s.Name) OK -> http://127.0.0.1:$($s.Port)"
}

Write-Host ''
Write-Host 'Modelos listos. Verifica:'
Write-Host '  8081,8082,8083 | ForEach-Object { Invoke-RestMethod "http://127.0.0.1:$_/health" }'
Write-Host '  python .\agentlab.py --help'
