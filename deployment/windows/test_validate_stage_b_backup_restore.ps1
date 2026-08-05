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
$validDumpMax=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]::MaxValue;hash=('f'*64)}
Assert-StageBPgDumpResult $validDumpMax
$invalidDumpResults=@(
  @{name='null';value=$null},
  @{name='non-object';value='invalid'},
  @{name='missing-success';value=[pscustomobject]@{exit_code=[int]0;size=[int64]1;hash=('a'*64)}},
  @{name='missing-exit-code';value=[pscustomobject]@{success=$true;size=[int64]1;hash=('a'*64)}},
  @{name='missing-size';value=[pscustomobject]@{success=$true;exit_code=[int]0;hash=('a'*64)}},
  @{name='missing-hash';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1}},
  @{name='extra-property';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('a'*64);extra='x'}},
  @{name='success-null';value=[pscustomobject]@{success=$null;exit_code=[int]0;size=[int64]1;hash=('a'*64)}},
  @{name='success-false';value=[pscustomobject]@{success=$false;exit_code=[int]0;size=[int64]1;hash=('a'*64)}},
  @{name='success-int-truthy';value=[pscustomobject]@{success=1;exit_code=[int]0;size=[int64]1;hash=('a'*64)}},
  @{name='success-string-truthy';value=[pscustomobject]@{success='true';exit_code=[int]0;size=[int64]1;hash=('a'*64)}},
  @{name='success-float';value=[pscustomobject]@{success=[double]1;exit_code=[int]0;size=[int64]1;hash=('a'*64)}},
  @{name='exit-negative';value=[pscustomobject]@{success=$true;exit_code=[int]-1;size=[int64]1;hash=('a'*64)}},
  @{name='exit-nonzero';value=[pscustomobject]@{success=$true;exit_code=[int]1;size=[int64]1;hash=('a'*64)}},
  @{name='exit-int64';value=[pscustomobject]@{success=$true;exit_code=[int64]0;size=[int64]1;hash=('a'*64)}},
  @{name='exit-bool';value=[pscustomobject]@{success=$true;exit_code=$false;size=[int64]1;hash=('a'*64)}},
  @{name='exit-string';value=[pscustomobject]@{success=$true;exit_code='0';size=[int64]1;hash=('a'*64)}},
  @{name='exit-float';value=[pscustomobject]@{success=$true;exit_code=[double]0;size=[int64]1;hash=('a'*64)}},
  @{name='size-zero';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]0;hash=('a'*64)}},
  @{name='size-negative';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]-1;hash=('a'*64)}},
  @{name='size-int32';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int]1;hash=('a'*64)}},
  @{name='size-bool';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=$true;hash=('a'*64)}},
  @{name='size-string';value=[pscustomobject]@{success=$true;exit_code=[int]0;size='1';hash=('a'*64)}},
  @{name='size-float';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[double]1;hash=('a'*64)}},
  @{name='size-over-int64-max';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[decimal]9223372036854775808;hash=('a'*64)}},
  @{name='hash-null';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=$null}},
  @{name='hash-uppercase';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('A'*64)}},
  @{name='hash-malformed';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash='abc'}},
  @{name='hash-non-string';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=1}}
)
foreach($case in $invalidDumpResults) {
  try {Assert-StageBPgDumpResult $case.value; throw "pg_dump $($case.name) unexpectedly succeeded"} catch {Assert-True ($_.Exception.Message -ceq 'stage_b_pg_dump_result_invalid') "pg_dump $($case.name) privacy-safe reason"}
  $a=New-FakeAdapter $m '' $case.value
  $r=Invoke-StageBSequence $m $a
  Assert-True ($r.status -eq 'failed' -and $r.live_blocked -eq $true -and $r.criterion_8 -eq 'not_evaluable') "pg_dump $($case.name) failed safely"
  Assert-True (($script:events -join ',') -eq 'stop-worker,stop-web,pg_dump,start-web,start-worker') "pg_dump $($case.name) ordering"
  Assert-True ($script:catalogCalls -eq 0 -and $script:createCalls -eq 0 -and $script:dropCalls -eq 0) "pg_dump $($case.name) no downstream callbacks"
}
$dumpProviderSentinel='PG_DUMP_PROVIDER_SECRET raw-command=private-dump secret-db'
$a=New-FakeAdapter $m
$a.Process={param($operation,$arguments,$environment) $null=$script:events.Add($operation); throw $script:dumpProviderSentinel}
$r=Invoke-StageBSequence $m $a
$dumpErrorText=$r|ConvertTo-Json -Depth 10
Assert-True ($r.status -ceq 'failed' -and $r.error_code -ceq 'stage_b_operation_failed' -and $dumpErrorText -notmatch 'PG_DUMP_PROVIDER_SECRET|raw-command|private-dump|secret-db') 'pg_dump provider exception privacy-safe failure'
Assert-True (($script:events -join ',') -ceq 'stop-worker,stop-web,pg_dump,start-web,start-worker' -and $script:catalogCalls -eq 0 -and $script:createCalls -eq 0 -and $script:dropCalls -eq 0) 'pg_dump provider exception no downstream callbacks'
$malformedDumpSentinel='PG_DUMP_MALFORMED_SECRET'
$malformedDump=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('a'*64);diagnostic=$malformedDumpSentinel}
$a=New-FakeAdapter $m '' $malformedDump
$r=Invoke-StageBSequence $m $a
$dumpErrorText=$r|ConvertTo-Json -Depth 10
Assert-True ($r.status -ceq 'failed' -and $r.error_code -ceq 'stage_b_operation_failed' -and $dumpErrorText -notmatch $malformedDumpSentinel) 'pg_dump malformed provider privacy-safe failure'
Assert-True (($script:events -join ',') -ceq 'stop-worker,stop-web,pg_dump,start-web,start-worker' -and $script:catalogCalls -eq 0 -and $script:createCalls -eq 0 -and $script:dropCalls -eq 0) 'pg_dump malformed provider no downstream callbacks'

