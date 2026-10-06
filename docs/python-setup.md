# Python セットアップ

Python の依存管理は uv に統一する。セットアップ・パッケージ追加・実行の手順は、
利用者が指定した `python-setup-with-uv` skill を基準にした本書を正本とする。
参照資料に残る pip・手動 venv の手順より、本書を優先する。
uv 自体の導入は [公式のインストール手順](https://docs.astral.sh/uv/getting-started/installation/)に従う。

## Python と依存パッケージ

2026-10-04 に、依存パッケージが対応する最新の Python として **CPython 3.14.8** を採用した。
[Python の配布一覧](https://www.python.org/downloads/)で 3.14.8 を確認し、
[OR-Tools 9.15.6755](https://pypi.org/project/ortools/9.15.6755/)の Python 3.14 用 wheel と、
[jsonschema 4.26.0](https://pypi.org/project/jsonschema/4.26.0/)の対応を確認した。
macOS ARM64 で実際に依存をインストールして動作を確認した。
Python 3.15 用の OR-Tools wheel は確認できていないため、対応範囲は `>=3.14,<3.15` とする。
`.python-version` に `3.14.8` を固定し、ローカルと CI で同じ Python を使用する。
uv は **0.12.23** を使用する。直接インストールした uv は `uv self update 0.12.23` で更新できる。

| 用途 | パッケージ | 設定 |
| --- | --- | --- |
| JSON Schema 検証 | jsonschema | 実行依存 |
| CP-SAT | ortools | `cp-sat` extra |
| lint・format | ruff | 開発依存 |
| テストの入口 | pytest | 開発依存 |
| コミット前の Ruff 実行 | pre-commit | 開発依存 |

依存定義は `pyproject.toml`、解決した版は `uv.lock` に記録し、両方を Git で管理する。
`.venv/` とツールのキャッシュは Git の対象外である。
独立した `assignment` と、担当時間・担当切替を扱う CP-SAT の実行コードを導入した。
パッケージは `src/schedula/` に置き、
setuptools で版別 Schema を同梱する。利用・ビルドは [担当配置の手順](assignment.md)を参照する。
最小費用流だけを利用する場合は `uv sync --locked` / `uv run --locked ...` で実行でき、
OR-Tools は不要。開発・CI の検証では既存どおり `--extra cp-sat` を維持する。

## 初回セットアップ

リポジトリ直下で実行する。既存の `pyproject.toml` と `uv.lock` を使うので、
`uv init` やパッケージの再追加は不要である。仮想環境の手動 activate も不要である。

```sh
uv python install
uv sync --locked --extra cp-sat
```

`uv python install` は `.python-version` を参照する。
`--locked` は依存定義と lock file の不一致をエラーにし、意図しない再解決を防ぐ。
`dependency-groups.dev` は通常の同期で含まれるが、extras は明示指定が必要である。
CP-SAT の依存を維持するため、以下の実行でも `--extra cp-sat` を指定する。

## Git hook

`.pre-commit-config.yaml` には Ruff の `ruff-check`（`--fix`）と `ruff-format` を設定している。
`astral-sh/ruff-pre-commit` の `rev` は導入時の最新安定版 `v0.16.10` に固定した。
既存 hook の経路とファイルを確認し、衝突がない場合にインストールする。

```sh
git config --get core.hooksPath
git rev-parse --git-path hooks
uv run --locked --extra cp-sat pre-commit install --install-hooks
```

`core.hooksPath` が未設定の場合、最初のコマンドは終了コード1となる。
既存 hook と衝突する場合は上書きせず、手動検証を続ける。
依存に pre-commit を追加するだけでは Git commit 時に動かないため、clone 後に導入する。
Git worktree では hook 保存先を同じリポジトリ内で共有する。
この worktree では既存の `pre-commit` hook がないことを確認して導入した。
自動修正が入ると commit が止まるので、差分を確認してから `git add` し直す。

## 日常の検証

```sh
uv run --locked --extra cp-sat pre-commit run --all-files --show-diff-on-failure
uv run --locked --extra cp-sat pytest
bash -n scripts/deploy
```

既存の `unittest` テストは pytest から収集・実行する。
テスト未作成やスキップは未検証として記録し、空のテスト実行を成功扱いしない。
hook を使わない場合は `uv run --locked --extra cp-sat ruff check .` と
`uv run --locked --extra cp-sat ruff format --check .` で確認する。
両方の経路で同じ Ruff 検証を繰り返す必要はない。

CI の `deploy-entrypoint` も、uv 0.12.23 と `.python-version` を使い、
`uv sync --locked --extra cp-sat`、Ruff hook、pytest、デプロイスクリプトの構文を確認する。
CI 設定の導入と GitHub 上での実行成功は別であり、外部実行結果は workflow 実行時に確認する。

## 依存の変更と更新

実行時の依存は `uv add <package>`、開発専用の依存は `uv add --dev <package>`、
CP-SAT 用の任意依存は `uv add --optional cp-sat <package>` で追加する。
変更後は `uv sync --locked --extra cp-sat` で環境を揃え、日常の検証を実行する。
依存版を更新するときは `uv lock --upgrade-package <package>` を使い、lock file の差分を確認する。
Ruff 更新時は `uv run --extra cp-sat pre-commit autoupdate` も実行し、
hook の `rev` と開発依存の Ruff を同じ版に揃える。
Python 更新時も、依存の対応と wheel を確認して `uv python pin <version>` で固定し直す。

mypy は型注釈を保守対象にするときだけ、poethepoet は `uv run ...` のコマンド整理が
必要になったときだけ `uv add --dev` で追加する。現在はどちらも導入していない。

## セットアップ時の検証記録

2026-10-04、macOS ARM64 / Python 3.14.8 / uv 0.12.23 で確認した。
導入した版は jsonschema 4.26.0、OR-Tools 9.15.6755、Ruff 0.16.10、
pytest 9.1.1、pre-commit 4.6.2 である。

- Git hook のインストールと `pre-commit run --all-files`：Ruff の lint・format が成功。
- pytest：既存のデプロイ入口テスト2件が成功。
- jsonschema：参照入力3件と参照出力1件のスキーマ検証が成功。
- OR-Tools：整数変数の小規模 CP-SAT モデルで `OPTIMAL` と期待値7を確認。
- `bash -n scripts/deploy`、`git diff --check`、参照原本8件のハッシュと文書リンク：成功。

これらは環境と既存テストの確認であり、参照エンジン全体や勤務計画の検証ではない。
GitHub 上の更新後 CI はまだ実行していない。

## 参照 ZIP を評価する場合

`skillshift-starter-0.1.zip` を隔離ディレクトリに展開し、
`pyproject.toml` のある `skillshift-starter/` で実行する。
schedula 直下や `docs/reference/skillshift-starter-0.1/` には実行コードがない。
元パッケージの `dev` と `cp-sat` は extras なので、次のように両方を指定する。

```sh
uv sync --extra dev --extra cp-sat
uv run --extra dev --extra cp-sat pytest -q
uv run --extra dev --extra cp-sat python -m skillshift solve examples/assignment.json
uv run --extra dev --extra cp-sat python -m skillshift solve examples/linked_assignment.json
uv run --extra dev --extra cp-sat python -m skillshift solve examples/roster.json
```

元の `dev` extra と、新規の `uv add --dev` が作る `dependency-groups.dev` は別の宣言である。
毎回の実行で同じ extras を指定し、CP-SAT のテストが依存不足でスキップされないことを確認する。
環境・依存版・コマンド・結果・スキップ理由を評価記録に残す。
ZIP の過去の結果を、この手順による実測結果として扱わない。

2026-10-05 の [評価記録](evaluations/engine-introduction.md)に、取得した ZIP の照合、
Python 3.14.8 / OR-Tools 9.15.6755 での実行コマンド・結果・導入判断を記録した。
参照ソースは取り込まず、探索前の準備と出力構造検証の差分を後続実装の条件にした。

## 公式資料

- [uv のプロジェクト管理](https://docs.astral.sh/uv/guides/projects/)
- [依存管理と extras・dependency groups](https://docs.astral.sh/uv/concepts/projects/dependencies/)
- [uv のコマンドとオプション](https://docs.astral.sh/uv/reference/cli/)
