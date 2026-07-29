$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'validate_stage_b_backup_restore.ps1')
function Assert-True($Value,[string]$Message){if(-not $Value){throw $Message}}
function Assert-Throws($Action,[string]$Message){try {& $Action; throw $Message} catch {if($_.Exception.Message -eq $Message){throw $Message}}}
function New-Manifest {
 $h={param($x) Get-StageBTextHash $x}; [pscustomobject]@{schema_version=1;run_id='run-001';scope='stage-b-backup-restore';live_blocked=$true;criterion_8='not_evaluable';created_at=[DateTimeOffset]::UtcNow.ToString('o');expires_at=[DateTimeOffset]::UtcNow.AddHours(1).ToString('o');source=[pscustomobject]@{endpoint_hash=&$h 'source-endpoint';database_hash=&$h 'source-db';oid_hash=&$h 'source-oid';role_hash=&$h 'source-role';server_version_num_hash=&$h '16'};restore=[pscustomobject]@{endpoint_hash=&$h 'restore-endpoint';database_hash=&$h 'restore-db';oid_hash=&$h 'restore-oid';owner_hash=&$h 'restore-owner';state='absent'};protected=@([pscustomobject]@{endpoint_hash=&$h 'protected-endpoint';database_hash=&$h 'protected-db';oid_hash=&$h 'protected-oid'});source_baseline_hash=&$h 'baseline';clients=[pscustomobject]@{pg_dump_hash=&$h 'dump';pg_restore_hash=&$h 'restore';server_version_num_hash=&$h '16'};storage=[pscustomobject]@{root_hash=&$h 'local';capacity_bytes=[int64]100;required_bytes=[int64]10;retention_days=[int]1};owners=[pscustomobject]@{restore_owner_hash=&$h 'restore-owner';cleanup_owner_hash=&$h 'cleanup-owner'};services=[pscustomobject]@{worker_hash=&$h 'worker';web_hash=&$h 'web';stop_order=@('worker','web');recovery_order=@('web','worker')};execution_state='pending'}
}
function Copy-Manifest($m){$m|ConvertTo-Json -Depth 20|ConvertFrom-Json}
function New-ReadOnlyConfiguration {
 [pscustomobject]@{
  source=[pscustomobject]@{endpoint='raw-source-endpoint';database='raw-source-db';oid='raw-source-oid';role='raw-source-role';server_version_num='16'}
  restore=[pscustomobject]@{endpoint='raw-restore-endpoint';database='raw-restore-db';oid='raw-restore-oid';state='absent'}
  protected=@([pscustomobject]@{endpoint='raw-protected-endpoint';database='raw-protected-db';oid='raw-protected-oid'})
  source_baseline='raw-source-baseline'
  clients=[pscustomobject]@{pg_dump='raw-pg-dump';pg_restore='raw-pg-restore';server_version_num='16'}
  storage=[pscustomobject]@{root='raw-storage-root';capacity_bytes=[int64]100;required_bytes=[int64]10;retention_days=[int]1}
  owners=[pscustomobject]@{restore_owner='raw-restore-owner';cleanup_owner='raw-cleanup-owner'}
  services=[pscustomobject]@{worker='raw-worker';web='raw-web'}
 }
}
function New-CurrentState($m) {
 [pscustomobject]@{jobs=[int]0;source_baseline_hash=$m.source_baseline_hash;source=[pscustomobject]@{endpoint_hash=$m.source.endpoint_hash;database_hash=$m.source.database_hash;oid_hash=$m.source.oid_hash;role_hash=$m.source.role_hash;server_version_num_hash=$m.source.server_version_num_hash};restore=[pscustomobject]@{endpoint_hash=$m.restore.endpoint_hash;database_hash=$m.restore.database_hash;oid_hash=$m.restore.oid_hash;owner_hash=$m.restore.owner_hash;state=$m.restore.state};clients=[pscustomobject]@{pg_dump_hash=$m.clients.pg_dump_hash;pg_restore_hash=$m.clients.pg_restore_hash;server_version_num_hash=$m.clients.server_version_num_hash};storage=[pscustomobject]@{root_hash=$m.storage.root_hash;capacity_bytes=[int64]$m.storage.capacity_bytes;required_bytes=[int64]$m.storage.required_bytes;retention_days=[int]$m.storage.retention_days};owners=[pscustomobject]@{restore_owner_hash=$m.owners.restore_owner_hash;cleanup_owner_hash=$m.owners.cleanup_owner_hash};services=[pscustomobject]@{worker_hash=$m.services.worker_hash;web_hash=$m.services.web_hash;stop_order=@('worker','web');recovery_order=@('web','worker');worker_state='running';web_state='running'}}
}
function New-FakeAdapter($m,$Failure='',$DumpResult=$null,$ListResult=$null,$RestoreResult=$null) {
  $script:events=[Collections.Generic.List[string]]::new(); $script:mutations=0; $script:catalogCalls=0; $script:createCalls=0; $script:sourceSnapshotCalls=0; $script:restoreSnapshotCalls=0; $script:dropCalls=0
  $script:state=New-CurrentState $m; $script:manifest=$m; $script:failure=$Failure; $script:created=$false; $script:dumpOverrideEnabled=$PSBoundParameters.ContainsKey('DumpResult'); $script:dumpResult=$DumpResult; $script:listOverrideEnabled=$PSBoundParameters.ContainsKey('ListResult'); $script:listResult=$ListResult; $script:restoreOverrideEnabled=$PSBoundParameters.ContainsKey('RestoreResult'); $script:restoreResult=$RestoreResult
  @{Pending={param() $script:manifest};Jobs={param() 0};State={param($manifest) if($script:failure -eq 'state') {throw 'state failure'}; $script:state};Service={param($action,$service) $null=$script:events.Add("$action-$service"); if($script:failure -eq "service-$action-$service"){throw 'service failure'}; if($script:failure -eq "service-false-$action-$service"){return [pscustomobject]@{success=$false}}; if($script:failure -eq "service-malformed-$action-$service"){return [pscustomobject]@{}}; if($script:failure -eq "service-throw-$action-$service"){throw 'service throw'}; if($script:failure -eq "service-int1-$action-$service"){return [pscustomobject]@{success=1}}; if($script:failure -eq "service-strtrue-$action-$service"){return [pscustomobject]@{success='true'}}; if($script:failure -eq "service-state-$action-$service"){return [pscustomobject]@{success=$true;state=if($action -eq 'stop'){'running'}else{'stopped'}}}; if($action -eq 'stop'){$script:mutations++}; [pscustomobject]@{success=$true;state=if($action -eq 'stop'){'stopped'}else{'running'}}};Snapshot={param($target,$mode,$expectedSourceOidHash) if($mode -eq 'source'){$script:sourceSnapshotCalls++}else{$script:restoreSnapshotCalls++}; if($script:failure -eq "snapshot-$mode"){throw 'snapshot failure'}; [pscustomobject]@{identity=[pscustomobject]@{oid_hash=if($mode -eq 'source'){$script:manifest.source.oid_hash}else{$script:manifest.restore.oid_hash}};baseline_hash=$script:manifest.source_baseline_hash;semantic_hash=(Get-StageBTextHash 'semantic')}};Process={param($operation,$arguments,$environment) $null=$script:events.Add($operation); if($operation -eq 'pg_dump' -and $script:dumpOverrideEnabled){return $script:dumpResult}; if($operation -eq 'pg_restore_list' -and $script:listOverrideEnabled){return $script:listResult}; if($operation -eq 'pg_restore' -and $script:restoreOverrideEnabled){return $script:restoreResult}; if($script:failure -eq $operation){return [pscustomobject]@{success=$false;exit_code=[int]1;size=[int64]0;hash=$null}}; if($operation -eq 'pg_dump'){return [pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=(Get-StageBTextHash 'dump')}}; if($operation -eq 'pg_restore_list'){return [pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=(Get-StageBTextHash 'pg_restore_list')}}; [pscustomobject]@{success=$true;exit_code=[int]0}};Catalog={param($target) $script:catalogCalls++; if($script:failure -eq 'catalog') {throw 'catalog failure'};if($script:created){[pscustomobject]@{state='existing_empty';oid_hash=$script:manifest.restore.oid_hash;owner_hash=$script:manifest.owners.restore_owner_hash;connections=[int]0}}else{[pscustomobject]@{state='absent';oid_hash=$null;owner_hash=$null;connections=[int]0}}};CreateRestore={param($target,$ownerHash) $script:createCalls++; $script:created=$true; $null=$script:events.Add('create');[pscustomobject]@{success=$true}};DropRestore={param($target,$ownerHash) $script:dropCalls++; $null=$script:events.Add('drop');[pscustomobject]@{success=$true}}}
}
Assert-True (Test-StageBIdentifier 'restore_db') 'identifier'; Assert-True ((Normalize-StageBHost ' Db.Example. ') -eq 'db.example') 'host'; Assert-True ((Normalize-StageBPort '05432') -eq '5432') 'port'
$m=New-Manifest; Test-StageBManifest $m
$contractAdapter=New-FakeAdapter $m
Assert-StageBAdapter $contractAdapter
$script:contractCalls=0
foreach($case in @('missing','extra','non-scriptblock','drop-arity')){
 $candidate=@{}; foreach($key in $contractAdapter.Keys){$candidate[$key]=$contractAdapter[$key]}
 switch($case){
  'missing' {$candidate.Remove('Pending')}
  'extra' {$candidate.Extra={param() $script:contractCalls++}}
  'non-scriptblock' {$candidate.Pending='invalid'}
  'drop-arity' {$candidate.DropRestore={param($target) $script:contractCalls++}}
 }
 Assert-Throws {Assert-StageBAdapter $candidate} "adapter $case"
}
Assert-True ($script:contractCalls -eq 0) 'adapter rejection before callback'
$script:readOnlyConfiguration=New-ReadOnlyConfiguration
$production=New-StageBProductionAdapter {param() $script:readOnlyConfiguration} {param() 0}
Assert-StageBAdapter $production
$pending=& $production.Pending
Test-StageBManifest $pending
Assert-True ((ConvertTo-StageBCanonicalJson $pending) -notmatch 'raw-') 'pending hashes raw configuration'
$invalidConfiguration=New-ReadOnlyConfiguration; $invalidConfiguration.storage.capacity_bytes=1
$invalidProduction=New-StageBProductionAdapter ({param() $invalidConfiguration}.GetNewClosure()) {param() 0}
Assert-Throws {& $invalidProduction.Pending} 'invalid production pending'
$readOnlyCases=@(
  @{name='top-missing';change={param($x) $x.psobject.Properties.Remove('protected')}},
  @{name='top-extra';change={param($x) $x|Add-Member extra 'x'}},
  @{name='nested-missing';change={param($x) $x.source.psobject.Properties.Remove('role')}},
  @{name='nested-extra';change={param($x) $x.clients|Add-Member extra 'x'}},
  @{name='object-scalar';change={param($x) $x.source='x'}},
  @{name='empty-string';change={param($x) $x.source.endpoint=''}},
  @{name='numeric-string-field';change={param($x) $x.clients.pg_dump=1}},
  @{name='boolean-string-field';change={param($x) $x.services.worker=$true}},
  @{name='null-string-field';change={param($x) $x.owners.restore_owner=$null}},
  @{name='invalid-restore-state';change={param($x) $x.restore.state='eligible'}},
  @{name='uppercase-restore-state';change={param($x) $x.restore.state='ABSENT'}},
  @{name='protected-string';change={param($x) $x.protected='x'}},
  @{name='protected-empty';change={param($x) $x.protected=@()}},
  @{name='protected-record-extra';change={param($x) $x.protected[0]|Add-Member extra 'x'}},
  @{name='protected-record-numeric';change={param($x) $x.protected[0].oid=1}},
  @{name='capacity-int32';change={param($x) $x.storage.capacity_bytes=[int]100}},
  @{name='required-string';change={param($x) $x.storage.required_bytes='10'}},
  @{name='retention-int64';change={param($x) $x.storage.retention_days=[int64]1}},
  @{name='required-zero';change={param($x) $x.storage.required_bytes=[int64]0}},
  @{name='capacity-too-small';change={param($x) $x.storage.capacity_bytes=[int64]1}}
)
foreach($case in $readOnlyCases){$bad=New-ReadOnlyConfiguration; & $case.change $bad; $provider=New-StageBProductionAdapter ({param() $bad}.GetNewClosure()) {param() 0}; Assert-Throws {& $provider.Pending} "read-only $($case.name)"}
Assert-Throws {New-StageBPendingFromReadOnlyData $null 0} 'read-only null'
$negative=@(
  @{name='nested-extra';change={param($x) $x.clients|Add-Member bad x}},
  @{name='bad-hash';change={param($x) $x.source.oid_hash='x'}},
  @{name='expiry';change={param($x) $x.expires_at=$x.created_at}},
  @{name='capacity';change={param($x) $x.storage.capacity_bytes=1}},
  @{name='service-order';change={param($x) $x.services.stop_order=@('web','worker')}},
  @{name='collision';change={param($x) $x.restore.oid_hash=$x.source.oid_hash}}
)
foreach($case in $negative){$bad=Copy-Manifest $m; & $case.change $bad; Assert-Throws {Test-StageBManifest $bad} $case.name}
$approval=[pscustomobject]@{scope='stage-b-backup-restore';action='execute';manifest_sha256=('c'*64);approved_at=[DateTimeOffset]::UtcNow.ToString('o');approver_hash=('d'*64)}; Test-StageBApproval $approval ('c'*64) 'execute'; Assert-Throws {Test-StageBApproval $approval ('e'*64) 'execute'} 'approval'

