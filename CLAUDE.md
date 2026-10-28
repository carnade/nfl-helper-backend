Before pushing follow-up commits to a branch that already has a PR, check whether that PR has been merged (`gh pr view <n> --json state`). Pushing to a merged branch strands the work silently — it lands nowhere and no open PR shows it. Branch from the updated `main` and cherry-pick instead.

Check it **immediately before the push**, not when the branch was created. A PR merged in between is exactly the case that gets missed, and it is how work has been stranded twice: once by checking at branch time and pushing hours later, once by printing `MERGED` and continuing anyway because the check and the push were chained together. Read the answer before acting on it.

PRs here are squash-merged, so a branch's commits never become ancestors of `main`. `git merge-base --is-ancestor` will report merged work as missing. Check by commit subject against `git log main` (a squash commit keeps the PR title, usually with `(#NN)` appended, so match on substring), or by whether the branch's diff against `main` is empty. A two-dot diff (`main..branch`) is not a merge test — it also counts main's newer commits as differences.

**Never spend odds API credits without asking first.** **The quota is 500 a month** and `credits_remaining` on `/odds/status` is what is left of the current billing period, not of the season — it comes straight from the API's `x-requests-remaining` header. It resets monthly; it does not accumulate. October 2026 ran out with a week still to play, which is what prompted the sizing below.

A refresh costs `3` for the bulk game-lines call plus `markets x regions` for **each** event inside the lookahead window — so `3 + (games x len(PROP_MARKETS))` at one region. With 13 games and 5 prop markets that is ~68, and the two scheduled runs come to ~136 a week, or ~1470 for the rest of a season from late October.

Runs **Thursday and Saturday** (`REFRESH_CRON_DAYS`), and the window is per weekday (`PROPS_LOOKAHEAD_BY_WEEKDAY`): **Thursday 2 days, Saturday 3**. Sized so the two runs partition the week rather than overlap it — Thursday's cutoff is Saturday morning and Saturday's run starts there, so nothing falls between them and no game is bought twice.

- Thursday takes Thursday night and any Friday fixture.
- Saturday takes its own fixtures, the Sunday slate, Sunday night and Monday night. It needs **3** days, not 2: Monday night is Tuesday 00:15 UTC, and there is no later run to pick it up.

Worst calendar month, measured against the real schedule at 5 markets:

| schedule | credits/month | games lost |
|---|---|---|
| Thu 4 / Sun 4, 6 markets (what ran out) | 729 | none |
| Thu 4 / Sun 2, 5 markets | 647 | none |
| Thu 3 / Sun 2 | 377 | none |
| **Thu 2 / Sat 3 (current)** | **337** | none |
| Thu 2 / Sat 2 | 317 | every Monday night game |
| Thu 1 / Sat 3 | 322 | the Friday fixtures |

Results worth not re-deriving:

- **Shrinking the second run's window saves almost nothing** — ~5 credits a season. No game kicks off between Tuesday morning and Thursday evening, so those days were already empty.
- **Removing the overlap is the whole saving.** A 4-day Thursday reached across the Sunday slate and bought all thirteen games that the second run then bought again.
- **Past that, it stops saving and starts losing fixtures** that no later run can pick up, because they have already kicked off.
- **Saturday beats Sunday for the second run**: it is the only placement that covers the late-season Saturday fixtures without a third run, and it is a day earlier, so there is time to act on a line and time to notice a failed run.

What the single reading costs, measured over 2,553 graded snapshots whose first and last readings were Thursday and Sunday: **only 18% of prop lines moved at all** between them, median 2.0 when they did. By market — passing yards 42%, receiving yards 25%, rushing yards 25%, receptions 6%, rush attempts 7%. So the number you would have bet is unchanged four times in five; what is given up is the movement signal, concentrated in passing yards. **Game lines are unaffected** either way — the bulk h2h/spreads/totals call is a flat 3 credits for the whole board and ignores this window.

**Both runs are needed; one is not an economy.** Of 2,156 props on Sunday-slate games, 22.7% were not posted on Thursday at all, and 163 player-games (17.5%) had no prop of any kind until later in the week — those players would simply be absent, not merely stale. It lands where roles firm up late: rush attempts 35% new and RBs 28%, against passing yards at 1.9%, because quarterbacks are known on Thursday and carry splits are not. The late props are not throwaway either — 82.7% carried a value flag against a 75.7% baseline. Thursday cannot be dropped either, since Thursday night games kick off before the second run, but at one or two events it is nearly free.

