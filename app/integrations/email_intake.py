"""Email intake: turn a dictation emailed to the practice mailbox into a draft note for review.

The practice emails a visit's dictation to its Google Workspace mailbox (info@sdmobilept.com by
default — more mailboxes can be subscribed in Manage Office) with "Cadence" in the subject. While
the server runs, Cadence checks each subscribed mailbox every couple of minutes, and for each new
matching email:

1. checks the SENDER is allowed (default: the mailbox's own Workspace domain, so dictation never
   arrives from a personal account the Google BAA does not cover);
2. reads the visit date from the subject, else the body, else the email's own date;
3. creates a new patient "Unknown patient" with the visit date in the DOB column (one per email,
   so emailed notes never mix — the clinician renames it to the real patient);
4. queues the note (Daily Visit unless the subject says eval / re-eval / discharge) in "Notes in
   progress", where it waits for the clinician to review and Save, like any note.

PHI: the email lives in the practice's Google Workspace mailbox (BAA-covered). Cadence reads it
over IMAP/TLS onto this computer and nowhere else. The mailbox app password is stored only on this
computer, encrypted, in the config folder (git-ignored); it is never returned by the API. The state
file keeps Message-IDs and patient ids only — no email text.

Nothing unreviewed is saved: the note sits in the in-memory queue. If the server restarts before
the clinician saves it, the next check re-reads that email and queues it again.
"""

from __future__ import annotations

import email
import email.policy
import html
import imaplib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.paths import INSTALL_DIR, config_dir

SETTINGS_FILENAME = "email_intake.json"
STATE_FILENAME = "email_intake_state.json"
KEY_FILENAME = ".email_intake.key"

DEFAULT_MAILBOX = "info@sdmobilept.com"
IMAP_HOST = "imap.gmail.com"
SUBJECT_KEYWORD = "Cadence"
DEFAULT_POLL_SECONDS = 120
LOOKBACK_DAYS = 14                 # never reach further back than this
MAX_BODY_CHARS = 20000

PATIENT_NAME = "Unknown patient"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --- storage -----------------------------------------------------------------------------

def _dir() -> Path:
    return config_dir(INSTALL_DIR / "app" / "integrations")


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _fernet() -> Fernet:
    """The key that encrypts the mailbox app passwords. The key file itself is protected with
    Windows DPAPI (app/secure_store.py), so it only opens for this Windows user on this computer —
    copying the config folder elsewhere yields nothing usable. An older unprotected key file is
    re-saved protected the first time it is read."""
    from app import secure_store
    path = _dir() / KEY_FILENAME
    if path.exists():
        stored = path.read_bytes().strip()
        key = secure_store.unprotect(stored)
        if not secure_store.is_protected(stored) and secure_store.available():
            path.write_bytes(secure_store.protect(key))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        path.write_bytes(secure_store.protect(key))
    return Fernet(key)


class SettingsError(ValueError):
    pass


@dataclass
class Mailbox:
    address: str
    password: str            # decrypted, in memory only
    allowed_senders: list[str]


def load_settings() -> dict:
    data = _read(_dir() / SETTINGS_FILENAME)
    mailboxes = data.get("mailboxes")
    if not isinstance(mailboxes, list):
        mailboxes = [{"address": DEFAULT_MAILBOX, "password_enc": "", "allowed_senders": ""}]
    return {
        "enabled": bool(data.get("enabled", False)),
        "poll_seconds": int(data.get("poll_seconds") or DEFAULT_POLL_SECONDS),
        "mailboxes": [m for m in mailboxes if isinstance(m, dict) and m.get("address")],
    }


def public_settings() -> dict:
    """For the Manage Office tab: everything except the passwords."""
    s = load_settings()
    return {
        "enabled": s["enabled"],
        "poll_seconds": s["poll_seconds"],
        "subject_keyword": SUBJECT_KEYWORD,
        "mailboxes": [{"address": m["address"], "has_password": bool(m.get("password_enc")),
                       "allowed_senders": m.get("allowed_senders") or _domain_of(m["address"])}
                      for m in s["mailboxes"]],
    }


