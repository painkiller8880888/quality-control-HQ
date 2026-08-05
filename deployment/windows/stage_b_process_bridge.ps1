Set-StrictMode -Version Latest

$script:StageBProcessBridgeOperations = @('pg_dump','pg_restore_list')
$script:StageBProcessBridgeTimeoutGraceSeconds = 30
$script:StageBProcessBridgeMaxTransportTimeoutSeconds = 3900

function Assert-StageBProcessBridgeOperation([object]$Operation) {
  if($Operation -isnot [System.String]){throw 'stage_b_bridge_request_invalid'}
  if($Operation -notin $script:StageBProcessBridgeOperations){throw 'stage_b_bridge_operation_unsupported'}
}

function Assert-StageBProcessBridgePropertySet($Object,[string[]]$Names) {
  if($null -eq $Object){throw 'stage_b_bridge_transport_invalid'}
  $actual=@($Object.psobject.Properties.Name|Sort-Object)
  $expected=@($Names|Sort-Object)
  if(($actual -join "`0") -cne ($expected -join "`0")){throw 'stage_b_bridge_transport_invalid'}
}

function ConvertTo-StageBWindowsCommandLineArgument([string]$Value) {
  if($null -eq $Value){throw 'stage_b_bridge_request_invalid'}
  if($Value.Length -eq 0){return '""'}
  $builder=New-Object Text.StringBuilder
  [void]$builder.Append('"')
  $slashes=0
  foreach($character in $Value.ToCharArray()){
    if($character -ceq '\'){$slashes++; continue}
    if($character -ceq '"'){
      for($i=0;$i -lt (2*$slashes+1);$i++){[void]$builder.Append('\')}
      [void]$builder.Append('"')
      $slashes=0
      continue
    }
    for($i=0;$i -lt $slashes;$i++){[void]$builder.Append('\')}
    $slashes=0
    [void]$builder.Append($character)
  }
  for($i=0;$i -lt (2*$slashes);$i++){[void]$builder.Append('\')}
  [void]$builder.Append('"')
  $builder.ToString()
}

function Stop-StageBProcessTree($Process) {
  if($null -eq $Process){return}
  try {if($Process.HasExited){return}} catch {}
  $killer=$null
  try {
    $killerInfo=[Diagnostics.ProcessStartInfo]::new()
    $systemRoot=[Environment]::GetEnvironmentVariable('SystemRoot')
    $taskkill=if($systemRoot){Join-Path $systemRoot 'System32\taskkill.exe'}else{'taskkill.exe'}
    $killerInfo.FileName=$taskkill
    $killerInfo.Arguments="/PID $([int]$Process.Id) /T /F"
    $killerInfo.UseShellExecute=$false
    $killerInfo.CreateNoWindow=$true
    $killerInfo.RedirectStandardOutput=$true
    $killerInfo.RedirectStandardError=$true
    $killer=[Diagnostics.Process]::Start($killerInfo)
    if($null -ne $killer){
      $killerExited=$killer.WaitForExit(5000)
      if($killerExited){$null=$killer.StandardOutput.ReadToEnd();$null=$killer.StandardError.ReadToEnd()}
      else {try {$killer.Kill()} catch {}; try {$null=$killer.WaitForExit(1000)} catch {}}
    }
  } catch {} finally {
    if($null -ne $killer){$killer.Dispose()}
  }
  try {
    if(-not $Process.HasExited){try {$Process.Kill()} catch {}; try {$null=$Process.WaitForExit(5000)} catch {}}
  } catch {}
}

function Get-StageBProcessBridgeTransportTimeout([string]$RequestJson,[int]$GraceSeconds=$script:StageBProcessBridgeTimeoutGraceSeconds) {
  try {
    if([string]::IsNullOrWhiteSpace($RequestJson) -or $GraceSeconds -lt 0 -or $GraceSeconds -gt 300){throw 'invalid timeout'}
    $request=$RequestJson|ConvertFrom-Json -ErrorAction Stop
    if($null -eq $request -or $request -is [System.Array] -or $null -eq $request.artifact){throw 'invalid timeout'}
    $value=$request.artifact.timeout_seconds
    if($value -is [System.Boolean] -or $value -isnot [System.Int32] -and $value -isnot [System.Int64]){throw 'invalid timeout'}
    if($value -lt 1 -or $value -gt 3600){throw 'invalid timeout'}
    $total=[int64]$value+[int64]$GraceSeconds
    if($total -lt 1 -or $total -gt $script:StageBProcessBridgeMaxTransportTimeoutSeconds){throw 'invalid timeout'}
    [int]$total
  } catch {throw 'stage_b_bridge_request_invalid'}
}

function Invoke-StageBProcessBridgeCli(
  [string]$RequestJson,
  [string]$PythonExecutable='python',
  [string]$BridgeScriptPath=(Join-Path $PSScriptRoot '..\postgresql\stage_b_process_bridge.py'),
  [int]$TimeoutSeconds=30
) {
  if([string]::IsNullOrWhiteSpace($RequestJson) -or [string]::IsNullOrWhiteSpace($PythonExecutable) -or [string]::IsNullOrWhiteSpace($BridgeScriptPath) -or $TimeoutSeconds -lt 1 -or $TimeoutSeconds -gt $script:StageBProcessBridgeMaxTransportTimeoutSeconds){
    return [pscustomobject]@{exit_code=[int]127;stdout='';stderr='stage_b_bridge_request_invalid'}
  }
  $process=$null
  $previousPythonUtf8=$null
  $previousPythonIoEncoding=$null
  try {
    $previousPythonUtf8=[Environment]::GetEnvironmentVariable('PYTHONUTF8','Process')
    $previousPythonIoEncoding=[Environment]::GetEnvironmentVariable('PYTHONIOENCODING','Process')
    [Environment]::SetEnvironmentVariable('PYTHONUTF8','1','Process')
    [Environment]::SetEnvironmentVariable('PYTHONIOENCODING','utf-8','Process')
    $startInfo=[Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName=$PythonExecutable
    $startInfo.Arguments=ConvertTo-StageBWindowsCommandLineArgument $BridgeScriptPath
    $startInfo.UseShellExecute=$false
    $startInfo.CreateNoWindow=$true
    $startInfo.RedirectStandardInput=$true
    $startInfo.RedirectStandardOutput=$true
    $startInfo.RedirectStandardError=$true
    $process=[Diagnostics.Process]::new()
    $process.StartInfo=$startInfo
    if(-not $process.Start()){throw 'spawn'}
    $inputBytes=[Text.Encoding]::UTF8.GetBytes($RequestJson)
    $inputStream=$process.StandardInput.BaseStream
    $inputStream.Write($inputBytes,0,$inputBytes.Length)
    $inputStream.Flush()
    $inputStream.Close()
    if(-not $process.WaitForExit($TimeoutSeconds*1000)){
      Stop-StageBProcessTree $process
      try {$null=$process.WaitForExit(5000)} catch {}
      return [pscustomobject]@{exit_code=[int]124;stdout='';stderr='stage_b_bridge_timeout'}
    }
    $stdout=$process.StandardOutput.ReadToEnd()
    $stderr=$process.StandardError.ReadToEnd()
    return [pscustomobject]@{exit_code=[int]$process.ExitCode;stdout=[string]$stdout;stderr=[string]$stderr}
  } catch {
    return [pscustomobject]@{exit_code=[int]127;stdout='';stderr='stage_b_bridge_spawn_failed'}
  } finally {
    if($null -ne $process){$process.Dispose()}
    try {
      [Environment]::SetEnvironmentVariable('PYTHONUTF8',$previousPythonUtf8,'Process')
      [Environment]::SetEnvironmentVariable('PYTHONIOENCODING',$previousPythonIoEncoding,'Process')
    } catch {}
  }
}

function ConvertFrom-StageBProcessBridgeTransport($Transport,[string]$Operation) {
  try {
    Assert-StageBProcessBridgePropertySet $Transport @('exit_code','stdout','stderr')
    if($Transport.exit_code -isnot [System.Int32] -or $Transport.stdout -isnot [System.String] -or $Transport.stderr -isnot [System.String]){throw 'stage_b_bridge_transport_invalid'}
    if($Transport.exit_code -ne 0 -or $Transport.stderr.Length -ne 0){throw 'stage_b_operation_failed'}
    if($Transport.stdout -notmatch '^\{(?s:.*)\}\r?\n?$'){throw 'stage_b_bridge_result_invalid'}
    $parsed=$Transport.stdout|ConvertFrom-Json -ErrorAction Stop
    if($null -eq $parsed -or $parsed -is [System.Array] -or $parsed -is [System.String] -or $parsed -is [System.ValueType]){throw 'stage_b_bridge_result_invalid'}
    Assert-StageBProcessBridgePropertySet $parsed @('success','exit_code','size','hash')
    if($parsed.success -isnot [System.Boolean] -or $parsed.exit_code -isnot [System.Int32] -and $parsed.exit_code -isnot [System.Int64] -or $parsed.size -isnot [System.Int32] -and $parsed.size -isnot [System.Int64] -or $parsed.hash -isnot [System.String]){throw 'stage_b_bridge_result_invalid'}
    if($parsed.exit_code -lt [int32]::MinValue -or $parsed.exit_code -gt [int32]::MaxValue -or $parsed.size -le 0 -or $parsed.size -gt [int64]::MaxValue -or $parsed.hash -cnotmatch '^[a-f0-9]{64}$' -or $parsed.success -ne $true -or $parsed.exit_code -ne 0){throw 'stage_b_bridge_result_invalid'}
    $result=[pscustomobject][ordered]@{success=[bool]$parsed.success;exit_code=[int]$parsed.exit_code;size=[int64]$parsed.size;hash=[string]$parsed.hash}
    if($Operation -ceq 'pg_dump' -and (Get-Command Assert-StageBPgDumpResult -ErrorAction SilentlyContinue)){Assert-StageBPgDumpResult $result}
    if($Operation -ceq 'pg_restore_list' -and (Get-Command Assert-StageBPgRestoreListResult -ErrorAction SilentlyContinue)){Assert-StageBPgRestoreListResult $result}
    $result
  } catch {
    throw 'stage_b_operation_failed'
  }
}

function New-StageBProcessBridgeCallback(
  [scriptblock]$ArtifactProvider,
  [scriptblock]$BridgeInvoker,
  [string]$PythonExecutable='python',
  [string]$BridgeScriptPath=(Join-Path $PSScriptRoot '..\postgresql\stage_b_process_bridge.py'),
  [int]$TimeoutGraceSeconds=$script:StageBProcessBridgeTimeoutGraceSeconds
) {
  if($null -eq $ArtifactProvider){throw 'stage_b_bridge_configuration_invalid'}
  if([string]::IsNullOrWhiteSpace($PythonExecutable) -or [string]::IsNullOrWhiteSpace($BridgeScriptPath) -or $TimeoutGraceSeconds -lt 0 -or $TimeoutGraceSeconds -gt 300){throw 'stage_b_bridge_configuration_invalid'}
  if($null -eq $BridgeInvoker){
    $defaultPythonExecutable=$PythonExecutable
    $defaultBridgeScriptPath=$BridgeScriptPath
    $defaultTimeoutGraceSeconds=$TimeoutGraceSeconds
    $BridgeInvoker={param($requestJson)
      $transportTimeout=Get-StageBProcessBridgeTransportTimeout $requestJson $defaultTimeoutGraceSeconds
      Invoke-StageBProcessBridgeCli -RequestJson $requestJson -PythonExecutable $defaultPythonExecutable -BridgeScriptPath $defaultBridgeScriptPath -TimeoutSeconds $transportTimeout
    }.GetNewClosure()
  }
  $artifactProvider=$ArtifactProvider
  $bridgeInvoker=$BridgeInvoker
  {
    param($operation,$arguments,$environment)
    try {
      Assert-StageBProcessBridgeOperation $operation
      $artifact=& $artifactProvider $operation $arguments $environment
      if($null -eq $artifact){throw 'stage_b_bridge_request_invalid'}
      $request=[ordered]@{operation=$operation;arguments=@($arguments);environment=$environment;artifact=$artifact}
      $requestJson=$request|ConvertTo-Json -Depth 10 -Compress
      $transport=& $bridgeInvoker $requestJson
      ConvertFrom-StageBProcessBridgeTransport $transport $operation
    } catch {
      if($_.Exception.Message -ceq 'stage_b_bridge_operation_unsupported'){throw 'stage_b_bridge_operation_unsupported'}
      throw 'stage_b_operation_failed'
    }
  }.GetNewClosure()
}
