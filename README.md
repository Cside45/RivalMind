# RivalMind: v0.4 local telemetry alpha

## v0.4 telemetry foundation (experimental branch)

The v0.4 addon keeps the **existing minimal /rm panel**. It adds no overlays,
minimap buttons, networking, automatic gameplay or combat-log workarounds.

Observations saved in a bounded in-memory stream and exported to the local
`RivalMind.lua` SavedVariables file on logout or `/reload`:

| Source | Recorded fields | Important limitation |
| --- | --- | --- |
| Character | Class token and level changes | No character name, account name or GUID |
| Equipment | Inventory slot and equipped item ID | Does not inspect enchants, stats or upgrade value |
| Money | Copper balance; signed delta | **Net movement, not profit**; login balance is baseline |
| Bag inventory | Item ID and net quantity change | Does not prove looting, selling or item origin |
| Geography | Zone and subzone transition | No location coordinates or exact routes |

`/rm telemetry` reports a minimal one-line diagnostic count. The regular
window still defaults to hidden. There is no data sharing with RivalMind
maintainers, guildmates or AI providers in this build.

The v0.4 companion imports the strict `telemetryExport` (RT1) string into
a dedicated SQLite table, deduplicated by local source and event ID. It
shows observed character, last balance, net gold movement, number of zones,
equipment observations, and bag-item changes. Prior exports remain compatible.

**Important testing caveats:**
- v0.4 has not been validated in a real Forever client yet. Some character,
  equipment or bag fields may be unavailable or secret and are intentionally
  skipped rather than guessed.
- The current DB is account-scoped and does **not** separately identify each
  character. Limit v0.4 testing to one character until stable per-character
  anonymous profiles are implemented.
- `telemetryEvents` retains at most 600 records in WoW; SQLite retains older
  imported events. Import periodically and avoid inferring that a missing
  event never happened.
- Gold totals are observed **net copper changes** only. No vendor attribution
  or loot value calculation is implemented.
- Gear observations are **separated by type** in the latest v0.4 development
  build: S (initial slot snapshot) and D (observed slot change). Older v0.4
  E records remain explicitly **unclassified** because their origins are
  ambiguous. Reloading can still produce 19 new snapshot records, but they
  are not mislabeled as gear swaps.
- Bag counts reflect net changes across player bags, not exact loot pickup
  attribution. A baseline scan does not generate fake loot.
- This is a **development branch**, not a public signed Windows release.

### v0.4 test procedure
1. Make a backup of your current v0.2 `RivalMind` addon folder.
2. Copy the development branch's `addon/RivalMind` contents into the WoW
   `_forever_/Interface/AddOns/RivalMind` folder, or use the packaged alpha
   ZIP if one has been produced.
3. Confirm `/rm status` and `/rm quests` still work.
4. Type `/rm telemetry`. Change zones, swap an item, gain or spend a small
   amount of gold, and change bag item quantities through ordinary play.
5. Type `/reload`, then import `RivalMind.lua` using the new companion.
   Verify that raw observations match your actual actions and reimporting
   doesn't duplicate records.
6. Run `python -m unittest discover -s tests -v` to test the strict
   parser and local database schema.

For developer review, no model or AI account is needed to run any v0.4 test.


**Status:** early prototype. Not yet field-tested on a live WoW: Forever client.

RivalMind will eventually provide opt-in PvP, farming, and guild intelligence. This
starter is intentionally smaller: its purpose is to prove safe session collection,
SavedVariables export, and local SQLite import before enabling advanced features.

## What works in this alpha

- WoW: Forever addon (`Interface: 16001`): session time, XP gain/rate, level, deaths, latest zone.
- Tiny draggable session panel, **hidden by default**. `/rm` to toggle; `/rm status` for text.
- Last **100** session summaries retained in WoW's SavedVariables (bounded storage).
- **Quest Intelligence preview:** accepted, turned-in, quest-log completion and removed (reason unknown) events, including available quest title, ID, zone and reported reward XP. Last **200** quest events are kept locally.
- `/rm quests` shows a brief on-demand quest event summary; the existing session panel remains unchanged and hidden by default.
- Companion imports quest events into a separate SQLite table; v0.1 session exports are still supported.
- **v0.3 local companion analytics:** pairs quest acceptance and turn-in events by
  source and quest ID; displays elapsed wall-clock time and reported quest XP
  for recently turned-in quests.
- Missing acceptance records produce **unknown elapsed duration**. This is
  expected for quests accepted before the addon was installed or before the
  bounded record window. It does not fabricate completion times.
- Elapsed time includes AFK, travel, and time spent on other quests. It is
  *not* measured active questing time or a reliable route efficiency score yet.
- No changes to the v0.2 in-game UI or quest collection module in this step.
- Local companion: manually import the addon export into SQLite and view recent sessions.
- Companion has **no outbound network capabilities**, no AI authentication, no guild traffic.
- SQLite data stays in the local user profile. Reimports update records instead of duplicating.

