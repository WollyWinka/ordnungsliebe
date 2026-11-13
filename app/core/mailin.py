"""Mails aus einem eigenen Ablage-Postfach abholen (IMAP).

- Nur solange Ordnungsliebe geöffnet ist, alle paar Minuten.
- Nur Mails von freigegebenen Absendern; andere bleiben unberührt im Postfach liegen und
  werden in den Einstellungen zum Freigeben angezeigt.
- Abgeholte Mails landen als .eml im Scan-Ordner und werden im Postfach in den Ordner
  „Abgelegt“ verschoben – gelöscht wird nichts.
- Das Passwort wird mit Windows verschlüsselt gespeichert (nur dieser Benutzer kann es lesen).
"""

from __future__ import annotations

import base64
import email
import email.policy
import imaplib
import logging
import os
import re
import socket
import ssl
import threading
import time
from email.utils import parseaddr
from pathlib import Path

from .. import jsonfile, paths
from . import naming

log = logging.getLogger(__name__)

DONE_FOLDER = "Abgelegt"
MAX_SIZE = 60 * 1024 * 1024

PROVIDERS = {
    "gmx.de": ("imap.gmx.net", "gmx"), "gmx.net": ("imap.gmx.net", "gmx"), "gmx.at": ("imap.gmx.net", "gmx"),
    "gmx.ch": ("imap.gmx.net", "gmx"), "web.de": ("imap.web.de", "webde"),
    "gmail.com": ("imap.gmail.com", "gmail"), "googlemail.com": ("imap.gmail.com", "gmail"),
    "icloud.com": ("imap.mail.me.com", "icloud"), "me.com": ("imap.mail.me.com", "icloud"),
    "mac.com": ("imap.mail.me.com", "icloud"), "t-online.de": ("secureimap.t-online.de", "tonline"),
    "posteo.de": ("posteo.de", "posteo"), "posteo.net": ("posteo.de", "posteo"),
    "mailbox.org": ("imap.mailbox.org", "mailbox"), "freenet.de": ("mx.freenet.de", "freenet"),
    "outlook.com": ("", "microsoft"), "outlook.de": ("", "microsoft"), "hotmail.com": ("", "microsoft"),
    "hotmail.de": ("", "microsoft"), "live.com": ("", "microsoft"), "live.de": ("", "microsoft"),
    "msn.com": ("", "microsoft"),
}

HINTS = {
    "gmx": "Bei GMX musst du einmal erlauben, dass Programme die Mails abholen dürfen: im GMX-Postfach unter "
           "„Einstellungen“ → „POP3 & IMAP“ den Haken bei „POP3 und IMAP Zugriff erlauben“ setzen. "
           "Als Passwort nimmst du dein normales GMX-Passwort.",
    "webde": "Bei WEB.DE musst du einmal erlauben, dass Programme die Mails abholen dürfen: im Postfach unter "
             "„Einstellungen“ → „POP3 & IMAP“ den Zugriff erlauben. Als Passwort nimmst du dein WEB.DE-Passwort.",
    "gmail": "Google lässt Programme nur mit einem App-Passwort hinein. Dafür muss im Google-Konto die "
             "Bestätigung in zwei Schritten eingeschaltet sein; dann unter „Sicherheit“ → „App-Passwörter“ "
             "ein Passwort für „Ordnungsliebe“ erstellen und hier eintragen.",
    "icloud": "Apple verlangt ein app-spezifisches Passwort: auf account.apple.com unter „Anmelden und Sicherheit“ "
              "→ „App-spezifische Passwörter“ eines erstellen und hier eintragen.",
    "tonline": "Bei Telekom-Adressen brauchst du das E-Mail-Passwort (nicht das Kundencenter-Passwort). "
               "Du legst es im Telekom-Kundencenter unter E-Mail-Einstellungen fest.",
    "microsoft": "Private Outlook-/Hotmail-Adressen lassen keine Programme mehr mit Passwort hinein. "
                 "Bitte lege für die Ablage eine kostenlose Adresse bei GMX oder WEB.DE an.",
    "": "Trage das Passwort deines Postfachs ein. Den Servernamen findest du in der Hilfe deines Anbieters "
        "(Stichwort „IMAP-Server“).",
}


