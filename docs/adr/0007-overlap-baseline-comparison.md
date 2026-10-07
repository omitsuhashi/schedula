---
status: accepted
---

# 基準計画は原期間で保存し、重複期間だけを比較・固定する

[Issue #75](https://github.com/omitsuhashi/schedula/issues/75)と
[採用設計](../designs/continuity.md)に基づき、契約0.7で
[ADR-0005](0005-partial-baseline-and-independent-verification.md)の基準比較を移動期間へ拡張する。
[ADR-0006](0006-continuity-original-intervals.md)の原区間保持と事実の分離を維持する。

基準を新しい期間へ切り詰めると、過去の入力条件や固定状態を再検証できなくなる。
元Request・解・固定状態を原期間で保存して検証し、求解と独立検証時だけ新旧の重複期間へ投影する。
比較用固定は重複期間に限定し、実績・確定勤務は比較とは独立した業務事実として維持する。

同じタイムゾーン・粒度・枠境界を必須とし、期間外の削除・追加を変更に数えない。
その代わり粒度・タイムゾーン変換は扱わず、利用側で比較区間と集計単位を読む必要がある。
公開変換の引数・有限候補の同時最適化・ソルバーに依存しない検証・旧契約の意味は維持する。
詳細は[契約0.7](../io-contract-overlap.md)に記す。
