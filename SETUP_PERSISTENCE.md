# Persistence setup

State that must survive a restart — DFS tournaments, correction links, odds cache
and history — lives outside the process. On Koyeb's free tier the filesystem is
ephemeral and anything written locally is lost on redeploy, which is why the
remote tiers exist.

## Where a write goes

Tried in order of durability, first one configured wins:

| Tier | Enabled by | Notes |
|---|---|---|
| Supabase | `SUPABASE_URL` + `SUPABASE_KEY` | Preferred. One `app_data` table, one row per store. |
| GitHub Gist | `GITHUB_TOKEN` + `GIST_ID` | Fallback if Supabase is unset or a write fails. |
| Local file | nothing | `DATA_DIR` (default `./data`). Ephemeral on Koyeb. |

Reads follow the same order at startup.

## Running a local instance

Production and a local instance point at the same Supabase project, so by default
they share every row — including the ones the Thursday cleanup rewrites. Both of
these keep a dev run out of production's data; pick based on whether dev data
needs to survive a restart.

### `SUPABASE_KEY_PREFIX` (recommended)

```
SUPABASE_KEY_PREFIX=dev_
```

Gives the instance its own parallel rows in the same table — `dev_tinyurl_data`
beside `tinyurl_data` — isolated from production but read and written normally, so
dev data persists across restarts. Leave unset in production, which owns the bare
keys.

Storage is not a concern: all five production rows together are about 1 MB against
the free tier's 500 MB.

Dev starts with empty rows rather than a copy of production. To seed one, read the
production row and write it back under the prefixed key.

### `SUPABASE_READ_ONLY`

```
SUPABASE_READ_ONLY=true
```

Reads production state from Supabase but sends every write to a local file, and
skips Gist too, since the gist is shared with production the same way. Useful for
inspecting real data without any risk of writing to it.

**It does not give you a durable dev environment.** Loads still come from Supabase,
so anything written locally is discarded on the next restart. For testing that
spans restarts or a cleanup cycle — multiweek tournaments especially — use
`SUPABASE_KEY_PREFIX`.

## Startup banner

The log says which set of rows the instance owns:

```
Supabase rows namespaced with prefix 'dev_' (e.g. 'dev_tinyurl_data') — isolated from production.
```

or, when no prefix is set:

```
Supabase rows are the PRODUCTION set (no SUPABASE_KEY_PREFIX).
```
