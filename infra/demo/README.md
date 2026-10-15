# 公開デモの構築と配備

公開先は `https://the3.co.jp/products/schedula/demo/` と `docs/`、APIは同じprefixの `api/`。
S3・Lambda・ECR・IAM・ログと製品SSM契約をこのrootで管理する。会社CloudFront・OAC・経路・WAFはlanding-pageのcompany rootが所有する。
`schedula.the3.co.jp` はschedula-app用であり、このrootはDNS・ACM・Distributionを作成しない。

このPRではAWSへ適用していない。以下の初回構築・公開コマンドは、別途適用するときの手順である。
通常のCIはbackendを無効にし、provider mockだけで検証する。

## AWS認証なしの検証

Terraform 1.16.6とAWS provider 6.69.0を固定する。provider lockを更新せず、次を実行する。

```sh
terraform fmt -check -recursive infra
terraform -chdir=infra/demo init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/demo validate
terraform -chdir=infra/demo test
uv sync --locked
uv run --locked pytest -q tests/test_public_demo.py tests/test_web_release.py
uv run --locked python -m web.build test-results/public-site
uv build --wheel
docker build --provenance=false --platform linux/amd64 -t schedula-demo:check -f web/Dockerfile .
docker run --rm --read-only --tmpfs /tmp --entrypoint python schedula-demo:check -m web.smoke
node tests/public-browser.cjs
```

ブラウザー検証は既存CIと同じPlaywright 1.62.1 / Chromiumを使う。`PLAYWRIGHT_MODULE_PATH` で導入済みのモジュールを指定できる。
`tests.public_browser_server` はlocalhost専用の結合検証用であり、公開サーバーとして配備しない。

## 接続契約

すべて東京のSSM `String`。値の参照に他rootのstateは使わない。

| パス | 所有者 | このrootの権限 |
| --- | --- | --- |
| `/the3/production/foundation/v1/aws-account-id` | foundation | 読取 |
| `/the3/production/foundation/v1/github-oidc-provider-arn` | foundation | 読取 |
| `/the3/production/company/v1/edge` | company | 読取 |
| `/the3/production/products/schedula/v1/origins` | このroot | 作成・更新 |

会社契約は `schema_version: 1`、想定account、`host: the3.co.jp`、会社の `distribution_arn` を持つJSONである。
製品契約は同じschema版・account、`region: ap-northeast-1`、`static_origin_domain`、`function_url_domain`、`function_alias_arn` を持つ。
S3 domainはregional endpoint、Lambda domainはscheme・末尾slashを除いたFunction URL、aliasは `the3-schedula-demo-production:live` とする。
公開ロールにはSSMやstateの権限を与えず、IaCの管理主体だけが必要な契約を読み書きする。

## 初回構築の順序

1. landing-page側でfoundationとcompanyを構築し、schedulaの登録は `enable_schedula=false` にして会社契約を公開する。
2. 暗号化・非公開・バージョニング・TLS・native lockを持つstate backendを用意する。既存stateがある場合は所在と所有者を確認し、空keyへの切替を避ける。
3. `backend.hcl.example` と `terraform.tfvars.example` をコピーし、accountとbucketを設定する。`image_digest=null` でこのrootを初期構築する。ECR・S3等だけを作り、Lambdaや製品の配信元契約はまだ作らない。
4. 上の検証済みコンテナーを管理用認証でこのrootのECRへ投入し、その実digestを `image_digest` に記入して再度plan / show / applyする。
5. Lambdaの固定alias `live` と製品契約の作成後、会社側で `enable_schedula=true` のplanを確認して経路を登録する。
6. schedulaのWeb公開を行い、3教材・技術文書・Origin直アクセス拒否を確認する。その後、会社側の `PUBLIC_SCHEDULA_DEMO=true` で紹介ページのリンクを有効にする。

構築操作では管理用認証を使う。通常公開ロールへTerraform apply権限を与えない。
Lambda作成後に `image_digest` をnullへ戻すと削除計画になるため、初期digestを保持する。
コードの更新とaliasのversionは公開workflowが所有し、Terraformの `ignore_changes` で初期digestへ戻さない。
配信元domainを変更する置換は、新旧を併存させて会社経路を切り替えてから旧リソースを整理する。

## 公開設定

GitHubの `production` Environment variablesに、このrootのoutputから以下を登録する。
長期AWSアクセスキーは登録しない。

| 変数 | output |
| --- | --- |
| `AWS_ACCOUNT_ID` | `aws_account_id` |
| `AWS_REGION` | `aws_region` |
| `SITE_BUCKET` | `site_bucket` |
| `ECR_REPOSITORY` | `ecr_repository` |
| `LAMBDA_FUNCTION` | `lambda_function` |
| `AWS_ROLE_ARN` | `deploy_role_arn` |

mainのPR・`quality-checks`、`web-v*` タグの作成者制限・移動/削除禁止、productionの許可ref（mainとweb-v*）を設定する。
required reviewersは運用責任者・利用プランに合わせて設定する。OIDC subjectは確認済みのID形式
`repo:the3-inc@249383711/schedula@1403742307:environment:production`、audienceは `sts.amazonaws.com` とする。
移管やOIDC設定変更ではこの一致条件も更新する。

mainのCIが成功したcommitへ `web-vMAJOR.MINOR.PATCH` タグを付けてpushすると、`Deploy public demo` が起動する。
このPRではタグを作成・pushしない。既存 `v*` はPyPI公開用なのでWeb公開には使わない。
手動公開はmainのworkflowから既存Webタグを指定する。実行前にタグ形式・mainへの包含・最新main CI成功を検証する。

workflowはAWS認証前に同一commitの静的成果物・Linuxコンテナーをビルド・検証してchecksum付きartifactを保存し、配備ジョブがそれを使用する。
S3への配置は `products/schedula/` に限定し、hash付きassetsは保持する。HTML・文書・教材はno-storeで、会社CloudFrontの無効化権限は持たない。
Lambdaは固定digestでversionを公開し、live aliasだけを切り替える。commit・image digest・新旧Lambda versionを実行サマリーへ記録する。
公開後は実URLから3教材を再計算・再検証する。CloudFrontの経路・OAC・WAF変更をタグworkflowから行わない。

## 障害・切り戻し

S3のファイル単位更新とalias更新は原子的ではない。旧画面と新APIが混在しても動くHTTP契約を保つ。
失敗時は実行ログとlive alias・S3を確認し、同じタグの手動再実行または旧タグの再配備を行う。既存タグは移動しない。
再ビルドでは同一バイト復元を保証しない。厳密な復元には保持30日以内の `public-demo-release` artifactのchecksumを確認し、対応するsiteと記録済みLambda versionを一組で戻す。
旧assetを先に削除しない。S3旧版・ECRイメージ・Lambda versionの保持整理は、公開版と切り戻し対象を除外して別途行う。
異常な計算負荷は管理用認証でreserved concurrencyを0にして止め、会社側ではAPIパスだけの遮断を依頼する。
rate制限・同時数制限は費用の絶対上限ではない。通知先と費用予算、ログ保持は実公開前に確認する。
