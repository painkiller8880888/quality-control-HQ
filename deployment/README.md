# 疑似本番基盤

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
9. 手動確認後、管理者PowerShellから`install_pseudoprod_service.ps1`を実行してWinSWサービスを登録する。配置済みWinSW v2.12.0はSHA256で固定検証する。
10. `smoke_login.py --env-file deployment/pseudoprod/.env`で、実HTTPのCSRF、ログイン、セッション維持、ログアウトを試験する。一時ユーザーは試験後に削除される。
11. 管理者PowerShellから`test_service_recovery.ps1`を実行し、Waitressの異常終了後45秒以内に別PIDでHTTP 200へ復旧することを確認する。
12. `create_pseudoprod_admin.ps1 -LoginName <ID> -DisplayName <表示名>`を実行し、画面に表示せず対話入力したパスワードで初期管理者を作成する。

現在PCの既存開発DBを維持して疑似本番だけを追加する場合は、1と3の代わりに`initialize_pseudoprod.ps1 -PublicHost <DNS名>`を実行する。このスクリプトは秘密値を自動生成し、環境ファイルの継承権限を外してから`quality_prodlike`だけを初期化する。

HTTP承認書の原本、DBパスワード、Django secretはリポジトリへ保存しない。承認IDと期限だけを疑似本番の環境設定へ記録する。

更新作業枠は60分、通常停止目標は30分とする。frontendは停止前にstagingへビルドし、停止後にmigration、成果物切替、collectstatic、起動、簡易E2Eの順で実施する。失敗時は直前のfrontend成果物へ戻すが、DB migrationは自動では戻らないため、切戻し可能性を更新前に承認する。
