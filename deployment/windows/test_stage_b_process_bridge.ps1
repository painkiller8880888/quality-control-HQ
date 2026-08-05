$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'stage_b_process_bridge.ps1')

function Assert-True($Value,[string]$Message){if(-not $Value){throw $Message}}
function Assert-BridgeThrows([scriptblock]$Action,[string]$Expected,[string]$Message){
  try {& $Action; throw "$Message did not throw"} catch {Assert-True ($_.Exception.Message -ceq $Expected) "$Message reason"}
}
function Write-PythonScript([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,[Text.UTF8Encoding]::new($false))}
function Wait-ForFile([string]$Path,[int]$Attempts=50){for($i=0;$i -lt $Attempts -and -not(Test-Path -LiteralPath $Path -PathType Leaf);$i++){Start-Sleep -Milliseconds 100}; Test-Path -LiteralPath $Path -PathType Leaf}

$root=Join-Path ([IO.Path]::GetTempPath()) ('stage-b bridge '+[guid]::NewGuid().ToString('n'))
New-Item -ItemType Directory -Path $root|Out-Null
$activeChild=$null
try {
  $markerPath=Join-Path $root 'request marker.json'
  $scriptPath=Join-Path $root 'bridge script with spaces.py'
  $markerLiteral=$markerPath.Replace('\','/')
  $resultJson='{"success":true,"exit_code":0,"size":1,"hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
  Write-PythonScript $scriptPath @"
import pathlib
import sys
request = sys.stdin.read()
pathlib.Path(r'$markerLiteral').write_text(request, encoding='utf-8')
sys.stdout.write('$resultJson\n')
"@
  $requestJson='{"sentinel":"stdin-value"}'
  $transport=Invoke-StageBProcessBridgeCli -RequestJson $requestJson -PythonExecutable 'python' -BridgeScriptPath $scriptPath -TimeoutSeconds 10
  Assert-True ($transport.exit_code -is [int] -and $transport.exit_code -eq 0) 'default invoker exit code'
  Assert-True ($transport.stdout -ceq ($resultJson+[Environment]::NewLine) -and $transport.stderr -ceq '') 'default invoker stdout/stderr'
  Assert-True ((Get-Content -Raw -Encoding UTF8 -LiteralPath $markerPath) -ceq $requestJson) 'default invoker stdin'

  $failScriptPath=Join-Path $root 'nonzero script with spaces.py'
  Write-PythonScript $failScriptPath @"
import sys
sys.stdin.read()
sys.exit(7)
"@
  $failedTransport=Invoke-StageBProcessBridgeCli -RequestJson $requestJson -PythonExecutable 'python' -BridgeScriptPath $failScriptPath -TimeoutSeconds 10
  Assert-True ($failedTransport.exit_code -is [int] -and $failedTransport.exit_code -eq 7 -and $failedTransport.stdout -ceq '') 'default invoker nonzero'

  $pidMarker=Join-Path $root 'child pid.txt'
  $doneMarker=Join-Path $root 'child completed.txt'
  $sleepScriptPath=Join-Path $root 'tree sleep script with spaces.py'
  $pidLiteral=$pidMarker.Replace('\','/')
  $doneLiteral=$doneMarker.Replace('\','/')
  $childCode="import pathlib,time; time.sleep(60); pathlib.Path(r'$doneLiteral').write_text('child-done', encoding='utf-8')"
  $sleepScript=@"
import pathlib
import subprocess
import sys
import time
child = subprocess.Popen([sys.executable, '-c', "$childCode"])
pathlib.Path(r'$pidLiteral').write_text(str(child.pid), encoding='ascii')
sys.stdin.read()
time.sleep(60)
"@
  Write-PythonScript $sleepScriptPath $sleepScript
  $artifactProvider={param($operation,$arguments,$environment) [pscustomobject]@{path=(Join-Path $root 'fresh.dump');timeout_seconds=[int]1}}.GetNewClosure()
  $callback=New-StageBProcessBridgeCallback $artifactProvider $null 'python' $sleepScriptPath 1
  $watch=[Diagnostics.Stopwatch]::StartNew()
  Assert-BridgeThrows {& $callback 'pg_dump' @('--format=custom','--no-owner','--no-acl') @{}} 'stage_b_operation_failed' 'default callback timeout'
  $watch.Stop()
  Assert-True ($watch.Elapsed.TotalSeconds -lt 8) 'transport timeout derives from request timeout'
  Assert-True (Wait-ForFile $pidMarker 20) 'timeout child pid marker'
  $activeChild=[int](Get-Content -Raw -Encoding UTF8 -LiteralPath $pidMarker)
  for($i=0;$i -lt 20;$i++){
    if($null -eq (Get-Process -Id $activeChild -ErrorAction SilentlyContinue)){break}
    Start-Sleep -Milliseconds 100
  }
  Assert-True ($null -eq (Get-Process -Id $activeChild -ErrorAction SilentlyContinue)) 'timeout kills process tree'
  Assert-True (-not(Test-Path -LiteralPath $doneMarker)) 'timeout child did not continue'
} finally {
  if($null -ne $activeChild){
    $remaining=Get-Process -Id $activeChild -ErrorAction SilentlyContinue
    if($null -ne $remaining){Stop-StageBProcessTree $remaining}
  }
  if(Test-Path -LiteralPath $root){Remove-Item -LiteralPath $root -Recurse -Force}
}
Write-Output 'Stage B process bridge default invoker tests passed'