$validList=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('b'*64)}
Assert-StageBPgRestoreListResult $validList
$validListMax=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]::MaxValue;hash=('f'*64)}
Assert-StageBPgRestoreListResult $validListMax
$a=New-FakeAdapter $m -ListResult $validList
$r=Invoke-StageBSequence $m $a
$successListProperties=@($r.Keys|ForEach-Object {[string]$_}|Sort-Object)-join ','
Assert-True ($r.status -ceq 'success' -and $r.dump_hash -ceq (Get-StageBTextHash 'dump') -and $successListProperties -ceq 'criterion_8,dump_hash,live_blocked,stages,status') 'pg_restore_list valid provider success and safe result fields'
Assert-True (($script:events -join ',') -ceq 'stop-worker,stop-web,pg_dump,pg_restore_list,create,pg_restore,start-web,start-worker') 'pg_restore_list valid provider downstream order'
$invalidListResults=@(
  @{name='null';value=$null},
  @{name='non-object-string';value='invalid'},
  @{name='non-object-array';value=@([pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('b'*64)},[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('b'*64)})},
  @{name='non-object-scalar';value=[int]1},
  @{name='missing-success';value=[pscustomobject]@{exit_code=[int]0;size=[int64]1;hash=('b'*64)}},
  @{name='missing-exit-code';value=[pscustomobject]@{success=$true;size=[int64]1;hash=('b'*64)}},
  @{name='missing-size';value=[pscustomobject]@{success=$true;exit_code=[int]0;hash=('b'*64)}},
  @{name='missing-hash';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1}},
  @{name='extra-property';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('b'*64);extra='x'}},
  @{name='extra-diagnostic';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('b'*64);diagnostic='diagnostic-sentinel'}},
  @{name='extra-raw-output';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('b'*64);raw_output='raw-output-sentinel'}},
  @{name='success-null';value=[pscustomobject]@{success=$null;exit_code=[int]0;size=[int64]1;hash=('b'*64)}},
  @{name='success-false';value=[pscustomobject]@{success=$false;exit_code=[int]0;size=[int64]1;hash=('b'*64)}},
  @{name='success-int-truthy';value=[pscustomobject]@{success=1;exit_code=[int]0;size=[int64]1;hash=('b'*64)}},
  @{name='success-string-truthy';value=[pscustomobject]@{success='true';exit_code=[int]0;size=[int64]1;hash=('b'*64)}},
  @{name='success-float';value=[pscustomobject]@{success=[double]1.0;exit_code=[int]0;size=[int64]1;hash=('b'*64)}},
  @{name='exit-positive-nonzero';value=[pscustomobject]@{success=$true;exit_code=[int]1;size=[int64]1;hash=('b'*64)}},
  @{name='exit-negative-nonzero';value=[pscustomobject]@{success=$true;exit_code=[int]-1;size=[int64]1;hash=('b'*64)}},
  @{name='exit-int64';value=[pscustomobject]@{success=$true;exit_code=[int64]0;size=[int64]1;hash=('b'*64)}},
  @{name='exit-bool';value=[pscustomobject]@{success=$true;exit_code=$false;size=[int64]1;hash=('b'*64)}},
  @{name='exit-string';value=[pscustomobject]@{success=$true;exit_code='0';size=[int64]1;hash=('b'*64)}},
  @{name='exit-float';value=[pscustomobject]@{success=$true;exit_code=[double]0.0;size=[int64]1;hash=('b'*64)}},
  @{name='exit-null';value=[pscustomobject]@{success=$true;exit_code=$null;size=[int64]1;hash=('b'*64)}},
  @{name='size-zero';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]0;hash=('b'*64)}},
  @{name='size-negative';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]-1;hash=('b'*64)}},
  @{name='size-int32';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int]1;hash=('b'*64)}},
  @{name='size-bool';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=$true;hash=('b'*64)}},
  @{name='size-string';value=[pscustomobject]@{success=$true;exit_code=[int]0;size='1';hash=('b'*64)}},
  @{name='size-float';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[double]1.0;hash=('b'*64)}},
  @{name='size-null';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=$null;hash=('b'*64)}},
  @{name='size-over-int64-max';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[decimal]9223372036854775808;hash=('b'*64)}},
  @{name='hash-null';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=$null}},
  @{name='hash-empty';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=''}},
  @{name='hash-short';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('b'*63)}},
  @{name='hash-long';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('b'*65)}},
  @{name='hash-uppercase';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('B'*64)}},
  @{name='hash-nonhex';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('g'*64)}},
  @{name='hash-non-string';value=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=1}}
)
foreach($case in $invalidListResults) {
  try {Assert-StageBPgRestoreListResult $case.value; throw "pg_restore_list $($case.name) unexpectedly succeeded"} catch {Assert-True ($_.Exception.Message -ceq 'stage_b_pg_restore_list_result_invalid') "pg_restore_list $($case.name) privacy-safe reason"}
  $a=New-FakeAdapter $m -ListResult $case.value
  $r=Invoke-StageBSequence $m $a
  $listErrorText=$r|ConvertTo-Json -Depth 10
  Assert-True ($r.status -ceq 'failed' -and $r.error_code -ceq 'stage_b_operation_failed' -and $r.live_blocked -is [System.Boolean] -and $r.live_blocked -ceq $true -and $r.criterion_8 -ceq 'not_evaluable' -and $listErrorText -notmatch 'diagnostic-sentinel|raw-output-sentinel') "pg_restore_list $($case.name) failed safely"
  Assert-True ($r.dump_hash -ceq (Get-StageBTextHash 'dump')) "pg_restore_list $($case.name) retains dump hash"
  Assert-True (($script:events -join ',') -eq 'stop-worker,stop-web,pg_dump,pg_restore_list,start-web,start-worker') "pg_restore_list $($case.name) ordering"
  Assert-True ($script:catalogCalls -eq 0 -and $script:createCalls -eq 0 -and $script:restoreSnapshotCalls -eq 0 -and $script:dropCalls -eq 0 -and -not($script:events -contains 'pg_restore') -and @($r.stages|Where-Object {$_.stage -ceq 'pg_restore_list' -and $_.state -ceq 'succeeded'}).Count -eq 0) "pg_restore_list $($case.name) no downstream callbacks or succeeded stage"
}
$listProviderSentinel='PG_RESTORE_LIST_PROVIDER_SECRET raw-command=private-list secret-db'; $script:listProviderSentinel=$listProviderSentinel
$a=New-FakeAdapter $m
$a.Process={param($operation,$arguments,$environment) $null=$script:events.Add($operation); if($operation -ceq 'pg_dump'){return [pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=(Get-StageBTextHash 'dump')}}; if($operation -ceq 'pg_restore_list'){throw $script:listProviderSentinel}; [pscustomobject]@{success=$true;exit_code=[int]0}}
$r=Invoke-StageBSequence $m $a
$listErrorText=$r|ConvertTo-Json -Depth 10
Assert-True ($r.status -ceq 'failed' -and $r.error_code -ceq 'stage_b_operation_failed' -and $r.live_blocked -is [System.Boolean] -and $r.live_blocked -ceq $true -and $r.criterion_8 -ceq 'not_evaluable' -and $r.dump_hash -ceq (Get-StageBTextHash 'dump') -and $listErrorText -notmatch 'PG_RESTORE_LIST_PROVIDER_SECRET|raw-command|private-list|secret-db') 'pg_restore_list provider exception privacy-safe failure'
Assert-True (($script:events -join ',') -ceq 'stop-worker,stop-web,pg_dump,pg_restore_list,start-web,start-worker' -and $script:catalogCalls -eq 0 -and $script:createCalls -eq 0 -and $script:restoreSnapshotCalls -eq 0 -and $script:dropCalls -eq 0 -and @($r.stages|Where-Object {$_.stage -ceq 'pg_restore_list' -and $_.state -ceq 'succeeded'}).Count -eq 0) 'pg_restore_list provider exception no downstream callbacks or succeeded stage'
$listMalformedSentinel='PG_RESTORE_LIST_MALFORMED_SECRET'
$malformedList=[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]1;hash=('b'*64);diagnostic=$listMalformedSentinel}
$a=New-FakeAdapter $m -ListResult $malformedList
$r=Invoke-StageBSequence $m $a
$listErrorText=$r|ConvertTo-Json -Depth 10
Assert-True ($r.status -ceq 'failed' -and $r.error_code -ceq 'stage_b_operation_failed' -and $r.live_blocked -is [System.Boolean] -and $r.live_blocked -ceq $true -and $r.criterion_8 -ceq 'not_evaluable' -and $r.dump_hash -ceq (Get-StageBTextHash 'dump') -and $listErrorText -notmatch $listMalformedSentinel) 'pg_restore_list malformed provider privacy-safe failure'
Assert-True (($script:events -join ',') -ceq 'stop-worker,stop-web,pg_dump,pg_restore_list,start-web,start-worker' -and $script:catalogCalls -eq 0 -and $script:createCalls -eq 0 -and $script:restoreSnapshotCalls -eq 0 -and $script:dropCalls -eq 0 -and @($r.stages|Where-Object {$_.stage -ceq 'pg_restore_list' -and $_.state -ceq 'succeeded'}).Count -eq 0) 'pg_restore_list malformed provider no downstream callbacks or succeeded stage'

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

  Reset-ExecuteInputs
  $script:EvidenceRoot=Join-Path $executeRoot 'write-failure-execution'
  $script:executeAdapter=New-FakeAdapter $m
  $script:writeFailureContext='SENTINEL-CREDENTIAL user@raw-host C:\secret\dump'
  $script:preWriteTargets=@()
  $executionWriteError=$null
  $executionWriteObstruction={
    param($stagedPath)
    $script:preWriteTargets+=@([IO.Path]::GetFileName($stagedPath))
    if([IO.Path]::GetFileName($stagedPath) -ceq 'execution.json'){
      New-Item -ItemType Directory -LiteralPath $stagedPath|Out-Null
      [IO.File]::WriteAllText((Join-Path $stagedPath 'SENTINEL-CREDENTIAL.txt'),$script:writeFailureContext,[Text.UTF8Encoding]::new($false))
    }
  }
  try {Invoke-StageBMain {param() $script:executeAdapter} $null $executionWriteObstruction; throw 'execution write failure expected'} catch {$executionWriteError=$_.Exception.Message}
  Assert-True ($executionWriteError -ceq 'stage_b_operation_failed' -and $executionWriteError -notmatch 'SENTINEL|raw-host|secret|user@') 'execute execution write privacy-safe error'
  Assert-True (($script:preWriteTargets -join ',') -ceq 'execution.json' -and -not(Test-Path -LiteralPath $script:EvidenceRoot)) 'execute execution real write failure no final bundle'
  Assert-True (@(Get-ChildItem -LiteralPath $executeRoot -Directory -Filter '.stage-b-evidence-*.tmp').Count -eq 0) 'execute execution write no residue'

  Reset-ExecuteInputs
  $checksumDestination=Join-Path $executeRoot 'write-failure-checksum'
  $checksumKeepPath=Join-Path $checksumDestination 'keep.txt'
  $checksumKeepBytes=[Text.Encoding]::UTF8.GetBytes(('keep-'+[guid]::NewGuid().ToString('n')))
  $script:checksumDestination=$checksumDestination
  $script:checksumKeepPath=$checksumKeepPath
  $script:checksumKeepBytes=$checksumKeepBytes
  $script:EvidenceRoot=$checksumDestination
  $script:executeAdapter=New-FakeAdapter $m
  $script:preWriteTargets=@()
  $checksumWriteError=$null
  $checksumWriteObstruction={
    param($stagedPath)
    $script:preWriteTargets+=@([IO.Path]::GetFileName($stagedPath))
    if([IO.Path]::GetFileName($stagedPath) -ceq 'checksums.sha256'){
      [IO.Directory]::CreateDirectory($stagedPath)|Out-Null
      [IO.File]::WriteAllText((Join-Path $stagedPath 'SENTINEL-CREDENTIAL.txt'),$script:writeFailureContext,[Text.UTF8Encoding]::new($false))
      [IO.Directory]::CreateDirectory($script:checksumDestination)|Out-Null
      [IO.File]::WriteAllBytes($script:checksumKeepPath,$script:checksumKeepBytes)
    }
  }
  try {Invoke-StageBMain {param() $script:executeAdapter} $null $checksumWriteObstruction; throw 'checksum write failure expected'} catch {$checksumWriteError=$_.Exception.Message}
  Assert-True ($checksumWriteError -ceq 'stage_b_operation_failed' -and $checksumWriteError -notmatch 'SENTINEL|raw-host|secret|user@') 'execute checksum write privacy-safe error'
  Assert-True (($script:preWriteTargets -join ',') -ceq 'execution.json,checksums.sha256') 'execute checksum real write boundary'
  $checksumInventory=if(Test-Path -LiteralPath $checksumDestination -PathType Container){@((Get-ChildItem -LiteralPath $checksumDestination -Force).Name)-join ','}else{'<missing>'}
  Assert-True ($checksumInventory -ceq 'keep.txt') 'execute checksum destination exact inventory'
  Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes($checksumKeepPath)) -ceq [Convert]::ToBase64String($checksumKeepBytes)) 'execute checksum destination sentinel bytes preserved'
  Assert-True (-not(Test-Path -LiteralPath (Join-Path $checksumDestination 'execution.json')) -and -not(Test-Path -LiteralPath (Join-Path $checksumDestination 'checksums.sha256'))) 'execute checksum no partial bundle'
  Assert-True (@(Get-ChildItem -LiteralPath $executeRoot -Directory -Filter '.stage-b-evidence-*.tmp').Count -eq 0) 'execute checksum write no residue'

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