def save_settings(body: dict) -> dict:
    """Validate and store. A blank password keeps the one already saved for that address."""
    if not isinstance(body, dict):
        raise SettingsError("expected an object")
    current = {m["address"].lower(): m for m in load_settings()["mailboxes"]}
    out = []
    for row in body.get("mailboxes") or []:
        address = str((row or {}).get("address") or "").strip().lower()
        if not address:
            continue
        if not _EMAIL_RE.match(address):
            raise SettingsError(f"not an email address: {address}")
        password = "".join(str(row.get("password") or "").split())   # app passwords show spaced
        allowed = ",".join(p.strip().lower() for p in str(row.get("allowed_senders") or "").split(",")
                           if p.strip())
        if password:
            enc = _fernet().encrypt(password.encode()).decode()
        else:
            enc = (current.get(address) or {}).get("password_enc", "")
        out.append({"address": address, "password_enc": enc,
                    "allowed_senders": allowed or _domain_of(address)})
    poll = int(body.get("poll_seconds") or DEFAULT_POLL_SECONDS)
    if not 30 <= poll <= 3600:
        raise SettingsError("check interval must be between 30 and 3600 seconds")
    _atomic_write(_dir() / SETTINGS_FILENAME,
                  {"enabled": bool(body.get("enabled")), "poll_seconds": poll, "mailboxes": out})
    return public_settings()


def mailboxes() -> list[Mailbox]:
    out = []
    for m in load_settings()["mailboxes"]:
        if not m.get("password_enc"):
            continue
        try:
            pw = _fernet().decrypt(m["password_enc"].encode()).decode()
        except (InvalidToken, ValueError):
            continue
        allowed = [a.strip() for a in (m.get("allowed_senders") or _domain_of(m["address"])).split(",")
                   if a.strip()]
        out.append(Mailbox(m["address"], pw, allowed))
    return out


def load_state() -> dict:
    s = _read(_dir() / STATE_FILENAME)
    s.setdefault("processed", {})
    s.setdefault("last_check", None)
    s.setdefault("last_result", "")
    return s


def save_state(state: dict) -> None:
    cutoff = time.time() - (LOOKBACK_DAYS + 7) * 86400
    state["processed"] = {k: v for k, v in state.get("processed", {}).items()
                          if (v or {}).get("at", 0) >= cutoff}
    _atomic_write(_dir() / STATE_FILENAME, state)


# --- parsing (pure, unit-tested) ---------------------------------------------------------

def _domain_of(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def sender_allowed(from_header: str, allowed: list[str]) -> bool:
    """`allowed` holds domains ("sdmobilept.com") and/or full addresses. Exact matches only — a
    look-alike domain ("sdmobilept.com.evil.net") is not the practice."""
    addr = parseaddr(from_header or "")[1].lower()
    if not addr or "@" not in addr:
        return False
    domain = _domain_of(addr)
    for a in allowed:
        a = a.lower().strip()
        if not a:
            continue
        if ("@" in a and addr == a) or ("@" not in a and domain == a):
            return True
    return False


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b"), "mdy"),
    (re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})"
                r"(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I), "mon-d-y"),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
                r"[a-z]*\.?,?\s+(\d{4})\b", re.I), "d-mon-y"),
]
_VISIT_LABEL = re.compile(r"(?:visit|service|dos|date of service|visit date)\s*(?:date)?\s*[:\-]?\s*",
                          re.I)


def _to_date(m: re.Match, kind: str) -> date | None:
    try:
        if kind == "ymd":
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif kind == "mdy":
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
        elif kind == "mon-d-y":
            mo, d, y = _MONTHS[m.group(1)[:3].lower()], int(m.group(2)), int(m.group(3))
        else:
            d, mo, y = int(m.group(1)), _MONTHS[m.group(2)[:3].lower()], int(m.group(3))
        return date(y, mo, d)
    except (ValueError, KeyError):
        return None


def _first_date(text: str) -> date | None:
    best = None
    for rx, kind in _DATE_PATTERNS:
        for m in rx.finditer(text or ""):
            d = _to_date(m, kind)
            if d and (best is None or m.start() < best[0]):
                best = (m.start(), d)
                break
    return best[1] if best else None


def parse_visit_date(subject: str, body: str, sent: date | None = None) -> tuple[date | None, str]:
    """(visit date, where it came from). Order: a date labelled "visit/service date" anywhere,
    then any date in the subject, then the first date in the body, then the email's own date.
    A future date is rejected — a visit cannot happen after its note was sent."""
    today = (sent or date.today())
    candidates = []
    for text, where in ((subject, "subject"), (body, "body")):
        for lm in _VISIT_LABEL.finditer(text or ""):
            d = _first_date((text or "")[lm.end(): lm.end() + 40])
            if d:
                candidates.append((d, "labelled in the " + where))
                break
    candidates.append((_first_date(subject), "subject"))
    candidates.append((_first_date((body or "")[:4000]), "body"))
    for d, where in candidates:
        if d and d <= today + timedelta(days=1) and d.year >= 2000:
            return d, where
    return (sent, "email date") if sent else (None, "not found")


