# usirooms-cli

Unofficial REST/HTTP client for USI Lugano room availability.

Reverse-engineered from `usirooms.xyz` (frontend) and its upstream `aule.usi.ch`
(ASP.NET WebForms + Telerik RadScheduler). Read-only: **the university exposes no
booking API**.

## Endpoints

### Proxy (what usirooms.xyz calls)
```
GET https://www.usirooms.xyz/api/aule.php?name=C1.03
```
- `name` = room name (`C1.03`, `A-11`, `SI-003`, `250`, `D5.03`, ...)
- Returns the raw upstream HTML for **today only**
- `access-control-allow-origin: https://usirooms.xyz` → browser requests from
  another origin are blocked; `curl`/server-side works
- `POST` → `400`; only `GET` is proxied
- Source: <https://github.com/Steeven9/USIrooms/blob/main/api/aule.php>

### Upstream (no proxy, no auth)
```
GET  https://aule.usi.ch/aule/View.aspx?name=C1.03
POST https://aule.usi.ch/aule/View.aspx?name=C1.03
```
GET sets `ASP.NET_SessionId` and returns a day view (`RadScheduler1_SelectedDateCalendar_SD`
= today). Unknown room → body starting `non abilitato`.

Date switching is a **classic WebForms postback** (no query parameter exists —
`?date=`, `?d=`, `?selectedDate=` are all ignored):

| field | value |
|---|---|
| `__EVENTTARGET` | `RadScheduler1` |
| `__EVENTARGUMENT` | `{"Command":"NavigateToNextPeriod"}` / `"NavigateToPreviousPeriod"` |
| `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `RadScriptManager1_TSM` | echoed from the previous response |
| `RadScheduler1_SelectedDateCalendar_SD` | `[[YYYY,M,D]]` |

One POST moves exactly ±1 day; there is no `NavigateToDate` command (500).
Replay the POST serially, each with the viewstate of the previous reply.

### Parsing
```html
<div id="RadScheduler1_628_0" title="…" class="rsApt rsAptSimple">
  <span id="RadScheduler1_ctl132_lblSubject">Algorithms &amp; Complexity</span>
  <span id="RadScheduler1_ctl132_lblOrario">(11:00-12:30)</span>
  <span id="RadScheduler1_ctl132_lblOsservazioni"></span>
