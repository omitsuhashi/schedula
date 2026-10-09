---
status: accepted
---

# 全業務機能を現行契約0.15へ集約し旧契約の通常受付を終了する

2026-10-09、Issue #105で、0.1〜0.15の業務機能を0.15に集約することと、移行・検証後に一時変換コードを撤去することを所有者が承認した。
[ADR-0001](0001-json-first-engine.md)のJSON境界と[ADR-0002](0002-joint-roster-optimization.md)の有限候補・担当の同時最適化を維持する。
[ADR-0003](0003-extended-roster-contract.md)、[ADR-0004](0004-partial-plan-contract.md)、
[ADR-0005](0005-partial-baseline-and-independent-verification.md)、[ADR-0006](0006-continuity-original-intervals.md)、
[ADR-0007](0007-overlap-baseline-comparison.md)、[ADR-0008](0008-duty-balance-context.md)、
[ADR-0009](0009-mandatory-demand-minimum.md)の業務上の意味は引き継ぐ。
これらの「以前の契約のSchema・正常受付を維持する」という導入時の判断だけを、今回の確認済み移行範囲で置き換える。
過去の採用判断・測定・原入力は改変せず履歴として保持する。

通常のAPI・CLI・Schema・公開型・デモ・配布は0.15だけを扱い、旧版・未知版・版欠落を明示拒否する。
原需要・省略下限0・priority省略0・原勤務・目的順・不足・証明接頭辞・独立検証の意味を変更しない。
旧0.1/0.2の完全充足は明示下限へ、旧候補/履歴は現在形状へ明示移行し、
完全需要のbase最小費用流を保持する。架空の正常Requestへの補完や自動移行は行わない。

通常受付を重ねて保守する構成を終了する代わりに、全機能対応表、固定回帰、データ棚卸し、
原本を保護する明示移行、利用アプリの保存往復、独立検証、配布・性能・実画面の受け入れを終了条件にする。
今回、リポジトリ外の保存済み実データはないという所有者回答を記録し、例・fixture・候補アプリを検証した。
一時移行コードは撤去し、原SHA・移行先SHA・固定commit・PR・検証結果を履歴に残す。
過去の変換が必要な場合は固定Git履歴を参照し、最新配布に旧環境や変換基盤を常設しない。

[現行契約](../io-contract-current.md)を仕様の正本、[サポート方針](../contract-support.md)を今後の互換性・旧版終了の判断基準とする。
パッケージは破壊的変更を識別する0.2.0、JSON契約は0.15、Adapter形式は1.0である。
ローカルCIを今回の受け入れに使う所有者回答と、GitHub Actionsの結果は別に記録する。
PyPI公開・GitHub Release・実顧客デプロイは今回の採用に含まない。