$m=New-Manifest

$validSnapshot=[pscustomobject]@{identity=[pscustomobject]@{oid_hash=('a'*64)};baseline_hash=('b'*64);semantic_hash=('c'*64)}
Assert-StageBSnapshot $validSnapshot
$invalidSnapshots=@(
  @{name='null';value=$null},
  @{name='non-object';value='invalid'},
  @{name='missing';value=[pscustomobject]@{identity=$validSnapshot.identity;baseline_hash=('b'*64)}},
  @{name='extra';value=[pscustomobject]@{identity=$validSnapshot.identity;baseline_hash=('b'*64);semantic_hash=('c'*64);extra='x'}},
  @{name='identity-extra';value=[pscustomobject]@{identity=[pscustomobject]@{oid_hash=('a'*64);extra='x'};baseline_hash=('b'*64);semantic_hash=('c'*64)}},
  @{name='uppercase';value=[pscustomobject]@{identity=[pscustomobject]@{oid_hash=('A'*64)};baseline_hash=('b'*64);semantic_hash=('c'*64)}},
  @{name='non-string';value=[pscustomobject]@{identity=[pscustomobject]@{oid_hash=1};baseline_hash=('b'*64);semantic_hash=('c'*64)}},
  @{name='malformed';value=[pscustomobject]@{identity=[pscustomobject]@{oid_hash=('a'*64)};baseline_hash='bad';semantic_hash=('c'*64)}}
)
foreach($case in $invalidSnapshots){Assert-Throws {Assert-StageBSnapshot $case.value} "snapshot $($case.name)"}
$a=New-FakeAdapter $m; $a.Snapshot={param($target,$mode,$expectedSourceOidHash) $script:sourceSnapshotCalls++; [pscustomobject]@{identity=[pscustomobject]@{oid_hash='bad'};baseline_hash=$script:manifest.source_baseline_hash;semantic_hash=('c'*64)}}; $r=Invoke-StageBSequence $m $a
Assert-True (($script:events -join ',') -eq 'stop-worker,stop-web,start-web,start-worker' -and $script:sourceSnapshotCalls -eq 1 -and $script:catalogCalls -eq 0) 'invalid source snapshot precedes Process'

