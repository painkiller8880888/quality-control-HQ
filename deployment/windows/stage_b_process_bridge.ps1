Set-StrictMode -Version Latest

$script:StageBProcessBridgeOperations = @('pg_dump','pg_restore_list')

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

function Invoke-StageBProcessBridgeCli(
  [string]$RequestJson,
  [string]$PythonExecutable='python',
  [string]$BridgeScriptPath=(Join-Path $PSScriptRoot '..\postgresql\stage_b_process_bridge.py'),
  [int]$TimeoutSeconds=30
) {
  if([string]::IsNullOrWhiteSpace($RequestJson) -or [string]::IsNullOrWhiteSpace($PythonExecutable) -or [string]::IsNullOrWhiteSpace($BridgeScriptPath) -or $TimeoutSeconds -lt 1 -or $TimeoutSeconds -gt 300){
    return [pscustomobject]@{exit_code=[int]127;stdout='';stderr='stage_b_bridge_request_invalid'}
  }
  $process=$null
  try {
    $startInfo=[Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName=$PythonExecutable
    $null=$startInfo.ArgumentList.Add($BridgeScriptPath)
    $startInfo.UseShellExecute=$false
    $startInfo.CreateNoWindow=$true
    $startInfo.RedirectStandardInput=$true
    $startInfo.RedirectStandardOutput=$true
    $startInfo.RedirectStandardError=$true
    $startInfo.StandardInputEncoding=[Text.Encoding]::UTF8
    $startInfo.StandardOutputEncoding=[Text.Encoding]::UTF8
    $startInfo.StandardErrorEncoding=[Text.Encoding]::UTF8
    $process=[Diagnostics.Process]::new()
    $process.StartInfo=$startInfo
    if(-not $process.Start()){throw 'spawn'}
    $process.StandardInput.Write($RequestJson)
    $process.StandardInput.Close()
    if(-not $process.WaitForExit($TimeoutSeconds*1000)){
      try {$process.Kill()} catch {}
      return [pscustomobject]@{exit_code=[int]124;stdout='';stderr='stage_b_bridge_timeout'}
    }
    $stdout=$process.StandardOutput.ReadToEnd()
    $stderr=$process.StandardError.ReadToEnd()
    return [pscustomobject]@{exit_code=[int]$process.ExitCode;stdout=[string]$stdout;stderr=[string]$stderr}
  } catch {
    return [pscustomobject]@{exit_code=[int]127;stdout='';stderr='stage_b_bridge_spawn_failed'}
  } finally {
    if($null -ne $process){$process.Dispose()}
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

function New-StageBProcessBridgeCallback([scriptblock]$ArtifactProvider,[scriptblock]$BridgeInvoker) {
  if($null -eq $ArtifactProvider){throw 'stage_b_bridge_configuration_invalid'}
  if($null -eq $BridgeInvoker){$BridgeInvoker={param($requestJson) Invoke-StageBProcessBridgeCli $requestJson}}
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
