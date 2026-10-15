# ランディングページの配信と確認

主目的は導入・個別開発の相談につなげること。冒頭・デモ直後・文書案内・末尾に相談導線を置く。
問い合わせ先は権利者が指定した `omitsuhashi@the3-o.com` とし、末尾のボタンで件名と相談項目を含むメール作成を開く。
ページ側で連絡先や相談内容を収集・保存・送信する処理は持たない。

## ローカル確認

```sh
uv sync --locked
uv run --locked python demo/server.py
```

- LP：`http://127.0.0.1:8765/`
- ドキュメント案内：`http://127.0.0.1:8765/docs.html`
- デモ：`http://127.0.0.1:8765/demo/`

LPを親の `/`、デモを子の `/demo/` に配置する。デモのJavaScript・CSS・サンプル・計算APIも `/demo/` 配下へ揃える。
LPはJavaScriptや外部フォントを必要とせず、CSSとHTMLで表示する。デモはLPの `/landing.css` を読み込み、
紙色・深緑・フォント・共通ヘッダーを共有し、操作フォームと結果表は専用CSSで調整する。

旧 `/landing/` は `/`、末尾スラッシュのない `/demo` は `/demo/` へ308で転送する。
旧デモの `/#demand` などのブックマークは `/demo/#demand` へ更新する。
旧ルート直下の計算API・資産と `/landing/docs.html` などの旧文書URLは配信しない。
詳細文書は次の4件のみを許可リストに加えて、`text/plain` のMarkdown原文として表示する。
文書ディレクトリ全体や参照資料を公開しない。

- `docs/python-setup.md`
- `docs/python-api.md`
- `docs/io-contract-current.md`
- `docs/distribution.md`

## 公開時の配置

会社サイトと接続する今後の推奨構成は[商品紹介・公開デモ・利用アプリの配信設計](web-deployment.md)を参照する。
商品紹介・公開デモ・技術案内を会社の `/products/schedula/` 配下へ集約し、会社CloudFrontからschedula専用S3 / Lambdaへ振り分ける。
`schedula.the3.co.jp` はschedula-appの公開先とする。共有CloudFrontとデモ配信元のTerraformはprivateのthe3-infraが一括管理する。各コードrepoは自分の成果物だけを公開する。
以下はローカル構成に基づく経路対応として残し、公開時にはリンク・資産・サンプル・計算APIも新prefixへ揃える。

現時点では公開環境を作成していない。既存の `demo/server.py` はloopback専用の試用サーバーであり、
インターネットへ公開する実行基盤には使わない。
LPは静的配信できるが、デモには計算APIの実行環境が必要となる。

ローカル試用では同一オリジンで次の経路を使う。公開時の経路は上記の配信設計を正本とする。

| URL | ファイル・接続先 |
| --- | --- |
| `/` | `demo/landing.html` |
| `/landing.css` | `demo/landing.css` |
| `/docs.html` | `demo/guide.html` |
| `/docs/*.md` | 上記4件の文書のみ |
| `/license.txt` | `LICENSE` |
| `/demo/` | `demo/index.html` |
| `/demo/style.css`、`/demo/*.js` | 許可リストのデモ資産のみ |
| `/demo/samples/*`、`/demo/solve`、`/demo/solve-json`、`/demo/verify-json`、`/demo/adapter/*` | ローカルの教材配信・計算・独立検証・アダプター |

ローカルLPは `/` から確認する。会社HPで公開するときは `/products/schedula/` を紹介ページとし、
デモ・CSS・文書・計算API・戻り先を新しいprefixへ併せて変更する。
問い合わせ先を変更する場合は `demo/landing.html` と `demo/guide.html` を更新する。

## 公開前に確定すること

公開prefixの静的ビルド・Lambda入口はこのrepo、基盤はthe3-infraが所有する。[管理先と配備](../infra/README.md)を参照する。
AWS未適用であり、以下は実公開前の確認事項として残る。

- デモの公開URLと実行基盤。入力上限・プロセス隔離・応答期限などは公開APIとして別途設計する。
- ソース・配布の公開状況。現在は非公開・PyPI未公開として記載し、公開に合わせて案内と入手方法を更新する。
- 引き受ける開発・継続支援の範囲。現在は相談対象として説明し、費用・期間・SLAや実績は表示していない。
- 詳細Markdown内の相対リンク。原文への入口を提供しており、リンク先を網羅する公開ドキュメントサイトではない。
- メールアプリが使えない環境でもアドレスをコピーできること。実メール送信と受付先での受信は別途確認する。

## 検証

```sh
uv run --locked pytest -q tests/test_landing_page.py tests/test_playground_server.py
node tests/landing-browser.cjs
```

ブラウザー検証は既存CIと同じPlaywrightを使う。
`PLAYWRIGHT_MODULE_PATH` で導入済みのモジュールを指定できる。
相談・デモ・文書への遷移、LPとデモの背景色・フォント・操作ボタン、モバイルの横はみ出し、キーボード、JavaScriptなしの表示を確認する。

### 2026-10-14のローカル確認結果

- LPのHTTP・リンク検証2件と、既存HTTP回帰89件が成功。
- LPのChromium検証が成功。3つの実デモの検証済み結果への到達、メール作成の宛先・ひな型、
  文書への遷移、320・390・768・1440pxでの表示、キーボード操作、JavaScript無効時の相談導線を確認した。
- 既存の `tests/playground-browser.cjs` も成功。100人・30日の勤務計画を含む結合確認を実行した。
- Ruffのcheck、変更したPythonファイルのformat、`git diff --check` が成功。
  全体のformat確認には、未変更の既存Markdown3件に整形差分が残る。
- HTTP回帰の初回実行は既存の10秒通信期限で1件が失敗したが、ブラウザー確認完了後の単独再実行では89件すべて成功した。
- 外部公開、実メール送信・受信、売上や問い合わせ件数の効果測定は未実施。

### パス構成・スタイルの更新確認（2026-10-14）

- LP `/`、デモ `/demo/`、ドキュメント `/docs.html` のリンクとCSS・JavaScriptが配信されることを確認した。
- HTTP回帰92件が成功。308転送、許可リスト外の拒否、入力検証、計算・独立検証・入力アダプターを含む。
- ChromiumでLPから3つの実デモの検証済み結果へ到達し、相談・ホームへ戻る導線を確認した。
- 320・390・768・1440pxで、LP・文書案内・デモ一覧・必要人数デモに横はみ出しがないことを確認した。
  背景色・フォントの共有と深緑の実行ボタンを比較し、デスクトップと320pxの画面画像を目視した。
- LPとデモの本文スキップ、キーボードでの移動、JavaScript無効時のLP導線が成功した。
- 既存の `tests/playground-browser.cjs` も成功。実装済み主題、3シナリオ、100人・30日の勤務計画、JSON読込、入力アダプターの保存・再検証、応答失効を確認した。
- 変更したPythonのRuff check・format、JavaScript構文確認、`git diff --check` が成功した。
- 外部公開と実メール送信・受信は未実施。旧デモのブックマーク・旧APIを直接使う呼出元は新パスへ更新が必要。
