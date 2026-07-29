[CmdletBinding()]
param([switch]$PlanOnly,[switch]$Execute,[switch]$Cleanup,[string]$ApprovalPath,[string]$PendingManifestPath)
$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest

function Get-StageBSha256([string]$Path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() }
function Get-StageBHash([string]$Value) { ([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($Value)))).ToLowerInvariant() }
function Test-StageBIdentifier([string]$Value) { $Value -cmatch '^[a-z][a-z0-9_]{0,62}$' }
function Normalize-StageBHost([string]$Value) { $v=$Value.Trim().ToLowerInvariant().TrimEnd('.'); if(-not $v -or $v -match '[\s:/@\\]'){throw 'invalid protected host'}; $v }
function Normalize-StageBPort([string]$Value) { if($Value -notmatch '^\d+$'){throw 'invalid protected port'}; $p=[int]$Value; if($p -lt 1 -or $p -gt 65535){throw 'invalid protected port'}; $p.ToString([Globalization.CultureInfo]::InvariantCulture) }
function ConvertTo-StageBCanonicalJson([object]$Value) { $Value | ConvertTo-Json -Depth 20 -Compress }
function Write-StageBAtomicJson([string]$Path,$Value) { $tmp="$Path.tmp"; [IO.File]::WriteAllText($tmp,(ConvertTo-StageBCanonicalJson $Value)+"`n",[Text.UTF8Encoding]::new($false)); Move-Item -LiteralPath $tmp -Destination $Path -Force }
function Test-StageBHash([string]$Value) { $Value -match '^[a-f0-9]{64}$' }
function Test-StageBUtcTimestamp([string]$Value) { try { $null=[DateTimeOffset]::Parse($Value,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::RoundtripKind); $true } catch {$false} }
function Assert-StageBPropertySet($Object,[string[]]$Names) { $actual=@($Object.psobject.Properties.Name|Sort-Object); $expected=@($Names|Sort-Object); if(($actual -join "`0") -ne ($expected -join "`0")){throw 'strict schema mismatch'} }
function Assert-StageBNoProtectedTarget([hashtable]$Target,[hashtable[]]$Protected) { foreach($item in $Protected){if($Target.endpoint_hash -eq $item.endpoint_hash -and $Target.database_hash -eq $item.database_hash){throw 'protected target rejected'}; if($Target.oid_hash -and $Target.oid_hash -eq $item.oid_hash){throw 'protected OID rejected'}} }
function Get-StageBRedactedError([object]$ErrorRecord) { 'stage_b_operation_failed' }
function Test-StageBConstantTimeBytes([byte[]]$Left,[byte[]]$Right) { if($Left.Length -ne $Right.Length){return $false}; [int]$different=0; for($i=0;$i -lt $Left.Length;$i++){$different=$different -bor ($Left[$i] -bxor $Right[$i])}; $different -eq 0 }
function Test-StageBApproval($Approval,[string]$ManifestHash,[string]$Action) {
  Assert-StageBPropertySet $Approval @('scope','action','manifest_sha256','approved_at','approver_hash')
  if($Approval.scope -ne 'stage-b-backup-restore' -or $Approval.action -ne $Action -or -not(Test-StageBHash $Approval.manifest_sha256) -or -not(Test-StageBHash $Approval.approver_hash) -or -not(Test-StageBUtcTimestamp $Approval.approved_at)){throw 'invalid approval'}
  $bytes=[Text.Encoding]::UTF8.GetBytes($Approval.manifest_sha256.ToLowerInvariant()); $other=[Text.Encoding]::UTF8.GetBytes($ManifestHash.ToLowerInvariant())
  if(-not(Test-StageBConstantTimeBytes $bytes $other)){throw 'approval does not name exact manifest'}
  $at=[DateTimeOffset]::Parse($Approval.approved_at).ToUniversalTime(); $now=[DateTimeOffset]::UtcNow
  if($at -lt $now.AddHours(-24) -or $at -gt $now.AddMinutes(5)){throw 'approval time invalid'}
}
function Test-StageBManifest($Manifest) {
  Assert-StageBPropertySet $Manifest @('schema_version','run_id','scope','live_blocked','criterion_8','created_at','expires_at','source','restore','protected','source_baseline_hash','clients','storage','owners','services','execution_state')
  if($Manifest.schema_version -ne 1 -or $Manifest.scope -ne 'stage-b-backup-restore' -or $Manifest.live_blocked -ne $true -or $Manifest.criterion_8 -ne 'not_evaluable' -or -not(Test-StageBHash $Manifest.source_baseline_hash) -or -not(Test-StageBUtcTimestamp $Manifest.created_at) -or -not(Test-StageBUtcTimestamp $Manifest.expires_at)){throw 'invalid pending manifest'}
  Assert-StageBNoProtectedTarget $Manifest.restore @($Manifest.source)+@($Manifest.protected)
  if($Manifest.restore.state -notin @('absent','existing_empty')){throw 'invalid restore state'}
}
function New-StageBAdapter {
  @{ Snapshot={param($target,$mode,$oid) throw 'runtime adapter not configured'}; Catalog={param($target) throw 'runtime adapter not configured'}; Process={param($name,$args,$environment) throw 'runtime adapter not configured'}; Service={param($action,$name) throw 'runtime adapter not configured'}; Jobs={0}; CreateRestore={param($target,$owner) throw 'runtime adapter not configured'}; DropRestore={param($target) throw 'runtime adapter not configured'} }
}
function Invoke-StageBSequence($Manifest,$Adapter) {
  Test-StageBManifest $Manifest; $stages=[Collections.Generic.List[object]]::new(); $dump=$null
  try {
    if([int]$Adapter.Jobs -ne 0){throw 'active jobs'}
    foreach($service in @('worker','web')){& $Adapter.Service 'stop' $service|Out-Null; $null=$stages.Add(@{stage="stop_$service";state='succeeded';at=[DateTimeOffset]::UtcNow.ToString('o')})}
    $source=& $Adapter.Snapshot $Manifest.source 'source' $null
    if($source.identity.oid_hash -ne $Manifest.source.oid_hash){throw 'source drift'}
    $dump=& $Adapter.Process 'pg_dump' @('--format=custom','--no-owner','--no-acl') @{}
    if(-not $dump.success -or [int64]$dump.size -le 0){throw 'dump failed'}
    $catalog=& $Adapter.Catalog $Manifest.restore
    if($catalog.state -eq 'absent'){& $Adapter.CreateRestore $Manifest.restore $Manifest.owners.restore_owner_hash|Out-Null} elseif($catalog.state -ne 'existing_empty' -or $catalog.oid_hash -ne $Manifest.restore.oid_hash){throw 'restore drift'}
    & $Adapter.Process 'pg_restore' @('--exit-on-error','--single-transaction','--no-owner','--no-acl') @{}|Out-Null
    $restore=& $Adapter.Snapshot $Manifest.restore 'restore' $Manifest.source.oid_hash
    if($restore.identity.oid_hash -eq $Manifest.source.oid_hash){throw 'restore OID collision'}
    $null=$stages.Add(@{stage='restore';state='succeeded';at=[DateTimeOffset]::UtcNow.ToString('o')})
    @{status='success';live_blocked=$true;criterion_8='not_evaluable';stages=$stages;dump_hash=$dump.hash}
  } catch { @{status='failed';live_blocked=$true;criterion_8='not_evaluable';error_code=(Get-StageBRedactedError $_);stages=$stages;dump_hash=if($dump){$dump.hash}else{$null}} } finally { foreach($service in @('web','worker')){try {& $Adapter.Service 'start' $service|Out-Null} catch {}} }
}
function Write-StageBChecksums([string]$Root) { $items=Get-ChildItem -LiteralPath $Root -File -Recurse|Where-Object {$_.Name -notin @('checksums.sha256') -and $_.Name -notlike '*.tmp'}|Sort-Object @{Expression={$_.FullName.Substring($Root.Length).TrimStart('\','/').Replace('\','/')};Ascending=$true}; $lines=@($items|ForEach-Object {(Get-StageBSha256 $_.FullName)+'  '+$_.FullName.Substring($Root.Length).TrimStart('\','/').Replace('\','/')}); [IO.File]::WriteAllText((Join-Path $Root 'checksums.sha256'),(($lines -join "`n")+"`n"),[Text.UTF8Encoding]::new($false)) }
function Invoke-StageBMain {
  if(@($PlanOnly,$Execute,$Cleanup|Where-Object {$_}).Count -ne 1){throw 'Specify exactly one mode.'}
  if($PlanOnly){throw 'PlanOnly requires runtime adapter configuration and is intentionally not executed by this test-only cycle.'}
  if(-not $ApprovalPath -or -not $PendingManifestPath -or -not(Test-Path -LiteralPath $ApprovalPath) -or -not(Test-Path -LiteralPath $PendingManifestPath)){throw 'explicit approval and manifest required'}
  $hash=Get-StageBSha256 $PendingManifestPath; $approval=Get-Content -Raw -LiteralPath $ApprovalPath|ConvertFrom-Json; Test-StageBApproval $approval $hash $(if($Cleanup){'cleanup'}else{'execute'})
  if($Cleanup){throw 'Cleanup requires production adapter revalidation and is not executed by this test-only cycle.'}
  $manifest=Get-Content -Raw -LiteralPath $PendingManifestPath|ConvertFrom-Json; Test-StageBManifest $manifest; throw 'Execute requires production adapter revalidation and is not executed by this test-only cycle.'
}
if($MyInvocation.InvocationName -ne '.'){Invoke-StageBMain}
