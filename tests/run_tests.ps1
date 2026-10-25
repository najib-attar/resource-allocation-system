$temporaryRoot = (Resolve-Path -LiteralPath ([IO.Path]::GetTempPath())).Path.TrimEnd('\')
$temporaryDirectory = (New-Item -ItemType Directory -Path (Join-Path $temporaryRoot ("ras-cpp-tests-" + [Guid]::NewGuid().ToString('N')))).FullName
$exitCode = 1
try {
    $smokeExecutable = Join-Path $temporaryDirectory 'allocation_system_smoke.exe'
    $testRunner = Join-Path $temporaryDirectory 'tests_runner.exe'
    $allSources = Get-ChildItem -Recurse -Path src -Filter *.cpp |
        ForEach-Object { $_.FullName }

    Write-Host "Compiling backend smoke executable..."
    g++ -std=c++17 $allSources -o $smokeExecutable
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    Write-Host "Running backend smoke executable..."
    try {
        & "$PSScriptRoot/test_backend_runtime.ps1" -ExecutablePath $smokeExecutable
    } catch {
        Write-Error $_
        exit 1
    }

    $sources = Get-ChildItem -Recurse -Path src -Filter *.cpp |
        Where-Object { $_.Name -ne 'main.cpp' } |
        ForEach-Object { $_.FullName }
    $tests = Get-ChildItem -Path tests -Filter *.cpp |
        ForEach-Object { $_.FullName }

    Write-Host "Compiling test runner..."
    g++ -std=c++17 -I. -Isrc $sources $tests -o $testRunner
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    Write-Host "Running unit and integration tests..."
    & $testRunner
    $exitCode = $LASTEXITCODE
} finally {
    # Delete only this invocation's owned directory, including partial compiles.
    $resolved = (Resolve-Path -LiteralPath $temporaryDirectory).Path
    if ([IO.Path]::GetDirectoryName($resolved) -ne $temporaryRoot -or
        [IO.Path]::GetFileName($resolved) -notmatch '^ras-cpp-tests-[0-9a-f]{32}$') {
        throw 'Refusing to clean an unexpected test directory.'
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction Stop
}
exit $exitCode