def provider_for(address: str) -> dict:
    domain = (address or "").rsplit("@", 1)[-1].strip().lower()
    host, key = PROVIDERS.get(domain, ("", ""))
    return {"host": host, "key": key, "hint": HINTS.get(key, HINTS[""]), "supported": key != "microsoft"}


# --- Passwort sicher speichern ---------------------------------------------------------

def _protect(data: bytes) -> str:
    if paths.IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        buf = ctypes.create_string_buffer(data, len(data))
        inp = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(inp), "Ordnungsliebe", None, None, None, 0x1,
                                                      ctypes.byref(out)):
            raise OSError("Passwort konnte nicht verschlüsselt werden.")
        try:
            return "dpapi:" + base64.b64encode(ctypes.string_at(out.pbData, out.cbData)).decode()
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)
    return "plain:" + base64.b64encode(data).decode()  # nur Entwicklung/Tests


def _unprotect(token: str) -> bytes:
    kind, _, raw = (token or "").partition(":")
    data = base64.b64decode(raw or "")
    if kind == "dpapi" and paths.IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        buf = ctypes.create_string_buffer(data, len(data))
        inp = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0x1,
                                                        ctypes.byref(out)):
            raise OSError("Passwort konnte nicht entschlüsselt werden.")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)
    if kind == "plain":
        return data
    raise OSError("Passwort nicht lesbar.")


class MailError(ValueError):
    pass


def _connect(host: str, port: int, user: str, password: str) -> imaplib.IMAP4_SSL:
    if not host:
        raise MailError("Für diese Adresse kenne ich den Mail-Server nicht.")
    try:
        conn = imaplib.IMAP4_SSL(host, int(port or 993), ssl_context=ssl.create_default_context(), timeout=30)
    except (socket.gaierror, OSError) as exc:
        raise MailError("Der Mail-Server ist nicht erreichbar. Bist du mit dem Internet verbunden?") from exc
    try:
        conn.login(user, password)
    except imaplib.IMAP4.error as exc:
        try:
            conn.logout()
        except Exception:
            pass
        raise MailError("Die Anmeldung wurde abgelehnt. Stimmen Adresse und Passwort – und ist der "
                        "Zugriff für Programme (IMAP) erlaubt?") from exc
    return conn


def _quote(folder: str) -> str:
    return '"' + folder.replace('"', "") + '"'


