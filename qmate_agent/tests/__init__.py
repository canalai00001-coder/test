"""試験の共通の準備。どこで走らせても、本物のスプレッドシート・設定・記録には触らない。

- config/ は一時フォルダに写した settings.json・rules.json だけを読む
  （実行フォルダの settings.local.json で「入寮はツールで作る」などに変わっていても、試験の結果が変わらない）
- state/・output/ も一時フォルダにする
- 本物の Google スプレッドシートには接続させない（接続しようとしたら止める）
- gspread は環境変数を消す試験より先に読み込んでおく（読み込みのときに APPDATA を読むため）
"""
import atexit
import shutil
import tempfile
from pathlib import Path

from qmate_agent import config

_tmp = Path(tempfile.mkdtemp(prefix="qmate_test_"))
atexit.register(shutil.rmtree, _tmp, True)
(_tmp / "config").mkdir()
for _name in ("settings.json", "rules.json"):
    shutil.copy(config.CONFIG_DIR / _name, _tmp / "config" / _name)
config.CONFIG_DIR = _tmp / "config"
config.STATE_DIR = _tmp / "state"
config.OUTPUT_DIR = _tmp / "output"

try:
    import gspread
except ImportError:  # gspread が無い環境でも、使わない試験は走らせる
    gspread = None
else:
    def _refuse(*args, **kwargs):
        raise RuntimeError("試験から本物の Google スプレッドシートには接続しません")

    gspread.service_account = _refuse
    gspread.service_account_from_dict = _refuse
    gspread.oauth = _refuse
