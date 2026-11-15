import json
import zipfile

import pytest

from spacedigest.core.db import Database
from spacedigest.services import maintenance as M


def _data_dir(tmp_path):
    d = tmp_path / "data"
    (d / "weeks" / "2026-W45").mkdir(parents=True)
    (d / "weeks" / "2026-W45" / "articles.json").write_text("[]", encoding="utf-8")
    (d / "telegram").mkdir()
    (d / "telegram" / "tg_session.session").write_text("secret", encoding="utf-8")
    (d / "webview").mkdir()
    (d / "webview" / "Cookies").write_text("chatgpt", encoding="utf-8")
    (d / "settings.json").write_text('{"export": {"dedup": true}}', encoding="utf-8")
    (d / "location.json").write_text("{}", encoding="utf-8")
    db = Database(d / M.DB_NAME)
    db.migrate()
    db.set_meta("marker", "old")
    return d, db


def test_backup_is_consistent_and_excludes_logins(tmp_path):
    d, db = _data_dir(tmp_path)
    z = M.make_backup(d, tmp_path / "b.zip", db.backup)
    names = set(zipfile.ZipFile(z).namelist())
    assert {M.DB_NAME, "settings.json", "weeks/2026-W45/articles.json", "backup.json"} <= names
    assert not any(n.endswith(".session") or n.startswith("webview") or n.endswith(("-wal", "-shm"))
                   or n == "location.json" for n in names)
    assert M.check_backup(z)["has_db"]


def test_restore_applies_on_next_start_and_keeps_old_data(tmp_path):
    d, db = _data_dir(tmp_path)
    z = M.make_backup(d, tmp_path / "b.zip", db.backup)
    db.set_meta("marker", "new"); db.close()
    (d / "settings.json").write_text('{"changed": 1}', encoding="utf-8")
    M.schedule_restore(d, z)
    aside = M.apply_pending_restore(d, log=lambda m: None)
    assert aside and aside.exists() and (aside / "settings.json").read_text(encoding="utf-8") == '{"changed": 1}'
    assert json.loads((d / "settings.json").read_text(encoding="utf-8")) == {"export": {"dedup": True}}
    assert Database(d / M.DB_NAME).get_meta("marker") == "old"
    assert (d / "telegram" / "tg_session.session").read_text(encoding="utf-8") == "secret"   # вход сохранён
    assert (d / "webview" / "Cookies").exists() and (d / "location.json").exists()
    assert not (d / M.PENDING).exists() and M.apply_pending_restore(d) is None


def test_restore_rejects_foreign_or_unsafe_archives(tmp_path):
    bad = tmp_path / "x.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("photo.jpg", "x")
    with pytest.raises(ValueError, match="не резервная копия"):
        M.check_backup(bad)
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../evil.txt", "x"); z.writestr("settings.json", "{}")
    with pytest.raises(ValueError, match="недопустимые"):
        M.check_backup(bad)
    (tmp_path / "n.zip").write_text("not zip")
    with pytest.raises(ValueError, match="ZIP"):
        M.check_backup(tmp_path / "n.zip")


class _Resp:
    def __init__(self, data, code=200):
        self._d, self.status_code = data, code

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


RELEASE = {"tag_name": "v4.1.0", "html_url": "https://github.com/o/r/releases/v4.1.0", "body": "Новое",
           "assets": [{"name": "SpaceDigest-Setup-4.1.0.exe", "browser_download_url": "https://github.com/o/r/a.exe"},
                      {"name": "SpaceDigest-4.1.0-mac-arm64.dmg", "browser_download_url": "https://github.com/o/r/arm.dmg"},
                      {"name": "SpaceDigest-4.1.0-mac-x86_64.dmg", "browser_download_url": "https://github.com/o/r/x.dmg"}]}


def test_update_check_and_asset_choice():
    calls = []
    res = M.check_update("https://github.com/o/r.git", "4.0.0",
                         http_get=lambda u: calls.append(u) or _Resp(RELEASE))
    assert calls == ["https://api.github.com/repos/o/r/releases/latest"]
    assert res["available"] and res["latest"] == "4.1.0" and res["notes"] == "Новое"
    assert not M.check_update("o/r", "4.1.0", http_get=lambda u: _Resp(RELEASE))["available"]
    a = RELEASE["assets"]
    assert M.platform_asset(a, "Windows", "AMD64")["name"].endswith(".exe")
    assert "arm64" in M.platform_asset(a, "Darwin", "arm64")["name"]
    assert "x86_64" in M.platform_asset(a, "Darwin", "x86_64")["name"]
    assert M.platform_asset(a, "Linux", "x86_64") is None
    with pytest.raises(ValueError, match="ещё нет"):
        M.check_update("o/r", "4.0.0", http_get=lambda u: _Resp({}, 404))
    with pytest.raises(ValueError, match="owner/name"):
        M.check_update("not a repo", "4.0.0", http_get=lambda u: _Resp({}))
    assert M.parse_version("v10.2") > M.parse_version("9.9.9")


def test_installer_download_only_from_github(tmp_path):
    with pytest.raises(ValueError, match="GitHub"):
        M.download_installer("https://evil.test/a.exe", "a.exe", tmp_path)
