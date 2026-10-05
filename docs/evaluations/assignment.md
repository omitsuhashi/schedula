# 独立した担当配置の検証記録

検証日: 2026-10-05（Asia/Tokyo）。対象: [Issue #6](https://github.com/omitsuhashi/schedula/issues/6)。
[Issue #5 の参照評価](engine-introduction.md)とは別に、今回実装した schedula を実行した。
参照ソース・テストは取り込まず、保存済み原本8件のサイズと SHA-256 が manifest と一致することを確認した。

## 実行環境

| 対象 | 実測値 |
| --- | --- |
| OS / CPU | macOS 26.7.1 / ARM64 |
| Python / uv | CPython 3.14.8 / uv 0.12.23 |
| schedula / jsonschema | 0.1.0 / 4.26.0 |
| OR-Tools | 9.15.6755（開発環境の既存 extra。今回のソルバーは使用しない） |
| pytest / Ruff / pre-commit | 9.1.1 / 0.16.10 / 4.6.2 |

依存は `uv sync --locked --extra cp-sat` で同期した。
`uv.lock` の既存の依存版は維持し、ルートを virtual project から editable package に変更した。
wheel のビルドは `setuptools.build_meta` を使用し、実行用 Schema を明示的な package data として含めた。

## コマンドと結果

| 実行 | 成功 | 失敗 | スキップ・理由 |
| --- | --- | --- | --- |
| `uv run --locked --extra cp-sat pytest -q -ra` | 304件、既存 unittest の subtest 6件 | 0件 | 0件 |
| Ruff lint・format / pre-commit | 成功 | 0件 | なし |
| `uv run --locked --extra cp-sat python -m schedula solve examples/assignment.json` | `OPTIMAL`、ペナルティ0、検証成功、終了コード0 | 0件 | なし |
| `python -m schedula solve -` / `schema request` / `schema response` | CLI テストで成功 | 0件 | なし |
| `uv build --wheel` と wheel の API・CLI・Schema | 成功。ソース checkout の import を除外して検証 | 0件 | なし |
| OR-Tools なしの隔離実行 | `OPTIMAL`、ペナルティ0、検証成功 | 0件 | なし |
| `bash -n scripts/deploy` / `git diff --check` | 成功 | 0件 | なし |
| 参照原本の SHA-256 / サイズ | 8件一致 | 0件 | なし |

pytest の実測時間は3.18秒。単発の確認であり、実務規模の性能保証ではない。
GitHub CI の実行 URL と結果は本 Issue の PR に記録する。

OR-Tools なしの確認は、ビルドした wheel だけを `--with` に指定し、
作業用 `.venv` を探索しない `/private/tmp` から次の形で実行した。
`importlib.util.find_spec("ortools") is None` を先に検証し、`solve` の状態・目的値・検証結果を確認した。

```sh
uv run --no-project --isolated --python 3.14.8 \
  --with /private/tmp/schedula-issue6-wheel/schedula-0.1.0-py3-none-any.whl \
  python <確認スクリプト>
```

## 確認した境界

- 小規模担当配置150件は従業員4人・役割3件・時間枠2件で全探索と比較し、最適値と不可能性が一致。
- 空需要、未指定需要、技能の AND 条件とレベル0、技能の取り合い、残余経路での配置変更、必要な選好違反を確認。
- 入力の未知項目・参照・重複 ID と技能・JSON キー・非有限数・不正区間・粒度・資源上限・未対応条件を拒否。
- 半開区間の接合、異なるオフセットでの同一時点、時計変更をまたぐ実時間の正規化を確認。
- 壊れた解の技能・勤務可能時間・二重配置・不足・過剰配置・不正参照・未知項目・欠落・型不正を検出。
- 元入力から評価値を再計算し、ソルバーとの不一致を `INTERNAL_ERROR` / `solution: null` にする。
- 正規化テーブルを壊しても独立検証が元入力を照合すること、Response の状態・検証・目的 ID が整合することを確認。
- 準備の人工遅延で探索予算を減らさず、探索中・後続時間枠の時間切れで部分解を返さないことを確認。

開発途中の初回テスト収集は pytest の予約名 `request` の使用で失敗した。引数名を修正後、全件を実行した。
隔離確認の初回は作業用 `.venv` が参照されたため OR-Tools 不在の前提を満たさず、実測として採用しなかった。
`--isolated` と作業ディレクトリを指定した上記の実行で確認した。未解決のテスト失敗はない。

## 未検証事項

`roster`、時間横断制約、CP-SAT、勤務候補の最適化は未実装。今回の成功で代替しない。
実務規模の性能、HTTP API の隔離・期限・キャンセル、外部配布、Web・LLM、
実運用デプロイは未検証。ライセンスなど公開条件は [開発方針](../development-policy.md)に従う。
