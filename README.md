# usirooms

**Which USI Lugano rooms are free right now — and the booking e-mail, written
for you.**

`usirooms` answers the one question that otherwise needs a browser, a click and
a squint at a green/red grid: is this room free at 14:30, and if not, what is?
Then, when you pick one, it opens a reservation e-mail to the right office with
the room, date and time already filled in.

It exists primarily so **agents** can do this for you. Ask your coding agent a
normal question — "anything free on the east campus at 16?" — and it runs the
CLI, reads the answer, and can follow up by opening the prefilled mail. Install
the skill once and the agent knows the commands, the output format, and how to
build the tool if it is missing.

> Unofficial student project, not affiliated with USI. It reads the public
> timetable, so it is strictly read-only: nothing can be reserved
> programmatically. `book` prepares the e-mail; a human still presses send.

## What you can ask

| You say | What happens |
|---|---|
| "Which east campus rooms are free at 14:30?" | scans the campus, lists free rooms with the lecture that occupies each busy one |
| "Anything free at 16:00 today?" | scans every building in order, from the black building to the main one |
| "Is C1.03 free tomorrow at 11?" | one room, one instant, yes or no |
| "What does D3.01 look like today?" | the full timetable plus the free gaps between lectures |
| "Book D0.02 for 16:00 to 17:00 tomorrow" | checks the slot, then opens your mail client with the reservation e-mail prefilled |
| "Find me any free room right now and book two hours" | scans, picks a free room, prepares the mail |

Nothing is sent without you. If the slot is already taken, the CLI refuses and
says which lecture is in the way.

## Install the CLI

macOS, Python 3.9+:

```bash
git clone https://github.com/kvn1351/usirooms-cli
cd usirooms-cli
make && make install          # -> ~/.local/bin/usirooms
usirooms --help
```

The first `make` sets up its own build venv and takes a few seconds; nothing is
installed into your system Python. Make sure `~/.local/bin` is on your `PATH`.
Requires the Xcode command line tools (`xcode-select --install`).

Prefer no build step? `python3 usi_rooms.py --help` works straight from the
checkout.

## Install the skill (for agents)

```bash
npx skills add kvn1351/usirooms-cli -g -a '*'
npx skills list -g
```

That drops a single file into `~/.agents/skills/usirooms-cli` and wires it to
every agent the installer detects, so the next session knows how to use the CLI
— including cloning and building it when `usirooms` is not on `PATH` yet.

Either way the install needs your GitHub credentials: the repository is
private, so the clone authenticates through your existing `gh` login.

### Or let the agent do it

Paste the link and say what you want — no commands to type:

> Install the skill from https://github.com/kvn1351/usirooms-cli and build the
> CLI it needs.

The skill carries its own bootstrap instructions (look for `usirooms`, fall back
to a checkout, otherwise clone and `make && make install`), so the agent lands
in exactly the same place as the two commands above.

## Use it

```bash
usirooms free --time 14:30                  # both campuses
usirooms free --campus east --time 14:30    # east campus only
usirooms at --room C1.03 --time 14:30       # exit 1 when busy
usirooms day --room D3.01                   # timetable + free gaps
usirooms book --room D0.02 --from 16:00 --to 17:00
```

```
$ usirooms free --campus east --time 16:00
  BUSY C1.03   Interazione orale A2-B1corso pomeridiano (COM)Trincado PamelaSA 2026-2027
  FREE C1.04   
  BUSY C1.05   High-Performance Computing
  BUSY D0.02   Game Design & Development
  BUSY D0.03   Enterprise Information Systems
  BUSY D0.10   Competitive Programming
  BUSY D1.13   Computational Biology and Drug Design
  BUSY D1.14   Numerical Computing
  FREE D2.19   
  ??   D2.21   not enabled in the scheduler ('non abilitato')
  FREE D3.01   
  ??   D3.03   not enabled in the scheduler ('non abilitato')
  BUSY D4.01   Meeting OR Group
  ??   D4.08   not enabled in the scheduler ('non abilitato')
  FREE D5.01   
  ??   D5.03   not enabled in the scheduler ('non abilitato')

2026-10-20 16:00 [east campus]: 4 free / 16
```

`FREE` and `BUSY` are what you expect; `??` means the room has no timetable in
the scheduler at all, so it is unknown rather than available. Dates are
`--date YYYY-MM-DD` (default today), and times are Lugano wall clock.

Booking opens your default mail client with everything filled in:

```
$ usirooms book --room D0.02 --from 16:00 --to 17:00 --date 2026-10-23
To:      decanato.inf@usi.ch
Subject: Booking room D0.02

Hi, I'd like to book the room D0.02 in the east campus on Friday 23 October 2026 from 16:00 to 17:00.

Thank you!

Best regards,
Your Name
```

East campus rooms mail `decanato.inf@usi.ch` in English; the black, red and main
buildings mail `gestione-aule.lu@usi.ch` in Italian. Add `--no-open` to print
the `mailto:` link instead of launching the client, `--json` for structured
output, or `--force` to prepare a mail for a slot that is occupied.

## Defaults file

Optional — everything works without it. It stores the scope and signature you
use most, so that bare commands stay short.

Create it with the CLI:

```bash
usirooms config --campus east --buildings east,east2 --language english --name "Your Name"
usirooms config                    # show the file
usirooms config --unset name       # drop one key
usirooms config --reset            # delete it, back to built-in defaults
```

Or write `~/.config/usirooms/config.json` by hand:

```json
{
  "campus": "east",
  "buildings": ["east", "east2"],
  "language": "english",
  "name": "Your Name"
}
```

| key | allowed values | effect |
|---|---|---|
| `campus` | `east`, `west` | default scan scope; also picks the booking office when a room cannot be placed |
| `buildings` | list drawn from `black`, `east`, `east2`, `red`, `main` | default scan scope, takes priority over `campus` |
| `language` | `english`, `italian` (also `en`, `it`) | language of the booking e-mail, independent of campus |
| `name` | any non-empty string | signature at the end of the booking e-mail |

Unknown keys are ignored with a warning; an invalid value exits 1 naming the
offending key. The file is read from `$USI_ROOMS_CONFIG`, else
`~/.config/usirooms/config.json`; `--config PATH` overrides both.

Command-line flags always win, and every scan prints the scope it actually used
(`2026-10-20 16:00 [west campus]: 5 free / 25`), so a stored default can never
silently hide buildings.

## More

- [`docs/internals.md`](docs/internals.md) — the data source, why dates cost one
  request per day, build targets, signing, troubleshooting.
- [`skills/usirooms-cli/SKILL.md`](skills/usirooms-cli/SKILL.md) — what the agent
  reads.
