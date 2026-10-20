---
name: usirooms-cli
description: Check USI Lugano room availability and prepare a booking e-mail. Use when asked which rooms are free at a given time, whether one specific room is free, a room's daily timetable, or to start a room reservation at USI (east or west campus).
---

# usirooms-cli

Read-only availability for USI Lugano teaching rooms, read from the university
scheduler (`aule.usi.ch`). `book` only *prepares* an e-mail; nothing is
reserved and nothing is sent.

## Invocation

```bash
usirooms <command> [flags]
```

The binary normally lives at `~/.local/bin/usirooms` (symlink into
`~/.local/lib/usirooms`).

## If `usirooms` is missing

Installing this skill does **not** install the CLI. Never guess availability,
and do not fall back to the website by reading screenshots: build the tool.

1. Check for the binary: `command -v usirooms`.
2. Check for a checkout: if `usi_rooms.py` exists in the current project or a
   sibling directory, `python3 usi_rooms.py <command> [flags]` runs with no
   build at all.
3. Otherwise clone and build (roughly 10-30 s on first run, mostly the venv):

   ```bash
   git clone https://github.com/kvn1351/usirooms-cli   # or: gh repo clone kvn1351/usirooms-cli
   cd usirooms-cli && make && make install
   ```

   `make` creates `.venv-build`, installs PyInstaller into it, and produces
   `dist-dir/usirooms/`; `make install` puts the binary in `~/.local/bin`. The
   repository is private, so the clone needs the user's GitHub credentials
   (`gh auth status` should be green).

4. Verify: `usirooms --help | head -3`, then run the actual query.
5. If `make` fails, report the blocker instead of improvising:
   `xcode-select --install` fixes a missing `codesign`/SDK, and the build needs
   network access for the venv. `~/.local/bin` must be on `PATH` for step 4; if
   it is not, call the binary by path (`~/.local/bin/usirooms`) or use
   `dist-dir/usirooms/usirooms` directly.

Do not run `make build-one` for this: the single-file artifact costs ~4 s of
startup per call, which is pure waste for a CLI.

## Commands

| goal | command |
|---|---|
| rooms free at 14:30 today, east campus | `usirooms free --campus east --time 14:30` |
| same, another day | `usirooms free --campus east --time 14:30 --date 2026-10-23` |
| is one room free at a time | `usirooms at --room C1.03 --time 14:30` |
| one room's day: lectures + free gaps | `usirooms day --room C1.03` |
| which rooms exist at all | `usirooms rooms --campus east` |
| prepare a booking e-mail | `usirooms book --room D0.02 --from 16:00 --to 17:00` |

Exit codes: `0` free/success · `1` busy, or `book` refused an occupied slot ·
`2` bad input or upstream failure.

## Reading the output

`free` prints one line per room with the relevant time range, then a summary:

```
  FREE D0.02   12:30-15:30
  BUSY C1.03   13:30-15:00 Software Atelier 3: The Web
  ??   D2.21   not enabled in the scheduler ('non abilitato')

2026-10-20 13:45 [east campus (east+east2)]: 3 free / 16
```

- A `FREE` line already carries its whole window, so you do **not** need a
  `day` call per room to answer "how long is it free".
- The bracketed scope is the *effective* one (flags plus config) and names the
  buildings it covers. Never claim a scan covered every building without
  checking it.
- `--time` defaults to now, so `usirooms free --campus east` answers "what is
  free right now".
- `?? … non abilitato` means the room is missing from the scheduler. The public
  website renders these green; they are **not** verified free — do not report
  them as available.
- Intervals are half-open: a lecture ending at 15:00 leaves the room FREE at
  15:00.
- Times are Europe/Zurich wall clock exactly as served upstream. There is no
  timezone in the payload, so do not convert them.

## JSON shapes

`free`, `rooms`, `day` and `book` all accept `--json`. The exact shapes, so you
do not have to guess keys:

