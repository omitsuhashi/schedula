# ランディングページの配信と確認

主目的は導入・個別開発の相談につなげること。冒頭・デモ直後・文書案内・末尾に相談導線を置く。
問い合わせ先は権利者が指定した `omitsuhashi@the3-o.com` とし、末尾のボタンで件名と相談項目を含むメール作成を開く。
ページ側で連絡先や相談内容を収集・保存・送信する処理は持たない。

## ローカル確認

```sh
uv sync --locked
uv run --locked python demo/server.py
```

- LP：`http://127.0.0.1:8765/landing/`
- ドキュメント案内：`http://127.0.0.1:8765/landing/docs.html`
- 既存デモ：`http://127.0.0.1:8765/`

既存のデモURL・計算APIは変更しない。LPはJavaScriptや外部フォントを必要とせず、CSSとHTMLで表示する。
詳細文書は次の4件のみを許可リストに加えて、`text/plain` のMarkdown原文として表示する。
文書ディレクトリ全体や参照資料を公開しない。

- `docs/python-setup.md`
- `docs/python-api.md`
- `docs/io-contract-current.md`
- `docs/distribution.md`

## 公開時の配置

現時点では公開環境を作成していない。既存の `demo/server.py` はloopback専用の試用サーバーであり、
インターネットへ公開する実行基盤には使わない。
LPは静的配信できるが、デモには計算APIの実行環境が必要となる。

現在の同一オリジンのパスを維持する場合、静的配信側で次の対応を用意する。

| URL | ファイル・接続先 |
| --- | --- |
| `/landing/` | `demo/landing.html` |
| `/landing/style.css` | `demo/landing.css` |
| `/landing/docs.html` | `demo/guide.html` |
| `/landing/docs/*.md` | 上記4件の文書のみ |
| `/landing/license.txt` | `LICENSE` |
| `/` と計算API・デモ資産 | 公開用に別途構成したデモ実行基盤 |

会社HPから `/landing/` へリンクする。LPをサイトのルートに配置する場合は、
デモの移動先・CSS・文書・戻り先を併せて変更する。
問い合わせ先を変更する場合は `demo/landing.html` と `demo/guide.html` を更新する。

## 公開前に確定すること

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
相談・デモ・文書への遷移、モバイルの横はみ出し、キーボード、JavaScriptなしの表示を確認する。

### 2026-10-14のローカル確認結果

- LPのHTTP・リンク検証2件と、既存HTTP回帰89件が成功。
- LPのChromium検証が成功。3つの実デモの検証済み結果への到達、メール作成の宛先・ひな型、
  文書への遷移、320・390・768・1440pxでの表示、キーボード操作、JavaScript無効時の相談導線を確認した。
- 既存の `tests/playground-browser.cjs` も成功。100人・30日の勤務計画を含む結合確認を実行した。
- Ruffのcheck、変更したPythonファイルのformat、`git diff --check` が成功。
  全体のformat確認には、未変更の既存Markdown3件に整形差分が残る。
- HTTP回帰の初回実行は既存の10秒通信期限で1件が失敗したが、ブラウザー確認完了後の単独再実行では89件すべて成功した。
- 外部公開、実メール送信・受信、売上や問い合わせ件数の効果測定は未実施。
