# Internals

How `usirooms` gets its data, and how to keep it working when the university
changes something. Read this if you are maintaining the CLI or the parser —
users only need the top-level [README](../README.md).

## Data source

Availability is read from `aule.usi.ch`, the scheduling system behind
<https://www.usirooms.xyz>. That site is a static frontend plus a five-line PHP
proxy; the CLI talks to upstream directly, which is faster and has no CORS
wall.

### Upstream (no proxy, no auth)

```
GET  https://aule.usi.ch/aule/View.aspx?name=C1.03
POST https://aule.usi.ch/aule/View.aspx?name=C1.03
```

GET sets `ASP.NET_SessionId` and returns a day view
(`RadScheduler1_SelectedDateCalendar_SD` = today). An unknown room answers with
a body starting `non abilitato`, which is also what a room that exists but has
no timetable returns.

### The proxy variant

```
GET https://www.usirooms.xyz/api/aule.php?name=C1.03
```

Returns the same HTML for today only. `access-control-allow-origin` is pinned to
`https://usirooms.xyz`, so browser requests from another origin are blocked while
`curl` works; `POST` returns `400`. Source:
<https://github.com/Steeven9/USIrooms/blob/main/api/aule.php>.

## Walking to another date

No query parameter exists — `?date=`, `?d=`, `?selectedDate=` are all silently
ignored. Navigation is a classic WebForms postback, one day per request:

| field | value |
|---|---|
| `__EVENTTARGET` | `RadScheduler1` |
| `__EVENTARGUMENT` | `{"Command":"NavigateToNextPeriod"}` or `"NavigateToPreviousPeriod"` |
| `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `RadScriptManager1_TSM` | echoed from the previous response |
| `RadScheduler1_SelectedDateCalendar_SD` | `[[YYYY,M,D]]` |

`NavigateToDate` / `NextDay` with an explicit date return `500`. Posting only
`SelectedDateCalendar_SD` updates the hidden field but does not re-render the
schedule, so replay the postbacks serially, each with the viewstate of the
previous reply.

## Parsing

```html
<div id="RadScheduler1_628_0" title="…" class="rsApt rsAptSimple">
  <span id="RadScheduler1_ctl132_lblSubject">Algorithms &amp; Complexity</span>
  <span id="RadScheduler1_ctl132_lblOrario">(11:00-12:30)</span>
  <span id="RadScheduler1_ctl132_lblOsservazioni"></span>
</div>
```

`title` carries `course;teachers;semester`; `lblOrario` carries the wall-clock
range. Times are Europe/Zurich with no timezone in the payload, so the CLI does
no conversion. Absence of an appointment means the room is free. The markup
renders one of two ways depending on the response (`<font>` inside the span, or
a `style=` attribute), which is why the parser strips tags instead of matching
them.

Rooms answering `non abilitato` (currently D2.21, D3.03, D4.08, D5.03, SI-008)
have no timetable at all. The public website still paints them green, treating
"no appointments" as free; the CLI reports them as `??` instead.

## Booking

There is no booking endpoint. `usirooms.xyz` only builds `mailto:` links, with
the addresses obfuscated through a substitution table in its `app.js`:

| rooms | address | language |
|---|---|---|
| east campus (`C*`, `D*`) | `decanato.inf@usi.ch` | English |
| black / red / main | `gestione-aule.lu@usi.ch` | Italian |

`book` reproduces those templates, fills in room, date and time, and hands the
`mailto:` to the OS default client (`open` on macOS, `os.startfile` on Windows,
`webbrowser` elsewhere). Line breaks are `%0D%0A` per RFC 6068; the original
site emits bare `%0A`, which some clients collapse.

## Building

PyInstaller, driven by the `Makefile`. It creates `.venv-build` on first use, so
your system Python and pyenv are never touched.

| command | result |
|---|---|
| `make` / `make build-dir` | `dist-dir/usirooms/` — onedir bundle, recommended |
| `make build-one` | `dist/usirooms` — single self-unpacking file |
| `make install` | bundle into `~/.local/lib/usirooms` + symlink in `~/.local/bin` |
| `make uninstall` | removes both |
| `make clean` | drops `build/`, `dist/`, `dist-dir/`, `.venv-build/` |

`PREFIX` relocates the install: `make install PREFIX=/usr/local`.

Requirements: macOS with Xcode command line tools (`xcode-select --install`) for
`codesign` and the SDK PyInstaller links against, `python3` 3.9+, and network
access on the first build. No `requirements.txt` — the CLI is stdlib-only.

### Artifact cost

Measured with `--help`, arm64, Python 3.13.3:

| artifact | size | startup |
|---|---|---|
| `python3 usi_rooms.py` | — | 0.36 s |
| `dist-dir/usirooms/usirooms` (onedir) | 20 MB dir | **0.10 s** |
| `dist/usirooms` (onefile) | 7.8 MB file | 3.8–4.2 s |

Onefile unpacks itself into a temp directory on every invocation, so macOS
re-validates a freshly written Mach-O each run; ad-hoc signing does not change
that. A `day` call already spends ~0.3 s on the network, so onedir is the
default for a reason.

### Rebuilding

`make` wipes `build/` every time (`--clean` is baked into `PYI_FLAGS`) and
rebuilds the venv only when `.venv-build/bin/pyinstaller` is missing. After
editing `usi_rooms.py`: `make && make install`.

### Signing and distribution

The Makefile ad-hoc signs the output (`codesign -s -`), enough for the machine
that built it and for copies that never acquired a quarantine attribute.
Anything fetched through a browser or mail is quarantined, so distribution needs
a Developer ID certificate plus `notarytool` submission. Artifacts match the
architecture of the Python that built them; for a universal binary use a
universal2 Python.

## Troubleshooting

| symptom | cause and fix |
|---|---|
| `error: command not found: pyinstaller` | stale Homebrew shim pointing at a removed interpreter; use `make`, not `pyinstaller` |
| `zsh: command not found: usirooms` after `make install` | `~/.local/bin` not on `PATH`; add `export PATH="$HOME/.local/bin:$PATH"` |
| `bad CPU type in executable` | wrong architecture; rebuild with a Python of the target arch |
| `"usirooms" cannot be opened because the developer cannot be verified` | quarantined copy; `xattr -d com.apple.quarantine` on the bundle, or sign and notarize |
| exits 1 with `config file not found` | `--config` or `$USI_ROOMS_CONFIG` points at a missing file; unset it |

## Fragility

- One HTTP request per day of horizon; cache `(room, date)` and prefer today.
- Upstream is a scraped timetable, not an SLA'd API: the viewstate has no
  `__EVENTVALIDATION` (which is why replay works), but schema changes break the
  regexes.
- Cloudflare fronts the proxy; `aule.usi.ch` itself is unprotected.
- `usirooms.xyz` is an unofficial student project, unaffiliated with USI. So is
  this CLI.