Not yet implemented: combat encounter attribution, kill tracking, guild sync, live
PvP tactical advice, API connections, ChatGPT/Claude login, automatic import, auto-updates.
Quest event handling in **v0.2 is not yet tested inside WoW: Forever**. Removal events
must not be interpreted as abandonment; a turn-in may also trigger a removal.

## Install and test the addon

1. Copy the `RivalMind` directory (containing `RivalMind.toc`) into
   `World of Warcraft/_forever_/Interface/AddOns/`. Do not install into `_retail_`.
2. Launch WoW: Forever and enable RivalMind on the AddOns screen.
3. Run `/rm` to show the small panel. Run `/rm hide` or close it to hide it.
4. Play normally. The v0.2 addon collects player XP, deaths, zone, session time and basic quest events.
5. Type `/rm quests` after accepting and turning in a quest. Use `/reload` or log out to make WoW write `RivalMindDB.export` and `RivalMindDB.questExport` to disk.

Note: in-game memory does not automatically stream to the companion. WoW writes
SavedVariables on UI reload/logout. This first test deliberately avoids hacks or polling.

## Companion: developer run

Python 3.12+ is required to run from source. **End users will not need Python**
once a signed Windows executable is published.

```bash
python companion/rivalmind.py
# Or headless:
python companion/rivalmind.py --import-file "<your WoW _forever_/WTF/.../SavedVariables/RivalMind.lua>"
```

In the GUI, click Browse, select the `RivalMind.lua` SavedVariables file under your
WoW account/realm/character, and press **Import saved sessions**. Database is stored
under `%LOCALAPPDATA%/RivalMind/rivalmind.sqlite3` on Windows. Path selection is manual.

The companion **never executes** the Lua file. It reads only a strict ASCII-encoded
`export` field generated by our addon; malformed exports are rejected.

## Distribution plan

- **CurseForge:** publish the pure-Lua addon ZIP, `RivalMind-addon-0.2.0-alpha.zip`,
  tagged as WoW Forever 1.60.1 (interface 16001).
- **GitHub Releases:** publish a future standalone signed Windows companion binary.
  End users download a release asset, **not a Git clone**.
- **Open source:** public commits, reviews, reproducible documented build steps,
  SHA-256 checksums, and immutable GitHub releases where available.
- CI workflow currently builds an **UNSIGNED test executable** for internal alpha
  testing. Do not represent it as a trusted signed installer. Windows may show
  SmartScreen warnings. Never tell users to disable security protections.
- Future: signed installer, automatic trusted update checks (off by default),
  version compatibility check, signed release verification, explicit consent for AI.

## Security and privacy

- No developer-hosted service, no outbound connection, no telemetry, no API keys.
- No guild sharing in this build. Future guild exchange is **explicit opt-in**.
- This alpha records no character name, account name, GUID, or chat logs in its export.
- Quest titles, IDs, zone names and event timestamps are stored locally.
- Companion stores a one-way hash of the SavedVariables source path for deduplication.
- SQLite is local, under the user's profile; the companion never elevates privileges.
- **Do not commit or share your WTF or SavedVariables directory.**
- Windows executable builds require a trusted, reviewable release process and code signing
  before public distribution. Checksums and attestations verify origin/integrity, not safety.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Known limitations

- The v0.1 session collector was smoke-tested in-game for loading, XP, deaths and
  zone changes. The v0.2 quest acceptance and turn-in handlers have now
  been observed working in a live Forever client. The companion's new
  v0.3 elapsed-time analytics still require on-machine import verification.
- It does **not** register the restricted `COMBAT_LOG_EVENT_UNFILTERED` event.
- XP calculations across unusual leveling transitions may be approximate.
- It retains only 100 WoW session records and 200 quest events, so import periodically. Imported data remains
  in SQLite even after the addon ages older records out.
- Existing RivalTally/LootSnipe data is **not imported or modified** in this alpha.
- The source is published publicly as an experimental alpha. No signed companion installer or public release has been published.
## Validate quest efficiency locally (v0.3 companion)

1. Continue using the **v0.2 WoW addon**. Accept and turn in a new quest while it
   is loaded. In-game `/rm quests` verifies event collection.
2. Run `/reload` or log out to write `RivalMind.lua` SavedVariables to disk.
3. From the repository, run `python companion/rivalmind.py` (Python 3.12+).
   Choose your `RivalMind.lua` file and click **Import saved sessions**.
4. The local companion lists recent quest turn-ins with elapsed time and reward
   XP when acceptance and turn-in are both present. Missing starts show
   **unknown**. Reimporting should not create duplicates.

Run `python -m unittest discover -s tests -v` to validate the importer and
quest pairing. An unsigned Windows test executable may be available as a
GitHub Actions artifact after CI succeeds; it is **not a signed public installer**.
