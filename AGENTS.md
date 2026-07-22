# AGENTS.md

## Purpose

このリポジトリでは、複数のAI agentが役割分離されたパイプラインとして協調する。

現在の基本パイプライン:

1. planner(codex)
2. implementer(opencode)
3. reviewer(codex)

各agentは自分の責務のみ実行する。
1->2, 2->3は異なるクライアント間のhandoffとなる。
各エージェントは次のクライアントのためのhandoff生成をgoalとする。

---

## Shared Principles

- 現在はMVPフェーズ
- 最小変更を優先する
- 不要な抽象化を禁止する
- 不要リファクタを禁止する
- 既存コードスタイルを尊重する
- scope外変更を禁止する
- 推測で仕様変更しない
- 不明点は明示する
- 検証不能な完了宣言を禁止する

---

## Handoff Rules

agent間通信は structured handoff のみで行う。

各agentは:
- 自分の責務だけ実行する
- 次agentに必要な情報だけ渡す
- 思考ログを丸ごと渡さない
- 未検証情報を事実として渡さない
