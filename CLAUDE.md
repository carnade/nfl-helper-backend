Before pushing follow-up commits to a branch that already has a PR, check whether that PR has been merged (`gh pr view <n> --json state`). Pushing to a merged branch strands the work silently — it lands nowhere and no open PR shows it. Branch from the updated `main` and cherry-pick instead.

Check it **immediately before the push**, not when the branch was created. A PR merged in between is exactly the case that gets missed, and it is how work has been stranded twice: once by checking at branch time and pushing hours later, once by printing `MERGED` and continuing anyway because the check and the push were chained together. Read the answer before acting on it.

PRs here are squash-merged, so a branch's commits never become ancestors of `main`. `git merge-base --is-ancestor` will report merged work as missing. Check by commit subject against `git log main` (a squash commit keeps the PR title, usually with `(#NN)` appended, so match on substring), or by whether the branch's diff against `main` is empty. A two-dot diff (`main..branch`) is not a merge test — it also counts main's newer commits as differences.

**Never spend odds API credits without asking first.** **The quota is 500 a month** and `credits_remaining` on `/odds/status` is what is left of the current billing period, not of the season — it comes straight from the API's `x-requests-remaining` header. It resets monthly; it does not accumulate. October 2026 ran out with a week still to play, which is what prompted the sizing below.

A refresh costs `3` for the bulk game-lines call plus `markets x regions` for **each** event inside the lookahead window — so `3 + (games x len(PROP_MARKETS))` at one region. With 13 games and 5 prop markets that is ~68, and the two scheduled runs come to ~136 a week, or ~1470 for the rest of a season from late October.

The window is per weekday (`PROPS_LOOKAHEAD_BY_WEEKDAY`): **Thursday 3 days, Sunday 2**, sized so the two runs partition the week instead of overlapping it. Thursday + 3 days reaches Sunday 09:00 UTC, stopping just short of the 13:30 kickoffs, so Thursday buys Thursday night and any Friday or Saturday fixture while Sunday buys the slate plus Sunday and Monday night. Every game is bought once.

Worst calendar month, measured against the real schedule at 5 markets:

| Thursday window | credits/month | games lost |
|---|---|---|
| 4 days (what ran out) | 647 | none |
| **3 days (current)** | **377** | none |
| 2 days | 377 | late-season Saturday games |
| 1 day | 372 | Friday and Saturday games |

Three counter-intuitive results worth not re-deriving:

- **Shrinking Sunday saves almost nothing** — ~5 credits a season. No game kicks off between Tuesday morning and Thursday evening, so those days were already empty.
- **Thursday 4 to 3 is the whole saving.** Four days reached across the Sunday slate and bought all thirteen games that Sunday then bought again.
- **Below 3 days stops saving and starts losing fixtures**, and Sunday's run cannot pick them up because they have already kicked off.

What 3 days costs: Sunday's prop lines are first seen on Sunday morning, so prop line movement for the main slate has nothing earlier to move from. **Game lines are unaffected** — the bulk h2h/spreads/totals call is a flat 3 credits for the whole board and ignores this window. Keeping Thursday's reading of Sunday props costs 647 a month against a 500 quota, so it is not affordable.

The other lever is `len(PROP_MARKETS)`; `RETIRED_PROP_MARKETS` records what was dropped and why. Three paths spend them and nothing else does:

- `POST /admin/trigger-odds-fetch`
- `refresh_odds_and_cache()` / `odds_api.refresh_odds_data()` called directly
- the startup refresh, when cached odds are older than `STARTUP_REFRESH_MAX_AGE_HOURS`

Ask before any of those, every time, even when a refresh looks obviously useful. The user clicking the button on the Odds page is their own call and needs nothing.

Reading costs nothing and needs no permission: `/odds/status`, `/odds/games`, `/odds/props`, `/odds/results` and `/odds/prop-results` all serve what is already held in memory or in the snapshot history. Most questions about lines — including what has moved and by how much — can be answered from those, because the opening and current lines are both already stored.

The same goes for anything else bought rather than merely requested. Sleeper and nflverse are free and can be called freely; a paid or metered source cannot.

Run the tests with `/usr/local/bin/python3 -m pytest tests/` — plain `python` resolves to a 2.7 without pytest installed.

The backend runs on Koyeb's free tier with 512 MB and has been OOM-killed before, so weigh any change that holds more data in memory. Heavy scheduled jobs are deliberately staggered so two never start in the same hour.
