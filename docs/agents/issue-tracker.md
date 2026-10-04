# Issue tracker: GitHub

課題と仕様は `omitsuhashi/schedula` の GitHub Issues で管理する。
操作には `gh` CLI を使用する。

## 基本操作

- 作成：`gh issue create --title "..." --body-file <本文ファイル>`
- 読み取り：`gh issue view <番号> --comments`
- 一覧：`gh issue list --state open --json number,title,body,labels`
- コメント：`gh issue comment <番号> --body-file <本文ファイル>`
- ラベル追加：`gh issue edit <番号> --add-label "..."`
- ラベル削除：`gh issue edit <番号> --remove-label "..."`
- 終了：`gh issue close <番号> --comment "..."`

リポジトリ内で実行し、git remote から対象を解決する。
必要な場合は `--repo omitsuhashi/schedula` を指定する。
複数行の本文は一時ファイルに保存し、`--body-file` で渡す。

## PR の扱い

**PRs as a request surface: no.**

この設定が yes の場合のみ、外部 PR を課題と同じ分類対象にする。
その場合は gh pr の読み取り・コメント・ラベル・終了操作を使い、
投稿者の authorAssociation が CONTRIBUTOR、
FIRST_TIME_CONTRIBUTOR、NONE の PR を対象とする。

GitHub は Issue と PR で番号を共有する。
種類が不明な番号は `gh pr view` と `gh issue view` で確認する。

## スキルからの指示の解釈

「issue tracker に公開する」は GitHub Issue の作成を意味する。
「関連チケットを取得する」は該当 Issue とコメントの読み取りを意味する。

## Wayfinder の操作

- 全体の地図は `wayfinder:map` ラベルを付けた1件の Issue とする。
  本文にはメモ、決定事項、未解決事項を記録する。
- 子チケットは GitHub の sub-issue として関連付ける。
  利用できない場合は地図のタスクリストに追加し、
  子の本文冒頭に `Part of #<地図の番号>` を記載する。
- 子には `wayfinder:research`、`wayfinder:prototype`、
  `wayfinder:grilling`、`wayfinder:task` の該当ラベルを付ける。
- ブロッカーは GitHub のネイティブな Issue 依存関係で記録する。
  gh api で依存関係を追加する際は、番号ではなく
  ブロッカーの数値 database id を使う。
  利用できない場合は本文冒頭に `Blocked by: #<番号>` を記載する。
- 次の作業は、未完了のブロッカーも担当者もない子チケットから、
  地図に記載された順番で選ぶ。
- 着手時は `gh issue edit <番号> --add-assignee @me` で担当を設定する。
- 解決時は結果をコメントして Issue を閉じ、
  地図の決定事項に結果への参照を追記する。
