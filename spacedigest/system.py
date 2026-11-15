"""
Связь с системой: уведомления и запуск вместе с компьютером.

Без сторонних библиотек: Windows — всплывающее уведомление через PowerShell (Windows 10/11)
и ключ автозапуска в реестре пользователя; macOS — osascript и LaunchAgent; Linux — notify-send
и ~/.config/autostart.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)
APP_ID = "SpaceDigest"


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def notify(title: str, text: str) -> bool:
    """Системное уведомление. Ошибки не мешают работе — возвращаем False."""
    title, text = title[:120], text[:400]
    try:
        if sys.platform == "win32":
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
                "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
                "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                "$x = $t.GetElementsByTagName('text');"
                f"$x.Item(0).AppendChild($t.CreateTextNode({_ps_quote(title)})) > $null;"
                f"$x.Item(1).AppendChild($t.CreateTextNode({_ps_quote(text)})) > $null;"
                "$n = [Windows.UI.Notifications.ToastNotification]::new($t);"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
                "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($n)")
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                             creationflags=0x08000000)                       # CREATE_NO_WINDOW
        elif sys.platform == "darwin":
            esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')       # noqa: E731
            subprocess.Popen(["osascript", "-e", f'display notification "{esc(text)}" with title "{esc(title)}"'])
        else:
            subprocess.Popen(["notify-send", "-a", "Space Digest", title, text])
        return True
    except Exception as e:                                                   # noqa: BLE001
        log.info("Уведомление не показано: %s", e)
        return False


# ─── автозапуск ──────────────────────────────────────────────────────────────
def launch_command() -> list[str]:
    """Как запустить программу свёрнутой (собранная программа или исходники)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--minimized"]
    return [sys.executable, os.path.abspath(sys.argv[0]), "--minimized"]


def _mac_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.spacedigest.app.plist"


def _linux_desktop() -> Path:
    return Path.home() / ".config" / "autostart" / "space-digest.desktop"


def set_autostart(enabled: bool, cmd: list[str] | None = None) -> None:
    cmd = cmd or launch_command()
    if sys.platform == "win32":
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        try:
            if enabled:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, subprocess.list2cmdline(cmd))
            else:
                try:
                    winreg.DeleteValue(key, APP_ID)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
    elif sys.platform == "darwin":
        p = _mac_plist()
        if enabled:
            p.parent.mkdir(parents=True, exist_ok=True)
            args = "".join(f"<string>{a.replace('&', '&amp;').replace('<', '&lt;')}</string>" for a in cmd)
            p.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.spacedigest.app</string>
<key>ProgramArguments</key><array>{args}</array>
<key>RunAtLoad</key><true/>
</dict></plist>
""", encoding="utf-8")
        elif p.exists():
            p.unlink()
    else:
        p = _linux_desktop()
        if enabled:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("[Desktop Entry]\nType=Application\nName=Space Digest\n"
                         f"Exec={subprocess.list2cmdline(cmd)}\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")
        elif p.exists():
            p.unlink()


def autostart_enabled() -> bool:
    if sys.platform == "win32":
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")
            winreg.QueryValueEx(key, APP_ID)
            winreg.CloseKey(key)
            return True
        except OSError:
            return False
    return (_mac_plist() if sys.platform == "darwin" else _linux_desktop()).exists()
