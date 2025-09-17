#!/usr/bin/env pwsh
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Args
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Error "python3 is required to run flash_pi_media"
    exit 1
}

& $python.Path (Join-Path $scriptDir 'flash_pi_media.py') @Args
exit $LASTEXITCODE
