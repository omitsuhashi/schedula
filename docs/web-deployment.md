# 公開デモ・技術案内の配信と公開

会社サイトとschedulaの公開を独立させ、インフラをprivateの [infra](https://github.com/the3-inc/infra) に集約する。
公開担当は相手のrepoでapplyやタグ公開を行わない。infra担当は一つのrepoで初期構築を完了する。
この変更ではAWS適用・state移管・タグpush・公開を行っていない。

## URLと所有者

| 対象 | URL | コードと通常公開 |
| --- | --- | --- |
| 商品紹介 | https://the3.co.jp/products/schedula/ | landing-page |
| 公開デモ | https://the3.co.jp/products/schedula/demo/ | schedula |
| 技術案内 | https://the3.co.jp/products/schedula/docs/ | schedula |
| API | https://the3.co.jp/products/schedula/api/ | schedula |
| 利用アプリ | https://schedula.the3.co.jp | schedula-app。今回の構築対象外 |

公開デモは架空データの3教材だけで、顧客データ・ログイン・自由JSON・Adapter保存は公開しない。
ソース入手方法・MIT・PyPIやアプリの提供状態は確認済みの内容だけを案内する。

## インフラの責任

infra/foundationが共通OIDC・既存Hosted Zone確認・既存3識別子を所有する。
infra/public-webが会社/デモS3・ECR・Lambda・共有CloudFront/OAC/WAF・ACM/DNS・両公開ロールを一つのstateで所有する。
会社・製品間のSSM契約と登録フラグを廃止し、同じrootでresourceを直接参照する。
foundationのstateと既存3識別子は維持し、public-webから一方向に読む。
一つのDistributionを複数stateから変更せず、コードrepoのAWS CLIでOriginを追加しない。

## 初回構築

1. 実装をmainへマージし、対象main CI成功を確認する。schedulaの未変更main checkoutを構築コマンドへ渡す。
2. infra側で管理用認証・既存Hosted Zone・安全なstate用S3を用意し、config.jsonの3項目を設定する。
3. infraのbootstrapで共通基盤・S3/ECR・初期イメージ/静的成果物・Lambda/live alias・共有経路を構築し、実URLの3教材を検証する。
4. 各コードrepoにproductionと保護を用意し、infraのconfigure-deployで公開先変数を登録する。
5. landing-pageの会社タグで紹介を公開する。デモリンク用のフラグは使わない。

構築コマンド・設定値・公開先登録は[infraの初回構築手順](https://github.com/the3-inc/infra/blob/main/README.md#初回構築)を参照する。
初回イメージ投入はinfraの構築コマンドが検証済みmainから行う。以後のコードとaliasはschedulaの公開workflowが所有する。
初期digestを保管し、nullへ戻さない。既存AWS/stateがある場合、新規bootstrapではなくinfraの移管手順で実IDと所有権を確認する。
旧rootで定義削除をapplyしない。所有権移管と依存版更新を混ぜない。

## 配信・認証・キャッシュ

商品紹介は会社S3、demo/docs/assets/license.txtはデモS3、apiとapi/*はLambdaへ流す。products/schedula/*の一括転送はしない。
S3キーに公開prefixを含め、Origin pathを追加しない。APIへrewriteを付けない。demo/docsの末尾slashを308で補い、ディレクトリをindex.htmlへ対応付ける。
HTML・教材・文書・APIはCachingDisabled/no-store、内容hash付きassetsだけ長期キャッシュする。
Lambda URLはAWS_IAM、OAC always、会社Distributionだけを許可する。匿名のOrigin直接呼出しを許可しない。
viewer Host・Cookie・queryを転送せず、Origin・Content-Type・X-Demo-Lesson・X-Amz-Content-Sha256だけを転送する。
クライアントは送る本文のUTF-8バイト列からSHA-256を作る。

WAFはURI pathの `/products/schedula/api` 完全一致と `/products/schedula/api/` 前方一致のORをscopeとし、完全一致と配下の404経路も両rate制限へ含める。`api-reference` のような別ページを巻き込まない。
IPごと60回/5分・全体300回/5分、sampled request無効、ログへ本文を保存しない。
同時実行2・2048MB・Lambda30秒・子プロセス20秒・worker数1を出発点とする。費用の絶対上限や性能保証ではない。
実公開時に共有IP・連続操作・混雑・費用予算・通知先を確認する。

## 公開境界と成果物

既存HTML/JS/CSSと教材の正本を再利用する。web/build.pyは必要人数・連勤・手修正検証の3教材と現行4文書だけを出力する。
公開prefixを/products/schedula/へ統一し、JS/CSSへ内容hashを付ける。
公開Markdown間リンクを維持し、LICENSEをlicense.txtへ書き換える。非配信ファイルへのリンクはソース配布内の参照を示す通常テキストにする。
元文書と公開範囲は変えず、全出力Markdownの相対リンクを検査する。非公開GitHubへ誘導してリンク切れを隠さない。
Lambdaは2つの既知操作だけを受け付け、Origin・Content-Type・本文64KiB・hash・厳密JSON・教材ID/編集範囲を検査する。
期限付き子プロセスを使い、期限切れでは終了を確認する。顧客入力や結果を永続化しない。
PARTIALは不足のある有効な計画であり、独立検証成功は完全充足・最適性証明ではない。
ローカルの自由JSON・100人30日・Adapter試用と既存URLは維持する。

## アップデート

infra outputからproductionの6変数を登録する。AWS_ACCOUNT_ID、AWS_REGION、SITE_BUCKET、ECR_REPOSITORY、LAMBDA_FUNCTION、AWS_ROLE_ARN。
長期キーは登録しない。公開ロールは自S3 prefix・ECR・Lambdaコード/live aliasだけを更新し、state/SSM/IAM/DNS/CloudFront設定を変更できない。
mainのPR/quality-checks、web-v*の作成者制限と移動/削除禁止、productionのmain/web-v*許可refと必要なreviewersを設定する。

### デモ・技術文書・エンジンを更新する

1. schedulaで変更をPRにし、mainへマージする。公開対象文書の変更も同じWeb公開で反映する。
2. schedulaのcheckoutで対象commitとmain CIを確認する。

以下の `CI_RUN_ID` と `DEPLOY_RUN_ID` は置き換え用の表記である。
`gh run list` の出力で対象commitのheadSha（公開時は対象タグのheadBranchも）を確認し、その行のdatabaseIdの数値に置き換えてwatchを実行する。まだ表示されなければlistを再実行する。

```sh
git fetch origin main --tags
release_sha=$(git rev-parse origin/main)
git log -1 --oneline "$release_sha"
git tag --list 'web-v*' --sort=-version:refname
gh run list --repo the3-inc/schedula --workflow ci.yml --branch main \
  --event push --commit "$release_sha" --limit 1 --json databaseId,headSha,status,conclusion
# 表示された対象commitのCIを待ち、成功を確認する
gh run watch CI_RUN_ID --repo the3-inc/schedula --exit-status
```

3. 対象commitの最新main CI成功後、未使用の `web-vMAJOR.MINOR.PATCH` タグを作成してpushする。次は例で、版は未使用のものに置き換える。

```sh
release_tag=web-v1.0.1
git tag -a "$release_tag" "$release_sha" -m "Release $release_tag"
git push origin "refs/tags/$release_tag"
```

`v*` はPyPI用でありWeb公開に使わない。ローカルのタグ作成だけでは公開されない。
Web公開だけならPythonパッケージの版更新やGitHub Release作成は不要。

4. Actionsの **Deploy public demo** で対象タグ・commitを確認し、productionの承認が必要なら承認する。

```sh
gh run list --repo the3-inc/schedula --workflow deploy-demo.yml --limit 5 \
  --json databaseId,headBranch,headSha,status,conclusion
gh run watch DEPLOY_RUN_ID --repo the3-inc/schedula --exit-status
```

AWS認証前にタグ形式・main履歴・対象commitの最新main CI成功を確認する。
同一commitの静的成果物とLinuxコンテナーを検証し、checksum付きartifactから配備する。
新versionとlive aliasを更新し、自bucketのproducts/schedula/へ配置する。hash付き旧assetを保持する。

5. workflowの公開後検証が成功したことを確認し、[デモ](https://the3.co.jp/products/schedula/demo/)と[技術案内](https://the3.co.jp/products/schedula/docs/)をブラウザーで確認する。
   更新した文書内のリンクも確認する。workflowは実URLの3教材を再計算・独立検証する。
   run URL・タグ・commitと、Summaryのimage digest・Lambda version・previous Lambda versionを記録する。

通常のコード更新でbootstrap・Terraform apply・公開先変数の再登録は不要。
会社サイトの紹介文は[landing-pageのタグ公開](https://github.com/the3-inc/landing-page/blob/main/docs/site-deployment.md#タグによる公開)、
WAF・IAM・経路などの変更は[infraの更新手順](https://github.com/the3-inc/infra/blob/main/README.md#インフラを変更する)で行う。

### 失敗時に再実行・切り戻しする

失敗したrunのログと実URLを確認する。buildの失敗ではAWS更新前に停止するが、deployの失敗では部分更新の可能性がある。
同じタグを再配備する場合、または以前に公開成功したタグへ戻す場合は、mainのworkflowから既存タグを指定する。

```sh
# 例: 正常に公開できた既存タグを指定する
gh workflow run deploy-demo.yml --repo the3-inc/schedula --ref main -f tag=web-v1.0.0
gh run list --repo the3-inc/schedula --workflow deploy-demo.yml --event workflow_dispatch --limit 5 \
  --json databaseId,headBranch,headSha,status,conclusion
gh run watch DEPLOY_RUN_ID --repo the3-inc/schedula --exit-status
```

手動公開runのheadBranch/headShaはworkflowを実行したmainを指す。Actionsのbuildログで指定した既存タグと配備対象commitを確認してから承認する。
再実行でもproduction承認と公開後検証を行う。タグを移動・削除せず、新しい修正には次の版を使う。
旧タグもmain履歴と対象commitの最新main CI成功が必要で、公開workflow導入後のタグを選ぶ。

## 障害と検証

S3とalias更新は原子的ではない。画面/APIの互換性を保つ。失敗時はログと実状態を確認し、同タグ再実行か旧タグ再配備を行う。タグを移動しない。
再ビルドで同一バイト復元は保証しない。厳密な復元は保持30日内artifactと対応するLambda versionを一組で扱う。旧assetを先に消さない。
異常負荷時のconcurrency=0、API経路遮断はinfra担当が実施する。
コード・公開prefix・文書リンク・ブラウザー・read-only Linuxコンテナーはschedula CI、Terraform/WAF/IAM/URL rewriteはinfra CIが検証する。
mockは実AWSの権限・DNS・性能を保証しない。実公開で会社5ページ・デモ・文書・APIとOrigin直接アクセス拒否を確認する。
[インフラ管理先](../infra/README.md)と[LPの責任](landing-page.md)を参照する。
