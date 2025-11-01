# Low-CPU Mode: What To Disable and How

Purpose: help you drop CPU usage of the `python -m app.main` container to the minimum by turning off optional background loops and heavy features. This lists env-only variants (no code changes) and optional tiny code gates you can add.

## Where CPU comes from (idle vs. active)
- Telegram long-polling loop: `app/main.py:430` starts `dispatcher.start_polling(...)` and runs forever.
- Background schedulers/tasks:
  - Retention pruner: `app/services/context_store.py:1009` via `run_retention_pruning_task(...)` (interval; sleeps between runs).
  - Episode monitor: `app/services/context/episode_monitor.py:117` (periodic 5‑min sleep; only useful when auto episodes are enabled and messages arrive).
  - Donation scheduler (APScheduler): `app/services/donation_scheduler.py` started in `app/main.py:211` (jobs run at fixed times; will tick the scheduler loop even with empty targets).
  - Profile summarizer (APScheduler): disabled by default; started only if `ENABLE_PROFILE_SUMMARIZATION=true`.
- On‑message features (no idle CPU, but heavy when messages arrive): multi‑level context, hybrid search/embeddings, episodic memory, web search, image generation, bot self‑learning.

## Fastest win (no code changes)
Set these env vars to stop all background loops except Telegram polling:

- `RETENTION_ENABLED=false` — disables the retention pruning task (app/main.py creates the task only if enabled).
- `AUTO_CREATE_EPISODES=false` — disables the episode monitor background loop.
- `ENABLE_PROFILE_SUMMARIZATION=false` — keeps the profile summarizer scheduler off (default).
- `ENABLE_IMAGE_GENERATION=false` — prevents image service init.
- `ENABLE_WEB_SEARCH=false` — prevents web search tool use.
- `USE_REDIS=false` — avoids any Redis activity (processing lock falls back to in‑memory).

To reduce active-message CPU cost even further (still env‑only):

- `ENABLE_MULTI_LEVEL_CONTEXT=false` — fall back to recent context window only.
- `ENABLE_HYBRID_SEARCH=false` and/or `ENABLE_EPISODIC_MEMORY=false` — avoid embedding lookups and episode retrieval.
- `ENABLE_BOT_SELF_LEARNING=false` — skip bot profile/learning subsystems.
- `GEMINI_ENABLE_THINKING=false` — reduce generation complexity when messages are processed.
- `ENABLE_COMMAND_THROTTLING=false`, `ENABLE_PROCESSING_LOCK=false` — remove two middlewares (small impact).

Example minimal env excerpt (safe defaults):

```
RETENTION_ENABLED=false
AUTO_CREATE_EPISODES=false
ENABLE_PROFILE_SUMMARIZATION=false
ENABLE_IMAGE_GENERATION=false
ENABLE_WEB_SEARCH=false
USE_REDIS=false
ENABLE_MULTI_LEVEL_CONTEXT=false
ENABLE_HYBRID_SEARCH=false
ENABLE_EPISODIC_MEMORY=false
ENABLE_BOT_SELF_LEARNING=false
GEMINI_ENABLE_THINKING=false
ENABLE_COMMAND_THROTTLING=false
ENABLE_PROCESSING_LOCK=false
LOG_LEVEL=WARNING
ENABLE_FILE_LOGGING=false
```

Notes:
- Donation Scheduler has no dedicated flag today. If `BOT_BEHAVIOR_MODE` is not `whitelist`, `target_chat_ids=[]` and it effectively idles, but APScheduler still runs; see the “tiny code gates” below to fully disable.
- Resource monitor/optimizer is effectively disabled: `get_resource_monitor().is_available()` returns False, so `run_resource_monitoring_task(...)` is not created.

## Optional tiny code gates (very small patches)
If you want the absolute minimum idle CPU, gate these in `app/main.py`:

1) Add env flag to skip Telegram polling entirely (diagnostic idle mode):

- File: `app/main.py:428` (insert just before polling)
  - Before starting polling, guard with a flag so the process just initializes and sleeps.

```python
    # Diagnostic idle mode (no polling)
    if getattr(settings, "diagnostic_idle", False) or os.getenv("DIAGNOSTIC_IDLE", "false").lower() == "true":
        logging.warning("Diagnostic idle mode enabled: skipping Telegram polling")
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            return
```

2) Gate DonationScheduler behind a flag (so APScheduler doesn’t start):

- File: `app/main.py:205` (around DonationScheduler init/start)

```python
    if os.getenv("ENABLE_DONATION_SCHEDULER", "false").lower() == "true":
        donation_scheduler = DonationScheduler(...)
        await donation_scheduler.start()
    else:
        donation_scheduler = DonationScheduler(bot, settings.db_path, store, [], [])
        logging.info("Donation scheduler disabled (ENABLE_DONATION_SCHEDULER=false)")
```

3) Ensure the retention pruner never starts unless explicitly wanted:

- Already controlled by `RETENTION_ENABLED=false` (no patch needed). If you prefer explicit gating, keep as is.

4) Episode monitor already obeys `AUTO_CREATE_EPISODES=false` (no patch needed).

With the two tiny gates above, idle CPU typically drops to “just the event loop” (near zero) — especially if you also set `ENABLE_FILE_LOGGING=false`.

## File references (what starts what)
- Polling: `app/main.py:427` — `await dispatcher.start_polling(bot, skip_updates=True)`
- Donation scheduler: `app/main.py:211` → `DonationScheduler.start()`; implementation `app/services/donation_scheduler.py`
- Retention pruner task: `app/main.py:368` → `run_retention_pruning_task(...)` in `app/services/context_store.py:1009`
- Episode monitor: `app/main.py:268` → `EpisodeMonitor.start()` in `app/services/context/episode_monitor.py:117`
- Profile summarizer: `app/services/profile_summarization.py` (only if `ENABLE_PROFILE_SUMMARIZATION=true`)
- Resource monitoring: currently inert (monitor is disabled in `app/services/resource_monitor.py`)

## Quick recipes
- Minimal, still functional bot (answers messages, low idle CPU):
  - Set all envs in the “Fastest win” list.
  - Leave polling on; keep heavy features off.

- Diagnostic idle (near-zero CPU):
  - Apply the “Diagnostic idle mode” guard above and run with `DIAGNOSTIC_IDLE=true`.
  - Or comment out the `start_polling(...)` line temporarily.

## Troubleshooting spikes
- If CPU is high while idle, check logs for repeated polling errors (network/401). Polling restarts can loop quickly; fix token/connectivity or set `LOG_LEVEL=WARNING` to reduce log overhead.
- If CPU wakes regularly, confirm you disabled: retention pruner, episode monitor, donation scheduler.
- If CPU is high only when messages arrive, turn off hybrid search, episodic memory, and thinking mode as shown above.
