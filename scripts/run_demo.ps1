[CmdletBinding()]
param(
    [ValidatePattern('^[a-z][a-z0-9-]{0,40}$')][string]$Profile = 'university-demo',
    [string]$PythonPath,
    [string]$CompilerPath,
    [string]$PostgresBin,
    [int]$Seed,
    [string]$AcademicStart,
    [string]$AcademicEnd,
    [ValidateRange(1,65535)][int]$PostgresPort,
    [ValidateRange(1,65535)][int]$WebPort = 5000,
    [switch]$SetupOnly,
    [switch]$ServiceExamples
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$directory = Join-Path $root "build\local-demos\$Profile"
$previousLocation = Get-Location
$names = @('PATH','DATABASE_URL','PGPASSWORD','RESOURCE_ALLOCATION_SECRET_KEY','RESOURCE_ALLOCATION_TIMEZONE',
           'RESOURCE_ALLOCATION_BACKEND','RESOURCE_ALLOCATION_DEBUG','RESOURCE_ALLOCATION_SECURE_COOKIE','FLASK_DEBUG')
$previousEnvironment = @{}
foreach ($name in $names) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$lock = $null

function Find-Tool($explicit, $candidates, $description) {
    if ($explicit) { $candidates = @($explicit) }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    throw "$description was not found. Supply its path using the launcher parameters; no system installation or database reset was attempted."
}

function Invoke-Checked($program, $arguments) {
    & $program @arguments
    if ($LASTEXITCODE -ne 0) { throw "Setup command failed (exit $LASTEXITCODE). Existing data was not reset." }
}

try {
    Set-Location -LiteralPath $root
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    Invoke-Checked 'icacls.exe' @($directory, '/inheritance:r', '/grant:r', "${identity}:(OI)(CI)F", 'SYSTEM:(OI)(CI)F')
    try { $lock = [IO.File]::Open((Join-Path $directory 'launcher.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw 'This demo profile is already being prepared or served. Close its other launcher before retrying.' }
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    $python = Find-Tool $PythonPath @((Join-Path $root 'build\postgresql-venv\Scripts\python.exe'),
        (Join-Path $root '.venv\Scripts\python.exe'), $(if ($pythonCommand) { $pythonCommand.Source })) 'Python 3.12 or 3.13'
    Invoke-Checked $python @('-c', 'import sys; assert (3,12) <= sys.version_info[:2] <= (3,13), "Python 3.12 or 3.13 required"')
    $compilerCommand = Get-Command g++.exe -ErrorAction SilentlyContinue
    $compiler = Find-Tool $CompilerPath @($(if ($compilerCommand) { $compilerCommand.Source }),
        (Join-Path $env:USERPROFILE '.local\opt\gcc-14.3.0\bin\g++.exe')) 'C++17 g++ compiler'
    $pgCommand = Get-Command pg_ctl.exe -ErrorAction SilentlyContinue
    $pgControl = Find-Tool $(if ($PostgresBin) { Join-Path $PostgresBin 'pg_ctl.exe' }) @(
        (Join-Path $root 'build\postgresql-runtime\pgsql\bin\pg_ctl.exe'),
        $(if ($pgCommand) { $pgCommand.Source }), (Join-Path $env:ProgramFiles 'PostgreSQL\17\bin\pg_ctl.exe')) 'PostgreSQL 17 tools'
    $PostgresBin = Split-Path -Parent $pgControl
    $env:PATH = (Split-Path -Parent $compiler) + ';' + $PostgresBin + ';' + $env:PATH
    $demoPython = Join-Path $directory 'venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $demoPython)) { Invoke-Checked $python @('-m', 'venv', (Join-Path $directory 'venv')) }
    Invoke-Checked $demoPython @('-m', 'pip', 'install', '-r', (Join-Path $root 'requirements.txt'))
    $prepare = @('scripts/setup_local_demo.py', '--state-dir', $directory, 'prepare')
    foreach ($option in @(@('Seed','--seed'), @('AcademicStart','--start'), @('AcademicEnd','--end'), @('PostgresPort','--port'))) {
        if ($PSBoundParameters.ContainsKey($option[0])) { $prepare += @($option[1], [string](Get-Variable -Name $option[0] -ValueOnly)) }
    }
    Invoke-Checked $demoPython $prepare
    $settings = Get-Content -LiteralPath (Join-Path $directory 'settings.json') -Raw | ConvertFrom-Json
    $data = Join-Path $directory 'postgres-data'
    $marker = Join-Path $data 'local-demo-owner'
    if (Test-Path -LiteralPath $data) {
        if (-not (Test-Path -LiteralPath $marker) -or (Get-Content -LiteralPath $marker -Raw) -ne $settings.profileId) {
            throw 'PostgreSQL data directory is not owned by this demo. It was not started, migrated or changed.'
        }
    } else {
        $passwordFile = [IO.Path]::GetTempFileName()
        try {
            [IO.File]::WriteAllText($passwordFile, $settings.postgresPassword)
            Invoke-Checked (Join-Path $PostgresBin 'initdb.exe') @('-D', $data, '-U', $settings.postgresUser,
                '--encoding=UTF8', '--auth-local=scram-sha-256', '--auth-host=scram-sha-256', "--pwfile=$passwordFile")
            [IO.File]::WriteAllText($marker, $settings.profileId)
        } finally { Remove-Item -LiteralPath $passwordFile }
    }
    & $pgControl -D $data status *> $null
    if ($LASTEXITCODE -ne 0) {
        Invoke-Checked $pgControl @('-D', $data, '-l', (Join-Path $directory 'postgres.log'),
            '-o', "-p $($settings.postgresPort) -h 127.0.0.1", '-w', 'start')
    }
    $env:PGPASSWORD = $settings.postgresPassword
    $pgArgs = @('-h', '127.0.0.1', '-p', [string]$settings.postgresPort, '-U', $settings.postgresUser)
    # The Python settings validator restricts databaseName to supported literal names.
    $exists = & (Join-Path $PostgresBin 'psql.exe') @pgArgs -X -t -A -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$($settings.databaseName)'"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot connect to the owned demo PostgreSQL server.' }
    if ($exists -ne '1') { Invoke-Checked (Join-Path $PostgresBin 'createdb.exe') ($pgArgs + @($settings.databaseName)) }
    $env:DATABASE_URL = "postgresql+psycopg://$($settings.postgresUser):$($settings.postgresPassword)@127.0.0.1:$($settings.postgresPort)/$($settings.databaseName)"
    $env:RESOURCE_ALLOCATION_SECRET_KEY = $settings.sessionSecret
    $env:RESOURCE_ALLOCATION_TIMEZONE = 'Europe/Istanbul'
    $env:RESOURCE_ALLOCATION_SECURE_COOKIE = '0'
    $env:RESOURCE_ALLOCATION_DEBUG = '0'
    $env:FLASK_DEBUG = '0'
    $env:RESOURCE_ALLOCATION_BACKEND = Join-Path $root 'build\backend\allocation_system.exe'
    Invoke-Checked $demoPython @('-m', 'alembic', 'upgrade', 'head')
    & $demoPython -c 'from pathlib import Path; from web.backend_executable import resolve_backend_executable; resolve_backend_executable(Path.cwd())' 2>$null
    if ($LASTEXITCODE -ne 0) { Invoke-Checked $demoPython @('scripts/build_backend.py', '--compiler', $compiler) }
    Invoke-Checked $demoPython @('scripts/setup_local_demo.py', '--state-dir', $directory, 'seed')
    if ($ServiceExamples) {
        Invoke-Checked $demoPython @('scripts/seed_service_examples.py', '--state-dir', $directory)
    }
    Invoke-Checked $demoPython @('scripts/setup_local_demo.py', '--state-dir', $directory, 'show')
    if ($SetupOnly) {
        Write-Host 'Demo prepared. Rerun without -SetupOnly to start the website.'
    } else {
        Write-Host "Open http://127.0.0.1:$WebPort . Demo files are private under $directory ."
        Write-Host 'Keep this window open. Ctrl+C stops Flask; rerun this command to resume without resetting data.'
        & $demoPython -m flask --app web.app run --host 127.0.0.1 --port $WebPort
        if ($LASTEXITCODE -ne 0) { throw 'Flask did not run successfully. Check the error above; use another -WebPort if occupied.' }
    }
} finally {
    if ($lock) { $lock.Dispose() }
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process') }
    Set-Location -LiteralPath $previousLocation.Path
}
