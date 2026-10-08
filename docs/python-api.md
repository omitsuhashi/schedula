# Python公開API

JSONのdict/list境界を維持する。公開型は標準 `typing` の `TypedDict` / `Literal` であり、
新しい入力モデルや実行時の型変換は加えない。wheelとsdistには `py.typed` と公開入口のstubを含める。

| 呼び出し | 結果・用途 | 例外・エラーの扱い |
| --- | --- | --- |
| `load_json(text: str) -> JSONValue` | 厳密なJSON読み取り。Request以外のJSONも読める | 重複キー・非有限数・不正JSONは `InvalidInput` |
| `validate(request: object) -> Validation` | 構造・参照・時刻・候補・baselineの意味を探索なしで検証 | JSON結果の `VALID` / `INVALID_INPUT` / `INTERNAL_ERROR` |
| `solve(request: Request, *, num_workers: int = 2) -> Response` | 求解と独立検証 | 入力不備・依存不足・内部障害を既存Responseの状態で返す |
| `verify(request: Request, solution: Solution) -> Verification` | 保存・編集した解の独立検証。最適性は認定しない | `VALID` / `PARTIAL` / `INVALID_INPUT` / `INVALID_PLAN` / `INTERNAL_ERROR` |
| `get_schema(kind, schema_version="0.1")` | `request` / `response` / `solution` / `verification` のSchema | 未知の種類・版は `ValueError` |
| `make_baseline(request: Request04 \| Request05 \| Request06 \| Request07 \| Request08 \| Request09 \| Request010 \| Request011 \| Request012 \| Request013 \| Request014 \| Request015, solution: ExtendedSolution \| ContinuitySolution, plan_id: str) -> Baseline` | 契約0.4〜0.15のrosterから検証済み基準計画を作る | 入力・解の不備は `InvalidInput`。環境・内部例外は呼び出し側で扱う |

`InvalidInput` は `ValueError` の派生で、`diagnostics` に既存形式の診断配列を持つ。
公開関数は入力を書き換えない。make_baselineは返すスナップショットをコピーして作る。
新しい業務条件を旧契約で受理したり、固定の勤務候補数上限を設けたりしない。

## フォームでの入力検証

`validate` の結果は `schema_version`、`request_id`、`status`、`diagnostics`、
`stats.elapsed_seconds` を持つ。`VALID` は入力を受理できるという意味で、
実行可能な計画の存在や需要充足を保証しない。OR-Toolsなしで使え、
既存の `normalize` による意味検証とbaselineの独立照合を実行する。

```python
from shift_schedula import InvalidInput, load_json, validate

try:
    value = load_json(text)
except InvalidInput as error:
    print(error.diagnostics)
else:
    checked = validate(value)
    print(checked["status"], checked["diagnostics"])
```

`text` はUTF-8ファイルを `read_text(encoding="utf-8")` で読んだ文字列などを渡す。
不正なID参照・日時・基準計画は `INVALID_INPUT`、時刻データなどの環境障害は
`INTERNAL_ERROR` で区別する。入力検証と求解の入口は同じ意味検証を使う。

## 型付きの利用と状態分岐

