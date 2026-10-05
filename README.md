# schedula

技能・勤務可能時間・役割別需要・業務ルールから、担当配置と勤務計画を求める
最適化エンジンを目指します。飲食店を最初の利用例とし、役割や技能は設定データで表現します。
アルゴリズムと共通の JSON 入出力を先に整備し、LLM による入力生成を後から接続します。

## 設計ドキュメント

開発者・仕様を決める人が、対象範囲と守るべき意味を共有するためのひな形です。
次の順に読むと、全体から個別の実装条件まで確認できます。

| 文書 | 内容 |
| --- | --- |
| [全体像](docs/overview.md) | 目的、利用例、対象範囲、構成、公開物 |
| [設計方針](docs/design-policy.md) | アルゴリズム選択、制約・選好、検証、LLM の境界 |
| [入出力契約](docs/io-contract.md) | JSON の意味、日時、履歴、目的順序、結果状態 |
| [開発・検証方針](docs/development-policy.md) | 開発順序、完了条件、公開条件、未決定事項 |
| [参照実装の評価](docs/evaluations/engine-introduction.md) | CP-SAT を含む実測、導入時の修正、コードの採用可否と公開入口 |
| [用語集](GLOSSARY.md) | single-context の共通用語 |
| [設計判断](docs/adr/0001-json-first-engine.md) | JSON を中心にしたエンジンと、[勤務計画の同時最適化](docs/adr/0002-joint-roster-optimization.md) |
| [出典と採用判断](docs/sources.md) | 元チャット、ZIP、採用箇所、参照資料の来歴 |

schedula 0.1.0 は独立した `assignment` を最小費用流で解き、
結果の構造・担当資格・勤務可能時間・厳密な需要・二重配置と評価値を独立検証します。
ライブラリは `from schedula import solve`、CLI は `python -m schedula solve` です。
`roster`、時間横断制約、`cp_sat` は未対応で、指定すると `INVALID_INPUT` を返します。

```sh
uv sync --locked
uv run --locked python -m schedula solve examples/assignment.json
uv run --locked python -m schedula schema request
uv run --locked python -m schedula schema response
```

例は選好ペナルティ0の検証済み `OPTIMAL` を返します。
[担当配置の利用手順](docs/assignment.md)に、標準入力、ライブラリ、対応範囲、
診断・終了コード、探索予算と上限を記載しています。
[担当配置の検証記録](docs/evaluations/assignment.md)は、今回の実測と未検証事項を示します。

添付 `skillshift-starter-0.1.zip` は設計の参照元です。
保存済み原本は `docs/reference/skillshift-starter-0.1/` に保持し、変更していません。
参照コードはライセンス未選定のため取り込みを保留し、schedula のコード・Schema・例・テストは
採用済み業務仕様から独自実装しました。過去の参照評価は上記の評価記録と区別します。

## Python のセットアップ

依存の追加・インストール・実行は uv を標準とし、
[Python セットアップ](docs/python-setup.md)を手順の正本にします。
Python は依存パッケージが対応する最新の 3.14.8 に固定しています。
jsonschema・OR-Tools と Ruff・pytest・pre-commit を uv で管理します。
リポジトリ直下で初回セットアップと検証を実行してください。

```sh
uv python install
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat pre-commit install --install-hooks
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
uv run --locked --extra cp-sat pytest
bash -n scripts/deploy
```

既存 hook と衝突する場合は上書きせず、[Git hook の確認手順](docs/python-setup.md#git-hook)に従ってください。
参照 ZIP の評価手順と依存更新の方法も同じ文書に記載しています。

## デプロイ

デプロイの入口は、環境名とビルド済みの成果物ファイルを引数で受け取ります。

```bash
scripts/deploy staging ./release.tar.gz
scripts/deploy production ./release.tar.gz
```

デプロイ先は未定です。スクリプトは引数を検証し、デプロイが実装されるまでは
終了コード1で失敗します。引数が不正な場合は終了コード2で失敗します。
現時点ではビルド・アップロード・デプロイは行いません。

今後導入するリリース workflow では、staging と production に同じ成果物を渡して
このスクリプトを呼び出します。production は GitHub Environment の承認を待ってから
実行します。workflow の導入前に、Environment の保護を設定・検証します。

## Repository の変更管理

main の変更には PR と、CI チェック `deploy-entrypoint` の成功が必要です。
一人運用のため、PR の必須承認は0名です。merge は squash のみに限定し、
main の force push と削除は禁止します。ruleset の bypass は許可しません。

`v*` の正式タグを作成できるのは Repository Admin のみです。現在は
@omitsuhashi が該当します。将来 Admin を追加すると、その人もタグを作成できます。
既存の `v*` タグの移動・削除は禁止し、Admin による bypass も許可しません。

デプロイに関して未確定なのは、production の承認者、実際のビルドコマンド、
デプロイ先です。デプロイの入口と CI はセットアップ PR で導入し、
merge 後に main で利用できるようになります。
