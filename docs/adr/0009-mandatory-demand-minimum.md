---
status: accepted
---

# 元需要を保持し、明示した最低人数だけを必須にする

[Issue #87](https://github.com/omitsuhashi/schedula/issues/87)の実装依頼に基づき、
[ADR-0004](0004-partial-plan-contract.md)の全需要不足許容へ、契約0.12で明示的な必須下限を追加する。
責任者を必ず配置する条件はpriorityでは表せず、不足総量を先に最小化すると短い必須枠を空け得る。

元の必要人数を減らす代わりに、`minimum_people` を省略時0の必須条件とする。
その下限と既存の勤務条件を守る解の中で、不足総量・priority群・指定目的の順を維持する。
下限を満たせないときは空のPARTIALを返さず、証明済みのINFEASIBLEと未確定のUNKNOWNを区別する。
[ADR-0001](0001-json-first-engine.md)の版付きJSON境界と独立検証、
[ADR-0002](0002-joint-roster-optimization.md)の同時最適化は維持する。

下限が正なら既存のCP-SATへ送り、独立した配置の最小費用流は下限0の範囲を維持する。
診断は需要1件の上下限を一組にして人数条件だけを外し、背景・候補・変数を保持する。
変更案の下限編集も利用者の明示を要求し、元条件の解へ置き換えない。
0.1〜0.11のSchemaと意味は変更しない。詳細は[契約0.12](../io-contract-minimum-demand.md)に定める。