# Cleanup: exact successful execution linkage, guards, one drop, retained dump, and atomic evidence.
$cleanupRoot=Join-Path ([IO.Path]::GetTempPath()) ('stage-b-cleanup-'+[guid]::NewGuid())
New-Item -ItemType Directory -Path $cleanupRoot|Out-Null
try {
  $script:PlanOnly=$false; $script:Execute=$false; $script:Cleanup=$true
  $script:PendingManifestPath=Join-Path $cleanupRoot 'pending.json'
  $script:ApprovalPath=Join-Path $cleanupRoot 'approval.json'
  $script:EvidenceRoot=Join-Path $cleanupRoot 'execution'
  function Reset-CleanupInputs {
    foreach($path in @($script:PendingManifestPath,$script:ApprovalPath,(Join-Path $cleanupRoot 'checksums.sha256'),$script:EvidenceRoot)){if(Test-Path -LiteralPath $path){Remove-Item -LiteralPath $path -Recurse -Force}}
    [IO.File]::WriteAllText($script:PendingManifestPath,(ConvertTo-StageBCanonicalJson $m)+"`n",[Text.UTF8Encoding]::new($false))
    $script:cleanupManifestHash=Get-StageBSha256 $script:PendingManifestPath
    [IO.File]::WriteAllText((Join-Path $cleanupRoot 'checksums.sha256'),($script:cleanupManifestHash+'  pending.json'+"`n"),[Text.UTF8Encoding]::new($false))
    $approval=[pscustomobject]@{scope='stage-b-backup-restore';action='cleanup';manifest_sha256=$script:cleanupManifestHash;approved_at=[DateTimeOffset]::UtcNow.ToString('o');approver_hash=$m.owners.cleanup_owner_hash}
    [IO.File]::WriteAllText($script:ApprovalPath,(ConvertTo-StageBCanonicalJson $approval)+"`n",[Text.UTF8Encoding]::new($false))
    $sequence=[pscustomobject]@{status='success';dump_hash=(Get-StageBTextHash 'dump')}
    $null=Publish-StageBExecutionBundle $script:EvidenceRoot $sequence $script:cleanupManifestHash $null $null
    $script:cleanupExecutionHash=Get-StageBSha256 (Join-Path $script:EvidenceRoot 'execution.json')
  }
  function New-CleanupAdapter {
    $a=New-FakeAdapter $m
    $script:cleanupEvents=[Collections.Generic.List[string]]::new()
    $script:cleanupJobs=[int]0
    $script:retainedCall=0
    $script:retainedSize=[int64]17
    $script:retainedHash=Get-StageBTextHash 'dump'
    $script:retainedSecondSize=$script:retainedSize
    $script:retainedSecondHash=$script:retainedHash
    $script:cleanupCatalogMode='normal'
    $script:cleanupDropMode='normal'
    $a.Process={param($operation,$arguments,$environment)
      $null=$script:cleanupEvents.Add($operation)
      if($operation -cne 'retained_dump' -or @($arguments).Count -ne 0 -or $environment -isnot [Collections.IDictionary] -or $environment.Count -ne 0){throw 'retained invocation mismatch'}
      $script:retainedCall++
      [pscustomobject]@{success=$true;exit_code=[int]0;size=if($script:retainedCall -eq 1){[int64]$script:retainedSize}else{[int64]$script:retainedSecondSize};hash=if($script:retainedCall -eq 1){$script:retainedHash}else{$script:retainedSecondHash}}
    }
    $a.Catalog={param($target)
      $null=$script:cleanupEvents.Add('catalog')
      if((ConvertTo-StageBCanonicalJson $target) -cne (ConvertTo-StageBCanonicalJson $m.restore)){throw 'catalog invocation mismatch'}
      if($script:cleanupCatalogMode -eq 'malformed'){return [pscustomobject]@{state='eligible'}}
      if($script:dropCalls -eq 0){
        [pscustomobject]@{state=if($script:cleanupCatalogMode -eq 'state'){'existing_empty'}else{'eligible'};oid_hash=if($script:cleanupCatalogMode -eq 'oid'){('e'*64)}else{$m.restore.oid_hash};owner_hash=if($script:cleanupCatalogMode -eq 'owner'){('e'*64)}else{$m.owners.restore_owner_hash};connections=if($script:cleanupCatalogMode -eq 'connections'){'0'}elseif($script:cleanupCatalogMode -eq 'busy'){[int]1}else{[int]0}}
      } else {
        [pscustomobject]@{state=if($script:cleanupCatalogMode -eq 'after-state'){'eligible'}else{'absent'};oid_hash=if($script:cleanupCatalogMode -eq 'after-malformed'){$m.restore.oid_hash}else{$null};owner_hash=$null;connections=if($script:cleanupCatalogMode -eq 'after-busy'){[int]1}else{[int]0}}
      }
    }
    $a.Jobs={param() $null=$script:cleanupEvents.Add('jobs'); $script:cleanupJobs}
    $a.DropRestore={param($target,$ownerHash)
      $script:dropCalls++; $null=$script:cleanupEvents.Add('drop')
      if((ConvertTo-StageBCanonicalJson $target) -cne (ConvertTo-StageBCanonicalJson $m.restore) -or $ownerHash -cne $m.owners.cleanup_owner_hash){throw 'drop invocation mismatch'}
      if($script:cleanupDropMode -eq 'throw'){throw 'SENTINEL-CREDENTIAL C:\secret'}
      if($script:cleanupDropMode -eq 'false'){return [pscustomobject]@{success=$false}}
      if($script:cleanupDropMode -eq 'malformed'){return [pscustomobject]@{success=$true;extra='x'}}
      [pscustomobject]@{success=$true}
    }
    $a
  }

  Reset-CleanupInputs
  $script:CleanupEvidenceRoot=Join-Path $cleanupRoot 'cleanup-success'
  $script:cleanupAdapter=New-CleanupAdapter
  $script:publishStages=[Collections.Generic.List[string]]::new()
  $result=Invoke-StageBMain {param() $script:cleanupAdapter} {param($cleanupPath,$checksumPath,$stage) $null=$script:publishStages.Add($stage)} $null
  Assert-True (($script:cleanupEvents -join ',') -ceq 'retained_dump,catalog,jobs,drop,catalog,retained_dump') 'cleanup exact success order'
  Assert-True ($script:dropCalls -eq 1 -and $script:retainedCall -eq 2 -and ($script:publishStages -join ',') -ceq 'staged,published') 'cleanup exact counts and atomic publish order'
  $cleanupText=[IO.File]::ReadAllText((Join-Path $script:CleanupEvidenceRoot 'cleanup.json'),[Text.Encoding]::UTF8)
  $cleanupFile=$cleanupText|ConvertFrom-Json
  Assert-True ((@($cleanupFile.psobject.Properties.Name|Sort-Object)-join ',') -ceq 'cleanup_owner_hash,criterion_8,drop_count,dump_hash,dump_size,execution_sha256,live_blocked,manifest_sha256,restore_oid_hash,restore_owner_hash,restore_state,status') 'cleanup exact schema'
  Assert-True ($cleanupFile.live_blocked -is [bool] -and $cleanupFile.live_blocked -and $cleanupFile.criterion_8 -ceq 'not_evaluable' -and $cleanupFile.restore_state -ceq 'absent' -and $cleanupFile.drop_count -is [int] -and $cleanupFile.drop_count -eq 1) 'cleanup exact values'
  Assert-True ($cleanupFile.execution_sha256 -ceq $script:cleanupExecutionHash -and $cleanupFile.dump_size -eq [int64]17 -and (ConvertTo-StageBCanonicalJson $result) -ceq (ConvertTo-StageBCanonicalJson $cleanupFile)) 'cleanup linkage returned file equality'
  Assert-True ((@((Get-ChildItem -LiteralPath $script:CleanupEvidenceRoot -Force).Name|Sort-Object)-join ',') -ceq 'checksums.sha256,cleanup.json') 'cleanup exact inventory'
  $cleanupChecksum=[IO.File]::ReadAllText((Join-Path $script:CleanupEvidenceRoot 'checksums.sha256'),[Text.Encoding]::UTF8)
  Assert-True ($cleanupChecksum -cmatch '^([a-f0-9]{64})  cleanup\.json\n$' -and $Matches[1] -ceq (Get-StageBSha256 (Join-Path $script:CleanupEvidenceRoot 'cleanup.json'))) 'cleanup checksum recomputation'
  Assert-True ($cleanupText -notmatch 'raw-|C:\\|user@|SENTINEL|command|credential') 'cleanup privacy'

  foreach($case in @('missing','extra','tampered','failed','linkage')){
    Reset-CleanupInputs
    switch($case){
      'missing' {Remove-Item -LiteralPath $script:EvidenceRoot -Recurse -Force}
      'extra' {[IO.File]::WriteAllText((Join-Path $script:EvidenceRoot 'extra.txt'),'x')}
      'tampered' {[IO.File]::WriteAllText((Join-Path $script:EvidenceRoot 'execution.json'),'{}'+"`n",[Text.UTF8Encoding]::new($false))}
      'failed' {$failed=[pscustomobject]@{status='failed';dump_hash=$null}; Remove-Item $script:EvidenceRoot -Recurse -Force; $null=Publish-StageBExecutionBundle $script:EvidenceRoot $failed $script:cleanupManifestHash $null $null}
      'linkage' {[IO.File]::WriteAllText((Join-Path $script:EvidenceRoot 'execution.json'),(ConvertTo-StageBCanonicalJson ([pscustomobject]@{status='success';dump_hash=(Get-StageBTextHash 'dump');manifest_sha256=('e'*64)}))+"`n",[Text.UTF8Encoding]::new($false)); [IO.File]::WriteAllText((Join-Path $script:EvidenceRoot 'checksums.sha256'),((Get-StageBSha256 (Join-Path $script:EvidenceRoot 'execution.json'))+'  execution.json'+"`n"))}
    }
    $script:CleanupEvidenceRoot=Join-Path $cleanupRoot ('bad-execution-'+$case)
    $script:cleanupAdapter=New-CleanupAdapter
    Assert-Throws {Invoke-StageBMain {param() $script:cleanupAdapter}} ('cleanup execution '+$case)
    Assert-True ($script:dropCalls -eq 0 -and -not(Test-Path $script:CleanupEvidenceRoot)) ('cleanup execution zero drop '+$case)
  }

  Reset-CleanupInputs
  $ownerApproval=Get-Content -Raw $script:ApprovalPath|ConvertFrom-Json; $ownerApproval.approver_hash='e'*64
  [IO.File]::WriteAllText($script:ApprovalPath,(ConvertTo-StageBCanonicalJson $ownerApproval)+"`n",[Text.UTF8Encoding]::new($false))
  $script:CleanupEvidenceRoot=Join-Path $cleanupRoot 'owner-mismatch'; $script:cleanupAdapter=New-CleanupAdapter
  Assert-Throws {Invoke-StageBMain {param() $script:cleanupAdapter}} 'cleanup owner mismatch'
  Assert-True ($script:dropCalls -eq 0) 'cleanup owner mismatch zero drop'

  Reset-CleanupInputs
  $actionApproval=Get-Content -Raw $script:ApprovalPath|ConvertFrom-Json; $actionApproval.action='execute'
  [IO.File]::WriteAllText($script:ApprovalPath,(ConvertTo-StageBCanonicalJson $actionApproval)+"`n",[Text.UTF8Encoding]::new($false))
  $script:CleanupEvidenceRoot=Join-Path $cleanupRoot 'action-mismatch'; $script:cleanupAdapter=New-CleanupAdapter
  Assert-Throws {Invoke-StageBMain {param() $script:cleanupAdapter}} 'cleanup action mismatch'
  Assert-True ($script:dropCalls -eq 0 -and -not(Test-Path $script:CleanupEvidenceRoot)) 'cleanup action mismatch zero drop'

  Reset-CleanupInputs
  [IO.File]::WriteAllText((Join-Path $cleanupRoot 'checksums.sha256'),(('e'*64)+'  pending.json'+"`n"),[Text.UTF8Encoding]::new($false))
  $script:CleanupEvidenceRoot=Join-Path $cleanupRoot 'pending-linkage'; $script:cleanupAdapter=New-CleanupAdapter
  Assert-Throws {Invoke-StageBMain {param() $script:cleanupAdapter}} 'cleanup pending linkage'
  Assert-True ($script:dropCalls -eq 0 -and -not(Test-Path $script:CleanupEvidenceRoot)) 'cleanup pending linkage zero drop'

  foreach($mode in @('state','oid','owner','connections','busy','malformed')){
    Reset-CleanupInputs; $script:CleanupEvidenceRoot=Join-Path $cleanupRoot ('catalog-'+$mode); $script:cleanupAdapter=New-CleanupAdapter; $script:cleanupCatalogMode=$mode
    Assert-Throws {Invoke-StageBMain {param() $script:cleanupAdapter}} ('cleanup catalog '+$mode)
    Assert-True ($script:dropCalls -eq 0 -and -not(Test-Path $script:CleanupEvidenceRoot)) ('cleanup catalog zero drop '+$mode)
  }
  $jobCases=@(
    @{value=$null},@{value=[object[]]@(0,0)},@{value='0'},@{value=[long]0},
    @{value=[int]-1},@{value=[int]1},@{value=[uint64]::MaxValue}
  )
  $jobIndex=0
  foreach($jobCase in $jobCases){
    Reset-CleanupInputs; $script:CleanupEvidenceRoot=Join-Path $cleanupRoot ('jobs-'+$jobIndex); $script:cleanupAdapter=New-CleanupAdapter; $script:cleanupJobs=$jobCase.value
    Assert-Throws {Invoke-StageBMain {param() $script:cleanupAdapter}} ('cleanup jobs '+$jobIndex)
    Assert-True ($script:dropCalls -eq 0 -and -not(Test-Path $script:CleanupEvidenceRoot)) ('cleanup jobs zero drop '+$jobIndex)
    $jobIndex++
  }

  $retainedCases=@(
    [pscustomobject]@{success=$false;exit_code=[int]0;size=[int64]17;hash=(Get-StageBTextHash 'dump')},
    [pscustomobject]@{success=$true;exit_code=[long]0;size=[int64]17;hash=(Get-StageBTextHash 'dump')},
    [pscustomobject]@{success=$true;exit_code=[int]0;size=[int]17;hash=(Get-StageBTextHash 'dump')},
    [pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]0;hash=(Get-StageBTextHash 'dump')},
    [pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]17;hash=('e'*64)},
    [pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]17;hash=(Get-StageBTextHash 'dump');extra='x'}
  )
  $retainedIndex=0
  foreach($bad in $retainedCases){
    Reset-CleanupInputs; $script:CleanupEvidenceRoot=Join-Path $cleanupRoot ('retained-'+$retainedIndex); $script:cleanupAdapter=New-CleanupAdapter
    $script:cleanupAdapter.Process={param($operation,$arguments,$environment) $null=$script:cleanupEvents.Add($operation); $bad}.GetNewClosure()
    Assert-Throws {Invoke-StageBMain {param() $script:cleanupAdapter}} ('cleanup retained '+$retainedIndex)
    Assert-True ($script:dropCalls -eq 0 -and -not(Test-Path $script:CleanupEvidenceRoot)) ('cleanup retained zero drop '+$retainedIndex)
    $retainedIndex++
  }
  Reset-CleanupInputs; $script:CleanupEvidenceRoot=Join-Path $cleanupRoot 'retained-missing-before'; $script:cleanupAdapter=New-CleanupAdapter
  $script:cleanupAdapter.Process={param($operation,$arguments,$environment) throw 'SENTINEL-CREDENTIAL retained dump missing'}
  $cleanupError=$null; try {Invoke-StageBMain {param() $script:cleanupAdapter}; throw 'expected'} catch {$cleanupError=$_.Exception.Message}
  Assert-True ($cleanupError -ceq 'stage_b_operation_failed' -and $cleanupError -notmatch 'SENTINEL|missing' -and $script:dropCalls -eq 0 -and -not(Test-Path $script:CleanupEvidenceRoot)) 'cleanup retained disappearance before drop'

  Reset-CleanupInputs; $script:CleanupEvidenceRoot=Join-Path $cleanupRoot 'retained-missing-after'; $script:cleanupAdapter=New-CleanupAdapter
  $script:cleanupAdapter.Process={param($operation,$arguments,$environment) $script:retainedCall++; if($script:retainedCall -eq 2){throw 'SENTINEL-CREDENTIAL retained dump missing'}; [pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]17;hash=(Get-StageBTextHash 'dump')}}
  $cleanupError=$null; try {Invoke-StageBMain {param() $script:cleanupAdapter}; throw 'expected'} catch {$cleanupError=$_.Exception.Message}
  Assert-True ($cleanupError -ceq 'stage_b_operation_failed' -and $cleanupError -notmatch 'SENTINEL|missing' -and $script:dropCalls -eq 1 -and $script:retainedCall -eq 2 -and -not(Test-Path $script:CleanupEvidenceRoot)) 'cleanup retained disappearance after exact one drop'

  foreach($mode in @('false','malformed','throw')){
    Reset-CleanupInputs; $script:CleanupEvidenceRoot=Join-Path $cleanupRoot ('drop-'+$mode); $script:cleanupAdapter=New-CleanupAdapter; $script:cleanupDropMode=$mode
    $cleanupError=$null; try {Invoke-StageBMain {param() $script:cleanupAdapter}; throw 'expected'} catch {$cleanupError=$_.Exception.Message}
    Assert-True ($cleanupError -ceq 'stage_b_operation_failed' -and $cleanupError -notmatch 'SENTINEL|secret' -and $script:dropCalls -eq 1 -and -not(Test-Path $script:CleanupEvidenceRoot)) ('cleanup drop fail safe '+$mode)
  }
  foreach($mode in @('after-state','after-malformed','after-busy')){
    Reset-CleanupInputs; $script:CleanupEvidenceRoot=Join-Path $cleanupRoot ('after-'+$mode); $script:cleanupAdapter=New-CleanupAdapter; $script:cleanupCatalogMode=$mode
    Assert-Throws {Invoke-StageBMain {param() $script:cleanupAdapter}} ('cleanup after '+$mode)
    Assert-True ($script:dropCalls -eq 1 -and -not(Test-Path $script:CleanupEvidenceRoot)) ('cleanup after exact one drop '+$mode)
  }
  foreach($drift in @('hash','size')){
    Reset-CleanupInputs; $script:CleanupEvidenceRoot=Join-Path $cleanupRoot ('drift-'+$drift); $script:cleanupAdapter=New-CleanupAdapter
    if($drift -eq 'hash'){$script:retainedSecondHash='e'*64}else{$script:retainedSecondSize=[int64]18}
    Assert-Throws {Invoke-StageBMain {param() $script:cleanupAdapter}} ('cleanup drift '+$drift)
    Assert-True ($script:dropCalls -eq 1 -and $script:retainedCall -eq 2 -and -not(Test-Path $script:CleanupEvidenceRoot)) ('cleanup drift exact one drop '+$drift)
  }

  Reset-CleanupInputs
  $script:CleanupEvidenceRoot=Join-Path $cleanupRoot 'existing-cleanup'; New-Item -ItemType Directory $script:CleanupEvidenceRoot|Out-Null
  $keepBytes=[Text.Encoding]::UTF8.GetBytes(('keep-'+[guid]::NewGuid().ToString('n'))); [IO.File]::WriteAllBytes((Join-Path $script:CleanupEvidenceRoot 'keep.txt'),$keepBytes)
  $script:cleanupAdapter=New-CleanupAdapter; Assert-Throws {Invoke-StageBMain {param() $script:cleanupAdapter}} 'cleanup existing'
  Assert-True ($script:dropCalls -eq 0 -and [Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $script:CleanupEvidenceRoot 'keep.txt'))) -ceq [Convert]::ToBase64String($keepBytes)) 'cleanup existing preserved'

  foreach($boundary in @('write','tamper','checksum','race','post-publish','post-race')){
    Reset-CleanupInputs; $script:CleanupEvidenceRoot=Join-Path $cleanupRoot ('boundary-'+$boundary); $script:cleanupAdapter=New-CleanupAdapter
    $pre=$null; $hook=$null
    if($boundary -eq 'write'){$pre={param($path) if([IO.Path]::GetFileName($path) -ceq 'cleanup.json'){New-Item -ItemType Directory -LiteralPath $path|Out-Null; [IO.File]::WriteAllText((Join-Path $path 'SENTINEL-CREDENTIAL.txt'),'user@raw-host C:\secret')}}}
    elseif($boundary -eq 'tamper'){$hook={param($json,$checksum,$stage) if($stage -ceq 'staged'){[IO.File]::WriteAllText($json,'{}'+"`n")}}}
    elseif($boundary -eq 'checksum'){$hook={param($json,$checksum,$stage) if($stage -ceq 'staged'){[IO.File]::WriteAllText($checksum,('e'*64)+'  cleanup.json'+"`n")}}}
    elseif($boundary -eq 'race'){$hook={param($json,$checksum,$stage) if($stage -ceq 'staged'){New-Item -ItemType Directory $script:CleanupEvidenceRoot|Out-Null; [IO.File]::WriteAllText((Join-Path $script:CleanupEvidenceRoot 'keep.txt'),'keep')}}}
    elseif($boundary -eq 'post-publish'){$hook={param($json,$checksum,$stage) if($stage -ceq 'published'){[IO.File]::WriteAllText($json,'{}'+"`n"); throw 'SENTINEL-CREDENTIAL C:\secret'}}}
    else {$script:postRaceOriginal=Join-Path $cleanupRoot 'post-race-original'; $hook={param($json,$checksum,$stage) if($stage -ceq 'published'){Move-Item -LiteralPath $script:CleanupEvidenceRoot -Destination $script:postRaceOriginal; New-Item -ItemType Directory $script:CleanupEvidenceRoot|Out-Null; [IO.File]::WriteAllText((Join-Path $script:CleanupEvidenceRoot 'keep.txt'),'keep'); throw 'SENTINEL-CREDENTIAL C:\secret'}}}
    $cleanupError=$null; try {Invoke-StageBMain {param() $script:cleanupAdapter} $hook $pre; throw 'expected'} catch {$cleanupError=$_.Exception.Message}
    Assert-True ($cleanupError -ceq 'stage_b_operation_failed' -and $cleanupError -notmatch 'SENTINEL|secret' -and $script:dropCalls -eq 1) ('cleanup boundary safe exact one drop '+$boundary)
    if($boundary -in @('race','post-race')){
      Assert-True ((Get-Content (Join-Path $script:CleanupEvidenceRoot 'keep.txt')) -ceq 'keep') ('cleanup '+$boundary+' destination preserved')
    } elseif($boundary -eq 'post-publish'){
      Assert-True (Test-Path -LiteralPath $script:CleanupEvidenceRoot -PathType Container) 'cleanup post-publish retained'
      Assert-Throws {Assert-StageBCleanupBundle $script:CleanupEvidenceRoot $script:cleanupManifestHash $script:cleanupExecutionHash} 'cleanup post-publish retained invalid'
    } else {
      Assert-True (-not(Test-Path $script:CleanupEvidenceRoot)) ('cleanup boundary no false bundle '+$boundary)
    }
    Assert-True (@(Get-ChildItem -LiteralPath $cleanupRoot -Directory -Filter '.stage-b-cleanup-*.tmp').Count -eq 0) ('cleanup boundary no residue '+$boundary)
  }

  Reset-CleanupInputs
  $script:CleanupEvidenceRoot=Join-Path $cleanupRoot 'boundary-post-same-inventory'
  $script:postSameOriginal=Join-Path $cleanupRoot 'post-same-inventory-original'
  $script:cleanupAdapter=New-CleanupAdapter
  $executionJsonBefore=[IO.File]::ReadAllBytes((Join-Path $script:EvidenceRoot 'execution.json'))
  $executionChecksumBefore=[IO.File]::ReadAllBytes((Join-Path $script:EvidenceRoot 'checksums.sha256'))
  $script:replacementCleanupBytes=[Text.Encoding]::UTF8.GetBytes(('replacement-cleanup-'+[guid]::NewGuid().ToString('n')))
  $script:replacementChecksumBytes=[Text.Encoding]::UTF8.GetBytes(('replacement-checksum-'+[guid]::NewGuid().ToString('n')))
  $script:originalCleanupBytes=$null
  $script:originalChecksumBytes=$null
  $sameInventoryHook={
    param($json,$checksum,$stage)
    if($stage -ceq 'published'){
      $script:originalCleanupBytes=[IO.File]::ReadAllBytes($json)
      $script:originalChecksumBytes=[IO.File]::ReadAllBytes($checksum)
      Move-Item -LiteralPath $script:CleanupEvidenceRoot -Destination $script:postSameOriginal
      New-Item -ItemType Directory -Path $script:CleanupEvidenceRoot|Out-Null
      [IO.File]::WriteAllBytes((Join-Path $script:CleanupEvidenceRoot 'cleanup.json'),$script:replacementCleanupBytes)
      [IO.File]::WriteAllBytes((Join-Path $script:CleanupEvidenceRoot 'checksums.sha256'),$script:replacementChecksumBytes)
      throw 'SENTINEL-CREDENTIAL C:\secret'
    }
  }
  $cleanupError=$null; try {Invoke-StageBMain {param() $script:cleanupAdapter} $sameInventoryHook $null; throw 'expected'} catch {$cleanupError=$_.Exception.Message}
  Assert-True ($cleanupError -ceq 'stage_b_operation_failed' -and $cleanupError -notmatch 'SENTINEL|secret' -and $script:dropCalls -eq 1 -and $script:retainedCall -eq 2) 'cleanup same-inventory privacy exact one drop no retry'
  $replacementItems=@(Get-ChildItem -LiteralPath $script:CleanupEvidenceRoot -Force)
  Assert-True ($replacementItems.Count -eq 2 -and (@($replacementItems.Name|Sort-Object)-join ',') -ceq 'checksums.sha256,cleanup.json' -and @($replacementItems|Where-Object {$_.PSIsContainer}).Count -eq 0) 'cleanup same-inventory replacement exact regular inventory'
  Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $script:CleanupEvidenceRoot 'cleanup.json'))) -ceq [Convert]::ToBase64String($script:replacementCleanupBytes) -and [Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $script:CleanupEvidenceRoot 'checksums.sha256'))) -ceq [Convert]::ToBase64String($script:replacementChecksumBytes)) 'cleanup same-inventory replacement bytes preserved'
  $originalItems=@(Get-ChildItem -LiteralPath $script:postSameOriginal -Force)
  Assert-True ($originalItems.Count -eq 2 -and (@($originalItems.Name|Sort-Object)-join ',') -ceq 'checksums.sha256,cleanup.json' -and @($originalItems|Where-Object {$_.PSIsContainer}).Count -eq 0) 'cleanup same-inventory moved original exact regular inventory'
  Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $script:postSameOriginal 'cleanup.json'))) -ceq [Convert]::ToBase64String($script:originalCleanupBytes) -and [Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $script:postSameOriginal 'checksums.sha256'))) -ceq [Convert]::ToBase64String($script:originalChecksumBytes)) 'cleanup same-inventory moved original bytes preserved'
  $null=Assert-StageBCleanupBundle $script:postSameOriginal $script:cleanupManifestHash $script:cleanupExecutionHash
  Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $script:EvidenceRoot 'execution.json'))) -ceq [Convert]::ToBase64String($executionJsonBefore) -and [Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $script:EvidenceRoot 'checksums.sha256'))) -ceq [Convert]::ToBase64String($executionChecksumBefore)) 'cleanup same-inventory retained execution evidence unchanged'
  Assert-True (@(Get-ChildItem -LiteralPath $cleanupRoot -Directory -Filter '.stage-b-cleanup-*.tmp').Count -eq 0) 'cleanup same-inventory no residue'
} finally {
  $script:Cleanup=$false; $script:PendingManifestPath=$null; $script:ApprovalPath=$null; $script:EvidenceRoot=$null; $script:CleanupEvidenceRoot=$null
  Remove-Item -LiteralPath $cleanupRoot -Recurse -Force
}

