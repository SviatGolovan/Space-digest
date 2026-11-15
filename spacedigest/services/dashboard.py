"""Данные для экрана «Обзор»: что собрано, что сломалось, что с выгрузками."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..core.scheduler import MSK
from ..core.timeutil import from_iso, iso_after

DAYS = 14
SILENT_DAYS = 5          # источник «замолчал», если новых публикаций нет столько дней


def _msk_today() -> datetime:
    return datetime.now(timezone.utc).astimezone(MSK).replace(hour=0, minute=0, second=0, microsecond=0)


def overview(core) -> dict:
    db = core.db
    today = _msk_today()
    start = today - timedelta(days=DAYS - 1)
    # публикации по дням (по Москве) за 14 дней
    rows = db.query("""
        SELECT date(COALESCE(i.published_at, i.fetched_at), '+3 hours') AS d, s.kind AS kind, COUNT(*) AS n
        FROM items i JOIN sources s ON s.id = i.source_id
        WHERE i.origin IN ('collect', 'import30') AND COALESCE(i.published_at, i.fetched_at) >= ?
        GROUP BY d, kind""", (start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),))
    days = [(start + timedelta(days=k)).strftime("%Y-%m-%d") for k in range(DAYS)]
    series = {"rss": [0] * DAYS, "telegram": [0] * DAYS}
    for r in rows:
        if r["d"] in days and r["kind"] in series:
            series[r["kind"]][days.index(r["d"])] = r["n"]

    # источники: ошибки и «замолчавшие»
    problems, active = [], {"rss": 0, "telegram": 0}
    silent_border = (datetime.now(timezone.utc) - timedelta(days=SILENT_DAYS))
    for h in core.sources.health():
        if not h["enabled"] or h["kind"] not in active:
            continue
        active[h["kind"]] += 1
        last = from_iso(h["last_item_at"]) if h["last_item_at"] else None
        if h["problem"]:
            problems.append({"id": h["id"], "name": h["name"], "kind": h["kind"], "why": "error",
                             "text": (h["last_error"] or "ошибка сбора")[:140], "since": h["last_ok_at"]})
        elif h["items_total"] and last and last < silent_border:
            problems.append({"id": h["id"], "name": h["name"], "kind": h["kind"], "why": "silent",
                             "text": f"нет новых публикаций {(datetime.now(timezone.utc) - last).days} дн.",
                             "since": h["last_item_at"]})
    problems.sort(key=lambda p: (p["why"] != "error", p["name"].lower()))

    # топ источников за сегодня
    top = db.query("""
        SELECT s.name, s.kind, COUNT(*) AS n FROM items i JOIN sources s ON s.id = i.source_id
        WHERE i.origin = 'collect' AND COALESCE(i.published_at, i.fetched_at) >= ?
        GROUP BY s.id ORDER BY n DESC LIMIT 6""", (today.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),))

    # выгрузки
    exports = []
    for e in core.exports.list(limit=4):
        exports.append({"id": e["id"], "created_at": e["created_at"], "rows": e["items_exported"],
                        "period_from": e["period_from"], "period_to": e["period_to"],
                        "docx": bool(e.get("result_file"))})
    try:
        pv = core.exports.preview(mode="since_last")
        pending = {"total": pv["total"] - pv.get("filtered", 0), "filtered": pv.get("filtered", 0),
                   "by_kind": pv.get("by_kind", {})}
    except Exception:                                                        # noqa: BLE001
        pending = {"total": 0, "filtered": 0, "by_kind": {}}

    filtered_week = db.scalar("""
        SELECT COUNT(*) FROM export_items ei JOIN exports e ON e.id = ei.export_id
        WHERE ei.state = 'filtered' AND e.created_at >= ?""", (iso_after(minutes=-7 * 1440),)) or 0
    last_collect = db.scalar("SELECT MAX(fetched_at) FROM items WHERE origin = 'collect'")
    morning = core.morning_status()
    if morning.get("last") and isinstance(morning["last"], str):
        morning["last"] = json.loads(morning["last"])

    return {
        "now_msk": datetime.now(timezone.utc).astimezone(MSK).strftime("%Y-%m-%dT%H:%M"),
        "today": {"rss": series["rss"][-1], "telegram": series["telegram"][-1],
                  "yesterday": series["rss"][-2] + series["telegram"][-2]},
        "chart": {"days": days, "rss": series["rss"], "telegram": series["telegram"]},
        "sources": {"active": active, "problems": problems[:8], "problems_total": len(problems)},
        "top": top, "exports": exports, "pending": pending,
        "filtered_week": int(filtered_week), "fulltext": core.fulltext.stats(),
        "last_collect": last_collect, "morning": morning,
    }

