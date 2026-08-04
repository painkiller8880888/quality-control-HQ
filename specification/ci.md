# CI / Pull Request quality gates

## Check names and coverage

Branch rulesetで要求するstatus check名は、workflowのjob名と同じ次の5つです。

- backend: `requirements.lock`からPython依存をclean installし、PostgreSQL 18 service上でDjango check、migration drift check、configとqualityの全Django test、production-likeな check --deploy を実行します。`requirements.lock`は`requirements.txt`をPython 3.12向けにuvで固定したファイルです。Django test runnerが作るtest databaseのため、CIのservice roleにはCREATE DATABASE権限が必要です。
- frontend: frontend/package-lock.jsonに対する npm ci の後、lint、build、生成物が空でないことを確認します。
- dependency-audit: `requirements.lock`の固定versionをpip-audit、Nodeを npm audit --audit-level=high で監査します。High/Critical相当の結果は失敗扱いにし、恒久的なignoreは作りません。
- windows-dependency-audit: Windows runnerで同じ`requirements.lock`を`--require-hashes`付きでclean installし、`pip check`、`pip-audit --strict`、Windows固有依存（pywin32、Waitress等）のimportを確認します。実サービス、Office、UNC、ERPへは接続しません。
- secret-scan: PRでは`pull_request.base.sha..pull_request.head.sha`をGitleaks CLIの`--log-opts`へ明示的に渡して差分を検査します。mainへのpushでは`before..sha`を検査します。APIのコミット一覧には依存しません。検出時は失敗し、コメント・artifact・job summaryへの出力はありません。
- secret-scan-history: `.github/workflows/secret-history.yml`の`workflow_dispatch`でGitleaks CLIによるrepository全履歴検査を実行します。通常CIとはworkflowとconcurrencyを分離し、PR差分のrequired checkにはしません。

外部actionはworkflow内でcommit SHAに固定し、コメントに対応versionを記載しています。Gitleaks CLIは公式releaseのversionとSHA256をworkflow内で固定しています。workflowにpath filterは設定していないため、必須check自体が消えることはありません。

## Local verification

依存とPostgreSQLを先に準備し、実DB・実共有資源ではなくCI用のダミー環境変数を使って、リポジトリルートから次を実行します。

1. Windows PowerShellまたはPowerShell 7で、`requirements.lock`からPython依存をinstallし、PostgreSQLを起動します。
2. frontendで npm ci を実行します。
3. pwsh -NoProfile -File scripts/verify.ps1 -Scope All を実行します。
4. 監査ツールを用意できる場合は、`pip-audit -r requirements.lock --strict` と、frontend内の `npm audit --audit-level=high` を実行します。

依存範囲を変更した場合は、uv `0.11.11`を用意し、リポジトリルートで次を実行して`requirements.lock`を更新し、lockも同じPRへ含めます。CIのdependency-auditは同じ固定uvでこのコマンドを再実行し、差分があれば失敗します。backendとWindows dependency checkは、整合性が確認されたこのlockだけを使用します。

```text
uv pip compile requirements.txt --universal --python-version 3.12 --generate-hashes --output-file requirements.lock
```

production-like deployment checkは`--fail-level WARNING`で実行します。CIでは外部TLS終端後のHTTPS経路を表す`SECURE_SSL_REDIRECT=true`、`SECURE_HSTS_SECONDS=31536000`、HSTSのsubdomains/preload、十分な長さの非機密dummy `DJANGO_SECRET_KEY`を明示し、既知のsecurity warningを合格扱いにしません。実本番の値はCI dummyを流用せず、承認済みのTLS終端・環境設定で管理します。

verify.ps1は環境構築・依存install・本番接続を行わず、Backend、Frontend、AllのscopeでCI主要コマンドをfail-fastに再現します。

## CIで検証しない資源

PR CIはLinux runnerとmock済み自動試験だけを使用します。実際のUNC共有、社内LAN、ERP、Excel COM / Office、プリンタ、Windowsサービス、疑似本番DBへ接続しません。該当するbackend testはfixture、patch、非Windows用のtest shimで外部操作をmockします。Windows固有の実接続・サービス回復試験はWindows環境で別途実施します。

## Main Rulesetの手動設定

repository settings自体はこのPRで変更しません。管理者がmainのRulesetで次を手動設定してください。

1. mainへのPRを必須にする。
2. backend、frontend、dependency-audit、windows-dependency-audit、secret-scanをrequired status checksにする。`secret-scan-history`は手動workflowのためrequiredにはしない。
3. conversation resolutionを必須にする。
4. force pushとbranch deletionを禁止する。
5. approval数は個人開発の利用者が運用に合わせて設定する。ここでは1件に固定しません。

これにより、mainへの直接更新ではなく、Draft PR、CI、レビュー、マージを標準経路にできます。
