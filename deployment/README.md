# 疑似本番基盤

## Stage B backup/restore validation

`windows/validate_stage_b_backup_restore.ps1` is the sole Stage B orchestrator. Pending and final evidence use a versioned, strict allowlist schema: all protected identities are normalized and SHA-256 hashed, while raw database, host, role, service, storage, command, credential, and error values are excluded. The Python snapshot helper is the authority for canonical semantic hashes: compact sorted-key UTF-8 JSON, deterministic ordered rows, and a sorted distinct `InspectionFile` path set.

`-PlanOnly` is read-only: it requires a source baseline, protected-target denylist, distinct restore endpoint/OID proof, PostgreSQL client/version records, storage capacity and retention, owner roles, and service identities before atomically writing a pending manifest. `-Execute` requires a strict, time-bounded approval for that exact manifest and revalidates every protected identity, baseline, empty/absent restore state, capacity, retention, and client/server version before any mutation. The approved sequence is worker stop, web stop, dump, restore-target create/verify, restore, source/restore comparison, web start, worker start. Runtime adapters are deliberately not enabled by this implementation cycle, so all public modes remain fail-closed until an approved production adapter is supplied.

`-Cleanup` is separately approved and may only drop the approved restore database after owner, endpoint/database/OID, dump-hash, protected-target, and active-connection rechecks. Dumps and partial restore databases are retained on every failure; neither is automatically deleted. Evidence checksums use lowercase SHA-256 and ordinal, `/`-normalized relative paths, excluding the checksum file itself and temporary files.

The focused, mutation-free checks are:

`python deployment/postgresql/test_stage_b_snapshot.py`

`powershell.exe -NoProfile -ExecutionPolicy Bypass -File deployment/windows/test_validate_stage_b_backup_restore.ps1`

Before approval, the backup owner supplies distinct lowercase source/restore identities, development and production denylist entries, storage/retention details, service order, and named operator, cleanup, and rollback roles. The restore name is never derived from the source. Retain the dump and any partial restore database on failure; never delete either automatically. Cleanup later requires a recheck of the approved identity and dump hash by the cleanup owner. Preserve Web-first/worker-second recovery, zero active Jobs, `LIVE_BLOCKED=True`, and criterion 8 `not_evaluable`; no login, Job submission, UNC access, live A/B, or active-database restore is permitted.

現在のWindows PC上で、開発環境と分離した疑似本番を構築するための設定である。

## 初回準備

既存の`quality_control_hq`には開発データがあるため、当面はこれを開発DBとして保持する。疑似本番用`quality_prodlike`を別DB・別ロールで追加し、開発データを破壊または移動しない。

1. `deployment/pseudoprod/.env.example`と`.env.migrate.example`をそれぞれ拡張子なしの実設定へコピーし、置換対象を実値へ変更する。Waitressにはruntime設定だけを渡す。
2. 管理者PowerShellから`configure_postgresql_localhost.ps1`を実行し、PostgreSQLの待受をlocalhostへ限定する。
3. `deployment/postgresql/.env.bootstrap.example`を`.env.bootstrap`へコピーして秘密値を設定し、`initialize_databases.py --env-file <path>`で疑似本番・開発のDBとロールを分離する。
4. 仮想環境へ`requirements.txt`をインストールする。
5. `deployment/windows/build_pseudoprod.ps1`でfrontend build、サービス停止、migration、成果物切替、collectstatic、deployment check、サービス再開を実行する。旧frontend成果物は`runtime/rollback`へ保存される。
6. `deployment/windows/run_pseudoprod.ps1`でWaitressを手動起動し、疎通と異常応答を確認する。
7. クライアントIPが確定したら、管理者PowerShellから`configure_firewall.ps1 -ClientIp <IPv4>`を実行する。
8. `verify_network.ps1`でPostgreSQLがlocalhost以外に待ち受けていないことを確認する。
9. 手動確認後、管理者PowerShellから`install_pseudoprod_service.ps1`を実行してWinSWサービスを登録する。配置済みWinSW v2.12.0はSHA256で固定検証する。続けて`install_pseudoprod_worker_service.ps1`を実行し、Waitressとは別の`QualityControlHQ-Worker-Pseudoprod`サービスを登録する。workerは1プロセス・同時実行1で開始する。
10. `smoke_login.py --env-file deployment/pseudoprod/.env`で、実HTTPのCSRF、ログイン、セッション維持、ログアウトを試験する。一時ユーザーは試験後に削除される。
11. 管理者PowerShellから`test_service_recovery.ps1`を実行し、Waitressの異常終了後45秒以内に別PIDでHTTP 200へ復旧することを確認する。
12. `create_pseudoprod_admin.ps1 -LoginName <ID> -DisplayName <表示名>`を実行し、画面に表示せず対話入力したパスワードで初期管理者を作成する。
13. 定期保守として`python backend/manage.py cleanup_job_inputs --days 7`を実行し、完了・失敗Jobの入力ファイルを7日経過後に削除する。
14. `test_worker_recovery.ps1`でworker子プロセスを異常終了させ、45秒以内に別PIDで復旧することを確認する。

現在PCの既存開発DBを維持して疑似本番だけを追加する場合は、1と3の代わりに`initialize_pseudoprod.ps1 -PublicHost <DNS名>`を実行する。このスクリプトは秘密値を自動生成し、環境ファイルの継承権限を外してから`quality_prodlike`だけを初期化する。

HTTP承認書の原本、DBパスワード、Django secretはリポジトリへ保存しない。承認IDと期限だけを疑似本番の環境設定へ記録する。

更新作業枠は60分、通常停止目標は30分とする。frontendは停止前にstagingへビルドし、停止後はworker、Waitressの順に停止してからmigration、成果物切替、collectstatic、Waitress、workerの順で起動し、簡易E2Eを実施する。失敗時は直前のfrontend成果物へ戻すが、DB migrationは自動では戻らないため、切戻し可能性を更新前に承認する。

第2段階の既定値は、heartbeat 30秒、lease 120秒、最大3試行、再試行間隔30秒・120秒・300秒とする。`quality_master`のtimeoutは30分、ERPは10分、その他Jobは15分とする。印刷やERPなど外部副作用があるJobは、lease失効時に自動再試行せず失敗として管理者確認を要求する。