_FORM_KEYWORDS = [
    (re.compile(r"\bdischarge\b", re.I), "discharge"),
    (re.compile(r"\b(re-?eval\w*|reassess\w*|progress report)\b", re.I), "reeval"),
    (re.compile(r"\b(initial|eval(uation)?|ie)\b", re.I), "initial"),
]


def form_for_subject(subject: str) -> str:
    """Daily Visit unless the subject names another note type."""
    for rx, form_id in _FORM_KEYWORDS:
        if rx.search(subject or ""):
            return form_id
    return "followup"


_QUOTE_START = re.compile(r"^\s*(On .{4,200} wrote:|-----\s*Original Message\s*-----|From:\s.+)$",
                          re.I | re.M)


def body_text(msg: email.message.EmailMessage) -> str:
    """The dictation: the plain-text part (or the HTML part as text), without the quoted reply
    chain or the signature."""
    part = msg.get_body(preferencelist=("plain", "html")) if hasattr(msg, "get_body") else None
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_subtype() == "html":
        text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", text)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
    m = _QUOTE_START.search(text)
    if m:
        text = text[: m.start()]
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(">"))
    text = re.split(r"(?m)^--\s*$", text)[0]           # standard signature separator
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:MAX_BODY_CHARS]


def subject_without_keyword(subject: str) -> str:
    return re.sub(rf"\b{SUBJECT_KEYWORD}\b[:\-\s]*", "", subject or "", flags=re.I).strip()


# --- IMAP ----------------------------------------------------------------------------------

@dataclass
class IncomingEmail:
    mailbox: str
    message_id: str
    subject: str
    sender: str
    sent: date | None
    body: str
    uid: bytes


def _connect(mb: Mailbox) -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(IMAP_HOST, 993, timeout=30)
    conn.login(mb.address, mb.password)
    conn.select("INBOX")
    return conn


def test_login(mb: Mailbox) -> str:
    """'' on success, otherwise a reason a person can act on."""
    try:
        conn = _connect(mb)
        conn.logout()
        return ""
    except imaplib.IMAP4.error as e:
        msg = str(e)
        if "AUTHENTICATIONFAILED" in msg.upper() or "Invalid credentials" in msg:
            return ("Google refused the sign-in. Use an APP PASSWORD (Google Account → Security → "
                    "2-Step Verification → App passwords), not the normal password, and check IMAP "
                    "is allowed for this Workspace account.")
        return "IMAP error: " + msg[:160]
    except OSError as e:
        return "Could not reach Gmail (" + e.__class__.__name__ + "). Check the internet connection."


def fetch_new(mb: Mailbox, *, known_ids: set[str], resend_ids: set[str]) -> tuple[list[IncomingEmail], list[str]]:
    """Unread emails with the keyword in the subject from the last LOOKBACK_DAYS, plus any already
    processed ones listed in `resend_ids` (their note was never saved). Read with BODY.PEEK so an
    email is not marked read until it has been queued. Returns (emails, skipped-sender notes)."""
    conn = _connect(mb)
    try:
        since = (date.today() - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")
        found: dict[bytes, None] = {}
        typ, data = conn.uid("SEARCH", None, f'(SINCE {since} SUBJECT "{SUBJECT_KEYWORD}" UNSEEN)')
        for uid in (data[0] or b"").split() if typ == "OK" else []:
            found[uid] = None
        for mid in resend_ids:
            typ, data = conn.uid("SEARCH", None, "HEADER", "Message-ID", mid)
            for uid in (data[0] or b"").split() if typ == "OK" else []:
                found[uid] = None
        out, skipped = [], []
        for uid in found:
            typ, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                continue
            msg = email.message_from_bytes(data[0][1], policy=email.policy.default)
            mid = (msg.get("Message-ID") or f"<uid-{uid.decode()}@{mb.address}>").strip()
            subject = str(msg.get("Subject") or "")
            if SUBJECT_KEYWORD.lower() not in subject.lower():
                continue
            if mid in known_ids and mid not in resend_ids:
                continue
            sender = str(msg.get("From") or "")
            if not sender_allowed(sender, mb.allowed_senders):
                skipped.append(parseaddr(sender)[1] or "unknown sender")
                continue
            try:
                sent = parsedate_to_datetime(msg.get("Date")).date() if msg.get("Date") else None
            except (TypeError, ValueError):
                sent = None
            out.append(IncomingEmail(mb.address, mid, subject, sender, sent, body_text(msg), uid))
        return out, skipped
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def mark_seen(mb: Mailbox, uids: list[bytes]) -> None:
    if not uids:
        return
    conn = _connect(mb)
    try:
        for uid in uids:
            conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def dob_display(d: date | None) -> str | None:
    return d.strftime("%m/%d/%Y") if d else None


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
