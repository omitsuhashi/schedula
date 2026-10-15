# インフラの管理先

AWS定義と構築・更新手順はprivateの [infra](https://github.com/the3-inc/infra) に集約しました。閲覧には組織のアクセス権が必要です。
このリポジトリは公開デモ・技術文書・コンテナーのコードと、既存基盤への公開workflowを所有します。

会社とデモのS3・Lambda・ECR・IAM・CloudFront・WAFは `infra/public-web` が一つのstateで管理します。
会社・製品間のSSM契約、登録フラグ、他リポジトリのTerraform実行は不要です。
`schedula.the3.co.jp` のアプリ本体は別の公開対象で、今回のデモ構築には含めません。

初回構築と公開先の登録はinfra側で完了させ、その後はこのリポジトリのmain CI成功 → `web-v*` タグpushだけで公開します。
公開workflowは自分のS3 prefix・ECR・Lambdaのコードとlive aliasだけを更新し、Terraformや会社の公開workflowを実行しません。
[公開構成と手順](../docs/web-deployment.md)を参照してください。