```
`title` also carries `course;teachers;semester`. Times are Europe/Zurich wall
clock, no timezone in the payload. Absence of appointment = room free.

### Booking
No endpoint. `usirooms.xyz` only builds `mailto:` links (addresses obfuscated in
`app.js` with a substitution table):

| rooms | address | language |
|---|---|---|
| east campus (`C*`, `D*`) | `decanato.inf@usi.ch` | English |
| black / red / main | `gestione-aule.lu@usi.ch` | Italian |

`book` reproduces those templates and hands the `mailto:` to the OS default mail
client (`open` on macOS, `os.startfile` on Windows, `webbrowser` elsewhere), so
the compose window arrives with To / Subject / Body already filled. Nothing is
sent until you press send — the university has no programmatic reservation.

## Usage

```bash
./usi_rooms.py day   --room C1.03 [--date 2026-10-23] [--json]
./usi_rooms.py at    --room C1.03 --time 14:30 [--date 2026-10-23]   # exit 1 = busy
./usi_rooms.py free  --time 14:30 [--campus east|west] [--building east] [--date …]
./usi_rooms.py book  --room D0.02 --from 16:00 --to 17:00 [--campus east] [--date …] [--name …]
```

`book` checks the slot first and refuses to write if the room is occupied
(exit 1) unless `--force` is given. Flags: `--no-open` prints the `mailto:` URL
instead of launching the client, `--json` prints the message fields, `--name`
(or `$USI_BOOK_NAME`) overrides the signature, which otherwise comes from
`/usr/bin/id -F`.

Room sets per building live in `ROOMS` (mirrors `rooms.js`). Buildings:
`black` (SI-*), `east` (C1.*, D0.*, D1.1*), `east2` (D2.*–D5.*), `red` (A-*),
`main` (250–355).

`--campus` scopes a scan across buildings and picks the booking office; it is
orthogonal to `--building` (which narrows to one building and supplies the
phrase used in the mail body). Passing a building that is not on the given
campus is an error.

| `--campus` | buildings | mails |
|---|---|---|
| `east` | `east` + `east2` (C*/D*, Via La Santa) | `decanato.inf@usi.ch`, English |
| `west` | `black` + `red` + `main` (SI-*, A-*, 2xx/3xx) | `gestione-aule.lu@usi.ch`, Italian |

Rooms answering `non abilitato` (currently D2.21, D3.03, D4.08, D5.03, SI-008)
are not enabled in the university scheduler; the website still renders them
green as if free, so treat them as unknown, not available.

## Defaults file

Read on every run from `$USI_ROOMS_CONFIG`, else
`~/.config/usirooms/config.json` (`$XDG_CONFIG_HOME` respected), or `--config`.
Optional: with no file the CLI behaves exactly as before. Keys:

```json
{
  "campus": "east",
  "buildings": ["east", "east2"],
  "language": "italian",
  "name": "Your Name"
}
```

| key | values | effect |
|---|---|---|
| `campus` | `east` \| `west` | default scan scope; booking-office fallback for rooms the CLI cannot place |
| `buildings` | list from `black east east2 red main` | default scan scope, preferred over `campus` |
| `language` | `english` \| `italian` (or `en`/`it`) | mail body language, decoupled from campus |
| `name` | string | signature |

Precedence, most specific wins:

| setting | order |
|---|---|
| scan scope | `--building` → `--campus` → config `buildings` → config `campus` → every room |
| booking office | `--campus` → derived from the room → config `campus` |
| mail language | `--lang` → config `language` → campus (east English, west Italian) |
| signature | `--name` → `$USI_BOOK_NAME` → config `name` → `/usr/bin/id -F` |

Scan scope is echoed in the summary line, so a config default is never silent:
`2026-10-20 14:30 [west campus]: 5 free / 25`. An explicit `--building` also
overrides a conflicting config `campus` instead of erroring. Unknown keys warn;
invalid values and a missing `--config` path exit 1, while a missing default
path is simply ignored.

## Agent skill

`skills/usirooms-cli/SKILL.md` describes the CLI for coding agents: commands,
output semantics, exit codes, scope precedence and the traps (`?? non abilitato`
rooms, half-open intervals, `--date` cost). The `skills/<name>/` layout is
deliberate — installers package that directory on its own, so a skill install
pulls exactly one file and never the whole checkout.

Install it globally, into the same place as every other skill on the machine:

```bash
npx skills add kvn1351/usirooms-cli -g -a '*'   # -> ~/.agents/skills/usirooms-cli
npx skills list -g                              # verify it is listed
```

`-g` installs user-level, which is what `npx skills list -g` reports and what
most agents read (the rest get a symlink from their own skills directory);
`-a '*'` covers every agent the CLI detects. Without `-g` the skill lands in the
current project only (`./.agents/skills` plus `skills-lock.json`), so it stays
invisible to `list -g` and unavailable everywhere else — use that variant only
for a pinned, per-repo copy.

Manual fallback, no installer involved:

```bash
mkdir -p ~/.agents/skills/usirooms-cli
ln -s "$PWD/skills/usirooms-cli/SKILL.md" ~/.agents/skills/usirooms-cli/SKILL.md
```

The repo is private, so the clone uses your git credentials. Note that
`npx skill` (singular) is a different package that only resolves `skills/<name>`
inside `vercel-labs/agent-skills` and cannot install from here.

## Build & install

The CLI itself needs only Python 3.9+ (`python3 usi_rooms.py --help` works with
no install). To get a standalone `usirooms` binary, PyInstaller is driven by the
bundled `Makefile`; it creates its own build venv on first use, so your system
Python and pyenv are never touched.

```bash
git clone <repo> && cd usirooms-cli
make                 # recommended artifact: dist-dir/usirooms/
make install         # -> ~/.local/bin/usirooms + ~/.local/lib/usirooms/
usirooms free --campus east --time 14:30
```

### Targets

| command | result |
|---|---|
| `make` / `make build-dir` | `dist-dir/usirooms/` — onedir bundle, recommended |
| `make build-one` | `dist/usirooms` — single self-unpacking file |
| `make install` | copies the bundle to `~/.local/lib/usirooms` and symlinks `~/.local/bin/usirooms` |
| `make uninstall` | removes both |
| `make clean` | drops `build/`, `dist/`, `dist-dir/`, `.venv-build/` |

`PREFIX` relocates the install:
`make install PREFIX=/usr/local` (writes `/usr/local/bin` and
`/usr/local/lib/usirooms`).

### Build prerequisites

- macOS with the Xcode command line tools (`xcode-select --install`) for
  `codesign` and the SDK that PyInstaller links against.
- `python3` (3.9+) and network access on the first build, to create
  `.venv-build` and install PyInstaller into it.
- Nothing else: the CLI is stdlib-only, so there is no `requirements.txt`.

### Verified startup cost

Measured with `--help` on an arm64 Mac, Python 3.13.3:

| artifact | size | startup |
|---|---|---|
| `python3 usi_rooms.py` | — | 0.36 s |
| `dist-dir/usirooms/usirooms` (onedir) | 20 MB dir | **0.10 s** |
| `dist/usirooms` (onefile) | 7.8 MB file | 3.8–4.2 s |

Onefile unpacks itself into a temp directory on every invocation, so macOS
re-validates a freshly written Mach-O each run; ad-hoc signing does not change
that. Use it only when you need to move a single file around. A single `day`
call spends ~0.3 s on the network anyway, so onedir is the default for a reason.

### Rebuilding

`make` is incremental-safe: it wipes `build/` each time because the
`--clean` flag is baked into `PYI_FLAGS`, and rebuilds the venv only when
`.venv-build/bin/pyinstaller` is missing. After editing `usi_rooms.py`:

```bash
make && make install
```

### Signing and distribution

The Makefile ad-hoc signs the output (`codesign -s -`), enough for the binary to
launch on the machine that built it and on machines that copy it without the
quarantine attribute. Anything downloaded through a browser or received by mail
gets quarantined, so real distribution needs a Developer ID certificate plus
`notarytool` submission. Both artifacts match the architecture of the Python
that built them: `arm64` here. For a universal binary, build with a universal2
Python (`x86_64 arm64`).

### Troubleshooting

| symptom | cause and fix |
|---|---|
| `error: command not found: pyinstaller` | a stale Homebrew shim pointing at a removed interpreter; the Makefile uses its own venv, so invoke `make`, not `pyinstaller` |
| `zsh: command not found: usirooms` after `make install` | `~/.local/bin` is not on `PATH`; add `export PATH="$HOME/.local/bin:$PATH"` |
| `bad CPU type in executable` | built for the other architecture; rebuild with a Python of the target arch |
| `"usirooms" cannot be opened because the developer cannot be verified` | quarantined copy; `xattr -d com.apple.quarantine` on the bundle, or sign and notarize properly |
| bundle runs but exits 1 with `config file not found` | `--config` or `$USI_ROOMS_CONFIG` points at a missing file; unset it to fall back to the optional default path |

## Caveats

- One HTTP request per day of horizon; cache `(room, date)` and prefer today.
- The upstream is a scraped timetable, not an SLA'd API: viewstate has no
  `__EVENTVALIDATION` (good for replay), but schema changes break the regexes.
- `usirooms.xyz` is an unofficial student project, unaffiliated with USI.
- Cloudflare fronts the proxy; `aule.usi.ch` is unprotected and can be hit
  directly.
