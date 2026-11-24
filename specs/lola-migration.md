# Moving air-picture from the laptop to lola

Status: cut over to lola 2026-11-24 at 17:53 EST. Waiting on the dongle move.
Surveyed both machines 2026-11-24.

## Progress

- [x] node 26 on lola; wrangler 4.168 runs
- [x] lola's mcp-sdr pulled to current
- [x] air-picture cloned to `~/air-picture` on lola, venv built with Python 3.13, 179 tests pass
- [x] `~/mcp-sdr` added to the mcp-sdr search path (lola resolves it)
- [x] the five jobs templated in `launchd/` with `install.sh` (not loaded on lola yet)
- [x] `build_and_push.sh` reads a Cloudflare token from `.env`
- [x] `.env` copied to lola (mode 600)
- [x] test on a snapshot: 1-minute scan (receiver 0, OpenSky 55, deploy stubbed out) and site build
- [x] Cloudflare Pages token (Account > Cloudflare Pages > Edit) and account ID in `.env`, verified
- [x] cutover 17:53: laptop jobs stopped and their plists moved to
  `~/air-picture-laptop-launchd-backup/` (so a login can't reload them);
  database copied with `.backup` (286,080 flights, integrity ok) with
  reports, `.env` and alert state; deploy from lola succeeded;
  `launchd/install.sh` loaded all five jobs on lola
- [ ] move the dongle and whip (you); scans use OpenSky alone until then

## Why

The laptop needs to travel again. air-picture needs a machine that stays
put, stays awake, and keeps the dongle on the same antenna every day.
lola, the Mac Studio at the upstairs window, already does that for the
HackRF and drone-watch work.

This repo is public, so the plan names machines but not accounts,
addresses or credentials.

## What lola has

| | lola | Needed |
|---|---|---|
| Power | never sleeps (`sleep 0`), restarts after power loss, up 36 days | yes |
| Disk | 240 GB free | ~550 MB (repo, venv, 160 MB database) |
| dump1090-fa | 11.0, Homebrew (laptop has 10.2) | yes |
| rtl-sdr tools | installed | yes |
| Python | Homebrew 3.13 | yes |
| mcp-sdr | cloned at `~/mcp-sdr`, 2 commits behind origin | `git pull` |
| node / npx | **missing** | wrangler deploys the site |
| Network | ntfy, FAA, OpenSky, Anthropic, Cloudflare and Gmail SMTP all reachable | yes |
| **RTL-SDR dongle** | **none** | **yes** |

## The receiver is the real question

lola has **no RTL-SDR**. `rtl_test` finds nothing. Its only radio on USB is
the HackRF One, and that won't do for ADS-B here:

- dump1090-fa, which sdr_mcp drives, supports RTL-SDR, not HackRF.
- AIS-catcher uses the HackRF, and so does the drone-watch sweep every day
  from 13:25 to 14:35. Contending for it would break both of them.

So the dongle moves with the job: the **Nooelec NESDR SMArt v5** now on
the laptop goes to lola.

**Decided 2026-11-24: the laptop's antenna moves with the dongle.** The
antenna already on lola belongs to the HackRF and stays with it.

The laptop's receiver is weak: about 3 unique aircraft in a 5-minute scan,
where dozens would be normal. The antenna is the likeliest cause, so set
it up properly when it moves:

- It's a whip on the Nooelec. Kit whips are usually general-purpose, not
  tuned for 1090 MHz, which may explain the weak reception.
- If it's a telescoping one, pull each arm out
  to about 6.9 cm (a quarter wavelength at 1090 MHz).
- Mount it vertically, because ADS-B is vertically polarized, as high and
  as close to the window glass as you can, on a short cable.

The first scan by hand on lola (cutover step 5) shows whether this worked.
If it still hears only a handful of aircraft, the next step is a dedicated
1090 MHz antenna.

## What has to change

1. **Paths.** lola uses a different account, so its home directory is
   different. All five launchd plists hard-code the laptop's home and must
   be rewritten. The code's own paths are relative (`DB_PATH` sits next to
   `config.py`) or use `~`, so they're fine.
