param(
  [string]$Token = "mock_token_1",
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 9082,
  [string]$Sandbox = "workspace-write",
  [string]$Model = "",
  [double]$HeartbeatSec = 3,
  [int]$RunTimeoutSec = 900,
  [string]$RuntimeDir = "$env:TEMP\\telegram_bot_new_runtime",
  [string]$VenvDir = ".venv"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path "$PSScriptRoot/..").Path
Set-Location $projectRoot

function Get-ListenerPid {
  param(
    [int]$TargetPort
  )
  $lines = netstat -ano | Select-String -Pattern ":$TargetPort\s+.*LISTENING\s+(\d+)$"
  foreach ($line in $lines) {
    $candidate = $line.Matches[0].Groups[1].Value
    if ($candidate -match '^\d+$') {
      return [int]$candidate
    }
  }
  return $null
}

function Stop-MockProcesses {
  param(
    [int]$TargetPort
  )
  $pythonProcs = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and (
      $_.CommandLine -match 'telegram_bot_new\.mock_messenger\.codex_bridge' -or
      ($_.CommandLine -match 'telegram_bot_new\.mock_messenger\.main' -and $_.CommandLine -match "--port $TargetPort")
    )
  }
  foreach ($proc in $pythonProcs) {
    try {
      Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
    } catch {}
  }
}

$python = "$projectRoot/$VenvDir/Scripts/python.exe"
if (-not (Test-Path $python)) {
  throw "venv python not found: $python`nRun .\\scripts\\bootstrap-local.ps1 first."
}

if (-not (Test-Path $RuntimeDir)) {
  New-Item -ItemType Directory -Path $RuntimeDir | Out-Null
}

$mockOut = Join-Path $RuntimeDir "mock_messenger.out.log"
$mockErr = Join-Path $RuntimeDir "mock_messenger.err.log"
$bridgeOut = Join-Path $RuntimeDir "codex_bridge.out.log"
$bridgeErr = Join-Path $RuntimeDir "codex_bridge.err.log"
$pidFile = Join-Path $RuntimeDir "pids.json"
$dbPath = Join-Path $RuntimeDir "mock_messenger.db"
$dataDir = Join-Path $RuntimeDir "mock_data"
if (-not (Test-Path $dataDir)) {
  New-Item -ItemType Directory -Path $dataDir | Out-Null
}

# stop previous listeners on the same port
Stop-MockProcesses -TargetPort $Port
$listeners = netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING\s+(\d+)$"
foreach ($line in $listeners) {
  $listenerPidToStop = [int]$line.Matches[0].Groups[1].Value
  try {
    Stop-Process -Id $listenerPidToStop -Force -ErrorAction Stop
  } catch {}
}

$mockArgs = @(
  "-m", "telegram_bot_new.mock_messenger.main",
  "--host", $BindHost,
  "--port", "$Port",
  "--db-path", $dbPath,
  "--data-dir", $dataDir
)
$mockProc = Start-Process -FilePath $python -ArgumentList $mockArgs -WorkingDirectory $projectRoot -PassThru -RedirectStandardOutput $mockOut -RedirectStandardError $mockErr

Start-Sleep -Seconds 1
$mockPid = $null
for ($i = 0; $i -lt 20; $i++) {
  $mockPid = Get-ListenerPid -TargetPort $Port
  if ($null -ne $mockPid) {
    break
  }
  Start-Sleep -Milliseconds 300
}
if ($null -eq $mockPid) {
  throw "mock messenger failed to bind on port $Port. check $mockErr"
}
$baseUrl = "http://$BindHost`:$Port"
$bridgeArgs = @(
  "-m", "telegram_bot_new.mock_messenger.codex_bridge",
  "--base-url", $baseUrl,
  "--token", $Token,
  "--sandbox", $Sandbox,
  "--heartbeat-sec", "$HeartbeatSec",
  "--run-timeout-sec", "$RunTimeoutSec"
)
if ($Model -and -not [string]::IsNullOrWhiteSpace($Model)) {
  $bridgeArgs += @("--model", $Model)
}
$bridgeProc = Start-Process -FilePath $python -ArgumentList $bridgeArgs -WorkingDirectory $projectRoot -PassThru -RedirectStandardOutput $bridgeOut -RedirectStandardError $bridgeErr

Start-Sleep -Seconds 1
if ($bridgeProc.HasExited) {
  throw "codex bridge exited immediately. check $bridgeErr"
}
$health = $null
$healthOk = $false
for ($i = 0; $i -lt 20; $i++) {
  try {
    $health = Invoke-RestMethod -Uri "$baseUrl/healthz" -Method Get -TimeoutSec 3
    $healthOk = $true
    break
  } catch {
    Start-Sleep -Milliseconds 300
  }
}
if (-not $healthOk) {
  throw "mock messenger health check failed at $baseUrl/healthz. check $mockErr"
}

@{
  mock_pid = $mockPid
  mock_process_pid = $mockProc.Id
  bridge_pid = $bridgeProc.Id
  token = $Token
  base_url = $baseUrl
  sandbox = $Sandbox
  model = if ($Model) { $Model } else { $null }
  heartbeat_sec = $HeartbeatSec
  run_timeout_sec = $RunTimeoutSec
  ui_url = "$baseUrl/_mock/ui"
  ui_url_with_token = "$baseUrl/_mock/ui?token=$Token&chat_id=1001&user_id=9001"
  health = $health
  logs = @{
    mock_out = $mockOut
    mock_err = $mockErr
    bridge_out = $bridgeOut
    bridge_err = $bridgeErr
  }
} | ConvertTo-Json -Depth 6 | Set-Content -Path $pidFile -Encoding utf8

Get-Content $pidFile
