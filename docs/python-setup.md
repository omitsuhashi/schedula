# Python セットアップ

Python の依存管理は uv に統一する。セットアップ・パッケージ追加・実行の手順は、
利用者が指定した `python-setup-with-uv` skill を基準にした本書を正本とする。
参照資料に残る pip・手動 venv の手順より、本書を優先する。
uv 自体の導入は [公式のインストール手順](https://docs.astral.sh/uv/getting-started/installation/)に従う。

## 現在のリポジトリで実行できること

2026-10-04 時点では、最適化エンジン、`pyproject.toml`、`uv.lock`、
Ruff・pytest・pre-commit の設定を導入していない。
`tests/test_deploy.py` は標準ライブラリの `unittest` を使っており、外部パッケージは不要である。
リポジトリ直下で次を実行する。

```sh
bash -n scripts/deploy
uv run --no-project python -m unittest discover -s tests -v
```

`--no-project` は親ディレクトリの Python プロジェクトを探索しないために指定する。
現在の CI も同じ `unittest` を実行する。CI には uv をまだ導入していない。
以下のセットアップはエンジン導入時の手順であり、今回実行したものではない。

## エンジンを導入するとき

既存の `pyproject.toml`、lock file、テスト・hook 設定を確認し、同じ役割の仕組みを尊重する。
参照パッケージの設定を取り込む場合は、それを uv で管理し、再初期化しない。
Python プロジェクト設定がない場合だけ、リポジトリ直下で初期化する。

```sh
uv init --bare --no-pin-python
```

`--bare` は既存の README やコードのあるリポジトリで、`pyproject.toml` だけを作るために使う。
Python バージョンは要件がある場合だけ `uv python pin <version>` で固定する。
参照実装は Python 3.11 以上を前提とするので、取り込む際はその要件と対応環境を確認する。

継続開発では Ruff を lint・format、pytest をエンジンのテスト入口、
pre-commit をコミット前の Ruff 実行に使う。
現在の `unittest` テストは維持し、pytest 導入後はその入口から実行できることも確認する。

```sh
uv add --dev ruff pytest pre-commit
uv sync
```

実行時の依存は `uv add <package>`、開発専用の依存は `uv add --dev <package>` で追加する。
OR-Tools を任意機能として採用する場合は `uv add --optional cp-sat ortools` とし、
`uv sync --extra cp-sat` と `uv run --extra cp-sat ...` で有効化する。
既に宣言された依存をインストールするだけなら `uv sync` を使う。
`dependency-groups.dev` は通常の同期で含まれるが、extras は明示指定が必要である。
依存定義は `pyproject.toml`、解決した版は `uv.lock` に記録し、両方を Git で管理する。
`.venv/` とツールのキャッシュは `.gitignore` に追加する。仮想環境の手動 activate は不要である。

mypy は型注釈を保守対象にするときだけ、poethepoet は `uv run ...` のコマンド整理が
必要になったときだけ `uv add --dev` で追加する。

## Git hook と検証

`.pre-commit-config.yaml` には最初は Ruff の `ruff-check`（`--fix`）と `ruff-format` だけを載せる。
`astral-sh/ruff-pre-commit` の `rev` は導入時の最新安定版に固定し、
以後は `uv run pre-commit autoupdate` で更新する。
Ruff のルールは `pyproject.toml` に設定する。

hook をインストールする前に、既存の hook 経路とファイルを確認する。

```sh
git config --get core.hooksPath
git rev-parse --git-path hooks
```

`core.hooksPath` が未設定の場合、最初のコマンドは終了コード1となる。
既存 hook と衝突する場合は上書きせず、環境同期や手動検証を続ける。
設定を用意し、衝突がないことを確認してから次を実行する。

```sh
uv run pre-commit install --install-hooks
uv run pre-commit run --all-files --show-diff-on-failure
uv run pytest
```

`pre-commit install` はリポジトリごとに必要である。依存に追加するだけでは Git commit 時に動かない。
自動修正が入ると commit が止まるので、差分を確認してから `git add` し直す。
hook を使わない場合は `uv run ruff check .` と `uv run ruff format --check .` で確認する。
両方の経路で同じ Ruff 検証を繰り返す必要はない。
mypy を導入した場合は対象を指定して `uv run mypy <対象>` も実行する。
テスト未作成やスキップは未検証として記録し、空のテスト実行を成功扱いしない。

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
uv が生成する lock file と、環境・依存版・結果・スキップ理由を評価記録に保存する。
ZIP の過去の結果を、この手順による実測結果として扱わない。

## 公式資料

- [uv のプロジェクト管理](https://docs.astral.sh/uv/guides/projects/)
- [依存管理と extras・dependency groups](https://docs.astral.sh/uv/concepts/projects/dependencies/)
- [uv のコマンドとオプション](https://docs.astral.sh/uv/reference/cli/)
