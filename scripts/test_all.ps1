# One-shot gate for absolute-trading-bot-final (no exchange orders).
# bot_gate + pytest. Does not enable SPOT_ENTRIES / live.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Assert-NativeExit([string]$Step) {
  if ($null -eq $LASTEXITCODE -or $LASTEXITCODE -ne 0) {
    Write-Host "FAIL $Step exit=$LASTEXITCODE"
    exit $(if ($null -eq $LASTEXITCODE) { 1 } else { $LASTEXITCODE })
  }
}

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "== bot_gate =="
& $py "$Root\scripts\bot_gate.py"
Assert-NativeExit "bot_gate"

Write-Host "== pytest =="
& $py -m pytest tests/ -q
Assert-NativeExit "pytest"

Write-Host "RESULT: PASS test_all (entries stay off — see docs/PROTOCOL_STATUS.md)"
exit 0
