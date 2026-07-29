$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'validate_stage_b_backup_restore.ps1')
function Assert-True($Value,[string]$Message){if(-not $Value){throw $Message}}
Assert-True (Test-StageBIdentifier 'restore_db') 'identifier'
foreach($bad in @('Restore','a-b')){Assert-True (-not(Test-StageBIdentifier $bad)) 'invalid identifier'}
Assert-True ((Normalize-StageBHost ' Db.Example. ') -eq 'db.example') 'host normalization'
Assert-True ((Normalize-StageBPort '05432') -eq '5432') 'port normalization'
try {Normalize-StageBHost 'http://secret'; throw 'host accepted'} catch {Assert-True ($_.Exception.Message -ne 'host accepted') 'host rejected'}
$source=@{endpoint_hash='a';database_hash='b';oid_hash='c'}; $restore=@{endpoint_hash='x';database_hash='y';oid_hash='z';state='absent'}
$manifest=[pscustomobject]@{schema_version=1;run_id='run';scope='stage-b-backup-restore';live_blocked=$true;criterion_8='not_evaluable';created_at=[DateTimeOffset]::UtcNow.ToString('o');expires_at=[DateTimeOffset]::UtcNow.AddHours(1).ToString('o');source=$source;restore=$restore;protected=@(@{endpoint_hash='p';database_hash='q';oid_hash='r'});source_baseline_hash=('a'*64);clients=@();storage=@{};owners=@{restore_owner_hash=('b'*64)};services=@{};execution_state='pending'}
Test-StageBManifest $manifest
$approval=[pscustomobject]@{scope='stage-b-backup-restore';action='execute';manifest_sha256=('c'*64);approved_at=[DateTimeOffset]::UtcNow.ToString('o');approver_hash=('d'*64)}
Test-StageBApproval $approval ('c'*64) 'execute'
try {Test-StageBApproval $approval ('e'*64) 'execute'; throw 'tamper accepted'} catch {Assert-True ($_.Exception.Message -ne 'tamper accepted') 'tamper rejected'}
try {Test-StageBManifest ([pscustomobject]@{schema_version=1}); throw 'schema accepted'} catch {Assert-True ($_.Exception.Message -ne 'schema accepted') 'schema rejected'}
$events=[Collections.Generic.List[string]]::new(); $adapter=@{Jobs=0; Service={param($action,$name) $null=$events.Add("$action-$name")}; Snapshot={param($target,$mode,$oid) [pscustomobject]@{identity=@{oid_hash=if($mode -eq 'source'){'c'}else{'z'}}}}; Process={param($name,$args,$env) $null=$events.Add($name); [pscustomobject]@{success=$true;size=1;hash=('f'*64)}}; Catalog={param($target) [pscustomobject]@{state='absent';oid_hash=$null}}; CreateRestore={param($target,$owner) $null=$events.Add('create')}; DropRestore={param($target) $null=$events.Add('drop')}}
$result=Invoke-StageBSequence $manifest $adapter
Assert-True ($result.status -eq 'success') 'sequence'
Assert-True (($events -join ',') -eq 'stop-worker,stop-web,pg_dump,create,pg_restore,start-web,start-worker') 'order'
Assert-True (-not($events -contains 'drop')) 'no automatic cleanup'
try { throw 'password host db role C:\\secret' } catch {Assert-True ((Get-StageBRedactedError $_) -eq 'stage_b_operation_failed') 'redaction'}
$root=Join-Path ([IO.Path]::GetTempPath()) ('stage-b-'+[guid]::NewGuid()); New-Item -ItemType Directory -Path $root|Out-Null; [IO.File]::WriteAllText((Join-Path $root 'z.txt'),'z'); [IO.File]::WriteAllText((Join-Path $root 'a.txt'),'a'); Write-StageBChecksums $root; $lines=Get-Content (Join-Path $root 'checksums.sha256'); Assert-True ($lines[0] -match '  a.txt$') 'checksum order'; Remove-Item -LiteralPath $root -Recurse -Force
Write-Output 'Stage B pure validation tests passed'
