#!/usr/bin/env python3
"""Unofficial USI room-availability client.

Upstream: https://aule.usi.ch/aule/View.aspx?name=<ROOM>
  * GET            -> today's Telerik RadScheduler (day view) for one room
  * POST (WebForms) -> __EVENTTARGET=RadScheduler1,
                       __EVENTARGUMENT={"Command":"NavigateToNextPeriod"}
                       with the __VIEWSTATE of the previous response

There is no booking endpoint. Booking is an email to
  decanato.inf@usi.ch        (east campus, C*/D* rooms)
  gestione-aule.lu@usi.ch    (black / red / main buildings)
`book` builds that message and opens it in the default mail client.

Times are rendered in Europe/Zurich by the upstream server (no TZ in payload).

Usage:
  ./usi_rooms.py day   --room C1.03 [--date YYYY-MM-DD]
  ./usi_rooms.py at    --room C1.03 --time 14:30 [--date YYYY-MM-DD]
  ./usi_rooms.py free  --time 14:30 [--date YYYY-MM-DD] [--campus east|west]
  ./usi_rooms.py book  --room D0.02 --from 16:00 --to 17:00 [--campus east]

Defaults (campus, buildings, language, name) are read from
$USI_ROOMS_CONFIG or ~/.config/usirooms/config.json; flags always win.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

BASE = "https://aule.usi.ch/aule/View.aspx"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) appleWebKit/537.36 Safari/537.36"

ROOMS = {
    "black": ["SI-003", "SI-004", "SI-006", "SI-007", "SI-008", "SI-013", "SI-015"],
    "east": ["C1.03", "C1.04", "C1.05", "D0.02", "D0.03", "D0.10", "D1.13", "D1.14"],
    "east2": ["D2.19", "D2.21", "D3.01", "D3.03", "D4.01", "D4.08", "D5.01", "D5.03"],
    "red": [f"A-{f}" for f in (11, 12, 13, 14, 21, 22, 23, 24, 31, 32, 33, 34)],
    "main": ["250", "251", "253", "254", "354", "355"],
}
EMAIL = {"east": "decanato.inf@usi.ch", "east2": "decanato.inf@usi.ch"}
EMAIL_DEFAULT = "gestione-aule.lu@usi.ch"

# Two physical campuses: east (Via La Santa: C*/D* rooms, decanato.inf) and
# west (black/red/main buildings, gestione-aule.lu).
CAMPUSES = {
    "east": ROOMS["east"] + ROOMS["east2"],
    "west": ROOMS["black"] + ROOMS["red"] + ROOMS["main"],
}
BUILDING_CAMPUS = {"east": "east", "east2": "east", "black": "west", "red": "west", "main": "west"}
CAMPUS_BUILDINGS = {c: [b for b, camp in BUILDING_CAMPUS.items() if camp == c]
                    for c in ("east", "west")}
ALL_ROOMS = [r for v in ROOMS.values() for r in v]
CAMPUS_EMAIL = {"east": EMAIL["east"], "west": EMAIL_DEFAULT}
LABEL = {
    "east": "east campus", "east2": "east campus", "west": "west campus",
    "black": "black building", "red": "red building", "main": "main building",
}

# ---- defaults file --------------------------------------------------------
# $USI_ROOMS_CONFIG, else ~/.config/usirooms/config.json
CONFIG_KEYS = ("campus", "buildings", "exclude", "language", "name")
LANG_ALIAS = {"en": "en", "eng": "en", "english": "en",
              "it": "it", "ita": "it", "italian": "it", "italiano": "it"}
LANG_LONG = {"en": "english", "it": "italian"}


def config_path(explicit: str | None = None) -> str:
    if explicit:
        return os.path.expanduser(explicit)
    if os.environ.get("USI_ROOMS_CONFIG"):
        return os.path.expanduser(os.environ["USI_ROOMS_CONFIG"])
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "usirooms", "config.json")


def _check(key: str, value, path: str):
    """Validate and normalise one config entry."""
    if key == "campus":
        if value not in CAMPUSES:
            raise SystemExit(f"error: {path}: campus must be one of {list(CAMPUSES)}")
    elif key == "buildings":
        if not isinstance(value, list) or any(b not in ROOMS for b in value):
            raise SystemExit(f"error: {path}: buildings must be a list drawn from "
                             f"{list(ROOMS)}")
    elif key == "exclude":
        if not isinstance(value, list) or any(b not in ROOMS for b in value):
            raise SystemExit(f"error: {path}: exclude must be a list drawn from "
                             f"{list(ROOMS)}")
    elif key == "language":
        if LANG_ALIAS.get(str(value).strip().lower()) is None:
            raise SystemExit(f"error: {path}: language must be english|italian (or en|it)")
        return str(value).strip().lower()
    elif key == "name":
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"error: {path}: name must be a non-empty string")
        return value.strip()
    return value


def validate_config(raw: dict, path: str) -> dict:
    cfg: dict = {}
    for key, value in raw.items():
        if key not in CONFIG_KEYS:
            print(f"warning: {path}: ignoring unknown key {key!r} "
                  f"(known: {', '.join(CONFIG_KEYS)})", file=sys.stderr)
            continue
        cfg[key] = _check(key, value, path)
    return cfg


def read_config_file(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        try:
            raw = json.load(fh)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"error: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"error: {path}: top level must be a JSON object")
    return raw


def write_config_file(path: str, cfg: dict) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def load_config(explicit: str | None = None) -> dict:
    path = config_path(explicit)
    required = bool(explicit or os.environ.get("USI_ROOMS_CONFIG"))
    if not os.path.exists(path):
        if required:
            raise SystemExit(f"error: config file not found: {path}")
        return {}
    return validate_config(read_config_file(path), path)

_SD = re.compile(r'name="RadScheduler1_SelectedDateCalendar_SD" id="[^"]*" value="\[\[(\d+),(\d+),(\d+)\]\]"')
_INPUT = re.compile(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"')
_APT = re.compile(r'<div id="RadScheduler1_\d+_\d+"([^>]*)>')
_ORARIO = re.compile(r'lblOrario[^>]*>(.*?)</span>', re.S)
_SUBJ = re.compile(r'lblSubject[^>]*>(.*?)</span>', re.S)
_TAG = re.compile(r"<[^>]+>")


def _txt(fragment: str) -> str:
    return html.unescape(_TAG.sub("", fragment)).replace("\u00a0", " ").strip()


class Rooms:
    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self._opener.addheaders = [("User-Agent", UA)]
        self._cache: dict[tuple[str, dt.date], list[dict]] = {}

    # ---- transport -------------------------------------------------------
    def _get(self, room: str) -> str:
        url = f"{BASE}?name={urllib.parse.quote(room)}"
        with self._opener.open(url, timeout=self.timeout) as r:
            return r.read().decode("utf-8", "replace")

    def _post(self, room: str, page: str, command: str) -> str:
        form = {k: html.unescape(v) for k, v in _INPUT.findall(page)}
        form["__EVENTTARGET"] = "RadScheduler1"
        form["__EVENTARGUMENT"] = json.dumps({"Command": command}, separators=(",", ":"))
        body = urllib.parse.urlencode(form).encode()
        url = f"{BASE}?name={urllib.parse.quote(room)}"
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA},
        )
        with self._opener.open(req, timeout=self.timeout) as r:
            return r.read().decode("utf-8", "replace")

    # ---- parsing ---------------------------------------------------------
    @staticmethod
    def _page_date(page: str) -> dt.date | None:
        m = _SD.search(page)
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None

    @staticmethod
    def parse(page: str, day: dt.date) -> list[dict]:
        apts = []
        starts = [m for m in _APT.finditer(page)]
        for i, m in enumerate(starts):
            end = starts[i + 1].start() if i + 1 < len(starts) else len(page)
            chunk = page[m.start():end]
            time_m = _ORARIO.search(chunk)
            if not time_m:
                continue
            span = re.search(r"\((\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\)", _txt(time_m.group(1)))
            if not span:
                continue
            subj_m = _SUBJ.search(chunk)
            sh, sm, eh, em = (int(x) for x in span.groups())
            apts.append({
                "title": _txt(subj_m.group(1)) if subj_m else "",
                "start": dt.datetime.combine(day, dt.time(sh, sm)).isoformat(),
                "end": dt.datetime.combine(day, dt.time(eh, em)).isoformat(),
            })
        return sorted(apts, key=lambda a: a["start"])

    @staticmethod
    def gaps(apts: list[dict], day: dt.date, lo="08:00", hi="20:00") -> list[dict]:
        def at(t: str) -> dt.datetime:
            h, m = (int(x) for x in t.split(":"))
            return dt.datetime.combine(day, dt.time(h, m))

        cursor, out = at(lo), []
        for a in apts:
            s, e = dt.datetime.fromisoformat(a["start"]), dt.datetime.fromisoformat(a["end"])
            if s > cursor:
                out.append({"start": cursor.isoformat(), "end": s.isoformat()})
            cursor = max(cursor, e)
        if cursor < at(hi):
            out.append({"start": cursor.isoformat(), "end": at(hi).isoformat()})
        return out

    # ---- public ----------------------------------------------------------
    def day(self, room: str, when: dt.date | None = None) -> dict:
        when = when or dt.date.today()
        if (room, when) in self._cache:
            return {"room": room, "date": when.isoformat(), "appointments": self._cache[(room, when)]}

        page = self._get(room)
        cur = self._page_date(page)
        if cur is None:
            if page.lstrip().lower().startswith("non abilitato"):
                raise RuntimeError("not enabled in the scheduler ('non abilitato')")
            raise RuntimeError(f"no schedule returned for {room!r} (unknown room)")

        delta = (when - cur).days
        command = "NavigateToNextPeriod" if delta > 0 else "NavigateToPreviousPeriod"
        for _ in range(abs(delta)):
            page = self._post(room, page, command)
            moved = self._page_date(page)
            if moved is None or moved == cur:
                raise RuntimeError(f"date navigation stalled at {cur} for {room!r}")
            cur = moved

        apts = self.parse(page, when)
        self._cache[(room, when)] = apts
        return {"room": room, "date": when.isoformat(), "appointments": apts,
                "free": self.gaps(apts, when)}


def explain_error(exc: Exception, room: str | None) -> str:
    msg = str(exc)
    if room and "non abilitato" in msg and room not in ALL_ROOMS:
        msg += f"; {room!r} is not in the room inventory either (see `usirooms rooms`)"
    return msg


def _busy(apts: list[dict], when: dt.date, times: list[str]) -> bool:
    for a in apts:
        s, e = dt.datetime.fromisoformat(a["start"]), dt.datetime.fromisoformat(a["end"])
        for t in times:
            h, m = (int(x) for x in t.split(":"))
            if s <= dt.datetime.combine(when, dt.time(h, m)) < e:
                return True
    return False


# ---- booking (mailto, mirrors usirooms.xyz/app.js) ------------------------

WEEKDAY_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_EN = ["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"]
WEEKDAY_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MONTH_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
            "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def building_of(room: str) -> str | None:
    for name, rooms in ROOMS.items():
        if room in rooms:
            return name
    if re.match(r"^(C1\.|D[01]\.|A[123]\.)", room):
        return "east"
    if re.match(r"^D\d\.", room):
        return "east2"
    if room.startswith("SI-"):
        return "black"
    if re.match(r"^A-\d", room):
        return "red"
    return None


def full_name(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("USI_BOOK_NAME"):
        return os.environ["USI_BOOK_NAME"]
    try:
        out = subprocess.run(["/usr/bin/id", "-F"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "<INSERT NAME>"


def book_message(room: str, when: dt.date, frm: str, to: str, name: str,
                 campus: str, label: str, lang: str) -> dict:
    """The two templates app.js uses; language defaults from campus, overridable."""
    addr = CAMPUS_EMAIL[campus]
    if lang == "en":
        day = f"{WEEKDAY_EN[when.weekday()]} {when.day} {MONTH_EN[when.month - 1]} {when.year}"
        subject = f"Booking room {room}"
        body = (f"Hi, I'd like to book the room {room} in the {label} on {day} "
                f"from {frm} to {to}.\r\n\r\nThank you!\r\n\r\nBest regards,\r\n{name}")
    else:
        day = f"{WEEKDAY_IT[when.weekday()]} {when.day} {MONTH_IT[when.month - 1]} {when.year}"
        subject = f"Riservazione aula {room}"
        body = (f"Salve, vorrei riservare la stanza {room} nel {label} per il {day} "
                f"dalle {frm} alle {to}.\r\n\r\nGrazie!\r\n\r\nCordiali saluti,\r\n{name}")
    url = (f"mailto:{addr}?subject={urllib.parse.quote(subject)}"
           f"&body={urllib.parse.quote(body)}")
    return {"to": addr, "subject": subject, "body": body, "mailto": url}


def open_mailto(url: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
    elif os.name == "nt":
        os.startfile(urllib.parse.unquote(url))  # type: ignore[attr-defined]
    else:
        webbrowser.open(url)


def _split_buildings(value: str) -> list[str]:
    parts = [b.strip() for b in value.split(",") if b.strip()]
    bad = [b for b in parts if b not in ROOMS]
    if bad:
        raise SystemExit(f"error: unknown building(s) {', '.join(bad)}; "
                         f"choose from {', '.join(ROOMS)}")
    return parts


def _lang(value: str) -> str:
    lang = LANG_ALIAS.get(str(value).strip().lower())
    if not lang:
        raise argparse.ArgumentTypeError("must be english|italian (or en|it)")
    return lang


def _hhmm(value: str) -> dt.time:
    h, m = (int(x) for x in value.split(":"))
    return dt.time(h, m)


HELP_DESCRIPTION = """\
Unofficial USI Lugano room availability, read from the university scheduling
system (aule.usi.ch). Read-only: no booking API exists, so `book` prepares and
opens the booking e-mail instead of reserving anything."""

HELP_EPILOG = """\
commands:
  day    one room: lectures plus the free gaps between them
  at     one room: free at --time? exit 0 free, 1 busy, 2 error
  free   every room in scope: free/busy at --time, with the free window
  rooms  the room inventory in scope, grouped by building
  book   prefilled booking e-mail for --room/--from/--to, opened in your client
  config show, set, unset or reset the defaults file below

