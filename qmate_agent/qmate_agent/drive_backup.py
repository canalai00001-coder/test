"""入稿した原稿の CSV を、Google ドライブ（共有ドライブ）のフォルダにバックアップする。

settings.json の drive_backup.folder に保存先フォルダの URL（または ID）を入れると動く。空欄なら何もしない。
保存先の中に「年-月」（例 2026-11）のフォルダを作り、その中に CSV をそのままの名前で置く。

- サービスアカウントの鍵には自分の保存容量が無い（0 バイト）。マイドライブのフォルダには置けないので、
  共有ドライブのフォルダにし、鍵のメールアドレスを共有ドライブのメンバー（コンテンツ管理者）に入れる。
- 保存に失敗しても入稿は止めない。失敗は state/drive_backup.json に残り、drive-backup --retry で送り直せる。
"""
import json
import re
import threading
from datetime import datetime
from pathlib import Path

from . import config

API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER = "application/vnd.google-apps.folder"
STATE = "drive_backup.json"
_LOCK = threading.Lock()


def folder_id(text: str) -> str:
    """フォルダの URL か ID から ID を取り出す。"""
    text = (text or "").strip()
    m = re.search(r"/folders/([\w-]+)", text) or re.search(r"[?&]id=([\w-]+)", text)
    return m.group(1) if m else text


def _session(settings: dict):
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(str(config.ROOT / settings["service_account_file"]),
                                                  scopes=["https://www.googleapis.com/auth/drive"])
    return AuthorizedSession(creds)


def _check(r, what: str):
    if r.status_code >= 400:
        text = r.text
        if "storageQuotaExceeded" in text or "do not have storage quota" in text:
            raise RuntimeError("保存先が共有ドライブではありません（ツールの鍵はマイドライブに保存できません）。"
                               "共有ドライブのフォルダを指定してください")
        if r.status_code == 404:
            raise RuntimeError("保存先のフォルダが見つかりません。フォルダの URL と、ツールの鍵のメールアドレスが"
                               "共有ドライブのメンバーに入っているかを確かめてください")
        raise RuntimeError(f"{what}に失敗しました（{r.status_code}）: {text[:300]}")
    return r.json()


def _subfolder(s, parent: str, name: str) -> str:
    """parent の中の name フォルダの ID（無ければ作る）。"""
    q = f"'{parent}' in parents and name = '{name}' and mimeType = '{FOLDER}' and trashed = false"
    found = _check(s.get(API, params={"q": q, "fields": "files(id)", "supportsAllDrives": "true",
                                      "includeItemsFromAllDrives": "true", "corpora": "allDrives"}),
                   "フォルダの検索")["files"]
    if found:
        return found[0]["id"]
    return _check(s.post(API, params={"supportsAllDrives": "true", "fields": "id"},
                         json={"name": name, "mimeType": FOLDER, "parents": [parent]}), "フォルダの作成")["id"]


def _upload(s, parent: str, path: Path) -> dict:
    boundary = "qmate_backup_boundary"
    meta = json.dumps({"name": path.name, "parents": [parent]}, ensure_ascii=False)
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: text/csv\r\n\r\n").encode("utf-8") + path.read_bytes() \
        + f"\r\n--{boundary}--\r\n".encode("utf-8")
    r = s.post(UPLOAD, params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,webViewLink"},
               data=body, headers={"Content-Type": f"multipart/related; boundary={boundary}"})
    return _check(r, "アップロード")


def _record(entries: dict) -> None:
    path = config.STATE_DIR / STATE
    with _LOCK:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data.update(entries)
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def enabled(settings: dict) -> bool:
    return bool(folder_id((settings.get("drive_backup") or {}).get("folder", "")))


def backup(paths, settings: dict, log=print, when: datetime | None = None) -> list[str]:
    """CSV を保存先へ送る。送れたファイルのリンクを返す。失敗しても例外は出さず、記録して知らせる。"""
    paths = [Path(p) for p in paths]
    if not paths or not enabled(settings):
        return []
    root = folder_id(settings["drive_backup"]["folder"])
    month = (when or datetime.now()).strftime("%Y-%m")
    links, done = [], {}
    try:
        s = _session(settings)
        with _LOCK:  # 同時に動いたときに同じ月のフォルダを2つ作らない
            parent = _subfolder(s, root, month)
        for p in paths:
            f = _upload(s, parent, p)
            links.append(f.get("webViewLink", ""))
            done[str(p)] = {"at": datetime.now().isoformat(timespec="seconds"), "id": f["id"], "folder": month}
        log(f"原稿を Google ドライブに保存しました（{month} フォルダ・{len(paths)}ファイル）")
    except Exception as e:
        for p in paths:
            if str(p) not in done:
                done[str(p)] = {"at": datetime.now().isoformat(timespec="seconds"), "error": str(e)}
        log(f"（原稿を Google ドライブに保存できませんでした：{e}。入稿はそのまま続けます。"
            "あとで drive-backup --retry で送り直せます）")
    _record(done)
    return links


def check_folder(settings: dict) -> str:
    """保存先に届くかを確かめて、フォルダ名を返す（共有ドライブでなければ例外）。"""
    fid = folder_id((settings.get("drive_backup") or {}).get("folder", ""))
    if not fid:
        raise RuntimeError("settings の drive_backup.folder に保存先フォルダの URL が入っていません")
    f = _check(_session(settings).get(f"{API}/{fid}", params={"fields": "name,driveId,mimeType",
                                                               "supportsAllDrives": "true"}), "フォルダの確認")
    if f.get("mimeType") != FOLDER:
        raise RuntimeError("指定した URL はフォルダではありません")
    if not f.get("driveId"):
        raise RuntimeError(f"「{f['name']}」はマイドライブのフォルダです。ツールの鍵はマイドライブに保存できないので、"
                           "共有ドライブのフォルダを指定してください")
    return f["name"]


def failed() -> list[str]:
    path = config.STATE_DIR / STATE
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return [k for k, v in data.items() if "error" in v and Path(k).exists()]
