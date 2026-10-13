# 正式タグからPyPIへ公開する

配布名は `shift-schedula`、現在の配布版は `0.2.0`、Python要件は `>=3.14`。
OR-Toolsは通常の実行依存であり、extraの指定は不要。
`publish.yml` は `v*` タグのpushで起動し、次を順に実行する。

1. `vMAJOR.MINOR.PATCH` と `pyproject.toml` の `project.version` の一致を検査する。
2. タグのcommitが `origin/main` に含まれ、同じSHAに対する最新の `ci.yml` のmain push実行が
   `completed` / `success` であることをGitHub APIで確認する。PR時の成功や別SHAの成功では代替しない。
3. wheelとsdistをビルドし、メタデータとREADMEの描画を検査してSHA-256とともに保存する。
4. タグ時の全回帰・OS別テスト・Chromium検証は再実行しない。PR/main CIの責務とする。
5. 公開元と成果物の検証成功後、保存した成果物のSHA-256を照合し、PyPIへ公開する。

公開jobだけが `pypi` Environmentと `id-token: write` を使用する。
ビルドjobは `actions: read` と `GITHUB_TOKEN` でCIの結果だけを読み取る。
API tokenをRepository Secretsに保存せず、GitHubのOIDCによるTrusted Publishingで認証する。
タグ作成は公開の指示になるため、初回は[配布方針の公開条件](distribution.md#公開作業の完了条件)を
確認し、公開物・ライセンス・外部利用者向けセキュリティ窓口を整えてから実行する。
GitHubを非公開のまま運用しても、PyPIにアップロードしたソースと文書は公開される。

## 初回だけ必要な設定

workflowをmainへmergeする前に、次の設定を行う。

### GitHub Environment

`omitsuhashi/schedula` の Settings → Environments で `pypi` を作成する。
Deployment branches and tagsをSelected branches and tagsにし、Tagの `v*` を許可する。
タグpushだけで自動公開する運用ではRequired reviewersは設定しない。
承認を挟む運用を選ぶ場合はRequired reviewersを設定し、タグpush後の公開jobを承認する。
非公開repositoryで利用できるEnvironment保護はGitHubプランによるため、設定画面で確認する。

既存の `v*` RulesetではRepository Adminのみがタグを作成でき、移動・削除はできない方針を維持する。
EnvironmentとRulesetの実設定は、workflowの追加とは別に確認する。

### PyPI Trusted Publisher

PyPIアカウントのメール認証・2FAを設定する。
新規プロジェクトなら[Publishing設定](https://pypi.org/manage/account/publishing/)の
pending publisherを登録する。登録値は次のとおり。

| 項目 | 値 |
| --- | --- |
| PyPI project name | `shift-schedula` |
| Publisher | GitHub |
| GitHub repository owner | `omitsuhashi` |
| GitHub repository name | `schedula` |
| Workflow filename | `publish.yml` |
| Environment name | `pypi` |

既存プロジェクトなら、そのプロジェクトのPublishing設定から同じ値を登録する。
pending publisherの登録は名称の予約ではない。名称が使用可能であることを確認する。
初回の公開成功時にプロジェクトが作成される。
TestPyPIを使う場合は別サービスで別のpublisher登録と送信先設定が必要であり、
このworkflowの送信先は本番PyPIに固定する。

## 版を公開する

設定とworkflowのmerge後、公開対象のmainを取得する。
最初の公開では `pyproject.toml` が `0.2.0` であることを確認する。

```sh
git switch main
git pull --ff-only origin main
git status --short
git tag -a v0.2.0 -m 'Release 0.2.0'
git push origin v0.2.0
```

作業中の変更がある場合は先に整理する。タグはcommit済みの内容に付く。
次回は配布版と必要な版表記を変更し、`uv lock` の結果をPRでmainへmergeしてから、
その版の `vX.Y.Z` タグを作成する。pre-releaseタグには対応しない。

Actionsの `Publish to PyPI` が全job成功したことと、
[公開ページ](https://pypi.org/project/shift-schedula/0.2.0/)のwheel/sdistを確認する。
`pypi-distributions` artifactの `SHA256SUMS` と公開ファイルのハッシュを照合し、
タグ・commit・Actions URL・公開結果をリリース記録に残す。
checkout外の空ディレクトリで公開版を導入して確認する。

```sh
uv run --no-project --python 3.14 --with 'shift-schedula==0.2.0' \
  --refresh-package shift-schedula \
  python -c 'from importlib.metadata import version; from shift_schedula import get_schema; print(version("shift-schedula")); print(get_schema("request")["$id"])'
```

## 失敗した場合

版不一致・main未包含・対象commitのmain CI未実行/実行中/失敗では公開jobは動かない。
main CIの成功を待ってからActionsで公開workflowを再実行する。
同じSHAで複数のmain push実行がある場合は最新の結果を使い、古い成功で新しい失敗を迂回しない。
OIDC認証に失敗した場合はPyPIのowner・repository・workflow・Environmentの登録値を照合する。
認証設定だけを直した場合はActionsの失敗した公開jobを再実行できる。
同じ成果物の再送では `uv publish` が既存の同一ファイルを省略する。
公開済みファイルを別内容で差し替えることはできない。
コード・文書・workflowを修正する場合はmainにmergeし、新しい配布版とタグで公開する。
既存タグを移動・削除して再公開しない。

## 設定と動作確認の区別

リポジトリにworkflowが存在しても、Environment・Trusted Publisherの実設定、
GitHubでの実行成功、PyPIへの公開成功はそれぞれ別の確認が必要となる。
`scripts/deploy` のstaging/production入口はWebサービス向けの未実装入口で、
このPyPI公開では使用しない。

## 公式資料

- [uvによるGitHub Actionsからの公開](https://docs.astral.sh/uv/guides/integration/github/#publishing-to-pypi)
- [新規PyPIプロジェクトのTrusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
- [既存PyPIプロジェクトのTrusted Publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
- [PyPIのファイル名再利用制限](https://pypi.org/help/#file-name-reuse)

GitHub APIの検索条件は[workflow runs公式仕様](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow)を参照する。
