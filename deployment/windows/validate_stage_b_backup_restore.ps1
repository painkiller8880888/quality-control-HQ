[CmdletBinding()]
param([switch]$PlanOnly,[switch]$Execute,[switch]$Cleanup,[string]$ApprovalPath,[string]$PendingManifestPath,[string]$EvidenceRoot)
$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest

function Get-StageBSha256([string]$Path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() }
function Get-StageBTextHash([object]$Value) { $sha=[Security.Cryptography.SHA256]::Create(); try {([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$Value)))).Replace('-','').ToLowerInvariant()} finally {$sha.Dispose()} }
function Test-StageBHash([object]$Value) { $Value -is [string] -and $Value -cmatch '^[a-f0-9]{64}$' }
function Test-StageBIdentifier([string]$Value) { $Value -cmatch '^[a-z][a-z0-9_]{0,62}$' }
function Normalize-StageBHost([string]$Value) { $v=$Value.Trim().ToLowerInvariant().TrimEnd('.'); if(-not $v -or $v -match '[\s:/@\\]'){throw 'invalid protected host'}; $v }
function Normalize-StageBPort([string]$Value) { if($Value -notmatch '^\d+$'){throw 'invalid protected port'}; $p=[int]$Value; if($p -lt 1 -or $p -gt 65535){throw 'invalid protected port'}; $p.ToString([Globalization.CultureInfo]::InvariantCulture) }
function ConvertTo-StageBCanonicalJson($Value) { $Value | ConvertTo-Json -Depth 32 -Compress }
function Write-StageBAtomicJson([string]$Path,$Value) { $tmp="$Path.$([guid]::NewGuid().ToString('n')).tmp"; try {[IO.File]::WriteAllText($tmp,(ConvertTo-StageBCanonicalJson $Value)+"`n",[Text.UTF8Encoding]::new($false)); Move-Item -LiteralPath $tmp -Destination $Path -Force} finally {if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force}} }
function Test-StageBUtcTimestamp([object]$Value) { try {$x=[DateTimeOffset]::Parse([string]$Value,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::RoundtripKind); $x.Offset -eq [TimeSpan]::Zero} catch {$false} }
function Assert-StageBPropertySet($Object,[string[]]$Names) { if($null -eq $Object){throw 'strict schema mismatch'}; $actual=@($Object.psobject.Properties.Name|Sort-Object); $expected=@($Names|Sort-Object); if(($actual -join "`0") -cne ($expected -join "`0")){throw 'strict schema mismatch'} }
function Assert-StageBHashFields($Value,[string[]]$Names) { Assert-StageBPropertySet $Value $Names; foreach($n in $Names){if(-not(Test-StageBHash $Value.$n)){throw 'invalid identity hash'}} }
function Assert-StageBNoProtectedTarget($Target,$Protected) { foreach($item in $Protected){if($Target.endpoint_hash -ceq $item.endpoint_hash -and $Target.database_hash -ceq $item.database_hash){throw 'protected target rejected'}; if($Target.oid_hash -ceq $item.oid_hash){throw 'protected OID rejected'}} }
function Get-StageBRedactedError([object]$ErrorRecord) { 'stage_b_operation_failed' }
function Test-StageBConstantTimeBytes([byte[]]$Left,[byte[]]$Right) { if($Left.Length -ne $Right.Length){return $false}; [int]$different=0; for($i=0;$i -lt $Left.Length;$i++){$different=$different -bor ($Left[$i] -bxor $Right[$i])}; $different -eq 0 }
function Test-StageBApproval($Approval,[string]$ManifestHash,[string]$Action) {
  Assert-StageBPropertySet $Approval @('scope','action','manifest_sha256','approved_at','approver_hash')
  if($Approval.scope -cne 'stage-b-backup-restore' -or $Approval.action -cne $Action -or -not(Test-StageBHash $Approval.manifest_sha256) -or -not(Test-StageBHash $Approval.approver_hash) -or -not(Test-StageBUtcTimestamp $Approval.approved_at)){throw 'invalid approval'}
  if(-not(Test-StageBConstantTimeBytes ([Text.Encoding]::UTF8.GetBytes($Approval.manifest_sha256)) ([Text.Encoding]::UTF8.GetBytes($ManifestHash)))){throw 'approval does not name exact manifest'}
  $at=[DateTimeOffset]::Parse($Approval.approved_at).ToUniversalTime(); $now=[DateTimeOffset]::UtcNow; if($at -lt $now.AddHours(-24) -or $at -gt $now.AddMinutes(5)){throw 'approval time invalid'}
}
function Test-StageBManifest($Manifest) {
  Assert-StageBPropertySet $Manifest @('schema_version','run_id','scope','live_blocked','criterion_8','created_at','expires_at','source','restore','protected','source_baseline_hash','clients','storage','owners','services','execution_state')
  if($Manifest.schema_version -ne 1 -or $Manifest.run_id -notmatch '^[a-z0-9][a-z0-9_-]{2,63}$' -or $Manifest.scope -cne 'stage-b-backup-restore' -or $Manifest.live_blocked -ne $true -or $Manifest.criterion_8 -cne 'not_evaluable' -or $Manifest.execution_state -cne 'pending' -or -not(Test-StageBHash $Manifest.source_baseline_hash) -or -not(Test-StageBUtcTimestamp $Manifest.created_at) -or -not(Test-StageBUtcTimestamp $Manifest.expires_at)){throw 'invalid pending manifest'}
  $created=[DateTimeOffset]::Parse($Manifest.created_at); $expires=[DateTimeOffset]::Parse($Manifest.expires_at); if($expires -le $created -or $expires -gt $created.AddHours(24)){throw 'invalid manifest expiry'}
  Assert-StageBHashFields $Manifest.source @('endpoint_hash','database_hash','oid_hash','role_hash','server_version_num_hash')
  Assert-StageBPropertySet $Manifest.restore @('endpoint_hash','database_hash','oid_hash','owner_hash','state'); foreach($field in 'endpoint_hash','database_hash','oid_hash','owner_hash'){if(-not(Test-StageBHash $Manifest.restore.$field)){throw 'invalid identity hash'}}; if($Manifest.restore.state -notin @('absent','existing_empty')){throw 'invalid restore state'}
  if($Manifest.protected -isnot [System.Collections.IEnumerable] -or @($Manifest.protected).Count -lt 1){throw 'invalid protected set'}; foreach($item in @($Manifest.protected)){Assert-StageBHashFields $item @('endpoint_hash','database_hash','oid_hash')}
  Assert-StageBNoProtectedTarget $Manifest.restore (@($Manifest.source)+@($Manifest.protected)); if($Manifest.source.oid_hash -ceq $Manifest.restore.oid_hash){throw 'source restore collision'}
  Assert-StageBHashFields $Manifest.clients @('pg_dump_hash','pg_restore_hash','server_version_num_hash')
  Assert-StageBPropertySet $Manifest.storage @('root_hash','capacity_bytes','required_bytes','retention_days'); if(-not(Test-StageBHash $Manifest.storage.root_hash) -or [int64]$Manifest.storage.capacity_bytes -lt [int64]$Manifest.storage.required_bytes -or [int64]$Manifest.storage.required_bytes -le 0 -or [int]$Manifest.storage.retention_days -lt 1){throw 'invalid storage'}
  Assert-StageBHashFields $Manifest.owners @('restore_owner_hash','cleanup_owner_hash'); if($Manifest.owners.restore_owner_hash -ceq $Manifest.owners.cleanup_owner_hash){throw 'owners must be distinct'}
  Assert-StageBPropertySet $Manifest.services @('worker_hash','web_hash','stop_order','recovery_order'); if(-not(Test-StageBHash $Manifest.services.worker_hash) -or -not(Test-StageBHash $Manifest.services.web_hash) -or ((@($Manifest.services.stop_order)-join ',') -cne 'worker,web') -or ((@($Manifest.services.recovery_order)-join ',') -cne 'web,worker')){throw 'invalid service order'}
}
function Assert-StageBAdapter($Adapter) {
  $contract=[ordered]@{
    Pending=@()
    Snapshot=@('target','mode','expectedSourceOidHash')
    Catalog=@('target')
    Process=@('operation','arguments','environment')
    Service=@('action','service')
    Jobs=@()
    State=@('manifest')
    CreateRestore=@('target','ownerHash')
    DropRestore=@('target','ownerHash')
  }
  if($Adapter -isnot [Collections.IDictionary] -or (@($Adapter.Keys|Sort-Object)-join "`0") -cne (@($contract.Keys|Sort-Object)-join "`0")){throw 'invalid adapter contract'}
  foreach($name in $contract.Keys){
    $callback=$Adapter[$name]
    if($callback -isnot [scriptblock]){throw 'invalid adapter contract'}
    $actual=@($callback.Ast.ParamBlock.Parameters|ForEach-Object {$_.Name.VariablePath.UserPath})
    if(($actual -join "`0") -cne (@($contract[$name])-join "`0")){throw 'invalid adapter contract'}
  }
}
function Assert-StageBResult($Value,[string[]]$Fields) { Assert-StageBPropertySet $Value $Fields; $s=$Value.success; if($s -isnot [bool] -or $s -ne $true){throw 'callback failed'} }
function Assert-StageBSnapshot($Value) { Assert-StageBPropertySet $Value @('identity','baseline_hash','semantic_hash'); Assert-StageBHashFields $Value.identity @('oid_hash'); if(-not(Test-StageBHash $Value.baseline_hash) -or -not(Test-StageBHash $Value.semantic_hash)){throw 'invalid snapshot result'} }
function Assert-StageBCatalog($Value) { Assert-StageBPropertySet $Value @('state','oid_hash','owner_hash','connections'); if($Value.state -notin @('absent','existing_empty','eligible') -or ($Value.state -ne 'absent' -and (-not(Test-StageBHash $Value.oid_hash) -or -not(Test-StageBHash $Value.owner_hash))) -or [int]$Value.connections -lt 0){throw 'invalid catalog result'} }
function Get-StageBCurrentState($Manifest,$Adapter) { & $Adapter.State $Manifest }
function Assert-StageBCurrentState($Manifest,$State) {
  Assert-StageBPropertySet $State @('jobs','source_baseline_hash','source','restore','clients','storage','owners','services')
  if([int]$State.jobs -ne 0 -or $State.source_baseline_hash -cne $Manifest.source_baseline_hash){throw 'current state drift'}
  foreach($name in 'source','restore','clients','owners'){if((ConvertTo-StageBCanonicalJson $State.$name) -cne (ConvertTo-StageBCanonicalJson $Manifest.$name)){throw 'current state drift'}}
  if([int64]$State.storage.capacity_bytes -lt [int64]$Manifest.storage.required_bytes -or [int]$State.storage.retention_days -lt [int]$Manifest.storage.retention_days -or $State.storage.root_hash -cne $Manifest.storage.root_hash){throw 'storage drift'}
  if((ConvertTo-StageBCanonicalJson $State.services) -cne (ConvertTo-StageBCanonicalJson $Manifest.services) -or $State.clients.pg_dump_hash -cne $Manifest.clients.pg_dump_hash -or $State.clients.pg_restore_hash -cne $Manifest.clients.pg_restore_hash -or $State.clients.server_version_num_hash -cne $Manifest.clients.server_version_num_hash){throw 'runtime drift'}
}
function Assert-StageBJobsValue($Value) {
  if($null -eq $Value){throw 'invalid jobs provider data'}
  if($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]){throw 'invalid jobs provider data'}
  $s=[string][object]$Value
  if($s -notmatch '^-?\d+$'){throw 'invalid jobs provider data'}
  $j=[int]$Value
  if($j -lt 0){throw 'invalid jobs provider data'}
  $j
}
function New-StageBPendingFromReadOnlyData($Configuration,$ActiveJobs) {
  $ActiveJobs=Assert-StageBJobsValue $ActiveJobs
  Assert-StageBPropertySet $Configuration @('source','restore','protected','source_baseline','clients','storage','owners','services')
  Assert-StageBPropertySet $Configuration.source @('endpoint','database','oid','role','server_version_num')
  Assert-StageBPropertySet $Configuration.restore @('endpoint','database','oid','state')
  Assert-StageBPropertySet $Configuration.clients @('pg_dump','pg_restore','server_version_num')
  Assert-StageBPropertySet $Configuration.storage @('root','capacity_bytes','required_bytes','retention_days')
  Assert-StageBPropertySet $Configuration.owners @('restore_owner','cleanup_owner')
  Assert-StageBPropertySet $Configuration.services @('worker','web')
  if($ActiveJobs -ne 0 -or @($Configuration.protected).Count -lt 1){throw 'invalid read-only state'}
  foreach($item in @($Configuration.protected)){Assert-StageBPropertySet $item @('endpoint','database','oid')}
  $hash={param($value) if($null -eq $value -or -not([string]$value)){throw 'invalid read-only state'}; Get-StageBTextHash $value}
  $created=[DateTimeOffset]::UtcNow
  [pscustomobject]@{
    schema_version=1
    run_id=('stageb-'+[guid]::NewGuid().ToString('n'))
    scope='stage-b-backup-restore'
    live_blocked=$true
    criterion_8='not_evaluable'
    created_at=$created.ToString('o')
    expires_at=$created.AddHours(1).ToString('o')
    source=[pscustomobject]@{endpoint_hash=&$hash $Configuration.source.endpoint;database_hash=&$hash $Configuration.source.database;oid_hash=&$hash $Configuration.source.oid;role_hash=&$hash $Configuration.source.role;server_version_num_hash=&$hash $Configuration.source.server_version_num}
    restore=[pscustomobject]@{endpoint_hash=&$hash $Configuration.restore.endpoint;database_hash=&$hash $Configuration.restore.database;oid_hash=&$hash $Configuration.restore.oid;owner_hash=&$hash $Configuration.owners.restore_owner;state=[string]$Configuration.restore.state}
    protected=@($Configuration.protected|ForEach-Object {[pscustomobject]@{endpoint_hash=&$hash $_.endpoint;database_hash=&$hash $_.database;oid_hash=&$hash $_.oid}})
    source_baseline_hash=&$hash $Configuration.source_baseline
    clients=[pscustomobject]@{pg_dump_hash=&$hash $Configuration.clients.pg_dump;pg_restore_hash=&$hash $Configuration.clients.pg_restore;server_version_num_hash=&$hash $Configuration.clients.server_version_num}
    storage=[pscustomobject]@{root_hash=&$hash $Configuration.storage.root;capacity_bytes=[int64]$Configuration.storage.capacity_bytes;required_bytes=[int64]$Configuration.storage.required_bytes;retention_days=[int]$Configuration.storage.retention_days}
    owners=[pscustomobject]@{restore_owner_hash=&$hash $Configuration.owners.restore_owner;cleanup_owner_hash=&$hash $Configuration.owners.cleanup_owner}
    services=[pscustomobject]@{worker_hash=&$hash $Configuration.services.worker;web_hash=&$hash $Configuration.services.web;stop_order=@('worker','web');recovery_order=@('web','worker')}
    execution_state='pending'
  }
}
function New-StageBProductionAdapter([scriptblock]$ConfigurationProvider,[scriptblock]$JobsProvider) {
  if($null -eq $ConfigurationProvider){$ConfigurationProvider={param() if(-not $env:STAGE_B_PENDING_CONFIG){throw 'missing'}; $env:STAGE_B_PENDING_CONFIG|ConvertFrom-Json}}
  if($null -eq $JobsProvider){$JobsProvider={param() $configuration=& $ConfigurationProvider; Assert-StageBPropertySet $configuration @('manifest','active_jobs'); Assert-StageBJobsValue $configuration.active_jobs}.GetNewClosure()}
  $pending={param() try {$configuration=& $ConfigurationProvider; if($configuration.psobject.Properties.Name -contains 'manifest'){Assert-StageBPropertySet $configuration @('manifest','active_jobs'); $configuration=$configuration.manifest}; $manifest=New-StageBPendingFromReadOnlyData $configuration (& $JobsProvider); Test-StageBManifest $manifest; $manifest} catch {throw 'pending configuration invalid'}}.GetNewClosure()
  $runProcess={param($operation,$arguments,$environment) $psi=[Diagnostics.ProcessStartInfo]::new(); $psi.FileName=$operation; $psi.UseShellExecute=$false; $psi.RedirectStandardOutput=$true; $psi.RedirectStandardError=$true; foreach($argument in @($arguments)){$null=$psi.ArgumentList.Add([string]$argument)}; foreach($key in $environment.Keys){$psi.Environment[$key]=[string]$environment[$key]}; $p=[Diagnostics.Process]::Start($psi); $p.WaitForExit(); [pscustomobject]@{success=($p.ExitCode -eq 0);exit_code=$p.ExitCode;size=0;hash=$null}}
  $jobs={param() & $JobsProvider}.GetNewClosure()
  $adapter=@{Pending=$pending;Process=$runProcess;Snapshot={param($target,$mode,$expectedSourceOidHash) throw 'snapshot configuration unavailable'};Catalog={param($target) throw 'catalog configuration unavailable'};Service={param($action,$service) throw 'service configuration unavailable'};Jobs=$jobs;State={param($manifest) throw 'runtime state configuration unavailable'};CreateRestore={param($target,$ownerHash) throw 'create configuration unavailable'};DropRestore={param($target,$ownerHash) throw 'drop configuration unavailable'}}
  Assert-StageBAdapter $adapter
  $adapter
}
function New-StageBPendingManifest($Adapter) { Assert-StageBAdapter $Adapter; $m=& $Adapter.Pending; Test-StageBManifest $m; $m }
function Invoke-StageBSequence($Manifest,$Adapter) {
  $stages=[Collections.Generic.List[object]]::new(); $dump=$null; $result=$null
  $ownedServices=[System.Collections.Generic.HashSet[string]]::new()
  $workSucceeded=$false
  try {
    Test-StageBManifest $Manifest; Assert-StageBAdapter $Adapter; Assert-StageBCurrentState $Manifest (Get-StageBCurrentState $Manifest $Adapter)
    foreach($service in @($Manifest.services.stop_order)){
      $serviceResult=& $Adapter.Service 'stop' $service
      Assert-StageBResult $serviceResult @('success')
      $null=$ownedServices.Add($service)
      $null=$stages.Add(@{stage="stop_$service";state='succeeded'})
    }
    $source=& $Adapter.Snapshot $Manifest.source 'source' $null; Assert-StageBSnapshot $source; if($source.identity.oid_hash -cne $Manifest.source.oid_hash -or $source.baseline_hash -cne $Manifest.source_baseline_hash){throw 'source drift'}
    $dump=& $Adapter.Process 'pg_dump' @('--format=custom','--no-owner','--no-acl') @{}; if(-not $dump.success -or [int64]$dump.size -le 0 -or -not(Test-StageBHash $dump.hash)){throw 'dump failed'}
    $list=& $Adapter.Process 'pg_restore_list' @('--list') @{}; if(-not $list.success -or [int64]$list.size -le 0){throw 'dump list failed'}
    $catalog=& $Adapter.Catalog $Manifest.restore; Assert-StageBCatalog $catalog; if($catalog.state -eq 'absent'){$created=& $Adapter.CreateRestore $Manifest.restore $Manifest.owners.restore_owner_hash; Assert-StageBResult $created @('success'); $catalog=& $Adapter.Catalog $Manifest.restore; Assert-StageBCatalog $catalog} if($catalog.state -ne 'existing_empty' -or $catalog.oid_hash -cne $Manifest.restore.oid_hash -or $catalog.owner_hash -cne $Manifest.owners.restore_owner_hash){throw 'restore drift'}
    $restoreProcess=& $Adapter.Process 'pg_restore' @('--exit-on-error','--single-transaction','--no-owner','--no-acl') @{}; if(-not $restoreProcess.success){throw 'restore failed'}
    $restore=& $Adapter.Snapshot $Manifest.restore 'restore' $Manifest.source.oid_hash; Assert-StageBSnapshot $restore; if($restore.identity.oid_hash -ceq $Manifest.source.oid_hash -or $restore.semantic_hash -cne $source.semantic_hash){throw 'restore validation failed'}
    $after=& $Adapter.Snapshot $Manifest.source 'source' $null; Assert-StageBSnapshot $after; if($after.identity.oid_hash -cne $Manifest.source.oid_hash -or $after.baseline_hash -cne $Manifest.source_baseline_hash -or $after.semantic_hash -cne $source.semantic_hash){throw 'source changed'}
    $workSucceeded=$true
  } catch {
    $result=@{status='failed';live_blocked=$true;criterion_8='not_evaluable';error_code=(Get-StageBRedactedError $_);stages=$stages;dump_hash=if($dump){$dump.hash}else{$null}}
  }
  foreach($service in @($Manifest.services.recovery_order)){
    if(-not $ownedServices.Contains($service)){continue}
    try {
      $serviceResult=& $Adapter.Service 'start' $service
      Assert-StageBResult $serviceResult @('success')
      $null=$stages.Add(@{stage="start_$service";state='succeeded'})
    } catch {
      $result=if($result){$result}else{@{status='failed';live_blocked=$true;criterion_8='not_evaluable';error_code=(Get-StageBRedactedError $_);stages=$stages;dump_hash=if($dump){$dump.hash}else{$null}}}
      $result.status='failed'
    }
  }
  if(-not $result){
    if($workSucceeded){$result=@{status='success';live_blocked=$true;criterion_8='not_evaluable';stages=$stages;dump_hash=$dump.hash}}
    else {$result=@{status='failed';live_blocked=$true;criterion_8='not_evaluable';stages=$stages;dump_hash=if($dump){$dump.hash}else{$null}}}
  }
  $result
}
function Invoke-StageBCleanup($Manifest,$Adapter,$FinalEvidence,[string]$ManifestHash) { Test-StageBManifest $Manifest; Assert-StageBAdapter $Adapter; Assert-StageBCurrentState $Manifest (Get-StageBCurrentState $Manifest $Adapter); Assert-StageBPropertySet $FinalEvidence @('status','dump_hash','manifest_sha256'); if($FinalEvidence.status -cne 'success' -or -not(Test-StageBHash $FinalEvidence.dump_hash) -or -not(Test-StageBHash $FinalEvidence.manifest_sha256) -or -not(Test-StageBConstantTimeBytes ([Text.Encoding]::UTF8.GetBytes($FinalEvidence.manifest_sha256)) ([Text.Encoding]::UTF8.GetBytes($ManifestHash)))){throw 'invalid final evidence'}; $catalog=& $Adapter.Catalog $Manifest.restore; if($catalog.state -ne 'eligible' -or $catalog.oid_hash -cne $Manifest.restore.oid_hash -or $catalog.owner_hash -cne $Manifest.owners.restore_owner_hash -or [int]$catalog.connections -ne 0){throw 'cleanup guard failed'}; & $Adapter.DropRestore $Manifest.restore $Manifest.owners.cleanup_owner_hash; $after=& $Adapter.Catalog $Manifest.restore; if($after.state -ne 'absent'){throw 'cleanup verification failed'}; @{status='success';live_blocked=$true;criterion_8='not_evaluable';dump_hash=$FinalEvidence.dump_hash} }
function Write-StageBChecksums([string]$Root) { $items=Get-ChildItem -LiteralPath $Root -File -Recurse|Where-Object {$_.Name -notin @('checksums.sha256') -and $_.Name -notlike '*.tmp'}|Sort-Object FullName; $lines=@($items|ForEach-Object {(Get-StageBSha256 $_.FullName)+'  '+$_.FullName.Substring($Root.Length).TrimStart('\','/').Replace('\','/')}); [IO.File]::WriteAllText((Join-Path $Root 'checksums.sha256'),(($lines -join "`n")+"`n"),[Text.UTF8Encoding]::new($false)) }
function Publish-StageBPendingBundle([string]$ManifestPath,$Manifest,[scriptblock]$PostWriteHook) {
  $checksumPath=Join-Path ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($ManifestPath))) 'checksums.sha256'
  $leaf=[IO.Path]::GetFileName($ManifestPath).Replace('\','/')
  if(-not $leaf -or (Test-Path -LiteralPath $ManifestPath) -or (Test-Path -LiteralPath $checksumPath)){throw 'pending output already exists'}
  $token=[guid]::NewGuid().ToString('n')
  $manifestTemp="$ManifestPath.$token.tmp"
  $checksumTemp="$checksumPath.$token.tmp"
  $publishedManifest=$false
  $publishedChecksum=$false
  try {
    [IO.File]::WriteAllText($manifestTemp,(ConvertTo-StageBCanonicalJson $Manifest)+"`n",[Text.UTF8Encoding]::new($false))
    $hash=Get-StageBSha256 $manifestTemp
    [IO.File]::WriteAllText($checksumTemp,($hash+'  '+$leaf+"`n"),[Text.UTF8Encoding]::new($false))
    if((Test-Path -LiteralPath $ManifestPath) -or (Test-Path -LiteralPath $checksumPath)){throw 'pending output already exists'}
    Move-Item -LiteralPath $manifestTemp -Destination $ManifestPath
    $publishedManifest=$true
    Move-Item -LiteralPath $checksumTemp -Destination $checksumPath
    $publishedChecksum=$true
    if($null -ne $PostWriteHook){& $PostWriteHook $ManifestPath $checksumPath}
    $lines=@([IO.File]::ReadAllLines($checksumPath,[Text.Encoding]::UTF8))
    if($lines.Count -ne 1 -or $lines[0] -cnotmatch '^([a-f0-9]{64})  (.+)$' -or $Matches[2] -cne $leaf){throw 'pending verification failed'}
    $verified=Get-StageBSha256 $ManifestPath
    if(-not(Test-StageBConstantTimeBytes ([Text.Encoding]::UTF8.GetBytes($Matches[1])) ([Text.Encoding]::UTF8.GetBytes($verified)))){throw 'pending verification failed'}
    [pscustomobject]@{status='success';manifest_sha256=$verified}
  } catch {
    if($publishedChecksum -and (Test-Path -LiteralPath $checksumPath)){Remove-Item -LiteralPath $checksumPath -Force}
    if($publishedManifest -and (Test-Path -LiteralPath $ManifestPath)){Remove-Item -LiteralPath $ManifestPath -Force}
    throw 'pending publication failed'
  } finally {
    foreach($temporary in @($manifestTemp,$checksumTemp)){if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary -Force}}
  }
}
function Invoke-StageBMain([scriptblock]$AdapterFactory,[scriptblock]$PostWriteHook) {
  if(@($PlanOnly,$Execute,$Cleanup|Where-Object {$_}).Count -ne 1){throw 'Specify exactly one mode.'}
  if($null -eq $AdapterFactory){$AdapterFactory={param() New-StageBProductionAdapter}}
  $adapter=& $AdapterFactory
  Assert-StageBAdapter $adapter
  if($PlanOnly){if(-not $PendingManifestPath){throw 'pending manifest path required'}; $manifest=New-StageBPendingManifest $adapter; Publish-StageBPendingBundle $PendingManifestPath $manifest $PostWriteHook; return}
  if(-not $ApprovalPath -or -not $PendingManifestPath -or -not(Test-Path -LiteralPath $ApprovalPath) -or -not(Test-Path -LiteralPath $PendingManifestPath)){throw 'explicit approval and manifest required'}; $hash=Get-StageBSha256 $PendingManifestPath; $approval=Get-Content -Raw -LiteralPath $ApprovalPath|ConvertFrom-Json; Test-StageBApproval $approval $hash $(if($Cleanup){'cleanup'}else{'execute'}); $manifest=Get-Content -Raw -LiteralPath $PendingManifestPath|ConvertFrom-Json
  if($Cleanup){if(-not $EvidenceRoot){throw 'final evidence path required'}; $final=Get-Content -Raw -LiteralPath $EvidenceRoot|ConvertFrom-Json; Invoke-StageBCleanup $manifest $adapter $final $hash; return}; Invoke-StageBSequence $manifest $adapter
}
if($MyInvocation.InvocationName -ne '.'){Invoke-StageBMain}
