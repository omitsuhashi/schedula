# アプリ候補の明示移行と保存往復

> 履歴記録: 旧版からの明示移行を検証した際の手順と結果です。一時スクリプト・専用試験・旧fixtureは検証後に撤去しました。原資材は[固定commit](https://github.com/omitsuhashi/schedula/tree/d17a036a9790999c8182cdd319473d32368ddaec)に保存されています。現在の通常入口は契約0.15だけを受理します。

[Issue #125](https://github.com/omitsuhashi/schedula/issues/125)の早期検証です。
所有者が2026-10-09に、両リポジトリの例・テスト以外の実保存データなしと確認済みです。
対象は通常の例と合成代表であり、実顧客の更新・実データ移行ではありません。

## 現行基点と候補

アプリmain `87a87db` は #31/#32でDB Schema 2 / schedula-app/2へ進んでいました。
起票時の `ccd32402119762cca4c2981b705730b1e7dc3230` のSchema 1と、現在Schema 2の両方を検証します。
アプリの現在の保存版は2のまま、新たな保存形状・業務機能は追加しません。

候補エンジンは `58c304ff0f3c7f151a000f57de19825b9ecd63c0`、配布版0.1.6、既定実行契約0.15です。
`SOURCE_DATE_EPOCH=1791545862 uv build --wheel` と既存lockで構築したwheelのSHA-256は
`59daf999fc59163074b760a9d8320c57232a96e8029f7afd817a77d5f2b31afa`。
旧版除去前の候補なので0.1〜0.15を受理します。最終単一契約・新配布版と混同しません。
アプリのmanifest・wheel・lockと、通常フォーム/13例/入れ子基準を同時に更新します。
必要なアプリ変更と原/更新後SHA台帳は [app PR #33](https://github.com/omitsuhashi/schedula-app/pull/33)、
エンジン側の入口と原本は [PR #154](https://github.com/omitsuhashi/schedula/pull/154) で追跡します。

## 変更する境界

`scripts/migrate_app.py` は #109/#110 の既存移行を再利用する一回限りの入口です。
アプリのinstalled candidate wheelで実行し、`--app-source` の既存restoreへ
旧pin/原保存と、新pin/移行先の両方を渡します。restoreの厳密検査を緩和しません。
JSONは厳密読込、SQLiteの一セッションは明示IDと読取専用トランザクションで取り出します。
SQLiteは標準backupの整合したスナップショットを入力にしてください。

元Request・Response・record/run_id・固定・日付・原区間・解は
`evidence.migration.original_plan` に保持します。
移行だけで求解せず、移行後Requestへ旧run_idのrecordを付け替えません。
現在verifyをresult/current_verificationへ置き、証明フラグを転記しません。
再求解だけが既存APIで新しいrun_idを作ります。既存のQuery/採用/両再計画/保存を使います。

Draftは既存移行の確認保持/失効を使い、未完成inputは原文のままです。
有効なinputと埋め込み基準だけ明示変換します。修正途中の解は未確認のままです。
旧ピン・不正保存・変換不能・既存出力との競合・8 MiB超過は原本を保って終了2。
新規JSONのみ原子保存し、稼働DB・既存セッション・原本/成功済み出力を上書きしません。
追加履歴が必要な入力は補完しません。通常入口での旧版変換はありません。

```sh
# appは候補アプリcheckout、engineはこの移行スクリプトを持つ固定checkout。
git -C "$app" show 87a87db:vendor/schedula/manifest.json > source-manifest.json
uv run --project "$app/backend" --locked python "$engine/scripts/migrate_app.py" old-session.json \
  --source-manifest source-manifest.json --app-source "$app" --output new-session.json
uv run --project "$app/backend" --locked python "$engine/scripts/migrate_app.py" old-snapshot.sqlite3 \
  --session-id SESSION_ID --source-manifest source-manifest.json --app-source "$app" --output new-db-session.json
```

旧0.1.5には `ccd32402119762cca4c2981b705730b1e7dc3230` のmanifestを指定します。
新しい保存先で起動したアプリの既存JSON読込から、検証済み出力を新規セッションへ取り込みます。
旧環境のwheel等の複製保管・復旧試験を完了条件には追加しません。

## 検証範囲と後続のゲート

`tests/fixtures/contract-migration/app/` の完全/PARTIALは旧固定0.1.6のwheelで、
legacyは旧固定0.1.5のwheel/Storeで作った合成データです。
通常の例は需要下限省略の不足許容・候補ID・期間・休憩・固定・目的順を保持します。
旧JSONとDB Schema 1/2から同じ保存内容へ移行し、原本の非変更を確認しました。
現在verifyのelapsed_secondsは各実行で異なるため、内容比較からその実行時間だけを除きます。
元証拠のRequest/Response/recordとpin・解・条件・summaryは一致します。

手元の移行単体12件と既存Request/Adapter移行139件、アプリbackend 192件・front 4件、
型/Ruff/Biome/ビルドとSQLiteバックアップ/実HTTP再起動は成功。
原/更新後SHA、代表JSON、取込→再検証→採用→固定/全体再計画→保存→再読込、
不正/pin不一致/元record付替え/保存競合の検査はアプリ側に記録します。
エンジン全体は2,656 passed, 6 subtests passed in 694.11s、JUnit failure/error/skip 0。
その後追加したCLI原本保護と合成元記録のハッシュ照合を含め、移行12件も成功しました。
合成元記録のCPU数は実際の求解の既定値2に揃え、内容ハッシュとRequest/Responseの対応を検査しています。
隔離wheel/sdist・公開型・base/cp-satは全体回帰に含み、strict mypyとpre-commitも成功。
エンジン実Chromiumと、アプリのbuilt/Vite両入口の実Chromium35項目・page errors 0が成功しました。

前提PR #153はmain `e4b3005`へ反映され、ブランチに取り込みました。
PR #154のCIはLinux/Windowsのbase/cp-sat全4ジョブが成功し、全体/配布/ブラウザーのジョブは実行中です。
アプリPR #33の最新実装head `84fe4da` の
[CI 37928282081](https://github.com/omitsuhashi/schedula-app/actions/runs/37928282081)は、
GitHubの支払い・利用上限により検査開始前に失敗しました。手元成功を必須CI成功には代えません。

#125の受け入れは候補の移行/保存の証拠と必要なPRのmain反映後に判定します。
#124/#125が未受け入れのまま #111 の旧版除去をしません。
移行・保存検証後、#111でこの一時スクリプト・専用テスト・旧入力fixtureを撤去し、
現在の0.15業務回帰と固定commit/PR/SHAへの履歴参照を残します。
#115は #114 の最終固定成果物で実Chromium・再起動を再確認します。
#116の性能・解品質比較と #105 の全体完了は未完了です。