2. **mcp-sdr location.** `config._SDR_MCP_CANDIDATES` checks `~/Projects`
   and `~/Documents`. lola's checkout is in `~/mcp-sdr`. Either set
   `SDR_MCP_PATH` in lola's `.env`, or add `~/mcp-sdr` to the candidate
   list. Adding it is the safer choice: a wrong path costs the SDR quietly
   (see the comment in `config.py`).
3. **Site deploys.** lola needs node, and wrangler needs authorizing
   there, with either `wrangler login` (interactive, you'd run it) or a
   `CLOUDFLARE_API_TOKEN` limited to Pages for this one project.
4. **Secrets.** Copy `.env` across with `scp`. It stays uncommitted. It
   holds the Anthropic key, ntfy, the Gmail app password and the Facebook
   token.
5. **Do not copy the xhci LaunchDaemon.** `local.sdr.unload-xhci-driver`
   unloads `AppleUSBXHCI` at boot. On lola that would take the USB
   controller away from the external drive, the HackRF and the VM's
   radios. It's loaded on the laptop but not running, and nothing current
   seems to need it.
6. **Mac notifications.** The delivery-failure alert in `alerts.py` would
   show on lola's screen, which nobody watches. The ntfy and email alerts
   are unaffected.
7. **Claude Desktop.** The `sdr-adsb-local` MCP entry on the laptop
   expects the dongle on the laptop. Once the dongle moves, point that
   entry at lola over SSH, the way `sdr-hackrf-lola` already works. The
   dongle's other SDR use (tuning and scanning by hand) goes through that
   entry. A scheduled scan holds the dongle for 5 minutes in every 30, so
   work by hand during a scan can collide with it.

## Steps

### Prepare lola (no downtime; the laptop keeps running)

1. `brew install node`
2. `cd ~/mcp-sdr && git pull`, then rebuild its venv if its dependencies
   changed.
3. Clone air-picture to `~/air-picture`, outside any synced folder (see
   mcp-sdr's `MULTI_MAC_SETUP.md` on why a synced `.venv` breaks).
4. Build its venv with Homebrew Python 3.13: `pip install -r
   requirements.txt`, then `pip install -e ~/mcp-sdr`.
5. Commit the `~/mcp-sdr` candidate (change 2) and pull it on lola.
6. Copy `.env`. Authorize wrangler, then run `build_and_push.sh` by hand
   against a copy of the database to prove deploys work from lola.
7. Generate the five plists with lola's paths. Don't load them yet.
8. Run the test suite on lola.

### Cut over (about 15 minutes, best just after the 10:00 report)

1. Laptop: `launchctl bootout` all five `local.air-picture.*` jobs. Wait
   for any scan in progress to finish. The scan lock shows it.
2. Laptop: take a consistent copy of the database:
   `sqlite3 air_picture.db ".backup /tmp/ap.db"`. A plain copy can miss
   the WAL.
3. Copy `ap.db`, `reports/` and `.alert_state.json` to lola.
4. Move the dongle and antenna. On lola, `rtl_test -t` should list the
   NESDR.
5. lola: `agent.py --scan` by hand. The log should show `receiver N`,
   with N > 0, alongside OpenSky.
6. lola: `launchctl bootstrap` the five plists.
7. Next hour: confirm the site deployed. Next 10:00: confirm the email
   and ntfy arrive.

The OpenSky fallback means any scan that runs mid-move still records
traffic.

### Clean up (a week later)

- Laptop: remove the plists and the xhci daemon. Archive or delete the
  laptop copy of the database once lola's has a week of new data on top.
- Update the README's install section and the `requirements.txt`
  comment, which still name `~/Projects/mcp-sdr`.

### Rollback

On lola, `launchd/install.sh --remove`. On the laptop, move the plists back
from `~/air-picture-laptop-launchd-backup/` and bootstrap them, copy lola's
database back, and move the dongle back. The laptop
keeps its database until cleanup, so the only loss is the scans lola ran.

## Open questions

1. ~~What antenna?~~ Settled: the laptop's antenna moves to lola with the
   dongle (see "The receiver is the real question").
2. wrangler on lola: interactive login or a scoped API token?
3. ~~Should the laptop keep anything?~~ Settled: no. The laptop gives up
   both the dongle and the antenna.
