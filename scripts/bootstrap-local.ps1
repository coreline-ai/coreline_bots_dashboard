param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot/..").Path,
  [string]$VenvDir = ".venv"
)

$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot

if (-not (Test-Path "$ProjectRoot/$VenvDir")) {
  python -m venv $VenvDir
}

$python = "$ProjectRoot/$VenvDir/Scripts/python.exe"
if (-not (Test-Path $python)) {
  throw "python not found in venv: $python"
}

& $python -m pip install --upgrade pip
& $python -m pip install -e ".[dev]"

if (-not (Test-Path "$ProjectRoot/.env")) {
  Copy-Item "$ProjectRoot/.env.example" "$ProjectRoot/.env"
}

if (-not (Test-Path "$ProjectRoot/config/bots.yaml")) {
  @"
bots:
  - telegram_token: TELEGRAM_BOT_TOKEN
"@ | Set-Content -Path "$ProjectRoot/config/bots.yaml" -Encoding utf8
}

Write-Host "Bootstrap complete"
Write-Host "- Edit $ProjectRoot/.env"
Write-Host "- Edit $ProjectRoot/config/bots.yaml"
Write-Host "- Run: .\\scripts\\run-local.ps1 -Mode supervisor"
Write-Host "- Or run with local mock messenger: .\\scripts\\run-local-with-mock.ps1"