$validCatalog=[pscustomobject]@{state='eligible';oid_hash=('a'*64);owner_hash=('b'*64);connections=[int]0}
Assert-StageBCatalog $validCatalog
$invalidCatalogs=@(
  @{name='null';value=$null},
  @{name='non-object';value='invalid'},
  @{name='missing';value=[pscustomobject]@{state='absent';oid_hash=$null;owner_hash=$null}},
  @{name='extra';value=[pscustomobject]@{state='absent';oid_hash=$null;owner_hash=$null;connections=[int]0;extra='x'}},
  @{name='invalid-state';value=[pscustomobject]@{state='unknown';oid_hash=$null;owner_hash=$null;connections=[int]0}},
  @{name='uppercase-state';value=[pscustomobject]@{state='ABSENT';oid_hash=$null;owner_hash=$null;connections=[int]0}},
  @{name='state-non-string';value=[pscustomobject]@{state=1;oid_hash=$null;owner_hash=$null;connections=[int]0}},
  @{name='absent-hash';value=[pscustomobject]@{state='absent';oid_hash=('a'*64);owner_hash=$null;connections=[int]0}},
  @{name='absent-owner';value=[pscustomobject]@{state='absent';oid_hash=$null;owner_hash=('b'*64);connections=[int]0}},
  @{name='present-null';value=[pscustomobject]@{state='existing_empty';oid_hash=$null;owner_hash=$null;connections=[int]0}},
  @{name='present-partial';value=[pscustomobject]@{state='eligible';oid_hash=('a'*64);owner_hash=$null;connections=[int]0}},
  @{name='uppercase-hash';value=[pscustomobject]@{state='eligible';oid_hash=('A'*64);owner_hash=('b'*64);connections=[int]0}},
  @{name='connections-int64';value=[pscustomobject]@{state='absent';oid_hash=$null;owner_hash=$null;connections=[int64]0}},
  @{name='connections-string';value=[pscustomobject]@{state='absent';oid_hash=$null;owner_hash=$null;connections='0'}},
  @{name='connections-negative';value=[pscustomobject]@{state='absent';oid_hash=$null;owner_hash=$null;connections=[int]-1}}
)
foreach($case in $invalidCatalogs){Assert-Throws {Assert-StageBCatalog $case.value} "catalog $($case.name)"}
$a=New-FakeAdapter $m; $a.Catalog={param($target) $script:catalogCalls++; [pscustomobject]@{state='absent';oid_hash=('a'*64);owner_hash=$null;connections=[int]0}}; $r=Invoke-StageBSequence $m $a
Assert-True ($script:catalogCalls -eq 1 -and $script:createCalls -eq 0 -and -not($script:events -contains 'pg_restore')) 'invalid initial catalog precedes create restore'
$a=New-FakeAdapter $m; $a.Catalog={param($target) $script:catalogCalls++; if($script:catalogCalls -eq 1){[pscustomobject]@{state='absent';oid_hash=$null;owner_hash=$null;connections=[int]0}}else{[pscustomobject]@{state='existing_empty';oid_hash=$null;owner_hash=$null;connections=[int]0}}}; $r=Invoke-StageBSequence $m $a
Assert-True ($script:catalogCalls -eq 2 -and $script:createCalls -eq 1 -and -not($script:events -contains 'pg_restore')) 'invalid post-create catalog precedes restore'

$validState=New-CurrentState $m
Assert-StageBCurrentState $m $validState
$stateCases=@(
  @{name='top-missing';change={param($x) $x.psobject.Properties.Remove('jobs')}},
  @{name='top-extra';change={param($x) $x|Add-Member extra 'x'}},
  @{name='jobs-int64';change={param($x) $x.jobs=[int64]0}},
  @{name='jobs-string';change={param($x) $x.jobs='0'}},
  @{name='jobs-nonzero';change={param($x) $x.jobs=[int]1}},
  @{name='baseline-malformed';change={param($x) $x.source_baseline_hash='bad'}},
  @{name='source-extra';change={param($x) $x.source|Add-Member extra 'x'}},
  @{name='source-non-string';change={param($x) $x.source.oid_hash=1}},
  @{name='source-drift';change={param($x) $x.source.oid_hash=('d'*64)}},
  @{name='restore-state';change={param($x) $x.restore.state='eligible'}},
  @{name='restore-state-uppercase';change={param($x) $x.restore.state='ABSENT'}},
  @{name='restore-drift';change={param($x) $x.restore.owner_hash=('d'*64)}},
  @{name='clients-drift';change={param($x) $x.clients.pg_dump_hash=('d'*64)}},
  @{name='capacity-int32';change={param($x) $x.storage.capacity_bytes=[int]100}},
  @{name='required-int32';change={param($x) $x.storage.required_bytes=[int]10}},
  @{name='retention-int64';change={param($x) $x.storage.retention_days=[int64]1}},
  @{name='capacity-low';change={param($x) $x.storage.capacity_bytes=[int64]1}},
  @{name='required-drift';change={param($x) $x.storage.required_bytes=[int64]11}},
  @{name='root-drift';change={param($x) $x.storage.root_hash=('d'*64)}},
  @{name='owner-extra';change={param($x) $x.owners|Add-Member extra 'x'}},
  @{name='owner-drift';change={param($x) $x.owners.cleanup_owner_hash=('d'*64)}},
  @{name='services-missing-readback';change={param($x) $x.services.psobject.Properties.Remove('worker_state')}},
  @{name='worker-not-running';change={param($x) $x.services.worker_state='stopped'}},
  @{name='web-non-string';change={param($x) $x.services.web_state=1}},
  @{name='service-hash-drift';change={param($x) $x.services.worker_hash=('d'*64)}},
  @{name='stop-order-drift';change={param($x) $x.services.stop_order=@('web','worker')}},
  @{name='order-non-string';change={param($x) $x.services.recovery_order=@('web',1)}}
)
foreach($case in $stateCases){$a=New-FakeAdapter $m; & $case.change $script:state; Assert-Throws {Assert-StageBCurrentState $m $script:state} "state $($case.name)"; $r=Invoke-StageBSequence $m $a; Assert-True ($r.status -eq 'failed' -and $script:mutations -eq 0 -and $script:events.Count -eq 0) "state $($case.name) zero mutation"}
$a=New-FakeAdapter $m; $a.State={param($manifest) $null}; Assert-Throws {Assert-StageBCurrentState $m $null} 'state null'; $r=Invoke-StageBSequence $m $a; Assert-True ($r.status -eq 'failed' -and $script:mutations -eq 0) 'state null zero mutation'

