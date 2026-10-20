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
| prepare a booking e-mail | `usirooms book --room D0.02 --from 16:00 --to 17:00` |

Exit codes: `0` free/success · `1` busy, or `book` refused an occupied slot ·
`2` bad input or upstream failure.

## Reading the output

`free` prints one line per room, then a summary:

```
  FREE D0.02
  BUSY C1.03   Software Atelier 3: The Web
  ??   D2.21   room not enabled in the scheduling system

2026-10-20 14:30 [east campus]: 3 free / 16
```

- The bracketed scope is the *effective* one (flags plus config). Never claim a
  scan covered every building without checking it.
- `?? … non abilitato` means the room is missing from the scheduler. The public
  website renders these green; they are **not** verified free — do not report
  them as available.
- Intervals are half-open: a lecture ending at 15:00 leaves the room FREE at
  15:00.
- Times are Europe/Zurich wall clock exactly as served upstream. There is no
  timezone in the payload, so do not convert them.

## Automation notes

- `--json` gives structured output for `day` and `book`; `free` has no JSON.
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
all rooms. `--campus east` covers `east` + `east2`; `--campus west` covers
`black` + `red` + `main`.

Optional defaults file — `$USI_ROOMS_CONFIG`, else
`~/.config/usirooms/config.json`:

```json
{
  "campus": "east",
  "buildings": ["east", "east2"],
  "language": "english",
  "name": "Your Name"
}
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
