param(
  [string]$RuntimeDir = "$env:TEMP\\telegram_bot_new_runtime"
)

$ErrorActionPreference = "Stop"
$pidFile = Join-Path $RuntimeDir "pids.json"
if (-not (Test-Path $pidFile)) {
  Write-Output "pid file not found: $pidFile"
  exit 0
}

$raw = Get-Content $pidFile -Raw
if (-not $raw) {
  Write-Output "empty pid file: $pidFile"
  exit 0
}

$pids = $raw | ConvertFrom-Json
$targets = @($pids.mock_pid, $pids.mock_process_pid, $pids.bridge_pid) | Where-Object { $_ } | Select-Object -Unique
foreach ($id in $targets) {
  if ($id) {
    try {
      Stop-Process -Id ([int]$id) -Force -ErrorAction Stop
      Write-Output "stopped pid=$id"
    } catch {
      Write-Output "not running pid=$id"
    }
  }
}

$port = 9082
if ($pids.base_url -and ($pids.base_url -match ':(\d+)$')) {
  $port = [int]$matches[1]
}

$listeners = netstat -ano | Select-String -Pattern ":$port\s+.*LISTENING\s+(\d+)$"
foreach ($line in $listeners) {
  $listenerPid = [int]$line.Matches[0].Groups[1].Value
  try {
    Stop-Process -Id $listenerPid -Force -ErrorAction Stop
    Write-Output "stopped listener pid=$listenerPid (port=$port)"
  } catch {
    Write-Output "not running listener pid=$listenerPid (port=$port)"
  }
}

$pythonProcs = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq 'python.exe' -and (
    $_.CommandLine -match 'telegram_bot_new\.mock_messenger\.codex_bridge' -or
    ($_.CommandLine -match 'telegram_bot_new\.mock_messenger\.main' -and $_.CommandLine -match "--port $port")
  )
}
foreach ($proc in $pythonProcs) {
  try {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
    Write-Output "stopped process pid=$($proc.ProcessId)"
  } catch {
    Write-Output "not running process pid=$($proc.ProcessId)"
  }
}
