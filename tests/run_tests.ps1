$allSources = Get-ChildItem -Recurse -Path src -Filter *.cpp |
    ForEach-Object { $_.FullName }

Write-Host "Compiling backend smoke executable..."
g++ -std=c++17 $allSources -o allocation_system_smoke.exe
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Running backend smoke executable..."
try {
    & "$PSScriptRoot/test_backend_runtime.ps1" -ExecutablePath "$PWD/allocation_system_smoke.exe"
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
g++ -std=c++17 -I. -Isrc $sources $tests -o tests_runner.exe
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Running unit and integration tests..."
.\tests_runner.exe
exit $LASTEXITCODE
