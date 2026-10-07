# 無料利用・配布・サポートの範囲

2026-10-07、権利者がこの実装チャットでMITを選定した。
[Issue #56](https://github.com/omitsuhashi/schedula/issues/56)の決定として、
無料の自力導入・組み込みと商用利用を許可し、短い著作権・許諾表示を保持する方式を採用する。
[MIT原文](https://opensource.org/license/mit)・[LICENSE](../LICENSE)・
パッケージメタデータの `license = "MIT"` を一致させる。

## 権利の対象と確認範囲

対象はschedulaの独自コード、実行Schema、独自文書、架空の例・評価入力、CLIと試用デモ。
[来歴記録](sources.md)とGitの導入履歴では、参照ZIPのコード・テストを取り込まず、
業務仕様から独自実装したことを記録している。これは参照原本の再配布許諾を確認したという意味ではない。
`docs/reference/` の原本・ZIP由来のSchemaと例・研究資料はMITの対象に含めない。
無料配布物へ自動的に含めず、公開前にはGit履歴を含めた公開対象を確認する。

wheelには `src/schedula/` のコードと実行Schema、README、LICENSE、
[依存表示](../THIRD_PARTY_NOTICES.md)を含める。参照資料・テスト・実在従業員データは含めない。
デモ・利用例はソース配布の対象であり、wheelにWeb管理画面やその運用が入るわけではない。
各依存は独自ライセンスを維持する。表示はlock済み実行依存の配布元wheelから取得し、
同梱物の著作権・ライセンス原文を保持した。別OS・将来版の依存wheelはその版の表示も確認する。
OR-ToolsはApache-2.0で、任意の `cp-sat` extraとして導入する。
依存wheel自体をschedulaのwheelへ埋め込む構成は採用しない。

## 利用者と委託先の責務

無料範囲はライブラリ、CLI、機能を試せるローカルデモと利用文書。
商用アプリへの登録を自力利用の条件にしない。
利用者は需要・技能・勤務可能時間・履歴・勤務ルールの整備、導入、データ保存、
運用、バックアップ、契約版の選択、結果の採用判断を担う。
計画の独立検証に成功しても、法令・就業規則への適合や探索打切り時の最適性を保証しない。

商用の管理アプリ、顧客設定、初期導入、継続運用、個別開発の有料委託は別リポジトリ・別契約の責務。
このリポジトリがホスト型の無料管理アプリ、SLA、有料サポートを提供済みとは扱わない。
無償サポートはIssuesで受け付けるベストエフォートで、応答期限・個別改修を約束しない。

## 固定版での導入

現在はリポジトリが非公開で、PyPIには公開していない。
アクセスできる利用者はcloneし、READMEの手順で `uv sync --locked --extra cp-sat` を実行する。
対応はCPython 3.14、CIのLinuxと実測したmacOS ARM64。Windowsの実動作は未検証。
最小費用流と保存済み勤務計画の独立検証にはOR-Toolsが不要。

```sh
uv build --wheel
uv export --locked --extra cp-sat --no-dev --no-emit-project --output-file runtime-requirements.txt
sha256sum dist/schedula-0.1.4-py3-none-any.whl
uv init --python 3.14 my-scheduler
cd my-scheduler
uv add --constraints ../runtime-requirements.txt '../dist/schedula-0.1.4-py3-none-any.whl[cp-sat]'
uv run python -c 'from schedula import solve, verify, make_baseline, get_schema; print(get_schema("request", "0.4")["$id"])'
```

`dist/` と依存一覧はエンジン側で作った固定成果物を配布する。
利用側はそのwheel・SHA-256・採用したエンジン版・入出力契約版・自分のlock fileを保存する。
uv自体の導入は[Pythonセットアップ](python-setup.md)を参照する。
wheelの取得元を差し替えた場合はパスも明示して変更する。
`schema_version` とエンジンの配布版は別で、0.1.4のwheelは契約0.1〜0.4を同梱する。
新しい業務ルールは新契約版へ追加し、旧版の意味を黙って変更しない。
候補件数上限の撤廃は受理範囲の拡大であり、保存済みSchemaは再取得する。

## 問い合わせ・セキュリティ窓口

通常の不具合は[GitHub Issues](https://github.com/omitsuhashi/schedula/issues)で管理する。
受付担当はリポジトリ所有者 `@omitsuhashi`。
現時点のリポジトリは非公開なので、アクセス権を持つ利用者のセキュリティ連絡もこの非公開窓口で受け付ける。
初報にはエンジン版と影響概要を記載し、認証情報・実在従業員データ・攻撃可能な再現情報を載せない。
詳細の安全な受け渡し方法は所有者と決める。

公開前に外部利用者が使える非公開報告窓口を設定・確認し、案内を更新する。
Private vulnerability reportingの設定APIは今回404だったため、有効とは表示しない。
現在の非公開Issuesを、将来の公開環境でも非公開だと誤認して使わない。

## 公開作業の完了条件

このマイルストーンでは条件と配布物を整備し、可視性変更・タグ作成・PyPI公開は別作業とする。
実際の公開前に次を確認する。

- 公開対象のコード・文書・Git履歴から、許諾未確認の参照資料と機密情報を除外する。
- LICENSE・README・メタデータ・依存表示が一致し、対象環境の依存wheelの同梱表示を保持する。
- 必須CI、契約0.4、wheel隔離導入、OR-Toolsなしの検証、利用例を確認する。
- 外部利用者向け非公開セキュリティ窓口、対応環境、版管理、サポート範囲を確定する。
- 配布元・SHA-256・正式タグの権限を確認し、公開結果を別途記録する。

現在のwheel build・ローカル試用・非公開PRの成功は、無料公開や商用運用の開始を意味しない。