Measured Thursday-versus-Sunday, because there has never been a Saturday fetch to compare against; Saturday is 1.2 days out rather than 3, so it should catch most of that 22.7%, and the first Saturday run will say how much by what `player_prop_count` comes to against the ~317 these runs have produced.

`STARTUP_REFRESH_MAX_AGE_HOURS` must move whenever the days do. It is the widest legitimate gap between runs — Saturday to Thursday, 120 hours. Left narrower, a restart on the Tuesday or Wednesday reads as a missed run and buys a refresh it did not need, and a free-tier host restarts often.

The other lever is `len(PROP_MARKETS)`; `RETIRED_PROP_MARKETS` records what was dropped and why. Three paths spend them and nothing else does:

- `POST /admin/trigger-odds-fetch`
- `refresh_odds_and_cache()` / `odds_api.refresh_odds_data()` called directly
- the startup refresh, when cached odds are older than `STARTUP_REFRESH_MAX_AGE_HOURS`

Ask before any of those, every time, even when a refresh looks obviously useful. The user clicking the button on the Odds page is their own call and needs nothing.

Reading costs nothing and needs no permission: `/odds/status`, `/odds/games`, `/odds/props`, `/odds/results` and `/odds/prop-results` all serve what is already held in memory or in the snapshot history. Most questions about lines — including what has moved and by how much — can be answered from those, because the opening and current lines are both already stored.

The same goes for anything else bought rather than merely requested. Sleeper and nflverse are free and can be called freely; a paid or metered source cannot.

Run the tests with `/usr/local/bin/python3 -m pytest tests/` — plain `python` resolves to a 2.7 without pytest installed.

## Memory

The backend runs on Koyeb's free tier with **512 MB** and has been OOM-killed twice, most recently at 490 MB during startup. It is a **peak** problem, not a leak: loading players and nflverse costs ~240 MB between them and retains under 30, and what Python frees glibc keeps, so RSS only climbs. Weigh any change that holds more data in memory, and `/statistics` now reports `rss_mb` against `memory_limit_mb` so a climb is visible before it is fatal.

What is in place, and should not be undone without a measurement to replace it:

- **One scheduler worker** (`ThreadPoolExecutor(1)`) with `misfire_grace_time` at 3600. The staggering by cron hour is the intent; the single worker is what enforces it, because the DFS retry's now-plus-20-minutes trigger and the winter clock change both walk past the hours. The grace time has to stay large or a queued job is dropped as a misfire.
- **The scheduler starts after initialisation**, not at import (`start_scheduler()`, called from `_initialize`'s `finally`). Initialisation runs the same heavy functions on a plain thread the scheduler cannot see, so a boot at 14:58 had the 15:00 DFS scrape allocating beside initialisation's own.
- **`release_free_memory()`** (`gc.collect()` + `malloc_trim`) after every heavy job, via `_release_after`, and `limit_malloc_arenas()` at import so the freed bytes are not stranded across up to 8×ncores arenas.
- **Scrapers parse as little as possible.** The DFS scraper matches the row tags out of the raw HTML and builds a table of just those (`ROW_TAG_RE`): 27.6 MB → 1.6 MB per page, ~190 MB → ~11 MB per run. `scrape_ktc` reads each row's text while its page's soup is alive and collects per page rather than collecting bs4 `Tag`s — a `Tag` pins its whole document, and twenty of them were resident: 133 MB → 15 MB measured over the live twenty pages.
- **nflreadpy uses its filesystem cache**, set in `nflverse_stats.py`. Its default memory cache pinned ~22 MB of season parquet for 24 h behind the dicts that module distils it into, which no `gc` or `malloc_trim` in this process can reach.

Known and not done: **nflverse in a subprocess** is the biggest remaining win (~100 MB off the ~165 MB baseline) and its own change. `fantasy_points_data` and `odds_props_history` are never pruned and grow for the season (~8 MB now, ~16 by January). Production runs the Flask dev server, so request concurrency is unbounded, and `GET /dfs-salaries/data` and `/fantasy-points/data` each materialise a whole global per concurrent request.