`Request` は `Request01` / `Request02` / `Request03` / `Request04` / `Request05` / `Request06` / `Request07` / `Request08` / `Request09` / `Request010` / `Request011` / `Request012` のunion。
[契約0.6](io-contract-continuity.md)は実績・確定勤務と独立集計を扱い、移動Wの比較・固定は[契約0.7](io-contract-overlap.md)で扱います。
[契約0.8](diagnosis.md#契約08の条件グループ縮小)の `DiagnosisOptions08` と `Conflict08` は条件グループの縮小と証明範囲を扱う。
[契約0.9](io-contract-roster-metrics.md)の `Costs` / `CostObjective` / `DutyBalance` / `DutyObjective` は勤務費用と指定区間の目標偏差を扱う。
各版の構築用型と入れ子の型は `shift_schedula.types` にある。
[契約0.10](io-contract-duty-continuity.md)の `Request010` は確認済みの文脈期間へ指定区間の評価を広げる。
[契約0.11](io-contract-day-counts.md)の `Request011` は勤務日数・完全休日数の上下限を扱う。

[契約0.12](io-contract-minimum-demand.md)の `Request012` / `MinimumDemand` は必須の最低充足人数を扱う。

`schema_version` で契約版、`Response.status` で成功と失敗を分岐できる。
`PARTIAL` は0.3以降だけに存在し、成功状態では `solution` の内容を型付きで参照できる。

文字列の長さ、整数の範囲、boolと整数の区別、時間の整合や参照先は静的な型だけでは保証しない。
JSONを読んだ後は `validate` を通し、`VALID` を確認した境界で `cast(Request, value)` を使う。
型を付けただけの値を検証済みと扱わない。

## 内部障害を調べる

packageのlogger `shift_schedula` は `NullHandler` を持ち、root logger・handler・levelを変更しない。
求解・入力検証・独立検証・追加診断で捕捉した内部例外はDEBUGの `exc_info` として記録する。
通常の入力不備や解なしにはtracebackを付けない。ログ未設定時の出力とCLIのJSON stdoutは維持する。

組み込み側で、出力先を設定してから対象loggerのlevelを変える。

```python
import logging

handler = logging.StreamHandler()  # 既定はstderr。保存先は利用側で指定する。
logger = logging.getLogger("shift_schedula")
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)
```

ライブラリはRequest/Solutionや従業員情報をログ用に展開しない。
例外本文には利用側の値が含まれる場合があるため、DEBUGログの保存・アクセス・共有は利用側で管理する。

[実行例](../examples/typed_api.py)は厳密JSON読み取り、フォーム検証、`PARTIAL`を含む状態分岐を示す。

```sh
uv run --locked mypy --strict examples/typed_api.py
uv run --locked python examples/typed_api.py examples/partial_assignment.json
```

型チェックは公開typingのconsumerを対象とする。内部実装全体の静的型検証ではない。
CIではwheelを別環境へ導入し、このconsumerが成功することと、状態の綴り間違い・未知フィールドを
mypyが拒否することを検証する。型の仕組みは[mypyのTypedDict文書](https://mypy.readthedocs.io/en/stable/typed_dict.html)を参照する。

## CPU数・総期限・取消

同期 `solve(request)` を基本とする。`num_workers` はPythonの実行オプションで、
省略時2、boolを除いた正の整数を受け取り、CP-SATのint32範囲（最大2147483647）を検証する。
不備は `INVALID_INPUT` / `INVALID_EXECUTION_OPTION` として返す。
CP-SATでは指定値を `num_search_workers` へ渡し、`SEARCH_STATS.facts.num_workers` に記録する。
最小費用流では適用せず、この値をnull、`workers_applied` をfalseとして記録する。
業務Requestの内容とJSON契約は変えない。追加診断の子求解にも同じ値を渡す。

`solver.time_limit_seconds` は候補展開・モデル構築後の探索予算であり、呼び出し全体の期限ではない。
[実行管理例](../examples/controlled_solve.py)の `run_controlled` はstdlibのspawnを使い、
起動・IPC・求解・独立検証を含む総期限をmonotonic clockで管理する。
`cancel` には親側の `threading.Event` を渡す。Windowsでも `if __name__ == "__main__"` の
入口から呼ぶ。子は孫プロセスや共有lockを作らず、呼び出し専用の一時ファイルへJSONを保存する。
子の終了後に完成したResponseを読み取り、元Requestに対して再検証してから返す。

外側の `status` は `COMPLETED` / `DEADLINE_EXCEEDED` / `CANCELLED` / `WORKER_ERROR`。
`COMPLETED` の `response` だけが完全なエンジン結果であり、その中の
`UNKNOWN` / `INFEASIBLE` / `PARTIAL` などを読む。その他は `response: null`。
期限・取消時にはterminate、必要ならkillを実行してjoinし、プロセスhandleと一時ファイルを片付ける。
Pipe・Queueは作らないため、途中の大きな送信を親が受信して期限を超えることはない。
各呼び出しの子とIPCは独立し、一件の取消で他を停止しない。

```sh
uv run --locked --extra cp-sat python examples/controlled_solve.py examples/roster.json --num-workers 1 --total-seconds 30
uv run --locked --extra cp-sat python examples/controlled_solve.py examples/roster.json --total-seconds 0.001
uv run --locked --extra cp-sat python examples/controlled_solve.py examples/roster.json --cancel-after 0.1
```

OSのプロセス起動・終了、親のIPC読み取りや再検証は即時に中断できないため、ハードリアルタイムではない。
経過時間を再確認して遅い結果を破棄し、終了確認による超過は `elapsed_seconds` と
`cleanup_seconds` で区別する。停止確認を済ませてから親へ戻る。
macOSのローカル検証とWindows/LinuxのCIで正常完了・段階別の期限/取消・異常終了・並行実行を確認する。
spawnと終了処理は[Python 3.14公式文書](https://docs.python.org/3.14/library/multiprocessing.html)に基づく。

契約0.5の `PriorityDemand.priority` と `Response05Success.priority_summary` は
[需要priorityの契約](io-contract-priority.md)を参照する。独立検証の同集計は最小性の証明を付けない。

契約0.13の `Request013` / `ShiftCategory` / `Constraint013` は、勤務分類と4種類の必須パターンを扱う。
[契約・境界](io-contract-shift-patterns.md)に従い、原勤務と判定余白を入力する。

契約0.14の`Request014` / `Constraint014` / `RequiredCoworkers` / `IncompatibleEmployees`は、
[同時勤務条件](io-contract-coworkers.md)を扱う。勤務状態に対する必須条件で、待機を含み休憩を除く。

契約0.15の`Request015` / `ShiftCountBalance` / `ShiftCountObjective` / `ShiftCountBalanceSummary`は、
[勤務回数の明示目標](io-contract-shift-counts.md)を扱う。`balance_id`で目的と対応させ、
`shift_count_balance_summary`をsolve・verifyで読み取れる。独立検証の結果に最適性は付与しない。


## 分割入力と実行記録

外側の入力候補/記録は[Adapter形式1.0](input-adapter.md)で管理します。
`split_request` / `import_request`、`confirm_source` / `confirmation_state` / `assemble`、
`read_draft` / `run_draft`、`create_record` / `check_record` / `reverify_record` / `record_view`
と `get_adapter_schema` / `save_json` を公開します。従来のRequest/solve/verifyは変更しません。
公開型は `RequestDraft`、`Assembly`、`RunRecord`、`RecordVerification`、`RecordView`。
[型付き利用例](../examples/typed_adapter.py)をmypy strictで検査できます。
確認や保存設定を実行Requestへ混入させず、来歴不明と業務値の有効性を分けます。
