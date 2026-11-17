"""
Space Digest — точка входа настольного приложения.

Запускает встроенный веб-сервер на свободном порту 127.0.0.1 и показывает интерфейс
в родном окне (Windows — WebView2/Edge, macOS — WebKit) с обычным меню:
«Настройки…» (Ctrl+, / ⌘,), «Перейти», «Вид», «Справка».

Параметры запуска (для разработки):
    python main.py              — окно приложения
    python main.py --browser    — открыть в обычном браузере
    python main.py --server     — только сервер (без окна и браузера)
    python main.py --port 5001  — фиксированный порт
    python main.py --data DIR   — другая папка данных
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def _fix_std_streams(log_dir: Path) -> None:
    """В оконной сборке stdout/stderr = None — направляем их в лог-файл."""
    if sys.stdout is None or sys.stderr is None:
        f = open(log_dir / "app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def _running_instance(runtime_file: Path) -> str | None:
    """Если приложение уже запущено — вернуть его адрес."""
    try:
        info = json.loads(runtime_file.read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{int(info['port'])}"
        with urllib.request.urlopen(url + "/api/app/info", timeout=1.5) as r:
            if r.status == 200:
                return url
    except Exception:
        pass
    return None


def start_server(port: int):
    from werkzeug.serving import make_server
    from spacedigest import webapp
    srv = make_server("127.0.0.1", port, webapp.app, threaded=True)
    threading.Thread(target=srv.serve_forever, name="http", daemon=True).start()
    return srv, srv.server_port


# ─── Мост JS ↔ Python для окна (диалоги выбора/сохранения файлов) ─────────────

class WindowApi:
    def __init__(self, base_url: str):
        self._base = base_url
        self._window = None
        self._chat = None                       # окно ChatGPT (создаётся по требованию)
        self._last_dir = str(Path.home() / "Downloads") if (Path.home() / "Downloads").exists() \
            else str(Path.home())

    def _dlg(self, kind, **kw):
        res = self._window.create_file_dialog(kind, **kw)
        if not res:
            return None
        return res if isinstance(res, str) else res[0]

    def pick_folder(self):
        import webview
        return self._dlg(webview.FileDialog.FOLDER, directory=str(Path.home()))

    def pick_file(self, kind: str = "any"):
        import webview
        types = {"db": ("База Telegram (*.db)", "Все файлы (*.*)"),
                 "csv": ("CSV (*.csv)", "Все файлы (*.*)")}.get(kind, ("Все файлы (*.*)",))
        return self._dlg(webview.FileDialog.OPEN, directory=str(Path.home()), file_types=types)

    def save_url(self, path: str):
        """Скачать ответ сервера по относительному адресу и сохранить через системный диалог."""
        import webview
        try:
            with urllib.request.urlopen(self._base + path, timeout=600) as r:
                data = r.read()
                cd = r.headers.get("Content-Disposition", "")
            m = re.search(r'filename="?([^";]+)"?', cd)
            name = m.group(1) if m else "export.bin"
            target = self._dlg(webview.FileDialog.SAVE, directory=self._last_dir, save_filename=name)
            if not target:
                return {"ok": False, "cancelled": True}
            Path(target).write_bytes(data)
            self._last_dir = str(Path(target).parent)
            return {"ok": True, "path": target}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    def reveal(self, path: str):
        from spacedigest.paths import open_in_file_manager
        p = Path(path)
        open_in_file_manager(p.parent if p.is_file() else p)
        return True

    def open_external(self, url: str):
        webbrowser.open(url)
        return True

    def copy_text(self, text: str):
        from spacedigest.paths import copy_to_clipboard
        return copy_to_clipboard(text)

    def open_chatgpt(self, url: str = ""):
        """ChatGPT в отдельном окне программы: вход запоминается, загрузка DOCX разрешена."""
        import webview
        from spacedigest import webapp
        url = url or webapp.settings.get("export", "chatgpt_url") or "https://chatgpt.com/"
        if not webapp.settings.get("export", "chatgpt_in_app"):
            webbrowser.open(url)
            return "browser"
        if self._chat is not None:
            try:
                self._chat.show()
                self._chat.restore()
                return "focused"
            except Exception:
                self._chat = None
        self._chat = webview.create_window("ChatGPT — Space Digest", url, width=1120, height=900,
                                           min_size=(800, 600), text_select=True)

        def closed():
            self._chat = None
        self._chat.events.closed += closed
        return "opened"


def _mac_add_settings_item(open_settings) -> None:
    """macOS: «Настройки…» с ⌘, в меню приложения — как в обычных программах."""
    try:
        import objc                                  # noqa: F401
        from AppKit import NSApp, NSMenuItem
        from Foundation import NSObject
        from PyObjCTools import AppHelper

        class _Target(NSObject):
            def openSettings_(self, _sender):
                open_settings()

        def add():
            menu = NSApp.mainMenu()
            if menu is None or menu.numberOfItems() == 0:
                return
            app_menu = menu.itemAtIndex_(0).submenu()
            if app_menu.indexOfItemWithTitle_("Настройки…") >= 0:
                return
            target = _Target.alloc().init()
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Настройки…", "openSettings:", ",")
            item.setTarget_(target)
            app_menu.insertItem_atIndex_(NSMenuItem.separatorItem(), 1)
            app_menu.insertItem_atIndex_(item, 2)
            _mac_add_settings_item._keep = target    # не дать сборщику мусора удалить
        AppHelper.callAfter(add)
    except Exception as e:                           # меню — приятный бонус, не критично
        logging.warning("mac menu: %s", e)


def run_window(base_url: str, start_page: str, on_close, minimized: bool = False) -> bool:
    """Показать окно. False — если встроенный движок недоступен (тогда откроем браузер)."""
    try:
        import webview
        from webview.menu import Menu, MenuAction, MenuSeparator
    except Exception as e:
        logging.warning("pywebview недоступен: %s", e)
        return False

    from spacedigest import APP_NAME
    api = WindowApi(base_url)
    win = webview.create_window(APP_NAME, base_url + start_page, js_api=api,
                                width=1480, height=940, min_size=(1100, 700),
                                text_select=True, minimized=minimized)
    api._window = win

    def go(p):
        return lambda: win.load_url(base_url + p)

    def open_data():
        from spacedigest import webapp
        from spacedigest.paths import open_in_file_manager
        open_in_file_manager(webapp.DATA_DIR)

    is_mac = sys.platform == "darwin"
    file_items = [MenuAction("Выгрузка для ChatGPT", go("/export")),
                  MenuAction("Открыть ChatGPT", lambda: api.open_chatgpt()),
                  MenuSeparator(),
                  MenuAction("Настройки…  (Ctrl+,)", go("/settings")),
                  MenuSeparator(),
                  MenuAction("Открыть папку данных", open_data)]
    if not is_mac:
        file_items += [MenuSeparator(), MenuAction("Выход", win.destroy)]
    menu = [
        Menu("Файл", file_items),
        Menu("Перейти", [MenuAction("Обзор", go("/home")), MenuAction("Выгрузка", go("/export")),
                         MenuAction("Сайты", go("/")),
                         MenuAction("Telegram", go("/tg")),
                         MenuAction("Дедупликатор", go("/dedup"))]),
        Menu("Вид", [MenuAction("Обновить страницу", lambda: win.evaluate_js("location.reload()")),
                     MenuAction("Открыть в браузере", lambda: webbrowser.open(base_url))]),
        Menu("Справка", [MenuAction("О программе", go("/settings#about")),
                         MenuAction("Где мои данные", go("/settings#data"))]),
    ]
    if is_mac:                                   # «Настройки…» уходят в меню приложения
        menu[0] = Menu("Файл", [i for i in file_items if getattr(i, "title", "") != "Настройки…  (Ctrl+,)"])
    win.events.closed += on_close

    def close_chat():                                # главное окно закрыто → закрыть и ChatGPT
        if api._chat is not None:
            try:
                api._chat.destroy()
            except Exception:
                pass
    win.events.closed += close_chat

    def quit_watch():                                # «Выход» из интерфейса / установка обновления
        from spacedigest import webapp
        webapp.QUIT.wait()
        try:
            close_chat(); win.destroy()
        except Exception:
            pass
    threading.Thread(target=quit_watch, daemon=True, name="quit-watch").start()
    # Загрузки (DOCX из ChatGPT) — через обычный диалог «Сохранить»
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:
        pass
    try:
        webview.start(lambda: _mac_add_settings_item(go("/settings")) if is_mac else None,
                      menu=menu, private_mode=False,
                      storage_path=str(Path(os.environ["SPACEDIGEST_DATA_RESOLVED"]) / "webview"))
    except Exception as e:
        logging.exception("Окно не запустилось: %s", e)
        return False
    return True


def _wait_pid(pid: int, timeout: float = 30.0) -> None:
    """Перезапуск: дождаться, пока прежний процесс закроется (иначе сработает «уже запущено»)."""
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, pid)          # SYNCHRONIZE
        if h:
            k.WaitForSingleObject(h, int(timeout * 1000))
            k.CloseHandle(h)
        return
    end = time.time() + timeout
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.3)


def selftest() -> int:
    """Проверка установщика в CI: встроенная модель сюжетов и движок склейки работают."""
    os.environ["SPACEDIGEST_NO_MODEL_DOWNLOAD"] = "1"        # проверяем именно встроенную модель
    lines, ok = [], True
    try:
        from spacedigest import story_model
        v = story_model.encode(["SpaceX catches Starship with the tower",
                                "SpaceX поймала корабль Starship башней", "Курс рубля вырос"])
        same, other = float(v[0] @ v[1]), float(v[0] @ v[2])
        lines.append(f"story model: same={same:.3f} other={other:.3f} dir={story_model.model_dir()}")
        ok &= same > other + 0.03
    except Exception as e:                                       # noqa: BLE001
        lines.append(f"story model: FAIL {e!r}")
        ok = False
    try:
        from spacedigest import deduplicator
        lines.append(f"fastembed available: {deduplicator.neural_available()}")
        ok &= deduplicator.neural_available()
    except Exception as e:                                       # noqa: BLE001
        lines.append(f"fastembed: FAIL {e!r}")
        ok = False
    text = "\n".join(lines + ["SELFTEST " + ("OK" if ok else "FAILED")])
    print(text)
    try:
        (Path(os.environ.get("SPACEDIGEST_DATA") or ".") / "selftest.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass
    return 0 if ok else 1


def main() -> None:
    # Окно и фоновые задачи живут в одном процессе. Короткий интервал переключения потоков
    # не даёт сбору и разбору новостей надолго занимать интерпретатор, пока окно
    # перетаскивают или прокручивают.
    sys.setswitchinterval(0.001)
    wait = os.environ.pop("SPACEDIGEST_WAIT_PID", "")
    if wait.isdigit():
        _wait_pid(int(wait))
    ap = argparse.ArgumentParser(description="Space Digest")
    ap.add_argument("--browser", action="store_true", help="открыть в браузере вместо окна")
    ap.add_argument("--server", action="store_true", help="только сервер")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--data", default="")
    ap.add_argument("--minimized", action="store_true", help="запуск вместе с компьютером: окно свёрнуто")
    ap.add_argument("--selftest", action="store_true",
                    help="проверка сборки: модели дедупликации считаются (код выхода 0 — всё в порядке)")
    args, _ = ap.parse_known_args()                  # macOS может передать -psn_…
    if args.data:
        os.environ["SPACEDIGEST_DATA"] = args.data
    if args.selftest:
        sys.exit(selftest())

    from spacedigest import paths
    data_dir = paths.data_dir()
    os.environ["SPACEDIGEST_DATA_RESOLVED"] = str(data_dir)
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _fix_std_streams(log_dir)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(log_dir / "app.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stderr)])
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.ERROR)      # повторы запросов — шум в журнале

    from spacedigest.settings import Settings
    prefs = Settings(data_dir / "settings.json").get("general")
    use_browser = args.browser or prefs.get("open_in") == "browser"
    start_page = prefs.get("start_page") or "/"
    if not prefs.get("first_run_done"):
        start_page = "/settings#welcome"

    runtime = data_dir / "runtime.json"
    existing = _running_instance(runtime)
    if existing and not args.server:
        # Уже запущено: открываем ещё одно окно/вкладку к тому же серверу
        if use_browser or not run_window(existing, "/", lambda: None):
            webbrowser.open(existing)
        return

    from spacedigest import webapp
    webapp.init(data_dir)
    srv, port = start_server(args.port)
    base = f"http://127.0.0.1:{port}"
    runtime.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    logging.info("Space Digest запущен: %s (данные: %s)", base, data_dir)

    stop = threading.Event()

    def shutdown(*_):
        stop.set()

    if args.server:
        print(f"Сервер: {base}", flush=True)
    elif use_browser or not run_window(base, start_page, shutdown, minimized=args.minimized):
        webbrowser.open(base + start_page)
    else:
        stop.set()                                   # окно закрыто → выходим

    try:
        while not stop.is_set() and not webapp.QUIT.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    try:
        if webapp.core is not None:
            webapp.core.stop()
    except Exception:
        pass
    try:
        webapp.tg.shutdown()
    except Exception:
        pass
    srv.shutdown()
    try:
        runtime.unlink()
    except Exception:
        pass


if __name__ == "__main__":
    main()
