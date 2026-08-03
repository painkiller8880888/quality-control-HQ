# CI / Pull Request quality gates

## Check names and coverage

Branch rulesetで要求するstatus check名は、workflowのjob名と同じ次の4つです。

- backend: PostgreSQL 18 service上で依存をclean installし、Django check、migration drift check、configとqualityの全Django test、production-likeな check --deploy を実行します。Django test runnerが作るtest databaseのため、CIのservice roleにはCREATE DATABASE権限が必要です。
- frontend: frontend/package-lock.jsonに対する npm ci の後、lint、build、生成物が空でないことを確認します。
- dependency-audit: Pythonを pip-audit、Nodeを npm audit --audit-level=high で監査します。High/Critical相当の結果は失敗扱いにし、恒久的なignoreは作りません。
- secret-scan: GitleaksでPR差分とrepository historyを検査します。検出時は失敗し、コメント・artifact・job summaryへの出力は無効にしています。

外部actionはworkflow内でcommit SHAに固定し、コメントに対応versionを記載しています。workflowにpath filterは設定していないため、必須check自体が消えることはありません。

## Local verification

依存とPostgreSQLを先に準備し、実DB・実共有資源ではなくCI用のダミー環境変数を使って、リポジトリルートから次を実行します。

1. Windows PowerShellまたはPowerShell 7で、Python依存をinstallし、PostgreSQLを起動します。
2. frontendで npm ci を実行します。
3. pwsh -NoProfile -File scripts/verify.ps1 -Scope All を実行します。
4. 監査ツールを用意できる場合は、pip-audit -r requirements.txt --strict と、frontend内の npm audit --audit-level=high を実行します。

verify.ps1は環境構築・依存install・本番接続を行わず、Backend、Frontend、AllのscopeでCI主要コマンドをfail-fastに再現します。

## CIで検証しない資源

PR CIはLinux runnerとmock済み自動試験だけを使用します。実際のUNC共有、社内LAN、ERP、Excel COM / Office、プリンタ、Windowsサービス、疑似本番DBへ接続しません。該当するbackend testはfixture、patch、非Windows用のtest shimで外部操作をmockします。Windows固有の実接続・サービス回復試験はWindows環境で別途実施します。

## Main Rulesetの手動設定

repository settings自体はこのPRで変更しません。管理者がmainのRulesetで次を手動設定してください。

1. mainへのPRを必須にする。
2. backend、frontend、dependency-audit、secret-scanをrequired status checksにする。
3. conversation resolutionを必須にする。
4. force pushとbranch deletionを禁止する。
5. approval数は個人開発の利用者が運用に合わせて設定する。ここでは1件に固定しません。

これにより、mainへの直接更新ではなく、Draft PR、CI、レビュー、マージを標準経路にできます。
