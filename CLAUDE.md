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

`STARTUP_REFRESH_MAX_AGE_HOURS` must move whenever the days do. It is the widest legitimate gap between runs — Saturday to Thursday, 120 hours. Left narrower, a restart on the Tuesday or Wednesday reads as a missed run and buys a refresh it did not need, and a free-tier host restarts often.

The other lever is `len(PROP_MARKETS)`; `RETIRED_PROP_MARKETS` records what was dropped and why. Three paths spend them and nothing else does:

- `POST /admin/trigger-odds-fetch`
- `refresh_odds_and_cache()` / `odds_api.refresh_odds_data()` called directly
- the startup refresh, when cached odds are older than `STARTUP_REFRESH_MAX_AGE_HOURS`

Ask before any of those, every time, even when a refresh looks obviously useful. The user clicking the button on the Odds page is their own call and needs nothing.

Reading costs nothing and needs no permission: `/odds/status`, `/odds/games`, `/odds/props`, `/odds/results` and `/odds/prop-results` all serve what is already held in memory or in the snapshot history. Most questions about lines — including what has moved and by how much — can be answered from those, because the opening and current lines are both already stored.

The same goes for anything else bought rather than merely requested. Sleeper and nflverse are free and can be called freely; a paid or metered source cannot.

Run the tests with `/usr/local/bin/python3 -m pytest tests/` — plain `python` resolves to a 2.7 without pytest installed.

The backend runs on Koyeb's free tier with 512 MB and has been OOM-killed before, so weigh any change that holds more data in memory. Heavy scheduled jobs are deliberately staggered so two never start in the same hour.
