param([switch]$SelfTest)
$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$builder = $null
if (Test-Path -LiteralPath $vswhere) {
    $builder = & $vswhere -latest -products '*' -requires Microsoft.Component.MSBuild -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
}
if (-not $builder) {
    $command = Get-Command MSBuild.exe -ErrorAction SilentlyContinue
    if ($command) { $builder = $command.Source }
}
if (-not $builder) { throw 'Instala Visual Studio 2019 o posterior con Desarrollo de escritorio de .NET. Después vuelve a ejecutar Build-Desktop.ps1.' }
$solution = Join-Path $PSScriptRoot 'desktop\AgentLab.Desktop.sln'
& $builder $solution /restore /t:Build /p:Configuration=Release /nologo /verbosity:minimal
if ($LASTEXITCODE -ne 0) { throw 'No se pudo compilar la interfaz. Consulta la salida anterior.' }
$application = Join-Path $PSScriptRoot 'desktop\AgentLab.Desktop\bin\Release\AgentLab.Desktop.exe'
if ($SelfTest) {
    $logDirectory = Join-Path $PSScriptRoot 'work'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $report = Join-Path $logDirectory 'desktop-self-test.txt'
    $selfTestConfig = Join-Path $logDirectory 'desktop-test-config.json'
    # An absent test configuration exercises first-run without reading user paths.
    $arguments = @('--root', ('"' + $PSScriptRoot + '"'), '--config', ('"' + $selfTestConfig + '"'), '--self-test', '--report', ('"' + $report + '"'))
    $test = Start-Process -FilePath $application -ArgumentList $arguments -WindowStyle Hidden -PassThru
    if (-not $test.WaitForExit(60000)) { $test.Kill(); throw 'La prueba sin ventanas agotó el tiempo.' }
    if (Test-Path -LiteralPath $report) { Get-Content -LiteralPath $report }
    if ($test.ExitCode -ne 0) { throw "La prueba de escritorio falló: $($test.ExitCode)" }
}
Write-Host "Compilado: $application"
