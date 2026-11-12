"""Was die KI über abgelegte Dokumente herausgefunden hat: Fristen, Person, Steuer-Relevanz.

Gespeichert je Prüfsumme der abgelegten Datei (%APPDATA%\\Ordnungsliebe\\dokumente.json).
Die Dokumente selbst bleiben, wo sie sind – hier stehen nur Verweise.
"""

from __future__ import annotations

import datetime as _dt
import threading
import time
from pathlib import Path

from .. import jsonfile, paths


class DocMeta:
    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "dokumente.json")
        self._lock = threading.RLock()
        data = jsonfile.load(self.path, {})
        self.docs: dict[str, dict] = data.get("docs", {}) if isinstance(data, dict) else {}

    def _save(self) -> None:
        jsonfile.save(self.path, {"docs": self.docs})

    def record(self, sha: str, path: str, *, folder: str, summary: str = "", doc_date: str = "",
               deadlines: list[dict] | None = None, person: str = "", steuer: bool = False,
               entry_id: str = "") -> dict:
        if not sha:
            return {}
        with self._lock:
            old = self.docs.get(sha, {})
            done = {(d["date"], d["what"]) for d in old.get("deadlines", []) if d.get("done")}
            dls = [{"date": d["date"], "what": d["what"], "done": (d["date"], d["what"]) in done}
                   for d in (deadlines or [])]
            rec = {"path": path, "folder": folder, "summary": summary, "doc_date": doc_date,
                   "deadlines": dls, "person": person, "steuer": bool(steuer), "entry": entry_id,
                   "ts": time.time(), "collections": old.get("collections", [])}
            self.docs[sha] = rec
            self._save()
            return rec

    def get(self, sha: str) -> dict | None:
        with self._lock:
            rec = self.docs.get(sha)
            return dict(rec) if rec else None

    def find_path(self, path: str) -> tuple[str, dict] | None:
        with self._lock:
            for sha, rec in self.docs.items():
                if rec.get("path") == path:
                    return sha, dict(rec)
        return None

    def moved(self, old_path: str, new_path: str) -> None:
        with self._lock:
            for rec in self.docs.values():
                if rec.get("path") == old_path:
                    rec["path"] = new_path
                    self._save()
                    return

    def all(self) -> dict[str, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self.docs.items()}

    # --- Fristen ---------------------------------------------------------------------
    def deadlines(self, ahead_days: int = 60, overdue_days: int = 30, include_done: bool = False) -> list[dict]:
        today = _dt.date.today()
        out = []
        with self._lock:
            items = list(self.docs.items())
        for sha, rec in items:
            if not Path(rec.get("path", "")).exists():
                continue
            for i, d in enumerate(rec.get("deadlines", [])):
                if d.get("done") and not include_done:
                    continue
                try:
                    day = _dt.date.fromisoformat(d["date"])
                except (KeyError, ValueError):
                    continue
                delta = (day - today).days
                if delta > ahead_days or delta < -overdue_days:
                    continue
                out.append({"id": f"{sha}:{i}", "date": d["date"], "days": delta, "what": d["what"],
                            "done": bool(d.get("done")), "path": rec["path"], "name": Path(rec["path"]).name,
                            "summary": rec.get("summary", ""), "person": rec.get("person", "")})
        out.sort(key=lambda x: x["date"])
        return out

    def deadline(self, dl_id: str) -> dict | None:
        sha, _, idx = dl_id.rpartition(":")
        with self._lock:
            rec = self.docs.get(sha)
            try:
                d = rec["deadlines"][int(idx)] if rec else None
            except (IndexError, ValueError):
                d = None
            if d is None:
                return None
            return {"id": dl_id, **d, "path": rec["path"], "summary": rec.get("summary", "")}

    def set_done(self, dl_id: str, done: bool = True) -> bool:
        sha, _, idx = dl_id.rpartition(":")
        with self._lock:
            rec = self.docs.get(sha)
            try:
                rec["deadlines"][int(idx)]["done"] = bool(done)
            except (TypeError, KeyError, IndexError, ValueError):
                return False
            self._save()
            return True


def _ics_escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """ICS-Zeilen höchstens 75 Bytes lang (RFC 5545)."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 74:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n".join(out)


def make_ics(deadlines: list[dict]) -> str:
    """Kalenderdatei mit ganztägigen Terminen und einer Erinnerung zwei Tage vorher."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Ordnungsliebe//DE", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH"]
    for d in deadlines:
        day = _dt.date.fromisoformat(d["date"])
        nxt = day + _dt.timedelta(days=1)
        desc = " · ".join(x for x in (d.get("summary", ""), d.get("path", "")) if x)
        uid = d["id"].replace(":", "-") + "@ordnungsliebe"
        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{nxt.strftime('%Y%m%d')}",
                  f"SUMMARY:{_ics_escape(d['what'])}", f"DESCRIPTION:{_ics_escape(desc)}",
                  "TRANSP:TRANSPARENT",
                  "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(d['what'])}",
                  "TRIGGER:-P2D", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
