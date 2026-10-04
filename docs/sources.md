# 出典と採用判断

確認日: 2026-10-04（Asia/Tokyo）。
元資料を設計方針として採用し、schedula の全体と方針の文書を作る、という今回の依頼に基づく記録。

## 元資料

| 資料 | 来歴と読み取った範囲 |
| --- | --- |
| [シフト最適化手法調査](https://chatgpt.com/c/6ac1a7b4-2ee4-83e8-b914-1a1a0cd23cef) | 指定された ChatGPT チャット。利用者の2回の発言と、それぞれへの回答を読み取った |
| `skillshift-starter-0.1.zip` | 今回添付された22ファイルのアーカイブ。README、入出力仕様、検証報告、Schema、例、コードとテストの構成を確認した |
| 既存リポジトリ | `AGENTS.md`、README、`docs/agents/` にある日本語・single-context・Issue 運用・変更管理の方針 |

ブラウザでは指定 URL が未ログインの画面へ移動したため、
Codex のチャット読み取り機能から同じ ID の会話を取得した。
会話本文は取得できている。元チャットの引用番号や `sandbox:` リンクは
独立した一次資料の検証証跡として扱わない。

ZIP 全体の SHA-256:

```text
dd45f15862f866a0b28762b3314b2fb07c0f2d4942630b6a299106023c9879d6
```

添付文書や会話中の「次に実行すること」は資料として読んだ。
それ自体をインストール、コード実行、Issue 投稿、公開、デプロイの許可とは扱わない。
今回行ったことは設計文書の作成と参照資料の保存・整合確認である。

## 採用の基準

現在の利用者の依頼とリポジトリ指示を優先する。
元チャットでは利用目的と最後の利用者発言を設計の軸とし、
回答に含まれる提案は ZIP の具体的な契約・コード・検証報告と照合する。
初期回答の広い構想を、そのまま実装済み機能や確定した技術選定として扱わない。

| 採用・整理した内容 | 根拠 | 記録先 |
| --- | --- | --- |
| 技能を考慮した人員配置を一般利用できるエンジンにする | 元チャットの最初の利用者発言。飲食店の時間帯別需要と技能の例 | [全体像](overview.md) |
| 用途別のアルゴリズムを先に整え、LLM 入力を後から接続 | 元チャットの最後の利用者発言 | [設計方針](design-policy.md)、[ADR-0001](adr/0001-json-first-engine.md) |
| JSON Schema、ID、型付きルール、機械可読な診断を中心にする | 最後の回答、ZIP `docs/IO_CONTRACT.md`、`model.py`、Schema | [入出力契約](io-contract.md) |
| 独立した担当配置は最小費用流、時間横断条件・勤務計画は CP-SAT | 最後の回答、ZIP `model.py` の `choose_backend`、`flow.py`、`cpsat.py` | [設計方針](design-policy.md) |
| 必須条件と選好を分け、目的は辞書式の配列順とする | 最後の回答、ZIP の入出力仕様・モデル・評価処理 | [入出力契約](io-contract.md) |
| 勤務候補と担当配置を同時に決める | ZIP `cpsat.py`、勤務計画の説明 | [ADR-0002](adr/0002-joint-roster-optimization.md) |
| 必要人数は初期契約では厳密な担当枠数 | 初期回答は人数の下限という例。最後の回答・ZIP は等しい人数と明記し、`cpsat.py`・`verify.py` でも等値を確認 | [入出力契約](io-contract.md) |
| 結果検証に失敗した解を外へ出さず、未検証を真としない | ZIP `engine.py`、`verify.py`、Response Schema | [設計方針](design-policy.md) |
| 1人1日最大1勤務、夜勤未対応、候補集合内の最適性 | ZIP README、入出力仕様、候補展開とモデル | [全体像](overview.md)、[入出力契約](io-contract.md) |
| Python と OR-Tools を中核実装の出発点にする | ZIP `pyproject.toml` とコード | [全体像](overview.md) |
| 公平性・変更最小化・条件比較・詳細矛盾診断は拡張候補 | 初期回答の提案、ZIP の未実装一覧 | [開発・検証方針](development-policy.md) |
| CP-SAT の動作確認と実務評価を導入時の条件にする | ZIP `TEST_REPORT.md` の28件スキップと未検証事項 | [開発・検証方針](development-policy.md) |

TypeScript の UI / SDK、Web API、DB、認証、Docker、Apache-2.0 などのライセンス案は
元チャットの提案として残し、確定事項にしない。
SMILO、OptiMUS、Neural LNS などの研究も探索先の候補とする。
研究の数値・最新性・利用条件は今回再調査しておらず、性能保証や採用済みの根拠にしない。

このチャットでは、複数アルゴリズムの組合せや複数案からの選択も検討案として挙がった。
複雑性が増すなら現状を維持したい、という利用者の意向に沿い、
初期設計は `auto` による単一バックエンド選択・単一解の返却を維持する。
将来の探索改善と、複数案を利用者に提示する機能の採用は別途判断する。

## 保存した参照スナップショット

`docs/reference/skillshift-starter-0.1/` 以下の8ファイルは ZIP 内と同じバイト列を保存した。
各ファイルの元パス、サイズ、SHA-256 は [manifest.json](reference/skillshift-starter-0.1/manifest.json) に記録する。
元の識別子・日付・結果数値を保持しており、翻訳・名称変更した schedula の契約ではない。

| 保存先 | 用途 |
| --- | --- |
| [request.schema.json](reference/skillshift-starter-0.1/skillshift/schemas/request.schema.json) | 初期 Request の構造 |
| [response.schema.json](reference/skillshift-starter-0.1/skillshift/schemas/response.schema.json) | 初期 Response の構造 |
| [assignment.json](reference/skillshift-starter-0.1/examples/assignment.json) | 飲食店の独立した担当配置 |
| [assignment.result.json](reference/skillshift-starter-0.1/examples/assignment.result.json) | ZIP 同梱の結果。今回の実行結果ではない |
| [infeasible.json](reference/skillshift-starter-0.1/examples/infeasible.json) | 人数不足 |
| [linked_assignment.json](reference/skillshift-starter-0.1/examples/linked_assignment.json) | 担当切替の時間横断制約 |
| [roster.json](reference/skillshift-starter-0.1/examples/roster.json) | 2日間の勤務候補生成と担当配置 |
| [TEST_REPORT.md](reference/skillshift-starter-0.1/TEST_REPORT.md) | ZIP 作成時の検証と未検証事項 |

参照コードは ZIP から読み取り、schedula の実行コードとして取り込んでいない。
Schema と例の保存、JSON の読取りやリンクの整合確認は、
最適化アルゴリズムの実行検証とは別である。

## 公式一次資料の確認

ZIP の `docs/SOURCES.md` にある次の説明を2026-10-04に確認した。
本実装の正しさや性能が、公式例によって証明されるという意味ではない。

| 資料 | この文書で使う根拠の範囲 |
| --- | --- |
| [Assignment as a Minimum Cost Flow Problem](https://developers.google.com/optimization/flow/assignment_min_cost_flow) | 最小費用流が扱える割当の範囲と、MIP / CP-SAT の適用範囲との差 |
| [Employee Scheduling](https://developers.google.com/optimization/scheduling/employee_scheduling) | CP-SAT で勤務と勤務希望をモデル化する公式例 |
| [CP-SAT Solver](https://developers.google.com/optimization/cp/cp_solver) | `OPTIMAL`、`FEASIBLE`、`INFEASIBLE`、`UNKNOWN` の区別 |
| [JSON Schema: object](https://json-schema.org/understanding-json-schema/reference/object) | 必須項目と `additionalProperties` による未知プロパティの扱い |
