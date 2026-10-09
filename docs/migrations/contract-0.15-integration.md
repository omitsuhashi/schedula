# 単一契約への整理とローカル受け入れ

## 受け入れ方法

2026-10-09、リポジトリ所有者は「CIはローカルで動かしてそれが動けばCI成功とする」と回答した。
Issue #105の今回の受け入れは、対応するローカル検査の成功を基準とする。
GitHub Actionsの課金・利用上限による検査未開始はコード検査の失敗と区別する。
既存のCI設定、skip拒否、配布物・独立検証・実ブラウザーの検査は維持する。
各検査で使ったOSと成果物を記録し、ローカル結果をGitHubの成功として表示しない。

## 候補アプリの準備受け入れ

app main `2a27357efff63d1d048ae7fb038175acef8f281e`（PR #33反映済み）を取得し、
既存lockとvendor wheelで再実行した。配布版0.1.6 / Schema 0.15、engine commit
`58c304ff0f3c7f151a000f57de19825b9ecd63c0`、wheel SHA-256
`59daf999fc59163074b760a9d8320c57232a96e8029f7afd817a77d5f2b31afa`。

| 検査 | 結果 |
| --- | --- |
| backend / frontend | macOS、192件 / 4件成功 |
| Ruff / Biome / 型 / production build | 成功 |
| SQLite / 実HTTP再起動 | バックアップ・独立検証付きrestore・顧客分離・保存/再開が成功 |
| 実Chromium built / Vite | 両入口成功。3代表保存データの取込・再検証・採用・固定/全体再計画・保存/再読込と既存操作を保持 |
| SSH運用リハーサル | macOSはトンネル未成立。Linuxの隔離コンテナ・専用ユーザーで既存CIのスクリプトを実行し成功 |

Linuxの実行結果は[記録](../evaluations/contract-015-local-ci/app-customer-operations.json)に保存した。
固定commitからの独立導入、SSH権限と顧客分離、元保存とバックアップの保全、更新・復元・再検証を確認した。
[元/移行先SHAと候補保存往復](contract-0.15-app.md)の先行証拠を引き継ぎ、
[#125の受け入れ](https://github.com/omitsuhashi/schedula/issues/125#issuecomment-6081443777)を完了した。
所有者が確認した範囲に保存済み実データはなく、代表試験は実顧客の移行・配備を表さない。

## 応答生成の内部整理

対象は `contract.py`、`engine.py`、`verify.py`、CLIの読込失敗経路。
応答Schemaから集計欄を取得し、求解・独立検証の初期応答と失敗時のnullを揃える。
CLIの独立検証用読込失敗では、未実施応答を作り、不完全なRequestの補完や求解を行わない。
版ごとの通常受理・Schema・公開型・移行処理は、この内部整理では保持する。

変更前後の全15契約のRequest / Response / Solution / Verification、計60 Schemaの内容は一致した。
`test_response_initialization.py` は全契約の失敗応答のキー・null・証明なし・原入力非変更と、
現行0.15のCLI読込失敗を61ケースで検査する。既存の全業務回帰も保持する。

#111の最終切替、#112の旧版拒否・画面、#113の現在仕様、#114の新配布版、
#115の最終固定成果物によるアプリ受け入れ、#116の規模比較は別の検証結果として追記する。

内部整理の手元全体は2,720 passed + 6 subtests、698.45秒、failure/error/skip 0。
baseのOS行列相当（timezone / input / execution / 応答境界）は204件、
移行CLIの行列相当は44件、実Chromiumは既存10 scenarios / 21 interactions / 25 response samplesが成功。
隔離wheel/sdistと同梱業務回帰・型検査は全体pytestに含む。
pre-commitと `mypy --strict examples/typed_api.py examples/typed_adapter.py` が成功した。
この内部整理のWindows再実行は行っていない。既存のLinux/Windows CI設定は維持する。
