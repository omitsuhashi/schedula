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

wheelには `src/shift_schedula/` のコードと実行Schema、README、LICENSE、
[依存表示](../THIRD_PARTY_NOTICES.md)を含める。参照資料・テスト・実在従業員データは含めない。
デモ・利用例はソース配布の対象であり、wheelにWeb管理画面やその運用が入るわけではない。
sdistには利用例・デモ・中核テストと補助ファイル・利用文書・lockを含める。
`docs/reference/` の原本と `docs/evaluations/results/` の過去の測定生データは含めない。
非同梱資料への文書リンクは、保存時のGitHub参照へ案内する。
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

配布名は `shift-schedula`、Python package は `shift_schedula`、CLI は
`python -m shift_schedula` とする。GitHubのリポジトリ名は `omitsuhashi/schedula` を維持する。
既存の別作者の [schedula](https://pypi.org/project/schedula/) と同居できるよう、
`schedula` 名の互換packageは同梱しない。JSON契約版、業務ID、既存Schemaの
`urn:schedula:...` は保存済み入力との互換性のため維持する。

現在はリポジトリが非公開で、PyPIには公開していない。
アクセスできる利用者はcloneし、READMEの手順で `uv sync --locked --extra cp-sat` を実行する。
配布のPython要件は `>=3.14`。実測した対応は通常のCPython 3.14、CIのLinuxとmacOS ARM64。
2026-10-07時点の最新安定版も3.14.8であり、新しい安定版・free-threaded・他実装は未検証。
Windows x86_64は2026-10-07のCIでbase/extraのwheel導入・求解・独立検証・Schema取得・入力検証・spawnによる総期限/取消と独立した並行実行を確認した。
Windowsでの全中核テストとブラウザー検証は未実施。CP-SATは対象環境のOR-Tools wheelが必要となる。
最小費用流と保存済み勤務計画の独立検証にはOR-Toolsが不要。
`tzdata` はbaseの直接依存として同梱表示を保持し、OSの時刻データがない環境でも使う。
OSのTZDB優先・tzdata fallbackと再現方法は[Pythonセットアップ](python-setup.md)を参照する。

```sh
uv build --wheel
uv export --locked --extra cp-sat --no-dev --no-emit-project --output-file runtime-requirements.txt
sha256sum dist/shift_schedula-0.1.5-py3-none-any.whl
uv init --python 3.14 my-scheduler
cd my-scheduler
uv add --constraints ../runtime-requirements.txt '../dist/shift_schedula-0.1.5-py3-none-any.whl[cp-sat]'
uv run python -c 'from shift_schedula import solve, verify, make_baseline, get_schema; print(get_schema("request", "0.4")["$id"])'
```

`dist/` と依存一覧はエンジン側で作った固定成果物を配布する。
利用側はそのwheel・SHA-256・採用したエンジン版・入出力契約版・自分のlock fileを保存する。
uv自体の導入は[Pythonセットアップ](python-setup.md)を参照する。
wheelの取得元を差し替えた場合はパスも明示して変更する。
`schema_version` とエンジンの配布版は別で、0.1.5のwheelは契約0.1〜0.6を同梱する。
新しい業務ルールは新契約版へ追加し、旧版の意味を黙って変更しない。
候補件数上限の撤廃は受理範囲の拡大であり、保存済みSchemaは再取得する。

## sdistだけから利用・検証する

`uv build --sdist` で `dist/shift_schedula-0.1.5.tar.gz` を作る。
利用者は空のディレクトリに展開し、その中の `pyproject.toml` がある場所で次を実行する。

```sh
uv python install
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat python -m shift_schedula solve examples/assignment.json
uv run --locked --extra cp-sat python -m shift_schedula solve examples/roster.json
uv run --locked --extra cp-sat pytest -q -ra -m 'not repository and not distribution'
uv build --wheel
uv run --locked python demo/server.py
```

ライブラリ・CLI・デモの使い方は同梱の[README](../README.md)に従う。
OR-Toolsなしで配置と独立検証だけを使う場合は、同期・実行の `--extra cp-sat` を省略できる。
中核テスト一式にはCP-SATが必要となる。

`repository` はGitのcommit/lockを照合する評価テストとデプロイ入口の検証、
`distribution` は配布物のビルドと隔離導入を検証するテストを表す。
上の入口は両者を明示的に収集対象から外し、sdistに同梱した中核・CLI・デモのテストを実行する。
Git checkoutからの通常の `pytest` は両者も含める。sdistの成功で過去commitの評価や
デプロイを検証済みとは扱わない。

CIの配布検証では、sdistを展開して作ったwheelを別環境に依存宣言から導入し、
元checkoutをimportせずにSchema・ライセンス・例・デモ・中核テストを確認する。
参照原本と過去の測定生データは非同梱で、[出典](sources.md)から保存時のリポジトリへ辿れる。

## 旧ローカルwheelからの移行

自身のプロジェクトがこのリポジトリの旧 `schedula-0.1.4` wheelを依存に登録している場合は、
その依存を新wheelへ置き換える。別作者のPyPI版 `schedula` を使う依存は維持できる。
旧wheelと新wheelは別配布なので、通常の同名パッケージ更新では置き換わらない。

```sh
uv remove schedula
uv add '../dist/shift_schedula-0.1.5-py3-none-any.whl[cp-sat]'
uv run python -c 'from shift_schedula import solve, verify, make_baseline, get_schema; print(get_schema("request", "0.4")["$id"])'
```

コードの `from schedula ...` / `import schedula` を `shift_schedula` へ、
CLIの `python -m schedula` を `python -m shift_schedula` へ変更する。
保存済みJSONの名前やIDは変更しない。リポジトリの開発環境は更新後の
`uv sync --locked --extra cp-sat` で旧editable配布を置き換える。
過去の評価記録と参照資料は、実行時の識別子を保持している。

PyPIは配布名のハイフン・アンダースコア・ピリオドを同一視する。
公開直前に正規化名 `shift-schedula` の登録状況と公開権限を確認する。
名称移行とローカルwheelの成功は、PyPI公開や名前の予約を意味しない。

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
- 必須CI、契約0.5、wheel隔離導入、OR-Toolsなしの検証、利用例を確認する。
- 外部利用者向け非公開セキュリティ窓口、対応環境、版管理、サポート範囲を確定する。
- 配布元・SHA-256・正式タグの権限を確認し、公開結果を別途記録する。

現在のwheel build・ローカル試用・非公開PRの成功は、無料公開や商用運用の開始を意味しない。
