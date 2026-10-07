# ローカル担当配置デモの検証記録

2026-10-06、マイルストーン [#3](https://github.com/omitsuhashi/schedula/milestone/3) の
Issue #28〜#31 に対して、実行入口・共通画面・3シナリオ・比較・復元を実装し検証した。
仕様は [配置プレイグラウンド](../playground.md)、利用手順は [README](../../README.md#ブラウザーで担当配置を試す)を参照する。

## 対象と環境

基点は `4ad9714d1a636b9559c02a410e3004e20d6ed45e`。
検証時の実装・チェック・CI 定義の SHA-256、環境、コマンド、10条件の実結果を
[生データ](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-06-playground-runtime.json)に保存した。
確定した対象 commit と CI 実行 URL は、この変更を含む実装 PR の本文に記録する。
CI は既存の `deploy-entrypoint` で全回帰と実 Chromium の結合チェックを実行し、
JUnit XML・ブラウザー結果 JSON・画面画像を `pytest-results` artifact に保存する。

| 項目 | ローカルで確認した環境 |
| --- | --- |
| OS | macOS 26.7.1 / arm64 |
| Python / エンジン | Python 3.14.8 / schedula 0.1.3 |
| 依存 | jsonschema 4.26.0 / pytest 9.1.1 / OR-Tools 9.15.6755 |
| ブラウザー検証 | Playwright 1.62.1 / インストール済み Chrome 154.0.8037.98、headless |
| 新環境 | 別の作業コピーと新しい `.venv`。`uv sync --locked`、OR-Tools 不在を確認 |

新環境の Python と依存取得には既存の uv キャッシュを使用した。
OS・Git・uv 自体を未導入の機械からの導入は今回の実測に含めない。
新環境で README の導入・起動・全ブラウザー操作を実行し、Ctrl+C 相当の SIGINT で正常終了した。
8765のほか `--port 8766` の起動も確認した。

## 実エンジンの受け入れ結果

JSON を手作成せず、画面の「この変更を入力」・「再計算」・「サンプルへ復元」を操作した。
成立した9条件すべてで独立検証が成功した。人選や配列順序を受け入れ条件にしない。

| シナリオ | 初期 | 条件変更 | 明示的な修正 | 復元 |
| --- | --- | --- | --- | --- |
| 通常のランチ営業 | OPTIMAL、22人枠 | 11:30のホール1→2：OPTIMAL、23人枠 | — | OPTIMAL、22人枠 |
| 急な欠勤 | OPTIMAL、22人枠 | あおいの勤務可能時間を空にする：INFEASIBLE | 欠勤を維持し12:00・12:30の調理2→1：OPTIMAL、20人枠 | OPTIMAL、22人枠 |
| ピーク時の必要人数増加 | OPTIMAL、22人枠 | 12:00・12:30のホール2→3：OPTIMAL、24人枠 | — | OPTIMAL、22人枠 |

欠勤時は担当表・需要充足・担当差分を作らず、元の成立した配置と変更条件を保持した。
復元は入力・結果・比較元・ガイドをリセットし、自由編集はガイドだけを終了した。
名前の変更・重複で担当差分が増えないこと、切替確認の取消で元の選択を保持することも確認した。

## 境界・画面状態の確認

| 対象 | 確認結果 |
| --- | --- |
| HTTP と入力 | ライブラリ・CLIとの同じ入力の照合、JSON重複キー・非有限数・不正UTF-8、64 KiB上限、固定値・全ID・人数・技能・区間の範囲外拒否が成功 |
| ローカル境界 | Host / Origin、転送エンコーディング、Content-Length、不許可メソッド、限定配信、読み取り期限、同時実行BUSY、失敗後の復帰を確認 |
| 古い結果 | 編集直後に現在の担当表を消し、入力と前回結果を保持。二重送信・実行識別子の不一致・編集後と期限後の遅延応答を拒否 |
| 入力不備 | 空欄・小数・範囲外人数・勤務可能時間の逆転を拒否し、現在の配置を表示しない。診断から入力欄にフォーカス可能 |
| 文字表示 | `<img src=x>` を名前として表示しても画像要素を生成しない |
| 操作と幅 | キーボードで編集・計算・復元、フォーカス表示、1440pxで2列・390pxで1列。ページの横はみ出しなし、表内のスクロールで全枠へ到達可能 |
| 色以外の説明 | 強制配色でも状態、役割名、検証、充足の文字が残る。デスクトップと狭い画面の画像も目視確認 |

`FEASIBLE` / `UNKNOWN` / `INVALID_INPUT` / `BACKEND_UNAVAILABLE` / `INTERNAL_ERROR`、
HTTP 503、通信失敗、不正な参照・検証フラグ・実行識別子は **応答サンプル**で確認した。
これらを実エンジンで得た状態と混同しない。実エンジンによる `INFEASIBLE` は上記の欠勤と技能削除で確認した。
待機期限の失効チェックだけは15秒を100msに短縮した。サーバーの強制停止や総処理時間の保証ではない。
画面の未計算・処理中は初期化・遅延応答のチェックで、古い結果は条件編集で確認する。

## 再実行

通常利用にはブラウザー以外のフロントエンド依存は不要。
開発チェックでは既存の Python テストを使い、ブラウザー検証だけ固定版 Playwright と Chromium を導入する。
CI のブラウザー導入を含めるためジョブ期限を5分から10分へ変更した。

```sh
uv sync --locked --extra cp-sat
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
uv run --locked --extra cp-sat pytest -q -ra --junitxml=test-results/pytest.xml
bash -n scripts/deploy
uv build --wheel

browser_check_dir="$(mktemp -d)"
npm install --prefix "$browser_check_dir" --no-save --package-lock=false playwright@1.62.1
"$browser_check_dir/node_modules/.bin/playwright" install chromium
PLAYWRIGHT_MODULE_PATH="$browser_check_dir/node_modules/playwright" node tests/playground-browser.cjs
```

ブラウザーチェックは8765でサーバーを起動して終了する。利用中のサーバーで確認したい場合は
`PLAYGROUND_URL=http://127.0.0.1:8765` を追加する。
インストール済み Chrome を使う場合は `PLAYWRIGHT_CHANNEL=chrome` を追加できる。
LinuxでブラウザーのOS依存も必要なら、CIと同じ `install --with-deps chromium` を使用する。
生成結果は Git 対象外の `test-results/` に保存する。

全回帰は1004成功・6 subtests成功、121.33秒、失敗・エラー・スキップ0件。
最終の不許可メソッド対応後のHTTP再確認は38成功、19.73秒。
Ruff lint・format、pre-commit、JavaScript構文確認、`git diff --check`、wheelビルドも成功した。

初回のブラウザー起動は同梱Playwrightが要求するChromium実行ファイルの不在で失敗し、
インストール済みChromeへ切り替えた。初回の操作チェックはテストのシナリオID誤記を修正して再実行した。
macOS Chromeで狭い画面の全ページ画像が繰り返し描画されたため、
表示範囲ごとの画像で条件・結果を確認した。DOMの幅と実操作は別途成功している。

固定の架空データによる機能確認であり、実利用者による使いやすさ評価、実店舗の性能、公開デプロイは未実施。
Issue #28〜#31 の実装・検証条件を満たす変更をPRにまとめ、Issueの終了はそのマージで反映する。

## PRレビュー後の回帰修正

[PR #33](https://github.com/omitsuhashi/schedula/pull/33) の `d6ceff2` に対するレビューで、
勤務不可の選択時刻消失、初回失敗後のカスタム入力エラー残留、比較元の確立不備を確認した。
ガイドでの再描画時に選択時刻を保持し、入力編集時に共通検証を実行する。
比較元は元の条件の検証済み配置だけで確定し、それまでは変更ガイドを進めない。

既存の `tests/playground-browser.cjs` に以下のチェックを追加し、実Chromeで成功した。
修正前のチェックは、ゆいの終了時刻13:00が14:00になる差分で失敗した。
対象ソースのハッシュ・環境・結果は[レビュー修正の実行記録](https://github.com/omitsuhashi/schedula/blob/601f39283339fb7fee8d4469e62c928bead19adb/docs/evaluations/results/2026-10-06-playground-review-fixes.json)に保存した。
最新commitとCIのURL・結果はPR本文に記録する。

| 再現経路 | 確認した結果 |
| --- | --- |
| 勤務不可→需要ガイド→勤務不可解除 | サンプルの11:00〜13:00、編集した11:30〜12:30を保持。復元ではサンプル時刻へ戻る |
| 初回HTTP 500→21文字の名前→正常な名前へ修正 | カスタムエラーが消え、再送で実エンジンのOPTIMALを取得。開始時刻の修正で終了欄の項目間エラーも解除 |
| 初回UNKNOWN→正常再試行 | UNKNOWNを比較元にせず、再試行の検証済み配置で比較元を確定。需要変更後に担当差分を表示 |
| 初回HTTP 500→変更ガイド→正常再試行 | 比較元の確立まではガイドを無効にし、条件を変更しない。再試行後はガイドを進められ、元の検証済み配置を保持して比較 |

初回のHTTP 500とUNKNOWNは応答サンプルで再現し、その後の再計算は実エンジンを使用した。
従来の3シナリオ10条件、比較・復元・自由編集、キーボード、幅1440/390px、強制配色、遅延応答の拒否も再確認した。