$validDump=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('a'*64)}
Assert-StageBPgDumpResult $validDump
$invalidDumpResults=@(
  @{name='null';value=$null},
  @{name='non-object';value='invalid'},
  @{name='missing-property';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1}},
  @{name='extra-property';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('a'*64);extra='x'}},
  @{name='success-false';value=[pscustomobject]@{success=$false;exit_code=[int]0;size=[int64]1;hash=('a'*64)}},
  @{name='success-int-truthy';value=[pscustomobject]@{success=1;exit_code=[int]0;size=[int64]1;hash=('a'*64)}},
  @{name='success-string-truthy';value=[pscustomobject]@{success='true';exit_code=[int]0;size=[int64]1;hash=('a'*64)}},
  @{name='exit-nonzero';value=[pscustomobject]@{success=$true;exit_code=[int]1;size=[int64]1;hash=('a'*64)}},
  @{name='exit-int64';value=[pscustomobject]@{success=$true;exit_code=[int64]0;size=[int64]1;hash=('a'*64)}},
  @{name='exit-string';value=[pscustomobject]@{success=$true;exit_code='0';size=[int64]1;hash=('a'*64)}},
  @{name='size-zero';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]0;hash=('a'*64)}},
  @{name='size-negative';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]-1;hash=('a'*64)}},
  @{name='size-int32';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int]1;hash=('a'*64)}},
  @{name='size-string';value=[pscustomobject]@{success=$true;exit_code=[int]0;size='1';hash=('a'*64)}},
  @{name='hash-null';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=$null}},
  @{name='hash-uppercase';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('A'*64)}},
  @{name='hash-malformed';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash='abc'}},
  @{name='hash-non-string';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=1}}
)
foreach($case in $invalidDumpResults) {
  Assert-Throws {Assert-StageBPgDumpResult $case.value} "pg_dump $($case.name)"
  $a=New-FakeAdapter $m '' $case.value
  $r=Invoke-StageBSequence $m $a
  Assert-True ($r.status -eq 'failed' -and $r.live_blocked -eq $true -and $r.criterion_8 -eq 'not_evaluable') "pg_dump $($case.name) failed safely"
  Assert-True (($script:events -join ',') -eq 'stop-worker,stop-web,pg_dump,start-web,start-worker') "pg_dump $($case.name) ordering"
  Assert-True ($script:catalogCalls -eq 0 -and $script:createCalls -eq 0 -and $script:dropCalls -eq 0) "pg_dump $($case.name) no downstream callbacks"
}

$validList=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('b'*64)}
Assert-StageBPgRestoreListResult $validList
$invalidListResults=@(
  @{name='null';value=$null},
  @{name='non-object';value='invalid'},
  @{name='missing-property';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1}},
  @{name='extra-property';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('b'*64);extra='x'}},
  @{name='success-false';value=[pscustomobject]@{success=$false;exit_code=[int]0;size=[int64]1;hash=('b'*64)}},
  @{name='success-int-truthy';value=[pscustomobject]@{success=1;exit_code=[int]0;size=[int64]1;hash=('b'*64)}},
  @{name='success-string-truthy';value=[pscustomobject]@{success='true';exit_code=[int]0;size=[int64]1;hash=('b'*64)}},
  @{name='exit-nonzero';value=[pscustomobject]@{success=$true;exit_code=[int]1;size=[int64]1;hash=('b'*64)}},
  @{name='exit-int64';value=[pscustomobject]@{success=$true;exit_code=[int64]0;size=[int64]1;hash=('b'*64)}},
  @{name='exit-string';value=[pscustomobject]@{success=$true;exit_code='0';size=[int64]1;hash=('b'*64)}},
  @{name='size-zero';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]0;hash=('b'*64)}},
  @{name='size-negative';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]-1;hash=('b'*64)}},
  @{name='size-int32';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int]1;hash=('b'*64)}},
  @{name='size-string';value=[pscustomobject]@{success=$true;exit_code=[int]0;size='1';hash=('b'*64)}},
  @{name='hash-null';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=$null}},
  @{name='hash-uppercase';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('B'*64)}},
  @{name='hash-malformed';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash='abc'}},
  @{name='hash-non-string';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=1}}
)
foreach($case in $invalidListResults) {
  Assert-Throws {Assert-StageBPgRestoreListResult $case.value} "pg_restore_list $($case.name)"
  $a=New-FakeAdapter $m -ListResult $case.value
  $r=Invoke-StageBSequence $m $a
  Assert-True ($r.status -eq 'failed' -and $r.live_blocked -eq $true -and $r.criterion_8 -eq 'not_evaluable') "pg_restore_list $($case.name) failed safely"
  Assert-True ($r.dump_hash -ceq (Get-StageBTextHash 'dump')) "pg_restore_list $($case.name) retains dump hash"
  Assert-True (($script:events -join ',') -eq 'stop-worker,stop-web,pg_dump,pg_restore_list,start-web,start-worker') "pg_restore_list $($case.name) ordering"
  Assert-True ($script:catalogCalls -eq 0 -and $script:createCalls -eq 0 -and $script:restoreSnapshotCalls -eq 0 -and $script:dropCalls -eq 0) "pg_restore_list $($case.name) no downstream callbacks"
}

$validRestore=[pscustomobject]@{success=$true;exit_code=[int]0}
Assert-StageBPgRestoreResult $validRestore
$invalidRestoreResults=@(
  @{name='null';value=$null},
  @{name='non-object';value='invalid'},
  @{name='missing-property';value=[pscustomobject]@{success=$true}},
  @{name='extra-property';value=[pscustomobject]@{success=$true;exit_code=[int]0;extra='x'}},
  @{name='success-false';value=[pscustomobject]@{success=$false;exit_code=[int]0}},
  @{name='success-int-truthy';value=[pscustomobject]@{success=1;exit_code=[int]0}},
  @{name='success-string-truthy';value=[pscustomobject]@{success='true';exit_code=[int]0}},
  @{name='exit-nonzero';value=[pscustomobject]@{success=$true;exit_code=[int]1}},
  @{name='exit-int64';value=[pscustomobject]@{success=$true;exit_code=[int64]0}},
  @{name='exit-string';value=[pscustomobject]@{success=$true;exit_code='0'}}
)
foreach($case in $invalidRestoreResults) {
  Assert-Throws {Assert-StageBPgRestoreResult $case.value} "pg_restore $($case.name)"
  $a=New-FakeAdapter $m -RestoreResult $case.value
  $r=Invoke-StageBSequence $m $a
  Assert-True ($r.status -eq 'failed' -and $r.live_blocked -eq $true -and $r.criterion_8 -eq 'not_evaluable' -and $r.error_code -eq 'stage_b_operation_failed') "pg_restore $($case.name) failed safely"
  Assert-True ($r.dump_hash -ceq (Get-StageBTextHash 'dump')) "pg_restore $($case.name) retains dump hash"
  Assert-True (($script:events -join ',') -eq 'stop-worker,stop-web,pg_dump,pg_restore_list,create,pg_restore,start-web,start-worker') "pg_restore $($case.name) ordering"
  Assert-True ($script:catalogCalls -eq 2 -and $script:createCalls -eq 1) "pg_restore $($case.name) target prepared"
  Assert-True ($script:sourceSnapshotCalls -eq 1 -and $script:restoreSnapshotCalls -eq 0 -and $script:dropCalls -eq 0) "pg_restore $($case.name) no downstream snapshots or drop"
}

Assert-StageBServiceResult ([pscustomobject]@{success=$true;state='stopped'}) 'stop'
Assert-StageBServiceResult ([pscustomobject]@{success=$true;state='running'}) 'start'
$invalidServiceResults=@(
  @{name='null';value=$null;action='stop'},
  @{name='non-object';value='invalid';action='stop'},
  @{name='missing';value=[pscustomobject]@{success=$true};action='stop'},
  @{name='extra';value=[pscustomobject]@{success=$true;state='stopped';extra='x'};action='stop'},
  @{name='false';value=[pscustomobject]@{success=$false;state='stopped'};action='stop'},
  @{name='truthy-int';value=[pscustomobject]@{success=1;state='stopped'};action='stop'},
  @{name='truthy-string';value=[pscustomobject]@{success='true';state='stopped'};action='stop'},
  @{name='state-non-string';value=[pscustomobject]@{success=$true;state=1};action='stop'},
  @{name='stop-wrong-state';value=[pscustomobject]@{success=$true;state='running'};action='stop'},
  @{name='start-wrong-state';value=[pscustomobject]@{success=$true;state='stopped'};action='start'}
)
foreach($case in $invalidServiceResults){Assert-Throws {Assert-StageBServiceResult $case.value $case.action} "service result $($case.name)"}

