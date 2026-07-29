$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'validate_stage_b_backup_restore.ps1')
function Assert-True($Value,[string]$Message){if(-not $Value){throw $Message}}
function Assert-Throws($Action,[string]$Message){try {& $Action; throw $Message} catch {if($_.Exception.Message -eq $Message){throw $Message}}}
function New-Manifest {
 $h={param($x) Get-StageBTextHash $x}; [pscustomobject]@{schema_version=1;run_id='run-001';scope='stage-b-backup-restore';live_blocked=$true;criterion_8='not_evaluable';created_at=[DateTimeOffset]::UtcNow.ToString('o');expires_at=[DateTimeOffset]::UtcNow.AddHours(1).ToString('o');source=[pscustomobject]@{endpoint_hash=&$h 'source-endpoint';database_hash=&$h 'source-db';oid_hash=&$h 'source-oid';role_hash=&$h 'source-role';server_version_num_hash=&$h '16'};restore=[pscustomobject]@{endpoint_hash=&$h 'restore-endpoint';database_hash=&$h 'restore-db';oid_hash=&$h 'restore-oid';owner_hash=&$h 'restore-owner';state='absent'};protected=@([pscustomobject]@{endpoint_hash=&$h 'protected-endpoint';database_hash=&$h 'protected-db';oid_hash=&$h 'protected-oid'});source_baseline_hash=&$h 'baseline';clients=[pscustomobject]@{pg_dump_hash=&$h 'dump';pg_restore_hash=&$h 'restore';server_version_num_hash=&$h '16'};storage=[pscustomobject]@{root_hash=&$h 'local';capacity_bytes=100;required_bytes=10;retention_days=1};owners=[pscustomobject]@{restore_owner_hash=&$h 'restore-owner';cleanup_owner_hash=&$h 'cleanup-owner'};services=[pscustomobject]@{worker_hash=&$h 'worker';web_hash=&$h 'web';stop_order=@('worker','web');recovery_order=@('web','worker')};execution_state='pending'}
}
function Copy-Manifest($m){$m|ConvertTo-Json -Depth 20|ConvertFrom-Json}
function New-ReadOnlyConfiguration {
 [pscustomobject]@{
  source=[pscustomobject]@{endpoint='raw-source-endpoint';database='raw-source-db';oid='raw-source-oid';role='raw-source-role';server_version_num='16'}
  restore=[pscustomobject]@{endpoint='raw-restore-endpoint';database='raw-restore-db';oid='raw-restore-oid';state='absent'}
  protected=@([pscustomobject]@{endpoint='raw-protected-endpoint';database='raw-protected-db';oid='raw-protected-oid'})
  source_baseline='raw-source-baseline'
  clients=[pscustomobject]@{pg_dump='raw-pg-dump';pg_restore='raw-pg-restore';server_version_num='16'}
  storage=[pscustomobject]@{root='raw-storage-root';capacity_bytes=100;required_bytes=10;retention_days=1}
  owners=[pscustomobject]@{restore_owner='raw-restore-owner';cleanup_owner='raw-cleanup-owner'}
  services=[pscustomobject]@{worker='raw-worker';web='raw-web'}
 }
}
function New-FakeAdapter($m,$Failure='') {
  $script:events=[Collections.Generic.List[string]]::new(); $script:mutations=0
  $script:state=[pscustomobject]@{jobs=0;source_baseline_hash=$m.source_baseline_hash;source=$m.source;restore=$m.restore;clients=$m.clients;storage=$m.storage;owners=$m.owners;services=$m.services}; $script:manifest=$m; $script:failure=$Failure; $script:created=$false
  @{Pending={param() $script:manifest};Jobs={param() 0};State={param($manifest) if($script:failure -eq 'state') {throw 'state failure'}; $script:state};Service={param($action,$service) $null=$script:events.Add("$action-$service"); if($script:failure -eq "service-$action-$service"){throw 'service failure'}; if($script:failure -eq "service-false-$action-$service"){return [pscustomobject]@{success=$false}}; if($script:failure -eq "service-malformed-$action-$service"){return [pscustomobject]@{}}; if($script:failure -eq "service-throw-$action-$service"){throw 'service throw'}; if($script:failure -eq "service-int1-$action-$service"){return [pscustomobject]@{success=1}}; if($script:failure -eq "service-strtrue-$action-$service"){return [pscustomobject]@{success='true'}}; if($action -eq 'stop'){$script:mutations++}; [pscustomobject]@{success=$true}};Snapshot={param($target,$mode,$expectedSourceOidHash) if($script:failure -eq "snapshot-$mode"){throw 'snapshot failure'}; [pscustomobject]@{identity=[pscustomobject]@{oid_hash=if($mode -eq 'source'){$script:manifest.source.oid_hash}else{$script:manifest.restore.oid_hash}};baseline_hash=$script:manifest.source_baseline_hash;semantic_hash=(Get-StageBTextHash 'semantic')}};Process={param($operation,$arguments,$environment) $null=$script:events.Add($operation); if($script:failure -eq $operation){return [pscustomobject]@{success=$false;size=0;hash=$null}}; [pscustomobject]@{success=$true;size=1;hash=(Get-StageBTextHash 'dump')}};Catalog={param($target) if($script:failure -eq 'catalog') {throw 'catalog failure'};if($script:created){[pscustomobject]@{state='existing_empty';oid_hash=$script:manifest.restore.oid_hash;owner_hash=$script:manifest.owners.restore_owner_hash;connections=0}}else{[pscustomobject]@{state='absent';oid_hash=$null;owner_hash=$null;connections=0}}};CreateRestore={param($target,$ownerHash) $script:created=$true; $null=$script:events.Add('create');[pscustomobject]@{success=$true}};DropRestore={param($target,$ownerHash) $null=$script:events.Add('drop');[pscustomobject]@{success=$true}}}
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

# Focused Service Ownership Tests (12 test cases)
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
  @{name='20. both stops succeed, start-worker returns {success="true"}'; failure='service-strtrue-start-worker'; expectStatus='failed'; expectStarts=@('start-web','start-worker'); expectStages=@('stop_worker','stop_web','start_web'); expectMutations=2; desc='string true rejected for start-worker, no start_worker stage'}
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
$root=Join-Path ([IO.Path]::GetTempPath()) ('stage-b-'+[guid]::NewGuid()); New-Item -ItemType Directory -Path $root|Out-Null; try {[IO.File]::WriteAllText((Join-Path $root 'z.txt'),'z');[IO.File]::WriteAllText((Join-Path $root 'a.txt'),'a');Write-StageBChecksums $root;Assert-True ((Get-Content (Join-Path $root 'checksums.sha256'))[0] -match '  a.txt$') 'checksum'} finally {Remove-Item -LiteralPath $root -Recurse -Force}
Write-Output 'Stage B pure validation tests passed'