```jsonc
// free --json
{"date": "2026-10-20", "time": "13:45",
 "scope": "east campus (east+east2)",
 "rooms": [{"room": "D0.02", "free": true, "window": "12:30-15:30", "busy": null},
           {"room": "C1.03", "free": false, "window": null,
            "busy": "13:30-15:00 Software Atelier 3: The Web"},
           {"room": "D2.21", "error": "not enabled in the scheduler ('non abilitato')"}]}

// rooms --json
{"scope": "east campus (east+east2)", "rooms": ["C1.03", "..."]}

// day --json  (times are full ISO timestamps, Europe/Zurich wall clock)
{"room": "D0.02", "date": "2026-10-20",
 "appointments": [{"title": "Generative AI",
                   "start": "2026-10-20T09:00:00", "end": "2026-10-20T10:30:00"}],
 "free": [{"start": "2026-10-20T12:30:00", "end": "2026-10-20T15:30:00"}]}

// book --json
{"to": "decanato.inf@usi.ch", "subject": "Booking room D0.02",
 "body": "Hi, ...", "mailto": "mailto:..."}
```

Prefer one `free --json` over looping `day` per room: it is one process and
already includes windows. `free` also prints a human line per room for use
without JSON.

## Room names

One room per prefix family, so validate a name before querying it:

| building | campus | names |
|---|---|---|
| east | east | `C1.03`–`C1.05`, `D0.02`, `D0.03`, `D0.10`, `D1.13`, `D1.14` |
| east2 | east | `D2.19`, `D2.21`, `D3.01`, `D3.03`, `D4.01`, `D4.08`, `D5.01`, `D5.03` |
| red | west | `A-11` … `A-34` (dash, not dot: no `A1.02`) |
| black | west | `SI-003`, `SI-004`, `SI-006`, `SI-007`, `SI-008`, `SI-013`, `SI-015` |
| main | west | `250`, `251`, `253`, `254`, `354`, `355` |

`usirooms rooms` prints the authoritative list. An unknown name cannot be told
apart from an unscheduled room upstream, so the CLI says so explicitly:

```
error: not enabled in the scheduler ('non abilitato'); 'A1.02' is not in the
room inventory either (see `usirooms rooms`)
```

If you see that, the room code is wrong or the room is not covered. Ask which
building, or offer the nearest matches. If the hint is absent, the room exists
but has no timetable, which is a different answer: unknown, not free.

## Automation notes

- `--no-open` on `book` prints the `mailto:` URL and launches no mail client —
  use it in any non-interactive context.
- `book` refuses a slot that clashes with a lecture and exits `1`. Never add
  `--force` unless the user explicitly asks to send a conflicting request.
- Cost: one HTTP GET per room scanned (~16 east, ~25 west, ~41 all), a few
  seconds; `--date` adds one POST per day of horizon. Prefer today or a nearby
  date over scanning weeks ahead.
- Never say a room is booked. `book` yields an e-mail for the user to send; the
  reservation depends on `decanato.inf@usi.ch` (east) or
  `gestione-aule.lu@usi.ch` (west) confirming.

## Scope and defaults

Precedence: `--building` > `--campus` > config `buildings` > config `campus` >
all rooms, then the config `exclude` list is subtracted. `--campus east` covers
`east` + `east2`; `--campus west` covers `black` + `red` + `main`.

`exclude` is how a user skips buildings they never use. It only filters scans:
an explicit `--building` or `--room` still reaches an excluded building, and the
scope line says so (`[east campus (east+east2), excluding east2]`). If a scan
comes back with fewer rooms than the campus implies, read that bracket before
suspecting the tool.

Optional defaults file — `$USI_ROOMS_CONFIG`, else
`~/.config/usirooms/config.json`:

```json
{
  "campus": "east",
  "buildings": ["east", "east2"],
  "exclude": ["east2"],
  "language": "english",
  "name": "Your Name"
}
```

Write it with the CLI instead of hand-editing JSON:

```bash
usirooms config --campus east --buildings east,east2 --language english --name "Their Name"
usirooms config          # show      · --unset KEY  · --reset
```

Read it before diagnosing an unexpected scope: a config default silently
narrows a bare `usirooms free`, and `language` can flip a booking mail between
English and Italian independently of the campus.

## Common mistakes

- Passing `--time` to `book` — it takes `--from` and `--to`.
- Using `--building east-campus` — campuses are `--campus east|west`; buildings
  are `black`, `east`, `east2`, `red`, `main`.
- Expecting cheap arbitrary dates: `--date` walks the scheduler one day per
  POST, so querying a month out costs ~30 requests.
- Treating a free room as free all day: the answer holds for the queried
  `--time` only. Ask `day --room` for the full window.