# Focused Service Ownership Tests
$testCases=@(
  @{name='1. state/preflight failure before any stop'; failure='state'; expectStatus='failed'; expectStarts=@(); expectStages=@(); expectMutations=0; desc='no start-* calls'},
  @{name='2. first stop (worker) throws'; failure='service-stop-worker'; expectStatus='failed'; expectStarts=@(); expectStages=@(); expectMutations=0; desc='no service owned, no start'},
  @{name='3. first stop returns {success=$false}'; failure='service-false-stop-worker'; expectStatus='failed'; expectStarts=@(); expectStages=@(); expectMutations=0; desc='fail closed, no later stop, no start'},
  @{name='4. worker stop succeeds, web stop throws'; failure='service-stop-web'; expectStatus='failed'; expectStarts=@('start-worker'); expectStages=@('stop_worker','start_worker'); expectMutations=1; desc='only start-worker occurs'},
  @{name='5. worker stop succeeds, web stop returns {success=$false}'; failure='service-false-stop-web'; expectStatus='failed'; expectStarts=@('start-worker'); expectStages=@('stop_worker','start_worker'); expectMutations=1; desc='only start-worker occurs'},
  @{name='6. both stops succeed, later operation fails'; failure='catalog'; expectStatus='failed'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_web','start_worker'); expectMutations=2; desc='recovery calls start-web,start-worker'},
  @{name='7. all succeed'; failure=''; expectStatus='success'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_web','start_worker'); expectMutations=2; desc='existing order preserved'},
  @{name='8. owned service start returns {success=$false}'; failure='service-false-start-web'; expectStatus='failed'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_worker'); expectMutations=2; desc='fail-closed start, final failed, start_worker still attempted'},
  @{name='9. owned service start returns malformed or throws'; failure='service-malformed-start-web'; expectStatus='failed'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_worker'); expectMutations=2; desc='malformed/throw forces failed, start_worker still attempted'},
  @{name='10. start-web fails, start-worker still attempted once, no retry'; failure='service-throw-start-web'; expectStatus='failed'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_worker'); expectMutations=2; desc='no duplicate start-web attempt'},
  @{name='11. stages only for strict-success callbacks'; failure=''; expectStatus='success'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_web','start_worker'); expectMutations=2; desc='all strict-success stages recorded'},
  @{name='12. no DropRestore invoked'; failure=''; expectStatus='success'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_web','start_worker'); expectMutations=2; desc='no automatic drop'},
  @{name='13. first stop (worker) returns {success=1} (int)'; failure='service-int1-stop-worker'; expectStatus='failed'; expectStarts=@(); expectStages=@(); expectMutations=0; desc='int 1 rejected, no service owned, no start'},
  @{name='14. first stop (worker) returns {success="true"} (string)'; failure='service-strtrue-stop-worker'; expectStatus='failed'; expectStarts=@(); expectStages=@(); expectMutations=0; desc='string true rejected, no service owned, no start'},
  @{name='15. worker stop succeeds, web stop returns {success=1}'; failure='service-int1-stop-web'; expectStatus='failed'; expectStarts=@('start-worker'); expectStages=@('stop_worker','start_worker'); expectMutations=1; desc='int 1 rejected for web, only worker owned, start-worker only'},
  @{name='16. worker stop succeeds, web stop returns {success="true"}'; failure='service-strtrue-stop-web'; expectStatus='failed'; expectStarts=@('start-worker'); expectStages=@('stop_worker','start_worker'); expectMutations=1; desc='string true rejected for web, only worker owned, start-worker only'},
  @{name='17. both stops succeed, start-web returns {success=1}'; failure='service-int1-start-web'; expectStatus='failed'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_worker'); expectMutations=2; desc='int 1 rejected for start-web, start-worker still attempted'},
  @{name='18. both stops succeed, start-web returns {success="true"}'; failure='service-strtrue-start-web'; expectStatus='failed'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_worker'); expectMutations=2; desc='string true rejected for start-web, start-worker still attempted'},
  @{name='19. both stops succeed, start-worker returns {success=1}'; failure='service-int1-start-worker'; expectStatus='failed'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_web'); expectMutations=2; desc='int 1 rejected for start-worker, no start_worker stage'},
  @{name='20. both stops succeed, start-worker returns {success="true"}'; failure='service-strtrue-start-worker'; expectStatus='failed'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_web'); expectMutations=2; desc='string true rejected for start-worker, no start_worker stage'},
  @{name='21. first stop reports running'; failure='service-state-stop-worker'; expectStatus='failed'; expectStarts=@(); expectStages=@(); expectMutations=0; desc='wrong observed stop state establishes no ownership'},
  @{name='22. start-web reports stopped'; failure='service-state-start-web'; expectStatus='failed'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_worker'); expectMutations=2; desc='wrong observed start state fails but recovery continues'}
)

$passed=0; $failed=0
foreach($tc in $testCases){
  try {
    $a=New-FakeAdapter $m $tc.failure
    $r=Invoke-StageBSequence $m $a
    Write-Host "DEBUG $($tc.name): events=$($script:events -join ','), mutations=$($script:mutations), status=$($r.status), stages=$($r.stages.Count)"
    $ok=$true
    if($r.status -ne $tc.expectStatus){Write-Host "FAIL $($tc.name): status=$($r.status) expected=$($tc.expectStatus)"; $ok=$false}
    $actualStarts=$script:events|Where-Object {$_ -like 'start-*'}
    if(($actualStarts -join ',') -ne ($tc.expectStarts -join ',')){Write-Host "FAIL $($tc.name): starts=($($actualStarts -join ',')) expected=($($tc.expectStarts -join ','))"; $ok=$false}
    $actualStages=$r.stages|Where-Object {$_.state -eq 'succeeded'}|ForEach-Object {$_.stage}
    if(($actualStages -join ',') -ne ($tc.expectStages -join ',')){Write-Host "FAIL $($tc.name): stages=($($actualStages -join ',')) expected=($($tc.expectStages -join ','))"; $ok=$false}
    if($script:mutations -ne $tc.expectMutations){Write-Host "FAIL $($tc.name): mutations=$($script:mutations) expected=$($tc.expectMutations)"; $ok=$false}
    if($script:events -contains 'drop'){Write-Host "FAIL $($tc.name): DropRestore invoked"; $ok=$false}
    if($ok){Write-Host "PASS $($tc.name)"; $passed++}else{$failed++}
  } catch {
    Write-Host "EXCEPTION $($tc.name): $($_.Exception.Message)"
    Write-Host "FAIL $($tc.name): exception $($_.Exception.Message)"
    $failed++
  }
}
Write-Host "Service ownership + invalid truthy tests: $passed passed, $failed failed"
if($failed -gt 0){throw "Service ownership tests failed"}

# Original regression tests
foreach($case in @('state','pg_dump','pg_restore_list','catalog')) {$a=New-FakeAdapter $m $case; if($case -eq 'state'){$script:state.jobs=1}; $r=Invoke-StageBSequence $m $a; Assert-True ($r.status -eq 'failed') "$case failed"; if($case -eq 'state'){Assert-True ($script:mutations -eq 0) "$case zero mutation"}}
$a=New-FakeAdapter $m; $r=Invoke-StageBSequence $m $a; if($r.status -ne 'success'){$r|ConvertTo-Json -Depth 10|Write-Output}; Assert-True ($r.status -eq 'success') 'success'; Assert-True (($script:events -join ',') -eq 'stop-worker,stop-web,pg_dump,pg_restore_list,create,pg_restore,start-web,start-worker') 'order'; Assert-True (-not($script:events -contains 'drop')) 'no automatic cleanup'
$a=New-FakeAdapter $m 'service-start-web'; $r=Invoke-StageBSequence $m $a; Assert-True ($r.status -eq 'failed') 'recovery failure'
foreach($case in @('bad-final','cleanup-guard')) {$a=New-FakeAdapter $m; if($case -eq 'cleanup-guard'){$a.Catalog={param($target) [pscustomobject]@{state='eligible';oid_hash=$m.restore.oid_hash;owner_hash=$m.owners.restore_owner_hash;connections=1}}}; $final=if($case -eq 'bad-final'){[pscustomobject]@{status='failed';dump_hash=(Get-StageBTextHash 'dump');manifest_sha256=('a'*64)}}else{[pscustomobject]@{status='success';dump_hash=(Get-StageBTextHash 'dump');manifest_sha256=('a'*64)}}; Assert-Throws {Invoke-StageBCleanup $m $a $final ('a'*64)} $case; Assert-True ($script:mutations -eq 0) "$case zero mutation"}
try {throw 'password host db C:\\secret'} catch {Assert-True ((Get-StageBRedactedError $_) -eq 'stage_b_operation_failed') 'redaction'}
$planRoot=Join-Path ([IO.Path]::GetTempPath()) ('stage-b-plan-'+[guid]::NewGuid())
New-Item -ItemType Directory -Path $planRoot|Out-Null
try {
  $script:PlanOnly=$true; $script:Execute=$false; $script:Cleanup=$false
  $script:PendingManifestPath=Join-Path $planRoot 'pending.json'
  $script:planAdapter=New-FakeAdapter $m
  $script:pendingCalls=0
  $script:planAdapter.Pending={param() $script:pendingCalls++; $script:manifest}
  $result=Invoke-StageBMain {param() $script:planAdapter}
  Assert-True ($result.status -eq 'success' -and (Test-StageBHash $result.manifest_sha256)) 'plan success metadata'
  Assert-True ($script:pendingCalls -eq 1 -and $script:mutations -eq 0) 'plan only pending callback'
  $checksumPath=Join-Path $planRoot 'checksums.sha256'
  $checksum=[IO.File]::ReadAllText($checksumPath,[Text.Encoding]::UTF8)
  Assert-True ($checksum -cmatch '^([a-f0-9]{64})  pending\.json\n$') 'plan checksum format'
  Assert-True ($Matches[1] -ceq (Get-StageBSha256 $script:PendingManifestPath)) 'plan checksum recomputation'
  Assert-True (@(Get-ChildItem -LiteralPath $planRoot -Filter '*.tmp').Count -eq 0) 'plan no temporary residue'

  $existingRoot=Join-Path $planRoot 'existing'; New-Item -ItemType Directory -Path $existingRoot|Out-Null
  $script:PendingManifestPath=Join-Path $existingRoot 'pending.json'
  [IO.File]::WriteAllText($script:PendingManifestPath,'existing',[Text.UTF8Encoding]::new($false))
  Assert-Throws {Invoke-StageBMain {param() $script:planAdapter}} 'plan existing output'
  Assert-True (([IO.File]::ReadAllText($script:PendingManifestPath) -ceq 'existing') -and -not(Test-Path (Join-Path $existingRoot 'checksums.sha256'))) 'plan existing zero mutation'

  $existingChecksumRoot=Join-Path $planRoot 'existing-checksum'; New-Item -ItemType Directory -Path $existingChecksumRoot|Out-Null
  $script:PendingManifestPath=Join-Path $existingChecksumRoot 'pending.json'
  $existingChecksumPath=Join-Path $existingChecksumRoot 'checksums.sha256'
  [IO.File]::WriteAllText($existingChecksumPath,'existing-checksum',[Text.UTF8Encoding]::new($false))
  Assert-Throws {Invoke-StageBMain {param() $script:planAdapter}} 'plan existing checksum'
  Assert-True (([IO.File]::ReadAllText($existingChecksumPath) -ceq 'existing-checksum') -and -not(Test-Path $script:PendingManifestPath)) 'plan existing checksum zero mutation'

  $invalidRoot=Join-Path $planRoot 'invalid'; New-Item -ItemType Directory -Path $invalidRoot|Out-Null
  $script:PendingManifestPath=Join-Path $invalidRoot 'pending.json'
  $script:planAdapter.Pending={param() $bad=Copy-Manifest $script:manifest; $bad.live_blocked=$false; $bad}
  Assert-Throws {Invoke-StageBMain {param() $script:planAdapter}} 'plan invalid pending'
  Assert-True (@(Get-ChildItem -LiteralPath $invalidRoot -Force).Count -eq 0) 'plan invalid no residue'

  $privacyRoot=Join-Path $planRoot 'privacy'; New-Item -ItemType Directory -Path $privacyRoot|Out-Null
  $script:PendingManifestPath=Join-Path $privacyRoot 'pending.json'
  $script:privacyAdapter=New-StageBProductionAdapter {param() throw 'SENTINEL-CREDENTIAL raw-host'} {param() 0}
  try {Invoke-StageBMain {param() $script:privacyAdapter}; throw 'privacy failure expected'} catch {
   Assert-True ($_.Exception.Message -notmatch 'SENTINEL|raw-host') 'plan privacy error'
  }
  Assert-True (@(Get-ChildItem -LiteralPath $privacyRoot -Force).Count -eq 0) 'plan privacy no residue'

  $verifyRoot=Join-Path $planRoot 'verify'; New-Item -ItemType Directory -Path $verifyRoot|Out-Null
  $script:PendingManifestPath=Join-Path $verifyRoot 'pending.json'
  $script:planAdapter=New-FakeAdapter $m
  Assert-Throws {Invoke-StageBMain {param() $script:planAdapter} {param($manifestPath,$checksumPath) [IO.File]::WriteAllText($checksumPath,'bad',[Text.UTF8Encoding]::new($false))}} 'plan verification failure'
  Assert-True (@(Get-ChildItem -LiteralPath $verifyRoot -Force).Count -eq 0) 'plan verification cleanup'

  $script:PendingManifestPath=Join-Path (Join-Path $planRoot 'missing') 'pending.json'
  Assert-Throws {Invoke-StageBMain {param() $script:planAdapter}} 'plan write failure'
  Assert-True (-not(Test-Path (Join-Path $planRoot 'missing'))) 'plan write no residue'

  $nullJobsRoot=Join-Path $planRoot 'null-jobs'; New-Item -ItemType Directory -Path $nullJobsRoot|Out-Null
  $script:PendingManifestPath=Join-Path $nullJobsRoot 'pending.json'
  $nullJobsAdapter=New-StageBProductionAdapter {param() $script:readOnlyConfiguration} {param() $null}
  Assert-Throws {Invoke-StageBMain {param() $nullJobsAdapter}} 'null jobs'
  Assert-True (@(Get-ChildItem -LiteralPath $nullJobsRoot -Force).Count -eq 0) 'null jobs no residue'

  $stringJobsRoot=Join-Path $planRoot 'string-jobs'; New-Item -ItemType Directory -Path $stringJobsRoot|Out-Null
  $script:PendingManifestPath=Join-Path $stringJobsRoot 'pending.json'
  $stringJobsAdapter=New-StageBProductionAdapter {param() $script:readOnlyConfiguration} {param() 'not-a-number'}
  Assert-Throws {Invoke-StageBMain {param() $stringJobsAdapter}} 'string jobs'
  Assert-True (@(Get-ChildItem -LiteralPath $stringJobsRoot -Force).Count -eq 0) 'string jobs no residue'

  $arrayJobsRoot=Join-Path $planRoot 'array-jobs'; New-Item -ItemType Directory -Path $arrayJobsRoot|Out-Null
  $script:PendingManifestPath=Join-Path $arrayJobsRoot 'pending.json'
  $arrayJobsAdapter=New-StageBProductionAdapter {param() $script:readOnlyConfiguration} {param() @(1,2)}
  Assert-Throws {Invoke-StageBMain {param() $arrayJobsAdapter}} 'array jobs'
  Assert-True (@(Get-ChildItem -LiteralPath $arrayJobsRoot -Force).Count -eq 0) 'array jobs no residue'

  $negJobsRoot=Join-Path $planRoot 'neg-jobs'; New-Item -ItemType Directory -Path $negJobsRoot|Out-Null
  $script:PendingManifestPath=Join-Path $negJobsRoot 'pending.json'
  $negJobsAdapter=New-StageBProductionAdapter {param() $script:readOnlyConfiguration} {param() -1}
  Assert-Throws {Invoke-StageBMain {param() $negJobsAdapter}} 'neg jobs'
  Assert-True (@(Get-ChildItem -LiteralPath $negJobsRoot -Force).Count -eq 0) 'neg jobs no residue'

  $nonzeroJobsRoot=Join-Path $planRoot 'nonzero-jobs'; New-Item -ItemType Directory -Path $nonzeroJobsRoot|Out-Null
  $script:PendingManifestPath=Join-Path $nonzeroJobsRoot 'pending.json'
  $nonzeroJobsAdapter=New-StageBProductionAdapter {param() $script:readOnlyConfiguration} {param() 3}
  Assert-Throws {Invoke-StageBMain {param() $nonzeroJobsAdapter}} 'nonzero jobs'
  Assert-True (@(Get-ChildItem -LiteralPath $nonzeroJobsRoot -Force).Count -eq 0) 'nonzero jobs no residue'
} finally {
 $script:PlanOnly=$false; $script:PendingManifestPath=$null
 Remove-Item -LiteralPath $planRoot -Recurse -Force
}

# Execute evidence publication: checksum/approval linkage, exact schema, privacy, atomicity, tamper, and residue.
$executeRoot=Join-Path ([IO.Path]::GetTempPath()) ('stage-b-execute-'+[guid]::NewGuid())
New-Item -ItemType Directory -Path $executeRoot|Out-Null
try {
  $script:PlanOnly=$false; $script:Execute=$true; $script:Cleanup=$false
  $script:PendingManifestPath=Join-Path $executeRoot 'pending.json'
  $script:ApprovalPath=Join-Path $executeRoot 'approval.json'
  function Reset-ExecuteInputs {
    [IO.File]::WriteAllText($script:PendingManifestPath,(ConvertTo-StageBCanonicalJson $m)+"`n",[Text.UTF8Encoding]::new($false))
    $script:executeManifestHash=Get-StageBSha256 $script:PendingManifestPath
    [IO.File]::WriteAllText((Join-Path $executeRoot 'checksums.sha256'),($script:executeManifestHash+'  pending.json'+"`n"),[Text.UTF8Encoding]::new($false))
    $approval=[pscustomobject]@{scope='stage-b-backup-restore';action='execute';manifest_sha256=$script:executeManifestHash;approved_at=[DateTimeOffset]::UtcNow.ToString('o');approver_hash=('d'*64)}
    [IO.File]::WriteAllText($script:ApprovalPath,(ConvertTo-StageBCanonicalJson $approval)+"`n",[Text.UTF8Encoding]::new($false))
  }
  Reset-ExecuteInputs
  $script:EvidenceRoot=Join-Path $executeRoot 'evidence-success'
  $script:executeAdapter=New-FakeAdapter $m
  $script:stagingFinalWasAbsent=$false
  $published=Invoke-StageBMain {param() $script:executeAdapter} {param($executionPath,$checksumPath) $script:stagingFinalWasAbsent=-not(Test-Path -LiteralPath $script:EvidenceRoot)}
  Assert-True ($published.status -ceq 'success' -and $published.dump_hash -ceq (Get-StageBTextHash 'dump') -and $published.manifest_sha256 -ceq $script:executeManifestHash) 'execute exact returned evidence'
  Assert-True ($script:stagingFinalWasAbsent -and (($script:events -join ',') -ceq 'stop-worker,stop-web,pg_dump,pg_restore_list,create,pg_restore,start-web,start-worker') -and -not($script:events -contains 'drop')) 'execute order staging absence no drop'
  $executionJson=[IO.File]::ReadAllText((Join-Path $script:EvidenceRoot 'execution.json'),[Text.Encoding]::UTF8)
  $executionFile=$executionJson|ConvertFrom-Json
  Assert-True ((@($executionFile.psobject.Properties.Name|Sort-Object)-join ',') -ceq 'dump_hash,manifest_sha256,status') 'execute exact file schema'
  Assert-True ((ConvertTo-StageBCanonicalJson $published) -ceq (ConvertTo-StageBCanonicalJson $executionFile)) 'execute returned file equality'
  Assert-True ((@((Get-ChildItem -LiteralPath $script:EvidenceRoot -Force).Name|Sort-Object)-join ',') -ceq 'checksums.sha256,execution.json') 'execute exact inventory'
  $executionChecksum=[IO.File]::ReadAllText((Join-Path $script:EvidenceRoot 'checksums.sha256'),[Text.Encoding]::UTF8)
  Assert-True ($executionChecksum -cmatch '^([a-f0-9]{64})  execution\.json\n$' -and $Matches[1] -ceq (Get-StageBSha256 (Join-Path $script:EvidenceRoot 'execution.json'))) 'execute checksum recomputation'

  $validEvidence=[pscustomobject]@{status='failed';dump_hash=$null;manifest_sha256=$script:executeManifestHash}
  Assert-StageBExecutionEvidence $validEvidence $script:executeManifestHash
  $badEvidence=@(
    $null,
    'failed',
    [pscustomobject]@{status='success';dump_hash=$null;manifest_sha256=$script:executeManifestHash},
    [pscustomobject]@{status='Success';dump_hash=('a'*64);manifest_sha256=$script:executeManifestHash},
    [pscustomobject]@{status=$true;dump_hash=('a'*64);manifest_sha256=$script:executeManifestHash},
    [pscustomobject]@{status='failed';dump_hash=1;manifest_sha256=$script:executeManifestHash},
    [pscustomobject]@{status='failed';dump_hash=$null;manifest_sha256=$script:executeManifestHash;extra='x'}
  )
  foreach($bad in $badEvidence){Assert-Throws {Assert-StageBExecutionEvidence $bad $script:executeManifestHash} 'malformed execution evidence'}

  $script:EvidenceRoot=Join-Path $executeRoot 'evidence-private'
  $script:executeAdapter=New-FakeAdapter $m
  $script:executeAdapter.Snapshot={param($target,$mode,$expectedSourceOidHash) throw 'SENTINEL-CREDENTIAL user@raw-host C:\secret\dump'}
  $private=Invoke-StageBMain {param() $script:executeAdapter}
  $privateText=[IO.File]::ReadAllText((Join-Path $script:EvidenceRoot 'execution.json'),[Text.Encoding]::UTF8)
  Assert-True ($private.status -ceq 'failed' -and $null -eq $private.dump_hash -and $privateText -notmatch 'SENTINEL|raw-host|secret|user@') 'execute privacy failure evidence'
  Assert-True ((@(($privateText|ConvertFrom-Json).psobject.Properties.Name|Sort-Object)-join ',') -ceq 'dump_hash,manifest_sha256,status') 'execute privacy exact schema'

  $script:EvidenceRoot=Join-Path $executeRoot 'evidence-failed-with-dump'
  $script:executeAdapter=New-FakeAdapter $m 'pg_restore_list'
  $failedWithDump=Invoke-StageBMain {param() $script:executeAdapter}
  Assert-True ($failedWithDump.status -ceq 'failed' -and $failedWithDump.dump_hash -ceq (Get-StageBTextHash 'dump')) 'execute failed dump hash retention'

  $checksumPath=Join-Path $executeRoot 'checksums.sha256'
  $validChecksum=$script:executeManifestHash+'  pending.json'+"`n"
  $checksumCases=@(
    @{name='missing';bytes=$null},
    @{name='empty';bytes=''},
    @{name='malformed';bytes='bad'+"`n"},
    @{name='extra';bytes=$validChecksum+('a'*64)+'  pending.json'+"`n"},
    @{name='wrong-name';bytes=$script:executeManifestHash+'  other.json'+"`n"},
    @{name='uppercase';bytes=$script:executeManifestHash.ToUpperInvariant()+'  pending.json'+"`n"},
    @{name='mismatch';bytes=('e'*64)+'  pending.json'+"`n"}
  )
  foreach($case in $checksumCases){
    Reset-ExecuteInputs
    if($case.name -eq 'missing'){Remove-Item -LiteralPath $checksumPath -Force}else{[IO.File]::WriteAllText($checksumPath,$case.bytes,[Text.UTF8Encoding]::new($false))}
    $script:EvidenceRoot=Join-Path $executeRoot ('bad-checksum-'+$case.name)
    $script:executeAdapter=New-FakeAdapter $m
    Assert-Throws {Invoke-StageBMain {param() $script:executeAdapter}} ('execute checksum '+$case.name)
    Assert-True ($script:mutations -eq 0 -and $script:events.Count -eq 0 -and -not(Test-Path $script:EvidenceRoot)) ('execute checksum zero mutation '+$case.name)
  }

  Reset-ExecuteInputs
  $badApproval=Get-Content -Raw -LiteralPath $script:ApprovalPath|ConvertFrom-Json
  $badApproval.manifest_sha256='e'*64
  [IO.File]::WriteAllText($script:ApprovalPath,(ConvertTo-StageBCanonicalJson $badApproval)+"`n",[Text.UTF8Encoding]::new($false))
  $script:EvidenceRoot=Join-Path $executeRoot 'approval-mismatch'
  $script:executeAdapter=New-FakeAdapter $m
  Assert-Throws {Invoke-StageBMain {param() $script:executeAdapter}} 'execute approval mismatch'
  Assert-True ($script:mutations -eq 0 -and $script:events.Count -eq 0) 'execute approval zero mutation'

  Reset-ExecuteInputs
  $script:EvidenceRoot=Join-Path $executeRoot 'existing-destination'
  New-Item -ItemType Directory -Path $script:EvidenceRoot|Out-Null
  [IO.File]::WriteAllText((Join-Path $script:EvidenceRoot 'keep.txt'),'keep')
  $script:executeAdapter=New-FakeAdapter $m
  Assert-Throws {Invoke-StageBMain {param() $script:executeAdapter}} 'execute existing destination'
  Assert-True ($script:mutations -eq 0 -and (Get-Content (Join-Path $script:EvidenceRoot 'keep.txt')) -ceq 'keep') 'execute existing untouched'

  $script:EvidenceRoot=Join-Path $executeRoot 'existing-file'
  [IO.File]::WriteAllText($script:EvidenceRoot,'keep')
  $script:executeAdapter=New-FakeAdapter $m
  Assert-Throws {Invoke-StageBMain {param() $script:executeAdapter}} 'execute existing file'
  Assert-True ($script:mutations -eq 0 -and [IO.File]::ReadAllText($script:EvidenceRoot) -ceq 'keep') 'execute existing file untouched'

  $script:EvidenceRoot=''
  $script:executeAdapter=New-FakeAdapter $m
  Assert-Throws {Invoke-StageBMain {param() $script:executeAdapter}} 'execute empty destination'
  Assert-True ($script:mutations -eq 0) 'execute empty destination zero mutation'

  $script:EvidenceRoot=Join-Path (Join-Path $executeRoot 'missing-parent') 'evidence'
  $script:executeAdapter=New-FakeAdapter $m
  Assert-Throws {Invoke-StageBMain {param() $script:executeAdapter}} 'execute missing parent'
  Assert-True ($script:mutations -eq 0) 'execute missing parent zero mutation'

  foreach($tamper in @('unexpected','content','checksum','hook','race')){
    Reset-ExecuteInputs
    $script:EvidenceRoot=Join-Path $executeRoot ('tamper-'+$tamper)
    $script:executeAdapter=New-FakeAdapter $m
    $hook=switch($tamper){
      'unexpected' {{param($executionPath,$checksumPath) [IO.File]::WriteAllText((Join-Path ([IO.Path]::GetDirectoryName($executionPath)) 'extra.txt'),'x')}}
      'content' {{param($executionPath,$checksumPath) [IO.File]::WriteAllText($executionPath,'{}'+"`n",[Text.UTF8Encoding]::new($false))}}
      'checksum' {{param($executionPath,$checksumPath) [IO.File]::WriteAllText($checksumPath,('a'*64)+'  execution.json'+"`n",[Text.UTF8Encoding]::new($false))}}
      'hook' {{param($executionPath,$checksumPath) throw 'SENTINEL-HOOK C:\secret'}}
      'race' {{param($executionPath,$checksumPath) New-Item -ItemType Directory -Path $script:EvidenceRoot|Out-Null; [IO.File]::WriteAllText((Join-Path $script:EvidenceRoot 'keep.txt'),'keep')}}
    }
    try {Invoke-StageBMain {param() $script:executeAdapter} $hook; throw 'tamper failure expected'} catch {Assert-True ($_.Exception.Message -ceq 'stage_b_operation_failed') ('execute safe error '+$tamper)}
    if($tamper -eq 'race'){Assert-True ((Get-Content (Join-Path $script:EvidenceRoot 'keep.txt')) -ceq 'keep') 'execute race destination untouched'}else{Assert-True (-not(Test-Path $script:EvidenceRoot)) ('execute no partial '+$tamper)}
    Assert-True (@(Get-ChildItem -LiteralPath $executeRoot -Directory -Filter '.stage-b-evidence-*.tmp').Count -eq 0) ('execute no residue '+$tamper)
  }
} finally {
  $script:Execute=$false; $script:PendingManifestPath=$null; $script:ApprovalPath=$null; $script:EvidenceRoot=$null
  Remove-Item -LiteralPath $executeRoot -Recurse -Force
}
$root=Join-Path ([IO.Path]::GetTempPath()) ('stage-b-'+[guid]::NewGuid()); New-Item -ItemType Directory -Path $root|Out-Null; try {[IO.File]::WriteAllText((Join-Path $root 'z.txt'),'z');[IO.File]::WriteAllText((Join-Path $root 'a.txt'),'a');Write-StageBChecksums $root;Assert-True ((Get-Content (Join-Path $root 'checksums.sha256'))[0] -match '  a.txt$') 'checksum'} finally {Remove-Item -LiteralPath $root -Recurse -Force}
Write-Output 'Stage B pure validation tests passed'
