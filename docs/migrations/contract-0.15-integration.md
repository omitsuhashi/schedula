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

## 通常入口の単一契約切替

#124の入口準備と、#125の候補保存往復が完了した後、通常実行・Schema・公開型を0.15に統一した。
`validate/solve/verify/make_baseline`、AdapterのDraft/manifest/recordとCLIは、
0.1〜0.14・未知版・版欠落・不正型を拒否する。失敗応答も0.15の形を持ち、
原入力を架空の正常Requestへ補完しない。request_id・未実施の検証・nullの集計を保持する。
Schema取得の既定値とURNは0.15だけで、旧版を指定したSchema APIはValueError、CLIは終了コード2。

0.15のRequest/Response/solution/verification Schemaは整理前の内容と完全一致した。
原需要・下限省略0・priority省略0・目的順・証明接頭辞・原区間・固定・重複期間の意味を変更しない。
版で決まる分岐だけを整理し、assignment/roster・continuity有無・任意機能・backend能力・
解の状態に応じた分岐を維持した。テンプレート生成IDの`0.2`は既存IDのハッシュ名前空間であり、
旧契約の受付を残すものではない。完全需要のbase最小費用流とソルバーなし独立検証も維持する。

`SchemaVersion/Request/Response/Solution/Verification`とstubは現在契約の形だけを公開する。
旧専用のRequest01〜Request014、Responseの旧各版、旧候補・履歴の構築型を除去し、
呼出側は公開Request/Response/SolutionまたはRequest015へ移した。
勤務区間・休憩・履歴・制約・診断の業務構造は現在版で必要な共通型として保持する。

### テストと一時資材の行先

| 整理対象 | 切替後の検証 |
| --- | --- |
| 版だけ異なる同じ正常入力・全探索・CLI・型 | 0.15の同じ業務テストへ統合。技能AND、残余経路、競合、加算選好、辞書式目的、改ざん拒否を保持 |
| 旧勤務候補・テンプレート・履歴の形状 | segments/segment_options/last_work_dayで同じ休憩・展開・DST・休息・連勤を検証。旧版だけの日跨ぎ禁止は現在版の受理条件に持ち込まない |
| 旧版の基準の受理順・旧Response/Schema | 現在基準の原条件・元解の再検証と、旧版の明示拒否に置換 |
| 不足・勤務量・希望日時・再計画・独立検証 | `test_partial_contract/test_contract_04`の数量・状態・証明・全探索・両再計画・反復保存・公開verifyを維持 |
| 現行0.15の独立回帰 | `tests/test_contract_015_regression.py`へ分離し、base/cp-sat、既定値・空値・目的順・証明範囲を維持 |
| 旧版・未知版・欠落版の通常入口 | `tests/test_single_contract.py`でAPI/CLI/Adapterの明示拒否、原入力非変更、失敗応答の契約を確認 |
| 実ブラウザーの移行済みDraft | 現行の完全需要Draftの期間revision変更→確認失効→再確認→求解→保存→再読込を確認 |
| 一回限りのRequest/Draft/record/app移行 | #109/#110/#125の固定PR・commit・SHA・受入結果を履歴に残し、scripts/migrate_*.py・専用テスト・旧fixture・CI専用ステップを撤去 |

現在の固定代表は`tests/fixtures/contract-015/`、旧原SHAと移行先SHAは
[比較台帳](contract-0.15-cases.json)に保存する。一回限りの原資材は
[撤去前の固定commit](https://github.com/omitsuhashi/schedula/tree/d17a036a9790999c8182cdd319473d32368ddaec)
から参照できる。履歴文書のコマンドは撤去前の手順として表示し、現在の実行手順と区別する。

### 切替時の受け入れ結果

macOS ARM64 / Python 3.14.8 / OR-Tools 9.15.6755 / lock固定で、生成物を消してから
全体pytestを実行し、2,149 passed + 6 subtests、547.36秒、failure/error/skip 0を確認した。
隔離sdistからの再構築wheelと同梱中核回帰、base/cp-satの隔離導入・公開型はこの全体検査に含む。
旧版・未知版の実HTTP/API/CLI/Adapter境界は別途193件成功。
実Chromiumは10 scenarios / 21 interactions / 25 response samples、page error 0で成功し、
0.1〜0.14・未知版・版欠落の入力と旧応答拒否も検証した。
Ruff/pre-commit、mypy strictのAPI/Adapter型例、deployのbash構文検査が成功した。
Windows/Linuxの既存CI行列・skip拒否・配布とChromium検査は維持する。
