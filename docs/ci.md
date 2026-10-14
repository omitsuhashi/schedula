# CIの検証範囲

PRでは変更ファイルに応じてジョブを選択し、mainへのpushでは全ジョブを実行する。
Ruff、deployスクリプトの構文、CIの選択・集約ロジックは毎回確認する。

| PRの変更 | 通常のPythonテスト・Linux/Windows互換性 | 配布検証 | Chromium画面検証 |
| --- | --- | --- | --- |
| demoのHTML/CSS/JavaScript、testsのcjs | 省略 | 実行 | 実行 |
| docsのMarkdown/HTML/JSON | 省略 | 実行 | 実行 |
| README.md、AGENTS.md、GLOSSARY.md、THIRD_PARTY_NOTICES.md | 省略 | 実行 | 省略 |
| LICENSE | 省略 | 実行 | 実行 |
| docs/designs、docs/evaluations/inputs | 実行 | 実行 | 実行 |
| 共通エンジン、Python、例・fixture、依存関係、CI設定、その他のファイル | 実行 | 実行 | 実行 |

複数種類の変更は必要な検証の和集合を実行する。分類できないファイルや差分が空の場合は全検証する。
docs/designsとdocs/evaluations/inputsは文書の一般則より優先し、実行用データと設計断片の専用Pythonテストを維持する。
PRのbaseとheadの共通祖先からの差分をGitで取得し、削除とrenameの旧・新パスも判定対象にする。
差分取得に失敗した場合はCIを失敗させ、省略で成功扱いにしない。

Pythonテスト、配布検証、画面検証、OS互換性検証は変更判定の後に並列で実行する。
通常のPythonテストはdistributionマーカーを除き、配布ジョブがそのマーカーのテストを実行する。
配布検証ではsdistから再構築したwheelの隔離導入とPython回帰テストを引き続き確認する。
画面・文書だけの変更でも配布内容に影響するため、この検証は省略しない。

必須チェック名quality-checksとtimezone-distributionのLinux/Windows名は維持する。
quality-checksは失敗後も動き、必要なジョブがすべて成功した場合だけ成功する。
変更判定・lintの失敗、必要なジョブの失敗・取消・意図しない省略、不正な選択結果は拒否する。
不要と判定されたジョブの省略だけを許容する。

PyPI公開は引き続き、公開対象commitに対するci.ymlのmain push実行が成功していることを要求する。
PRの部分検証の成功を公開条件の代わりには使わない。
