param(
  [string]$Config = "config/bots.yaml",
  [string]$MockHost = "127.0.0.1",
  [int]$MockPort = 9082,
  [string]$MockDbPath = ".mock_messenger/mock_messenger.db",
  [string]$MockDataDir = ".mock_messenger",
  [switch]$AllowGetUpdatesWithWebhook,
  [string]$VenvDir = ".venv"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path "$PSScriptRoot/..").Path
Set-Location $projectRoot

$python = "$projectRoot/$VenvDir/Scripts/python.exe"
if (-not (Test-Path $python)) {
  throw "venv python not found: $python`nRun .\\scripts\\bootstrap-local.ps1 first."
}

$mockArgs = @(
  "-m", "telegram_bot_new.mock_messenger.main",
  "--host", $MockHost,
  "--port", "$MockPort",
  "--db-path", $MockDbPath,
  "--data-dir", $MockDataDir
)
if ($AllowGetUpdatesWithWebhook) {
  $mockArgs += "--allow-get-updates-with-webhook"
}

$mockProcess = Start-Process -FilePath $python -ArgumentList $mockArgs -PassThru
Start-Sleep -Seconds 1

$env:TELEGRAM_API_BASE_URL = "http://$MockHost`:$MockPort"
if (-not $env:TELEGRAM_VIRTUAL_TOKEN -or [string]::IsNullOrWhiteSpace($env:TELEGRAM_VIRTUAL_TOKEN)) {
  $env:TELEGRAM_VIRTUAL_TOKEN = "mock_token_1"
}
Write-Host "Mock messenger started at $($env:TELEGRAM_API_BASE_URL) (pid=$($mockProcess.Id))"
Write-Host "Virtual token for simulator: $($env:TELEGRAM_VIRTUAL_TOKEN)"

try {
  & "$PSScriptRoot/run-local.ps1" -Mode supervisor -Config $Config -VenvDir $VenvDir
}
finally {
  if (-not $mockProcess.HasExited) {
    Stop-Process -Id $mockProcess.Id -Force -ErrorAction SilentlyContinue
  }
}