# Production adapter: exact controlled runtime-provider contract and complete non-live integration.
$script:providerConfigurationCalls=0
$script:providerJobsCalls=0
$script:providerRuntimeCalls=0
$script:providerDrops=0
$providerContract=@{
  Snapshot={param($target,$mode,$expectedSourceOidHash) $script:providerRuntimeCalls++}
  Catalog={param($target) $script:providerRuntimeCalls++}
  Process={param($operation,$arguments,$environment) $script:providerRuntimeCalls++}
  Service={param($action,$service) $script:providerRuntimeCalls++}
  State={param($manifest) $script:providerRuntimeCalls++}
  CreateRestore={param($target,$ownerHash) $script:providerRuntimeCalls++}
  DropRestore={param($target,$ownerHash) $script:providerRuntimeCalls++}
}
Assert-StageBRuntimeProvider $providerContract
foreach($case in @('missing','extra','non-scriptblock','wrong-arity')){
  $candidate=@{}; foreach($name in $providerContract.Keys){$candidate[$name]=$providerContract[$name]}
  switch($case){
    'missing' {$candidate.Remove('State')}
    'extra' {$candidate.Unexpected={param() $script:providerRuntimeCalls++}}
    'non-scriptblock' {$candidate.Process='invalid'}
    'wrong-arity' {$candidate.DropRestore={param($target) $script:providerRuntimeCalls++}}
  }
  Assert-Throws {New-StageBProductionAdapter {param() $script:providerConfigurationCalls++; New-ReadOnlyConfiguration} {param() $script:providerJobsCalls++; 0} $candidate} ('runtime provider '+$case)
}
Assert-True ($script:providerConfigurationCalls -eq 0 -and $script:providerJobsCalls -eq 0 -and $script:providerRuntimeCalls -eq 0) 'runtime provider rejection before callbacks'
$defaultProduction=New-StageBProductionAdapter {param() New-ReadOnlyConfiguration} {param() 0}
try {& $defaultProduction.Process 'SENTINEL-NOT-AN-EXECUTABLE' @() @{}; throw 'default process failure expected'} catch {Assert-True ($_.Exception.Message -ceq 'process configuration unavailable') 'default process unavailable'}

