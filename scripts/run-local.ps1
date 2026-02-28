param(
  [ValidateSet("supervisor", "run-bot", "run-gateway")]
  [string]$Mode = "supervisor",
  [string]$Config = "config/bots.yaml",
  [string]$BotId = "bot-1",
  [string]$EmbeddedHost = "127.0.0.1",
  [int]$EmbeddedBasePort = 8600,
  [int]$EmbeddedPort = 8600,
  [string]$GatewayHost = "0.0.0.0",
  [int]$GatewayPort = 4312,
  [string]$VenvDir = ".venv"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path "$PSScriptRoot/..").Path
Set-Location $projectRoot

$python = "$projectRoot/$VenvDir/Scripts/python.exe"
if (-not (Test-Path $python)) {
  throw "venv python not found: $python`nRun .\\scripts\\bootstrap-local.ps1 first."
}

if (-not (Test-Path $Config)) {
  Write-Host "bots config not found: $Config"
  Write-Host "falling back to env token mode (TELEGRAM_BOT_TOKEN)."
}

$envPath = "$projectRoot/.env"
if (Test-Path $envPath) {
  $tokenLine = Get-Content $envPath | Where-Object { $_ -match '^TELEGRAM_BOT_TOKEN=' } | Select-Object -First 1
  if ($null -eq $tokenLine -or $tokenLine -match '^TELEGRAM_BOT_TOKEN=\s*$') {
    Write-Host "warning: TELEGRAM_BOT_TOKEN is empty in .env"
  }
}

if ($Mode -eq "supervisor") {
  & $python -m telegram_bot_new.main supervisor --config $Config --embedded-host $EmbeddedHost --embedded-base-port $EmbeddedBasePort --gateway-host $GatewayHost --gateway-port $GatewayPort
  exit $LASTEXITCODE
}

if ($Mode -eq "run-gateway") {
  & $python -m telegram_bot_new.main run-gateway --config $Config --host $GatewayHost --port $GatewayPort
  exit $LASTEXITCODE
}

& $python -m telegram_bot_new.main run-bot --config $Config --bot-id $BotId --embedded-host $EmbeddedHost --embedded-port $EmbeddedPort
exit $LASTEXITCODE