examples:
  %(prog)s free --campus east --time 14:30
  %(prog)s free --time 16:00 --building red --date 2026-10-23
  %(prog)s at --room C1.03 --time 14:30
  %(prog)s rooms --campus east
  %(prog)s day --room D3.01 --json
  %(prog)s book --room D0.02 --from 16:00 --to 17:00
  %(prog)s config --campus east --buildings east,east2 --language english
  %(prog)s config --unset name

config file (optional; command-line flags always win):
  read from $USI_ROOMS_CONFIG, else ~/.config/usirooms/config.json, else --config
  write it with `%(prog)s config --campus east --language english --name "…"`
  {
    "campus": "east",
    "buildings": ["east", "east2"],
    "exclude": ["east2"],
    "language": "english",
    "name": "Your Name"
  }
  campus     default scan scope, east or west
  buildings  default scan scope, a list drawn from the buildings below
  exclude    buildings to leave out of scans (an explicit --building still wins)
  language   english or italian; mail body language, decoupled from campus
  name       signature used in booking mails

  scope      --building > --campus > config buildings > config campus > all,
             then minus config exclude
  language   --lang > config language > campus default (east EN, west IT)
  signature  --name > $USI_BOOK_NAME > config name > macOS full name

coverage:
  buildings  black  east  east2  red  main
  campuses   east = east + east2        -> decanato.inf@usi.ch
             west = black + red + main  -> gestione-aule.lu@usi.ch
  times      Europe/Zurich wall clock; one upstream request per day of horizon
  gaps       a room with no lecture in the scheduler answers "non abilitato"
             and is reported as ??, since the website would wrongly call it free