function New-ControlledRuntimeProvider {
  $script:providerCalls=[Collections.Generic.List[string]]::new()
  $script:providerArguments=[Collections.Generic.List[string]]::new()
  $script:providerCreated=$false
  $script:providerCleanupMode=$false
  $script:providerDrops=0
  $script:providerMutations=0
  $script:providerSentinel='SENTINEL-CREDENTIAL user@raw-host C:\secret\controlled.dump'
  @{
    State={param($manifest)
      $null=$script:providerCalls.Add('state')
      $null=$script:providerArguments.Add((ConvertTo-StageBCanonicalJson $manifest))
      if((ConvertTo-StageBCanonicalJson $manifest) -cne (ConvertTo-StageBCanonicalJson $script:controlledManifest)){throw 'controlled state arguments mismatch'}
      New-CurrentState $manifest
    }
    Service={param($action,$service)
      $null=$script:providerCalls.Add("$action-$service")
      $null=$script:providerArguments.Add((ConvertTo-StageBCanonicalJson @($action,$service)))
      if($action -cnotin @('stop','start') -or $service -cnotin @('worker','web')){throw 'controlled service arguments mismatch'}
      $script:providerMutations++
      [pscustomobject]@{success=$true;state=if($action -ceq 'stop'){'stopped'}else{'running'}}
    }
    Snapshot={param($target,$mode,$expectedSourceOidHash)
      $null=$script:providerCalls.Add("snapshot-$mode")
      $null=$script:providerArguments.Add((ConvertTo-StageBCanonicalJson @($target,$mode,$expectedSourceOidHash)))
      $expectedTarget=if($mode -ceq 'source'){$script:controlledManifest.source}elseif($mode -ceq 'restore'){$script:controlledManifest.restore}else{throw 'controlled snapshot arguments mismatch'}
      $expectedOid=if($mode -ceq 'source'){$null}else{$script:controlledManifest.source.oid_hash}
      if((ConvertTo-StageBCanonicalJson $target) -cne (ConvertTo-StageBCanonicalJson $expectedTarget) -or $expectedSourceOidHash -cne $expectedOid){throw 'controlled snapshot arguments mismatch'}
      [pscustomobject]@{identity=[pscustomobject]@{oid_hash=$target.oid_hash};baseline_hash=$script:controlledManifest.source_baseline_hash;semantic_hash=(Get-StageBTextHash 'controlled-semantic')}
    }
    Process={param($operation,$arguments,$environment)
      $null=$script:providerCalls.Add($operation)
      $null=$script:providerArguments.Add((ConvertTo-StageBCanonicalJson @($operation,@($arguments),$environment)))
      $expectedArguments=switch($operation){'pg_dump'{@('--format=custom','--no-owner','--no-acl')};'pg_restore_list'{@('--list')};'pg_restore'{@('--exit-on-error','--single-transaction','--no-owner','--no-acl')};'retained_dump'{@()};default{throw $script:providerSentinel}}
      if((@($arguments)-join "`0") -cne ($expectedArguments-join "`0") -or $environment -isnot [Collections.IDictionary] -or $environment.Count -ne 0){throw 'controlled process arguments mismatch'}
      if($operation -ceq 'pg_dump'){[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]23;hash=(Get-StageBTextHash 'controlled-dump')}}
      elseif($operation -ceq 'pg_restore_list'){[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]11;hash=(Get-StageBTextHash 'controlled-list')}}
      elseif($operation -ceq 'pg_restore'){[pscustomobject]@{success=$true;exit_code=[int]0}}
      elseif($operation -ceq 'retained_dump'){[pscustomobject]@{success=$true;exit_code=[int]0;size=[int64]23;hash=(Get-StageBTextHash 'controlled-dump')}}
      else {throw $script:providerSentinel}
    }
    Catalog={param($target)
      $null=$script:providerCalls.Add('catalog')
      $null=$script:providerArguments.Add((ConvertTo-StageBCanonicalJson $target))
      if((ConvertTo-StageBCanonicalJson $target) -cne (ConvertTo-StageBCanonicalJson $script:controlledManifest.restore)){throw 'controlled catalog arguments mismatch'}
      if($script:providerCleanupMode){
        if($script:providerDrops -eq 0){[pscustomobject]@{state='eligible';oid_hash=$script:controlledManifest.restore.oid_hash;owner_hash=$script:controlledManifest.owners.restore_owner_hash;connections=[int]0}}
        else {[pscustomobject]@{state='absent';oid_hash=$null;owner_hash=$null;connections=[int]0}}
      } elseif($script:providerCreated) {
        [pscustomobject]@{state='existing_empty';oid_hash=$script:controlledManifest.restore.oid_hash;owner_hash=$script:controlledManifest.owners.restore_owner_hash;connections=[int]0}
      } else {[pscustomobject]@{state='absent';oid_hash=$null;owner_hash=$null;connections=[int]0}}
    }
    CreateRestore={param($target,$ownerHash)
      $null=$script:providerCalls.Add('create')
      $null=$script:providerArguments.Add((ConvertTo-StageBCanonicalJson @($target,$ownerHash)))
      if((ConvertTo-StageBCanonicalJson $target) -cne (ConvertTo-StageBCanonicalJson $script:controlledManifest.restore) -or $ownerHash -cne $script:controlledManifest.owners.restore_owner_hash){throw 'controlled create arguments mismatch'}
      $script:providerMutations++; $script:providerCreated=$true
      [pscustomobject]@{success=$true}
    }
    DropRestore={param($target,$ownerHash)
      $null=$script:providerCalls.Add('drop')
      $null=$script:providerArguments.Add((ConvertTo-StageBCanonicalJson @($target,$ownerHash)))
      if((ConvertTo-StageBCanonicalJson $target) -cne (ConvertTo-StageBCanonicalJson $script:controlledManifest.restore) -or $ownerHash -cne $script:controlledManifest.owners.cleanup_owner_hash){throw 'controlled drop arguments mismatch'}
      $script:providerMutations++; $script:providerDrops++
      [pscustomobject]@{success=$true}
    }
  }
}

