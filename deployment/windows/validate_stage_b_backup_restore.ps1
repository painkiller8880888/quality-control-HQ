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
function Assert-StageBAdapter($Adapter) { foreach($name in 'Snapshot','Catalog','Process','Service','Jobs','State','CreateRestore','DropRestore'){if(-not $Adapter.ContainsKey($name) -or $Adapter[$name] -isnot [scriptblock]){throw 'invalid adapter contract'}} }
function Get-StageBCurrentState($Manifest,$Adapter) { & $Adapter.State $Manifest }
function Assert-StageBCurrentState($Manifest,$State) {
  Assert-StageBPropertySet $State @('jobs','source_baseline_hash','source','restore','clients','storage','owners','services')
  if([int]$State.jobs -ne 0 -or $State.source_baseline_hash -cne $Manifest.source_baseline_hash){throw 'current state drift'}
  foreach($name in 'source','restore','clients','owners'){if((ConvertTo-StageBCanonicalJson $State.$name) -cne (ConvertTo-StageBCanonicalJson $Manifest.$name)){throw 'current state drift'}}
  if([int64]$State.storage.capacity_bytes -lt [int64]$Manifest.storage.required_bytes -or [int]$State.storage.retention_days -lt [int]$Manifest.storage.retention_days -or $State.storage.root_hash -cne $Manifest.storage.root_hash){throw 'storage drift'}
  if((ConvertTo-StageBCanonicalJson $State.services) -cne (ConvertTo-StageBCanonicalJson $Manifest.services) -or $State.clients.pg_dump_hash -cne $Manifest.clients.pg_dump_hash -or $State.clients.pg_restore_hash -cne $Manifest.clients.pg_restore_hash -or $State.clients.server_version_num_hash -cne $Manifest.clients.server_version_num_hash){throw 'runtime drift'}
}
function New-StageBProductionAdapter {
  $runProcess={param($name,$args,$environment) $psi=[Diagnostics.ProcessStartInfo]::new(); $psi.FileName=$name; $psi.UseShellExecute=$false; $psi.RedirectStandardOutput=$true; $psi.RedirectStandardError=$true; foreach($arg in @($args)){$null=$psi.ArgumentList.Add([string]$arg)}; foreach($key in $environment.Keys){$psi.Environment[$key]=[string]$environment[$key]}; $p=[Diagnostics.Process]::Start($psi); $p.WaitForExit(); [pscustomobject]@{success=($p.ExitCode -eq 0);exit_code=$p.ExitCode;size=0;hash=$null}}
  @{ Pending={throw 'read-only pending-manifest configuration required'}; Process=$runProcess; Snapshot={param($target,$mode,$oid) throw 'snapshot executable configuration required'}; Catalog={param($target) throw 'catalog query configuration required'}; Service={param($action,$name) throw 'service configuration required'}; Jobs={param() throw 'job query configuration required'}; State={param($manifest) throw 'read-only runtime state configuration required'}; CreateRestore={param($target,$owner) throw 'create configuration required'}; DropRestore={param($target) throw 'drop configuration required'} }
}
function New-StageBPendingManifest($Adapter) { $m=& $Adapter.Pending; Test-StageBManifest $m; $m }
function Invoke-StageBSequence($Manifest,$Adapter) {
  $stages=[Collections.Generic.List[object]]::new(); $dump=$null; $result=$null
  try {
    Test-StageBManifest $Manifest; Assert-StageBAdapter $Adapter; Assert-StageBCurrentState $Manifest (Get-StageBCurrentState $Manifest $Adapter)
    foreach($service in @($Manifest.services.stop_order)){& $Adapter.Service 'stop' $service|Out-Null; $null=$stages.Add(@{stage="stop_$service";state='succeeded'})}
    $source=& $Adapter.Snapshot $Manifest.source 'source' $null; if($source.identity.oid_hash -cne $Manifest.source.oid_hash -or $source.baseline_hash -cne $Manifest.source_baseline_hash){throw 'source drift'}
    $dump=& $Adapter.Process 'pg_dump' @('--format=custom','--no-owner','--no-acl') @{}; if(-not $dump.success -or [int64]$dump.size -le 0 -or -not(Test-StageBHash $dump.hash)){throw 'dump failed'}
    $list=& $Adapter.Process 'pg_restore_list' @('--list') @{}; if(-not $list.success -or [int64]$list.size -le 0){throw 'dump list failed'}
    $catalog=& $Adapter.Catalog $Manifest.restore; if($catalog.state -eq 'absent'){& $Adapter.CreateRestore $Manifest.restore $Manifest.owners.restore_owner_hash|Out-Null} elseif($catalog.state -ne 'existing_empty' -or $catalog.oid_hash -cne $Manifest.restore.oid_hash){throw 'restore drift'}
    $restoreProcess=& $Adapter.Process 'pg_restore' @('--exit-on-error','--single-transaction','--no-owner','--no-acl') @{}; if(-not $restoreProcess.success){throw 'restore failed'}
    $restore=& $Adapter.Snapshot $Manifest.restore 'restore' $Manifest.source.oid_hash; if($restore.identity.oid_hash -ceq $Manifest.source.oid_hash -or $restore.semantic_hash -cne $source.semantic_hash){throw 'restore validation failed'}
    $after=& $Adapter.Snapshot $Manifest.source 'source' $null; if($after.baseline_hash -cne $Manifest.source_baseline_hash){throw 'source changed'}
    foreach($service in @($Manifest.services.recovery_order)){& $Adapter.Service 'start' $service|Out-Null; $null=$stages.Add(@{stage="start_$service";state='succeeded'})}
    $result=@{status='success';live_blocked=$true;criterion_8='not_evaluable';stages=$stages;dump_hash=$dump.hash}
  } catch {$result=@{status='failed';live_blocked=$true;criterion_8='not_evaluable';error_code=(Get-StageBRedactedError $_);stages=$stages;dump_hash=if($dump){$dump.hash}else{$null}}; foreach($service in @($Manifest.services.recovery_order)){try {& $Adapter.Service 'start' $service|Out-Null} catch {$result.status='failed'}}}
  $result
}
function Invoke-StageBCleanup($Manifest,$Adapter,$FinalEvidence,[string]$ManifestHash) { Test-StageBManifest $Manifest; Assert-StageBAdapter $Adapter; Assert-StageBCurrentState $Manifest (Get-StageBCurrentState $Manifest $Adapter); Assert-StageBPropertySet $FinalEvidence @('status','dump_hash','manifest_sha256'); if($FinalEvidence.status -cne 'success' -or -not(Test-StageBHash $FinalEvidence.dump_hash) -or -not(Test-StageBHash $FinalEvidence.manifest_sha256) -or -not(Test-StageBConstantTimeBytes ([Text.Encoding]::UTF8.GetBytes($FinalEvidence.manifest_sha256)) ([Text.Encoding]::UTF8.GetBytes($ManifestHash)))){throw 'invalid final evidence'}; $catalog=& $Adapter.Catalog $Manifest.restore; if($catalog.state -ne 'eligible' -or $catalog.oid_hash -cne $Manifest.restore.oid_hash -or $catalog.owner_hash -cne $Manifest.owners.restore_owner_hash -or [int]$catalog.connections -ne 0){throw 'cleanup guard failed'}; & $Adapter.DropRestore $Manifest.restore $Manifest.owners.cleanup_owner_hash; $after=& $Adapter.Catalog $Manifest.restore; if($after.state -ne 'absent'){throw 'cleanup verification failed'}; @{status='success';live_blocked=$true;criterion_8='not_evaluable';dump_hash=$FinalEvidence.dump_hash} }
function Write-StageBChecksums([string]$Root) { $items=Get-ChildItem -LiteralPath $Root -File -Recurse|Where-Object {$_.Name -notin @('checksums.sha256') -and $_.Name -notlike '*.tmp'}|Sort-Object FullName; $lines=@($items|ForEach-Object {(Get-StageBSha256 $_.FullName)+'  '+$_.FullName.Substring($Root.Length).TrimStart('\','/').Replace('\','/')}); [IO.File]::WriteAllText((Join-Path $Root 'checksums.sha256'),(($lines -join "`n")+"`n"),[Text.UTF8Encoding]::new($false)) }
function Invoke-StageBMain {
  if(@($PlanOnly,$Execute,$Cleanup|Where-Object {$_}).Count -ne 1){throw 'Specify exactly one mode.'}; $adapter=New-StageBProductionAdapter
  if($PlanOnly){if(-not $PendingManifestPath){throw 'pending manifest path required'}; $manifest=New-StageBPendingManifest $adapter; Write-StageBAtomicJson $PendingManifestPath $manifest; return}
  if(-not $ApprovalPath -or -not $PendingManifestPath -or -not(Test-Path -LiteralPath $ApprovalPath) -or -not(Test-Path -LiteralPath $PendingManifestPath)){throw 'explicit approval and manifest required'}; $hash=Get-StageBSha256 $PendingManifestPath; $approval=Get-Content -Raw -LiteralPath $ApprovalPath|ConvertFrom-Json; Test-StageBApproval $approval $hash $(if($Cleanup){'cleanup'}else{'execute'}); $manifest=Get-Content -Raw -LiteralPath $PendingManifestPath|ConvertFrom-Json
  if($Cleanup){if(-not $EvidenceRoot){throw 'final evidence path required'}; $final=Get-Content -Raw -LiteralPath $EvidenceRoot|ConvertFrom-Json; Invoke-StageBCleanup $manifest $adapter $final $hash; return}; Invoke-StageBSequence $manifest $adapter
}
if($MyInvocation.InvocationName -ne '.'){Invoke-StageBMain}
