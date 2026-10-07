# 需要priorityと不足配分の契約0.5

[Issue #66](https://github.com/omitsuhashi/schedula/issues/66)に基づき、
需要ごとの任意 `priority` を追加する。親Issue #58で版を採番した。
0.1〜0.4のSchemaと意味は変更しない。0.5は0.4の勤務条件・未完成の基準計画・公開検証を引き継ぐ。

## 入力と目的順序

`demand[].priority` は非負整数で、省略時0。大きい値ほど先に比較する。
必須条件や元の `required_people` は変更しない。求解は次の順序で行う。

1. 全需要の不足合計人分を最小化する。
2. その最小値を固定し、priorityの高い需要群から順に群の不足人分を最小化する。
3. 証明済みの上位値を固定し、利用者の `objectives` を指定順に最小化する。

同じpriorityの需要は一群として合算する。ID・配列順・priorityの値の差を重みに使わない。
重要な需要を充足するために不足総量を増やすことはしない。
各段階で最適性が証明されなければ、下位段階へ進まない。
全priorityが0または省略なら、従来の不足総量と利用者目的だけを探索する。

非既定priorityがあれば `auto` は `cp_sat` を選択し、選択理由を `DEMAND_PRIORITY` とする。
明示 `min_cost_flow` では `INVALID_INPUT` / `UNSUPPORTED_BACKEND` として拒否する。
全priorityが0なら既存のbackend選択を維持する。探索段階はすべて一つの
`solver.time_limit_seconds` を共有する。起動・候補展開・検証を含む総期限は
[Pythonの実行管理例](python-api.md#cpu数総期限取消)で別途扱う。

## 出力と証明範囲

解があるとき、`shortage_summary` は従来どおり全需要の不足一覧・合計人分・総量の
`proven_minimal` を持つ。0.5では別に `priority_summary` を必須で返す。
解のない応答では両集計をnullとする。

```json
{
  "groups": [
    {"priority": 10, "total_person_minutes": 0, "proven_minimal": true},
    {"priority": 0, "total_person_minutes": 30, "proven_minimal": false}
  ]
}
```

全需要に現れるpriorityを降順で一行ずつ返し、充足した群も0人分で残す。
需要が空なら `groups: []`。群の人分合計は全体の不足合計人分と一致する。
群の `proven_minimal` は、総量とそれより高いpriority群の最小値を固定した条件での証明。
上の例はpriority 10まで証明済みで、priority 0と利用者目的は未証明である。
総量・群・利用者目的の証明は順序の先頭から連続する。
総量0なら各群も0であり、非負性から群の最小性を認定できる。
全priorityが0の場合は一群の値と証明が全体と同じになる。

`PARTIAL` は需要不足を伴う計画であり、全体の最小性や優先配分の証明と区別する。
`OPTIMAL` は需要を充足し、群と利用者目的を含む証明が揃った状態。
探索した群の下限は `PRIORITY_SHORTAGE_BOUND` の診断で示す。

独立検証 `verify` は元需要と担当配置から群の不足を再計算する。
最小性を認定しないので、各 `proven_minimal` はfalse。
保存・編集した解は再検証し、元の求解の証明を転記しない。
`make_baseline` は0.4・0.5のrosterを受理する。0.5の基準を旧契約へ入れると拒否する。

## 具体例と検証

[利用例](../examples/demand_priority.json)は1人・同時刻の2役割・各1人の需要で、
両計画とも不足30人分になる。選好はホールを望むが、priority 10の調理を担当し、
priority 0のホールに30人分の不足を残す。ID順を逆にしても優先度の意味は変わらない。

```sh
uv run --locked --extra cp-sat python -m shift_schedula solve examples/demand_priority.json
uv run --locked --extra cp-sat pytest -q tests/test_demand_priority.py
```

別の検証例では、1日1勤務の同じ従業員が重要需要の30分勤務か通常需要の60分勤務を選ぶ。
重要需要を担当すると不足60人分、通常需要を担当すると不足30人分なので、後者を選ぶ。
全探索との一致、共有予算・証明の先頭範囲、集計の改ざん拒否、旧版の拒否・既定値の互換、
未完成の基準計画からの固定再計画・全体再計画を回帰検証する。
