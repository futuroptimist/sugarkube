#!/usr/bin/env pwsh

Write-Warning "[DEPRECATED] scripts/docs_verify.ps1 will be removed once callers migrate to 'python -m sugarkube_toolkit docs verify'."
Write-Host "Forwarding to the unified CLI—update your workflow to call it directly." -ForegroundColor Yellow

$python = $env:SUGARKUBE_PYTHON
if (-not $python) {
    if (Get-Command python3 -ErrorAction SilentlyContinue) {
        $python = "python3"
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $python = "python"
    } else {
        Write-Error "Unable to find a Python interpreter for sugarkube_toolkit."
        exit 1
    }
}

& $python -m sugarkube_toolkit docs verify @args
exit $LASTEXITCODE