class MailFetcher:
    def __init__(self, settings_store, bus, inbox_dir):
        self.settings_store = settings_store
        self.bus = bus
        self.inbox_dir = inbox_dir  # Funktion → Path | None
        self.secret_file = paths.data_dir() / "mailzugang.json"
        self.state_file = paths.local_dir() / "mailabruf.json"
        self.state = jsonfile.load(self.state_file, {})
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # --- Einstellungen ------------------------------------------------------------------
    def config(self) -> dict:
        st = self.settings_store.get()
        ex = st.extra.get("mail", {}) if isinstance(st.extra, dict) else {}
        return {"enabled": bool(ex.get("enabled")), "address": ex.get("address", ""), "host": ex.get("host", ""),
                "port": int(ex.get("port") or 993), "senders": list(ex.get("senders", [])),
                "interval": int(ex.get("interval") or 5)}

    def public(self) -> dict:
        c = self.config()
        s = self.state
        return {**c, "has_password": self.secret_file.exists(), "provider": provider_for(c["address"]),
                "last_check": s.get("last_check", 0), "last_ok": s.get("last_ok", 0), "error": s.get("error", ""),
                "imported": s.get("imported", 0), "unknown": s.get("unknown", [])[:6], "busy": self._lock.locked()}

    def _password(self) -> str:
        data = jsonfile.load(self.secret_file, {})
        return _unprotect(data.get("password", "")).decode("utf-8")

    def save(self, address: str, password: str | None, senders: list[str], host: str = "", port: int = 993,
             enabled: bool = True) -> dict:
        address = (address or "").strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", address):
            raise ValueError("Bitte eine gültige Mailadresse eintragen.")
        prov = provider_for(address)
        if not prov["supported"]:
            raise ValueError(prov["hint"])
        host = (host or prov["host"]).strip()
        clean = []
        for x in senders or []:
            a = parseaddr(str(x))[1].strip().lower()
            if a and "@" in a and a not in clean and a != address.lower():
                clean.append(a)
        if enabled and not clean:
            raise ValueError("Bitte mindestens eine Absender-Adresse eintragen (die Adresse, von der du weiterleitest).")
        if password:
            self.test(address, password, host, port)
            jsonfile.save(self.secret_file, {"password": _protect(password.encode("utf-8"))})
        elif not self.secret_file.exists():
            raise ValueError("Bitte das Passwort eintragen.")
        st = self.settings_store.get()
        extra = dict(st.extra or {})
        extra["mail"] = {"enabled": bool(enabled), "address": address, "host": host, "port": int(port or 993),
                         "senders": clean, "interval": 5}
        self.settings_store.update(extra=extra)
        self.state["unknown"] = [u for u in self.state.get("unknown", []) if u["address"] not in clean]
        self._save_state()
        self.start()
        self.wake()
        return self.public()

    def set_enabled(self, enabled: bool) -> dict:
        st = self.settings_store.get()
        extra = dict(st.extra or {})
        m = dict(extra.get("mail", {}))
        if enabled and not (m.get("address") and self.secret_file.exists()):
            raise ValueError("Bitte zuerst das Ablage-Postfach einrichten.")
        m["enabled"] = bool(enabled)
        extra["mail"] = m
        self.settings_store.update(extra=extra)
        if enabled:
            self.start()
            self.wake()
        return self.public()

    def allow_sender(self, address: str) -> dict:
        a = parseaddr(address)[1].lower()
        st = self.settings_store.get()
        extra = dict(st.extra or {})
        m = dict(extra.get("mail", {}))
        senders = list(m.get("senders", []))
        if a and a not in senders:
            senders.append(a)
        m["senders"] = senders
        extra["mail"] = m
        self.settings_store.update(extra=extra)
        self.state["unknown"] = [u for u in self.state.get("unknown", []) if u["address"] != a]
        self._save_state()
        self.wake()
        return self.public()

    def forget(self) -> dict:
        try:
            self.secret_file.unlink()
        except OSError:
            pass
        st = self.settings_store.get()
        extra = dict(st.extra or {})
        extra.pop("mail", None)
        self.settings_store.update(extra=extra)
        self.state = {}
        self._save_state()
        return self.public()

    def test(self, address: str, password: str, host: str = "", port: int = 993) -> bool:
        host = host or provider_for(address)["host"]
        conn = _connect(host, port, address, password)
        try:
            typ, _ = conn.select("INBOX", readonly=True)
            if typ != "OK":
                raise MailError("Der Posteingang ließ sich nicht öffnen.")
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        return True

    # --- Abholen --------------------------------------------------------------------------
    def _save_state(self) -> None:
        jsonfile.save(self.state_file, self.state)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="mail-abruf", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        self._stop.wait(5)
        while not self._stop.is_set():
            c = self.config()
            if c["enabled"]:
                try:
                    self.fetch()
                except Exception:
                    log.exception("Mail-Abruf fehlgeschlagen")
            self._wake.wait(max(1, c["interval"]) * 60)
            self._wake.clear()

    def fetch(self) -> int:
        """Holt neue Mails ab. Gibt die Zahl der abgelegten Mails zurück."""
        if not self._lock.acquire(blocking=False):
            return 0
        try:
            return self._fetch()
        except MailError as exc:
            self.state.update(error=str(exc), last_check=time.time())
            self._save_state()
            return 0
        except Exception:
            log.exception("Mail-Abruf: unerwarteter Fehler")
            self.state.update(error="Beim Abholen der Mails ist etwas schiefgegangen. Ich versuche es später erneut.",
                              last_check=time.time())
            self._save_state()
            return 0
        finally:
            self._lock.release()
            self._emit()

    def _emit(self) -> None:
        try:
            self.bus.emit("mail", self.public())
        except Exception:
            pass

    def _fetch(self) -> int:
        c = self.config()
        inbox = self.inbox_dir()
        if not c["enabled"] or not c["address"]:
            return 0
        if not inbox or not Path(inbox).is_dir():
            raise MailError("Der Scan-Ordner ist nicht erreichbar.")
        allowed = {a.lower() for a in c["senders"]}
        conn = _connect(c["host"], c["port"], c["address"], self._password())
        imported = 0
        unknown: dict[str, dict] = {u["address"]: u for u in self.state.get("unknown", [])}
        seen = set(self.state.get("seen", []))
        too_big = 0
        try:
            typ, _ = conn.select("INBOX")
            if typ != "OK":
                raise MailError("Der Posteingang ließ sich nicht öffnen.")
            conn.create(_quote(DONE_FOLDER))  # existiert er schon, meldet der Server nur „NO“
            typ, data = conn.uid("SEARCH", None, "ALL")
            uids = (data[0] or b"").split() if typ == "OK" and data else []
            try:
                typ, cap = conn.capability()
                can_move = typ == "OK" and b"MOVE" in b" ".join(x for x in cap if isinstance(x, bytes)).upper().split()
            except Exception:
                can_move = False
            moved_any = False
            for uid in uids[:200]:
                if self._stop.is_set():
                    break
                typ, head = conn.uid("FETCH", uid, "(RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID SUBJECT DATE)])")
                if typ != "OK" or not head or not isinstance(head[0], tuple):
                    continue
                size_m = re.search(rb"RFC822\.SIZE (\d+)", head[0][0] or b"")
                hdr = email.message_from_bytes(head[0][1], policy=email.policy.default)
                sender = parseaddr(str(hdr.get("From", "")))[1].lower()
                msgid = str(hdr.get("Message-ID", "")).strip() or f"uid-{uid.decode()}"
                if sender not in allowed:
                    if sender and sender not in unknown:
                        unknown[sender] = {"address": sender, "subject": str(hdr.get("Subject", ""))[:80]}
                    continue
                if size_m and int(size_m.group(1)) > MAX_SIZE:
                    too_big += 1
                    continue
                if msgid not in seen:
                    typ, full = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                    if typ != "OK" or not full or not isinstance(full[0], tuple):
                        continue
                    raw = full[0][1]
                    self._write(Path(inbox), raw, hdr)
                    seen.add(msgid)
                    imported += 1
                    self.state["seen"] = sorted(seen)[-2000:]
                    self._save_state()
                # erst nach dem sicheren Speichern im Postfach verschieben
                if can_move:
                    conn.uid("MOVE", uid, _quote(DONE_FOLDER))
                else:
                    typ, _ = conn.uid("COPY", uid, _quote(DONE_FOLDER))
                    if typ == "OK":
                        conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                        moved_any = True
            if moved_any:
                conn.expunge()
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        self.state.update(last_check=time.time(), last_ok=time.time(),
                          error=(f"{too_big} Mail(s) sind zu groß (über 60 MB) und bleiben im Postfach." if too_big else ""),
                          imported=self.state.get("imported", 0) + imported,
                          unknown=list(unknown.values())[:20])
        self._save_state()
        return imported

    @staticmethod
    def _write(inbox: Path, raw: bytes, hdr) -> Path:
        from email.utils import parsedate_to_datetime
        try:
            day = parsedate_to_datetime(str(hdr.get("Date"))).strftime("%Y-%m-%d")
        except Exception:
            day = time.strftime("%Y-%m-%d")
        subject = re.sub(r"^\s*((wg|fwd?|aw|re)\s*:\s*)+", "", str(hdr.get("Subject", "")), flags=re.I)
        name = naming.clean_filename(f"Mail {day} {subject}".strip(), ".eml")
        target = naming.unique_path(inbox / name)
        tmp = inbox / (".ordnungsliebe-" + target.stem[:40] + ".part")
        with open(tmp, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        if tmp.stat().st_size != len(raw):
            tmp.unlink(missing_ok=True)
            raise MailError("Eine Mail konnte nicht vollständig gespeichert werden.")
        tmp.replace(target)
        return target
