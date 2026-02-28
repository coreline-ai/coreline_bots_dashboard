param(
  [string]$Host = "127.0.0.1",
  [int]$Port = 9082,
  [string]$DbPath = ".mock_messenger/mock_messenger.db",
  [string]$DataDir = ".mock_messenger",
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

$args = @(
  "-m", "telegram_bot_new.mock_messenger.main",
  "--host", $Host,
  "--port", "$Port",
  "--db-path", $DbPath,
  "--data-dir", $DataDir
)
if ($AllowGetUpdatesWithWebhook) {
  $args += "--allow-get-updates-with-webhook"
}

& $python @args
exit $LASTEXITCODE
