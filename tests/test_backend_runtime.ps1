param(
    [Parameter(Mandatory = $true)]
    [string]$ExecutablePath
)

$ErrorActionPreference = 'Stop'
$executable = (Resolve-Path -LiteralPath $ExecutablePath).Path
$projectRoot = Split-Path -Parent $PSScriptRoot
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$workspace = Join-Path $tempRoot ("resource-allocation-runtime-" + [guid]::NewGuid().ToString('N'))
$inputs = @('users.csv', 'spaces.csv', 'requests.csv', 'user_busy_slots.csv', 'request_participants.csv', 'config.txt')
$outputs = @('allocations.csv', 'request_results.csv', 'request_summaries.csv', 'allocation_summaries.csv')

function Invoke-RuntimeSmoke([string]$inputDirectory, [string]$caseName, [bool]$checkCleanSlot) {
    $caseDirectory = Join-Path $workspace $caseName
    $dataDirectory = Join-Path $caseDirectory 'data'
    New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
    foreach ($inputFile in $inputs) {
        Copy-Item -LiteralPath (Join-Path $inputDirectory $inputFile) -Destination $dataDirectory
    }

    Push-Location $caseDirectory
    try {
        & $executable > (Join-Path $caseDirectory 'backend.log')
        if ($LASTEXITCODE -ne 0) {
            throw "Backend smoke '$caseName' failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }

    foreach ($output in $outputs) {
        $path = Join-Path $dataDirectory $output
        if (!(Test-Path -LiteralPath $path) -or (Get-Item -LiteralPath $path).Length -eq 0) {
            throw "Backend smoke '$caseName' did not generate $output."
        }
    }

    $requestIds = @(Import-Csv -LiteralPath (Join-Path $dataDirectory 'requests.csv') | ForEach-Object { $_.requestId })
    $allocations = @(Import-Csv -LiteralPath (Join-Path $dataDirectory 'allocations.csv'))
    $allocationSummaries = @(Import-Csv -LiteralPath (Join-Path $dataDirectory 'allocation_summaries.csv'))
    foreach ($allocation in @($allocations) + @($allocationSummaries)) {
        if ($allocation.requestId -notin $requestIds) {
            throw "Backend smoke '$caseName' injected unexplained request $($allocation.requestId)."
        }
    }

    if ($checkCleanSlot) {
        $results = @(Import-Csv -LiteralPath (Join-Path $dataDirectory 'request_results.csv'))
        $summaries = @(Import-Csv -LiteralPath (Join-Path $dataDirectory 'request_summaries.csv'))
        if ($results.Count -ne 1 -or $results[0].requestId -ne '1' -or $results[0].status -ne 'Approved' -or
            $summaries.Count -ne 1 -or $summaries[0].requestId -ne '1' -or $summaries[0].status -ne 'Approved') {
            throw 'The clean Monday 10:00-12:00 request was not approved consistently.'
        }
        if ($allocations.Count -ne 1 -or $allocations[0].allocationId -ne '1' -or
            $allocations[0].spaceId -ne '101' -or $allocations[0].day -ne '1' -or
            $allocations[0].startHour -ne '10:00' -or $allocations[0].endHour -ne '12:00' -or
            $allocations[0].assignedParticipants -ne '5') {
            throw 'The clean run contains an unexpected allocation or blocked slot.'
        }
    }
    Write-Host "PASS: backend runtime smoke '$caseName' (no injected bookings)."
}

try {
    Invoke-RuntimeSmoke (Join-Path $PSScriptRoot 'fixtures/runtime_no_demo') 'clean-slot' $true
    Invoke-RuntimeSmoke (Join-Path $projectRoot 'data') 'normal-dataset' $false
} finally {
    # Delete only the unique temporary workspace created by this invocation.
    $resolvedWorkspace = [System.IO.Path]::GetFullPath($workspace)
    $allowedPrefix = Join-Path $tempRoot 'resource-allocation-runtime-'
    if (!$resolvedWorkspace.StartsWith($allowedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Refusing to remove a workspace outside the runtime smoke temporary directory.'
    }
    if (Test-Path -LiteralPath $resolvedWorkspace) {
        Remove-Item -LiteralPath $resolvedWorkspace -Recurse -Force
    }
}