$providerRoot=Join-Path ([IO.Path]::GetTempPath()) ('stage-b-provider-'+[guid]::NewGuid())
New-Item -ItemType Directory -Path $providerRoot|Out-Null
try {
  $script:providerConfigurationCalls=0
  $script:providerJobsCalls=0
  $script:providerRecordJobs=$false
  $script:controlledConfiguration=New-ReadOnlyConfiguration
  $script:controlledProvider=New-ControlledRuntimeProvider
  $script:controlledAdapter=New-StageBProductionAdapter {param() $script:providerConfigurationCalls++; $script:controlledConfiguration} {param() $script:providerJobsCalls++; if($script:providerRecordJobs){$null=$script:providerCalls.Add('jobs')}; 0} $script:controlledProvider
  Assert-StageBAdapter $script:controlledAdapter

  $script:PlanOnly=$true; $script:Execute=$false; $script:Cleanup=$false
  $script:PendingManifestPath=Join-Path $providerRoot 'pending.json'
  $planResult=Invoke-StageBMain {param() $script:controlledAdapter}
  $script:controlledManifest=Get-Content -Raw -LiteralPath $script:PendingManifestPath|ConvertFrom-Json
  $script:controlledManifestHash=Get-StageBSha256 $script:PendingManifestPath
  Test-StageBManifest $script:controlledManifest
  Assert-True ($planResult.status -ceq 'success' -and $planResult.manifest_sha256 -ceq $script:controlledManifestHash) 'controlled plan linkage'
  Assert-True ($script:providerConfigurationCalls -eq 1 -and $script:providerJobsCalls -eq 1 -and $script:providerCalls.Count -eq 0 -and $script:providerMutations -eq 0) 'controlled plan zero runtime mutation'
  Assert-True ((@((Get-ChildItem -LiteralPath $providerRoot -Force).Name|Sort-Object)-join ',') -ceq 'checksums.sha256,pending.json') 'controlled plan exact inventory'

  $script:PlanOnly=$false; $script:Execute=$true
  $script:ApprovalPath=Join-Path $providerRoot 'execute-approval.json'
  $executeApproval=[pscustomobject]@{scope='stage-b-backup-restore';action='execute';manifest_sha256=$script:controlledManifestHash;approved_at=[DateTimeOffset]::UtcNow.ToString('o');approver_hash=('d'*64)}
  [IO.File]::WriteAllText($script:ApprovalPath,(ConvertTo-StageBCanonicalJson $executeApproval)+"`n",[Text.UTF8Encoding]::new($false))
  $script:EvidenceRoot=Join-Path $providerRoot 'execution'
  $execution=Invoke-StageBMain {param() $script:controlledAdapter}
  Assert-True ($execution.status -ceq 'success' -and $execution.dump_hash -ceq (Get-StageBTextHash 'controlled-dump') -and $execution.manifest_sha256 -ceq $script:controlledManifestHash) 'controlled execute success'
  Assert-True (($script:providerCalls -join ',') -ceq 'state,stop-worker,stop-web,snapshot-source,pg_dump,pg_restore_list,catalog,create,catalog,pg_restore,snapshot-restore,snapshot-source,start-web,start-worker') 'controlled execute exact provider order'
  Assert-True ($script:providerDrops -eq 0 -and $script:providerCreated -and $script:providerMutations -eq 5) 'controlled execute exact mutations no drop'
  $null=Assert-StageBEvidenceBundle $script:EvidenceRoot $script:controlledManifestHash

  $script:Execute=$false; $script:Cleanup=$true; $script:providerCleanupMode=$true
  $script:providerCalls.Clear(); $script:providerArguments.Clear()
  $script:providerRecordJobs=$true
  $script:ApprovalPath=Join-Path $providerRoot 'cleanup-approval.json'
  $cleanupApproval=[pscustomobject]@{scope='stage-b-backup-restore';action='cleanup';manifest_sha256=$script:controlledManifestHash;approved_at=[DateTimeOffset]::UtcNow.ToString('o');approver_hash=$script:controlledManifest.owners.cleanup_owner_hash}
  [IO.File]::WriteAllText($script:ApprovalPath,(ConvertTo-StageBCanonicalJson $cleanupApproval)+"`n",[Text.UTF8Encoding]::new($false))
  $script:CleanupEvidenceRoot=Join-Path $providerRoot 'cleanup'
  $cleanupResult=Invoke-StageBMain {param() $script:controlledAdapter}
  $executionHash=Get-StageBSha256 (Join-Path $script:EvidenceRoot 'execution.json')
  Assert-True (($script:providerCalls -join ',') -ceq 'state,retained_dump,catalog,jobs,drop,catalog,retained_dump') ('controlled cleanup provider order actual='+($script:providerCalls -join ','))
  Assert-True ($script:providerDrops -eq 1 -and $cleanupResult.drop_count -eq 1 -and $cleanupResult.restore_state -ceq 'absent' -and $cleanupResult.live_blocked -eq $true -and $cleanupResult.criterion_8 -ceq 'not_evaluable') 'controlled cleanup exact one drop'
  $null=Assert-StageBCleanupBundle $script:CleanupEvidenceRoot $script:controlledManifestHash $executionHash
  Assert-True ((Test-Path -LiteralPath $script:EvidenceRoot -PathType Container) -and (Test-Path -LiteralPath $script:PendingManifestPath -PathType Leaf)) 'controlled retained execution and pending'
  $allProviderText=(Get-ChildItem -LiteralPath $providerRoot -File -Recurse|ForEach-Object {[IO.File]::ReadAllText($_.FullName,[Text.Encoding]::UTF8)}) -join "`n"
  Assert-True ($allProviderText -notmatch 'SENTINEL|raw-host|secret|user@|controlled\.dump') 'controlled bundles privacy'
  Assert-True (@(Get-ChildItem -LiteralPath $providerRoot -Force -Recurse|Where-Object {$_.Name -like '*.tmp'}).Count -eq 0) 'controlled integration no temporary residue'

  $script:Cleanup=$false; $script:Execute=$true; $script:providerCleanupMode=$false
  $script:providerRecordJobs=$false
  [IO.File]::WriteAllText($script:ApprovalPath,(ConvertTo-StageBCanonicalJson $executeApproval)+"`n",[Text.UTF8Encoding]::new($false))
  $throwProvider=New-ControlledRuntimeProvider
  $throwProvider.Snapshot={param($target,$mode,$expectedSourceOidHash) $null=$script:providerCalls.Add("snapshot-$mode"); throw $script:providerSentinel}
  $throwAdapter=New-StageBProductionAdapter {param() $script:controlledConfiguration} {param() 0} $throwProvider
  $script:EvidenceRoot=Join-Path $providerRoot 'throw-execution'
  $throwResult=Invoke-StageBMain {param() $throwAdapter}
  Assert-True ($throwResult.status -ceq 'failed' -and $null -eq $throwResult.dump_hash -and $script:providerDrops -eq 0) 'throwing provider failed without drop'
  Assert-True (($script:providerCalls -join ',') -ceq 'state,stop-worker,stop-web,snapshot-source,start-web,start-worker') 'throwing provider recovery order'
  $throwText=[IO.File]::ReadAllText((Join-Path $script:EvidenceRoot 'execution.json'),[Text.Encoding]::UTF8)
  Assert-True ($throwText -notmatch 'SENTINEL|raw-host|secret|user@|controlled\.dump' -and (($throwText|ConvertFrom-Json).status -ceq 'failed')) 'throwing provider privacy no false success'
  Assert-True (@(Get-ChildItem -LiteralPath $providerRoot -Force -Recurse|Where-Object {$_.Name -like '*.tmp'}).Count -eq 0) 'throwing provider no temporary residue'

  $malformedProvider=New-ControlledRuntimeProvider
  $malformedProvider.Snapshot={param($target,$mode,$expectedSourceOidHash) $null=$script:providerCalls.Add("snapshot-$mode"); [pscustomobject]@{leak=$script:providerSentinel}}
  $malformedAdapter=New-StageBProductionAdapter {param() $script:controlledConfiguration} {param() 0} $malformedProvider
  $script:EvidenceRoot=Join-Path $providerRoot 'malformed-execution'
  $malformedResult=Invoke-StageBMain {param() $malformedAdapter}
  $malformedText=[IO.File]::ReadAllText((Join-Path $script:EvidenceRoot 'execution.json'),[Text.Encoding]::UTF8)
  Assert-True ($malformedResult.status -ceq 'failed' -and $null -eq $malformedResult.dump_hash -and $script:providerDrops -eq 0) 'malformed provider failed without drop'
  Assert-True (($script:providerCalls -join ',') -ceq 'state,stop-worker,stop-web,snapshot-source,start-web,start-worker') 'malformed provider recovery order'
  Assert-True ($malformedText -notmatch 'SENTINEL|raw-host|secret|user@|controlled\.dump' -and (($malformedText|ConvertFrom-Json).status -ceq 'failed')) 'malformed provider privacy no false success'
  Assert-True (@(Get-ChildItem -LiteralPath $providerRoot -Force -Recurse|Where-Object {$_.Name -like '*.tmp'}).Count -eq 0) 'malformed provider no temporary residue'
} finally {
  $script:PlanOnly=$false; $script:Execute=$false; $script:Cleanup=$false
  $script:PendingManifestPath=$null; $script:ApprovalPath=$null; $script:EvidenceRoot=$null; $script:CleanupEvidenceRoot=$null
  Remove-Item -LiteralPath $providerRoot -Recurse -Force
}
$root=Join-Path ([IO.Path]::GetTempPath()) ('stage-b-'+[guid]::NewGuid()); New-Item -ItemType Directory -Path $root|Out-Null; try {[IO.File]::WriteAllText((Join-Path $root 'z.txt'),'z');[IO.File]::WriteAllText((Join-Path $root 'a.txt'),'a');Write-StageBChecksums $root;Assert-True ((Get-Content (Join-Path $root 'checksums.sha256'))[0] -match '  a.txt$') 'checksum'} finally {Remove-Item -LiteralPath $root -Recurse -Force}
Write-Output 'Stage B pure validation tests passed'
