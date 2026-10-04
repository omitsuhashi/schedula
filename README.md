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
| [用語集](GLOSSARY.md) | single-context の共通用語 |
| [設計判断](docs/adr/0001-json-first-engine.md) | JSON を中心にしたエンジンと、[勤務計画の同時最適化](docs/adr/0002-joint-roster-optimization.md) |
| [出典と採用判断](docs/sources.md) | 元チャット、ZIP、採用箇所、参照資料の来歴 |

2026-10-04 時点で、このリポジトリには最適化エンジンを導入していません。
添付 `skillshift-starter-0.1.zip` は設計・実装の参照元です。
その JSON Schema、例、検証報告を `docs/reference/skillshift-starter-0.1/` に保存しています。
ZIP の報告は 196 passed / 28 skipped で、CP-SAT は実行未検証です。
今回の文書整備でエンジンの動作を再検証したという意味ではありません。

## Python のセットアップ

依存の追加・インストール・実行は uv を標準とし、
[Python セットアップ](docs/python-setup.md)を手順の正本にします。
現在は `pyproject.toml` と `uv.lock` がなく、デプロイ入口のテストは標準ライブラリだけで実行できます。
リポジトリ直下で次を実行してください。

```sh
bash -n scripts/deploy
uv run --no-project python -m unittest discover -s tests -v
```

エンジン導入時の開発依存・Git hook と、参照 ZIP を隔離環境で評価する手順も
[Python セットアップ](docs/python-setup.md)に記載しています。

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