"""


def cmd_config(a) -> int:
    """usirooms config — show, set, unset or reset the defaults file."""
    path = config_path(a.config)
    exists = os.path.exists(path)
    cfg = validate_config(read_config_file(path), path) if exists else {}

    if a.reset:
        if exists:
            os.remove(path)
            print(f"removed {path}", file=sys.stderr)
        else:
            print(f"no config at {path}", file=sys.stderr)
        return 0

    changed = False
    if a.campus:
        cfg["campus"], changed = a.campus, True
    if a.lang:
        cfg["language"], changed = LANG_LONG[a.lang], True
    if a.buildings:
        cfg["buildings"] = [b.strip() for b in a.buildings.split(",") if b.strip()]
        changed = True
    if a.exclude is not None:
        cfg["exclude"] = [b.strip() for b in a.exclude.split(",") if b.strip()]
        changed = True
    if a.name:
        cfg["name"], changed = a.name, True
    for key in [k.strip() for k in (a.unset or "").split(",") if k.strip()]:
        if key not in CONFIG_KEYS:
            raise SystemExit(f"error: unknown key {key!r} (known: {', '.join(CONFIG_KEYS)})")
        cfg.pop(key, None)
        changed = True

    if changed:
        cfg = validate_config(cfg, path)
        write_config_file(path, cfg)
        print(f"{'updated' if exists else 'created'} {path}", file=sys.stderr)

    if not exists and not changed:
        print(f"no config at {path}\n"
              f"create one with: usirooms config --campus east --language english "
              f"--name \"Your Name\"", file=sys.stderr)
        return 0

    print(json.dumps(cfg, indent=2) if cfg else "(empty)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="usirooms",
        description=HELP_DESCRIPTION,
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("command", choices=["day", "at", "free", "rooms", "book", "config"],
                    help="action to run; see commands below")
    ap.add_argument("--room", help="room name, e.g. C1.03, A-11, SI-006, 251")
    ap.add_argument("--building", choices=list(ROOMS), default=None,
                    help="narrow a scan to one building")
    ap.add_argument("--campus", choices=list(CAMPUSES), default=None,
                    help="scope a scan, or pick the booking office: east | west")
    ap.add_argument("--date", default=None,
                    help="YYYY-MM-DD, default today")
    ap.add_argument("--time", default=None,
                    help="HH:MM, the instant to test (at, free); default now")
    ap.add_argument("--from", dest="frm", help="HH:MM, booking start (book)")
    ap.add_argument("--to", dest="to", help="HH:MM, booking end (book)")
    ap.add_argument("--name", help="signature; default $USI_BOOK_NAME, config "
                                   "name, then the macOS full name")
    ap.add_argument("--force", action="store_true",
                    help="book even if the room is occupied")
    ap.add_argument("--no-open", action="store_true",
                    help="print the mailto: URL instead of opening the client")
    ap.add_argument("--lang", "--language", dest="lang", type=_lang, default=None,
                    help="mail language: english|italian (or en|it); default from "
                         "config, else the campus")
    ap.add_argument("--config", default=None,
                    help="defaults file; default $USI_ROOMS_CONFIG or "
                         "~/.config/usirooms/config.json")
    ap.add_argument("--buildings", default=None,
                    help="comma-separated building list, e.g. east,east2 (config)")
    ap.add_argument("--exclude", default=None,
                    help="comma-separated buildings to skip in scans, e.g. east2 "
                         "(config); empty string clears")
    ap.add_argument("--unset", default=None,
                    help="comma-separated config keys to remove (config)")
    ap.add_argument("--reset", action="store_true",
                    help="delete the defaults file (config)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable output where supported")
    a = ap.parse_args(argv)

    if a.command == "config":
        return cmd_config(a)

    cfg = load_config(a.config)
    cli_campus = a.campus
    a.campus = cli_campus or cfg.get("campus")
    lang = a.lang or LANG_ALIAS.get(str(cfg.get("language", "")).lower())
    scope_buildings = cfg.get("buildings") or []

    api = Rooms()
    when = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    a.time = a.time or dt.datetime.now().strftime("%H:%M")

    if a.command in ("day", "at", "book") and (a.buildings is not None
                                               or a.exclude is not None):
        print("error: --buildings and --exclude apply to free/rooms (per run) and "
              "to config (persisted); use --room here", file=sys.stderr)
        return 2

    if a.command in ("day", "at"):
        try:
            out = api.day(a.room, when)
        except Exception as exc:
            print(f"error: {explain_error(exc, a.room)}", file=sys.stderr)
            return 2

        if a.command == "day":
            if a.json:
                print(json.dumps(out, indent=2))
            else:
                print(f"{out['room']}  {out['date']}")
                for x in out["appointments"]:
                    print(f"  busy {x['start'][11:16]}-{x['end'][11:16]}  {x['title']}")
                for g in out["free"]:
                    print(f"  free {g['start'][11:16]}-{g['end'][11:16]}")
            return 0

        busy = _busy(out["appointments"], when, [a.time])
        print(f"{out['room']} {out['date']} {a.time}: {'BUSY' if busy else 'FREE'}")
        for x in out["appointments"]:
            if x["start"][11:16] <= a.time < x["end"][11:16]:
                print(f"  <- {x['title']} ({x['start'][11:16]}-{x['end'][11:16]})")
        return 1 if busy else 0

    if a.command in ("free", "rooms"):
        if cli_campus and a.building and BUILDING_CAMPUS[a.building] != cli_campus:
            print(f"error: {a.building} is not on the {a.campus} campus", file=sys.stderr)
            return 2
        run_buildings = _split_buildings(a.buildings) if a.buildings else None
        run_exclude = _split_buildings(a.exclude) if a.exclude is not None else None

        if a.building:
            rooms, scope = ROOMS[a.building], a.building
        elif run_buildings:
            rooms = [r for b in run_buildings for r in ROOMS[b]]
            scope = ", ".join(run_buildings)
        elif cli_campus:
            rooms = CAMPUSES[cli_campus]
            scope = f"{cli_campus} campus ({'+'.join(CAMPUS_BUILDINGS[cli_campus])})"
        elif scope_buildings:
            rooms = [r for b in scope_buildings for r in ROOMS[b]]
            scope = ", ".join(scope_buildings)
        elif a.campus:
            rooms = CAMPUSES[a.campus]
            scope = f"{a.campus} campus ({'+'.join(CAMPUS_BUILDINGS[a.campus])})"
        else:
            rooms, scope = ALL_ROOMS, "all buildings"

        if run_exclude is not None:
            excluded = set(run_exclude)   # per-run override, "" clears
        elif a.building or run_buildings:
            excluded = set()              # explicit scope beats the stored exclusion
        else:
            excluded = set(cfg.get("exclude") or [])
        if excluded:
            rooms = [r for r in rooms if building_of(r) not in excluded]
            if not rooms:
                print("error: every room in scope is excluded by config 'exclude' "
                      f"({', '.join(sorted(excluded))})", file=sys.stderr)
                return 2
            scope += f", excluding {'+'.join(b for b in ROOMS if b in excluded)}"

        if a.command == "rooms":
            if a.json:
                print(json.dumps({"scope": scope, "rooms": rooms}, indent=2))
            else:
                print(f"{len(rooms)} rooms [{scope}]", file=sys.stderr)
                for building in ROOMS:
                    in_scope = [r for r in ROOMS[building] if r in rooms]
                    if in_scope:
                        print(f"  {building:<6} {' '.join(in_scope)}")
            return 0

        moment = a.time or dt.datetime.now().strftime("%H:%M")
        rows = []
        for room in rooms:
            try:
                out = api.day(room, when)
            except Exception as exc:  # unknown room / upstream hiccup
                rows.append({"room": room, "error": str(exc)})
                continue
            busy = next((x for x in out["appointments"]
                         if x["start"][11:16] <= moment < x["end"][11:16]), None)
            window = next((g for g in out["free"]
                           if g["start"][11:16] <= moment < g["end"][11:16]), None)
            rows.append({
                "room": room,
                "free": busy is None,
                "window": f"{window['start'][11:16]}-{window['end'][11:16]}" if window else None,
                "busy": f"{busy['start'][11:16]}-{busy['end'][11:16]} {busy['title']}"
                        if busy else None,
            })

        if a.json:
            print(json.dumps({"date": when.isoformat(), "time": moment,
                              "scope": scope, "rooms": rows}, indent=2))
            return 0

        for r in rows:
            if "error" in r:
                print(f"  ??   {r['room']:<7} {r['error']}")
            elif r["free"]:
                print(f"  FREE {r['room']:<7} {r['window'] or ''}")
            else:
                print(f"  BUSY {r['room']:<7} {r['busy']}")
        print(f"\n{when} {moment} [{scope}]: "
              f"{sum(1 for r in rows if r.get('free'))} free / {len(rows)}")
        return 0

    if a.command == "book":
        if not (a.room and a.frm and a.to):
            print("error: book needs --room, --from and --to", file=sys.stderr)
            return 2
        try:
            frm, to = _hhmm(a.frm), _hhmm(a.to)
        except ValueError:
            print("error: --from/--to must be HH:MM", file=sys.stderr)
            return 2
        if frm >= to:
            print("error: --from must be before --to", file=sys.stderr)
            return 2

        building = a.building or building_of(a.room)
        derived = BUILDING_CAMPUS.get(building) if building else None
        campus = cli_campus or derived or cfg.get("campus")
        if not campus:
            print(f"error: unknown campus/building for {a.room!r}; "
                  f"pass --campus east|west or --building", file=sys.stderr)
            return 2
        if building and derived != campus:
            print(f"error: {building} is not on the {campus} campus", file=sys.stderr)
            return 2
        label = LABEL[building] if building else LABEL[campus]

        try:
            out = api.day(a.room, when)
        except Exception as exc:
            print(f"error: {explain_error(exc, a.room)}", file=sys.stderr)
            return 2

        start = dt.datetime.combine(when, frm)
        end = dt.datetime.combine(when, to)
        clashes = [x for x in out["appointments"]
                   if dt.datetime.fromisoformat(x["start"]) < end
                   and dt.datetime.fromisoformat(x["end"]) > start]
        if clashes:
            for x in clashes:
                print(f"busy {x['start'][11:16]}-{x['end'][11:16]}  {x['title']}", file=sys.stderr)
            if not a.force:
                print(f"error: {a.room} is occupied {a.frm}-{a.to}; --force to write anyway",
                      file=sys.stderr)
                return 1
            print("warning: occupied slot, sending anyway (--force)", file=sys.stderr)

        signature = a.name or os.environ.get("USI_BOOK_NAME") or cfg.get("name")
        msg = book_message(a.room, when, a.frm, a.to, full_name(signature),
                           campus, label, lang or ("en" if campus == "east" else "it"))
        if a.json:
            print(json.dumps(msg, indent=2))
        else:
            print(f"To:      {msg['to']}")
            print(f"Subject: {msg['subject']}")
            print()
            print(msg["body"])
        if not a.no_open:
            open_mailto(msg["mailto"])
            print(f"\nopened default mail client ({msg['to']})", file=sys.stderr)
        else:
            print(f"\n{msg['mailto']}", file=sys.stderr)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
