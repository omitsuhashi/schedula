# 移行前の固定環境と合成保存データ

契約0.15への明示移行・旧解検証・復旧のため、旧環境をGitのこのディレクトリに保存する。
通常のwheel/sdistからは除外する。`manifest.json` に原bytesのSHA-256・版・commit・期待値を固定し、
`tests/test_migration_inventory.py` が整合性を確認する。利用者の実データは含めない。

## 保存した成果物

| 保存先 | 内容 |
| --- | --- |
| engine-0.1.6 | 基点 `bbb7a93b757cc3272943bbc09f9f2dcb359bd457` のwheel、uv.lock、base/cp-satのハッシュ付きrequirements |
| app-0.1.5 | アプリ `ccd32402119762cca4c2981b705730b1e7dc3230` のbackend source archive/uv.lock、既存0.1.5 wheel原本/vendor manifest、runtime requirements |
| app-0.1.5/representative.json | 旧公開solveで作った完全/PARTIAL二案、未完成基準を含むinput、selected/baseline、edit。求解時の元Responseを保持したschedula-app/1 |
| app-0.1.5/representative.sqlite3 | 上記JSONを旧restoreで再検証して旧Storeへ保存し、標準backupで作ったDB Schema 1、1セッション/2計画。resultは現在検証、evidenceは元証拠。隣のrepresentative.sqlite3.jsonに復元用のDB版・pin・SHAを保存 |

0.1.6のwheel SHA-256は `90e2c2ad0f5df80f4e222e6540acccb3ca23bd7cf74dffbd10b1636df4a52010`。
アプリ0.1.5は既存vendor SHA
`3b8256c0d277da253cd79252683727c65c9ab7265c02aec93ff26a24006e9195` と一致する。
0.1.6の構築はGit archiveで得た固定ソースに
`SOURCE_DATE_EPOCH=1791463601 uv build --wheel` を適用した。
依存一覧は各lockに `uv export --locked --no-dev --no-emit-project` を適用し、
extra側は `--extra cp-sat`、アプリ側は `--no-emit-package shift-schedula` でローカルwheel行を除いた。
requirementsの生成コメントから開発機の絶対パスだけ除き、依存版・条件・hashを変更していない。

## 別ディレクトリでの再作成

リポジトリrootから実行する。新しい環境名を選び、稼働原本へ適用しない。
SHAを先に照合する。manifestの自己hashは保存せず、Gitのcommitでmanifest自体を固定する。

```sh
python3 - <<'PY'
import hashlib, json
from pathlib import Path
root = Path('docs/migrations/legacy')
for entry in json.loads((root / 'manifest.json').read_text())['files']:
    raw = (root / entry['path']).read_bytes()
    assert len(raw) == entry['bytes']
    assert hashlib.sha256(raw).hexdigest() == entry['sha256'], entry['path']
PY

uv venv --python 3.14.8 /tmp/schedula-legacy-engine
uv pip sync --python /tmp/schedula-legacy-engine/bin/python --require-hashes docs/migrations/legacy/engine-0.1.6/cp-sat-requirements.txt
uv pip install --python /tmp/schedula-legacy-engine/bin/python --no-deps docs/migrations/legacy/engine-0.1.6/shift_schedula-0.1.6-py3-none-any.whl

uv venv --python 3.14.8 /tmp/schedula-legacy-app
uv pip sync --python /tmp/schedula-legacy-app/bin/python --require-hashes docs/migrations/legacy/app-0.1.5/runtime-requirements.txt
uv pip install --python /tmp/schedula-legacy-app/bin/python --no-deps docs/migrations/legacy/app-0.1.5/shift_schedula-0.1.5-py3-none-any.whl
```

baseだけを確認する場合は別venvへ `base-requirements.txt` をsyncして0.1.6 wheelを導入する。
Windowsでは `/tmp` を新規の一時ディレクトリへ、`bin/python` を `Scripts/python.exe` へ置き換える。
Python3.14.8とuv0.12.23、requirementsに記載した配布元への接続が必要。
lockを保存したことは全依存wheelのオフライン保管を意味しない。

アプリbackendの再検証は固定archiveを新しいディレクトリへ展開する。

```sh
mkdir /tmp/schedula-legacy-app-source
tar -xzf docs/migrations/legacy/app-0.1.5/backend-source.tar.gz -C /tmp/schedula-legacy-app-source
mkdir -p /tmp/schedula-legacy-app-source/vendor/schedula
cp docs/migrations/legacy/app-0.1.5/vendor-manifest.json /tmp/schedula-legacy-app-source/vendor/schedula/manifest.json
cp docs/migrations/legacy/app-0.1.5/shift_schedula-0.1.5-py3-none-any.whl /tmp/schedula-legacy-app-source/vendor/schedula/
/tmp/schedula-legacy-app/bin/python /tmp/schedula-legacy-app-source/backend/check_saved.py docs/migrations/legacy/app-0.1.5/representative.json
```

`restorable: true`、plans=2、engine_version=0.1.5/schema_version=0.10が期待値。
復旧試験では `storage_admin.py` のbackup/restoreを使用し、SQLite本体だけを稼働中にコピーしない。
representative.sqlite3は原本として読取専用で扱い、実行用には新しい700の専用ディレクトリへ
600のファイルとしてコピーする。格納時のGit modeは実行時のアクセス権を保証しない。

## 期待値と利用範囲

2026-10-09のmacOS ARM64隔離導入では、0.1.6の完全assignment、不足assignment、
0.15の結合条件、Adapterの実行記録と再検証が成功した。
アプリ0.1.5では旧restoreによる完全/PARTIALの再検証、証明false、JSON原本非変更、
SQLiteのquick_check・外部キー・件数、保存archiveからのcheck_savedと別ディレクトリへのrestore_backupを確認した。
新0.15への変換・新pinでの保存往復・実Chromium受け入れは #109/#125/#115の後続作業である。
合成代表の成功を顧客実データの移行完了としない。
