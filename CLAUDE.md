Before pushing follow-up commits to a branch that already has a PR, check whether that PR has been merged (`gh pr view <n> --json state`). Pushing to a merged branch strands the work silently — it lands nowhere and no open PR shows it. Branch from the updated `main` and cherry-pick instead.

Check it **immediately before the push**, not when the branch was created. A PR merged in between is exactly the case that gets missed, and it is how work has been stranded twice: once by checking at branch time and pushing hours later, once by printing `MERGED` and continuing anyway because the check and the push were chained together. Read the answer before acting on it.

PRs here are squash-merged, so a branch's commits never become ancestors of `main`. `git merge-base --is-ancestor` will report merged work as missing. Check by commit subject against `git log main` (a squash commit keeps the PR title, usually with `(#NN)` appended, so match on substring), or by whether the branch's diff against `main` is empty. A two-dot diff (`main..branch`) is not a merge test — it also counts main's newer commits as differences.

**Never spend odds API credits without asking first.** They are a finite purchased balance, not a rate limit that refills — about 50 go per refresh, and `/odds/status` reports what is left under `credits_remaining`. Three paths spend them and nothing else does:

- `POST /admin/trigger-odds-fetch`
- `refresh_odds_and_cache()` / `odds_api.refresh_odds_data()` called directly
- the startup refresh, when cached odds are older than `STARTUP_REFRESH_MAX_AGE_HOURS`

Ask before any of those, every time, even when a refresh looks obviously useful. The user clicking the button on the Odds page is their own call and needs nothing.

Reading costs nothing and needs no permission: `/odds/status`, `/odds/games`, `/odds/props`, `/odds/results` and `/odds/prop-results` all serve what is already held in memory or in the snapshot history. Most questions about lines — including what has moved and by how much — can be answered from those, because the opening and current lines are both already stored.

The same goes for anything else bought rather than merely requested. Sleeper and nflverse are free and can be called freely; a paid or metered source cannot.

Run the tests with `/usr/local/bin/python3 -m pytest tests/` — plain `python` resolves to a 2.7 without pytest installed.

The backend runs on Koyeb's free tier with 512 MB and has been OOM-killed before, so weigh any change that holds more data in memory. Heavy scheduled jobs are deliberately staggered so two never start in the same hour.
