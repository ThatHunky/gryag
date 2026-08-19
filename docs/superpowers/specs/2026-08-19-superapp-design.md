# Gryag Superapp — Design Spec

**Date:** 2026-08-19
**Status:** approved, not yet implemented
**Builds on:** `2026-08-19-gryag-v3-design.md`, which describes the running bot

Three pieces of work, in order: the `/gryag` admin menu becomes a hub of screens, a daily
"підарас дня" game is added for everyone in the chat, and a morning "підрахуйка" digest
pulls verified enemy-loss figures from the Unmanned Systems Forces public killboard.

The V3 governing rule still holds and constrains all three:

> **The LLM is called only when the bot speaks.** The decision to speak is plain code.

Neither the game nor the digest calls the model at runtime. Both use pools of phrases
generated once, offline, and committed to the repo.

---

## 1. Menu hub

### 1.1 What exists

`/gryag` is one screen. `menu.py` declares three sections (Модель / Тригер / Сам) as
tuples of `Setting`, each setting rendered as a button that cycles through its choices.
`admin.py` renders that, plus a chat on/off toggle, a mute row, and three action buttons
(spend panel, reload persona, rerun digest). The router filters on `admin_ids`, so the
whole surface is admin-only.

That single screen is already at the width Telegram will render without truncating, and
two more features need somewhere to live.

### 1.2 What it becomes

A hub. The root screen carries live status as text and six buttons; each button opens a
screen with a `← назад` row.

**Root text:** chat enabled/disabled, current speak model, mute state, spend for the last
24 hours, and the model-drift warning `admin.drift_warning` already produces.

**Screens:**

| Screen | Contents |
|---|---|
| ⚙️ Налаштування | The existing three sections, as sub-tabs |
| 🎭 Голос | Reload persona (shows resulting size), rerun digest |
| 💰 Витрати | `spend_report`, with a day / week / all switch |
| 👥 Люди | Active bans, image whitelist, pointers to `/nb` and `/unban` |
| 🎲 Гра | Game on/off, candidate window, announce hour, roll now, leaderboard |
| 📊 Табло | Digest on/off, morning hour, show now |

Muting and the chat toggle stay on the root screen rather than moving to one of their own.
Silencing the bot is the most urgent thing this menu does, and a screen deeper is a screen
too far when a chat is asking it to shut up. That leaves room for 📊 Табло as the sixth
screen, which the digest needs anyway.

Everything on every screen stays admin-only. The only public surfaces added by this spec
are the game and digest commands, and neither spends money.

### 1.3 Structure

`menu.py` keeps `SECTIONS` and gains `SCREENS`, a declaration of the hub: screen key,
title, icon, and which settings (if any) it renders. `admin.py` keeps only rendering and
callback handling. Callback data gains one prefix, `nav:<screen>`; `set:<section>:<key>`,
`mute:<hours>`, and `chat:toggle` keep their present meaning.

The target is `admin.py` under ~350 lines. If rendering pushes past that, the screen
renderers move to `gryag/screens.py` and `admin.py` keeps the routing.

**One incidental fix.** Registering the new routers means editing `__main__.build`, which
sits next to `serve_polling` — and `serve_polling` still unpacks `await build(secrets)` as
a two-tuple and then references `db`, `client` and `persona`, none of which are in scope.
It is dead today only because `MODE=webhook`; it cannot start if that ever changes. It
gets the same `Runtime` treatment `start()` already applies.

### 1.4 Edge cases already solved, not to be regressed

Two guards in `admin.show` exist because of real failures and must survive the rewrite:

* A menu older than 48 hours arrives as `InaccessibleMessage`, which has no `edit_text`.
  Answer fresh instead of raising.
* Tapping the screen you are already on produces an identical edit, which Telegram
  rejects with `message is not modified`. Swallow exactly that, re-raise anything else.

---

## 2. Підарас дня

A daily joke: once per day the bot picks one chat member at random and announces them.
Modelled on the Russian-language bots that popularised the format, with the registration
step removed.

### 2.1 Candidate pool

Telegram's Bot API cannot enumerate group members, so the pool is what the bot has
observed: rows in `users` for this chat whose `user_id` has sent at least one message in
the last `pidor_window_days` (default 30). Bots are excluded (`messages.sender_is_bot`),
gryag itself is excluded, and there is **no opt-out** — a decision taken deliberately.

Banned users stay in the pool. A ban means "gryag ignores you", not "you are not in the
chat"; excluding them would leak the ban list into a game everyone can see.

Below `pidor_min_players` (default 3) candidates the bot says there is nobody to pick
from and rolls nothing. The measured chat has 29 users, so this only bites a fresh chat.

### 2.2 One winner per day

```sql
CREATE TABLE pidor_days (
    chat_id   INTEGER NOT NULL,
    day       TEXT    NOT NULL,   -- Kyiv calendar day, YYYY-MM-DD
    user_id   INTEGER NOT NULL,
    chosen_at TEXT    NOT NULL,
    PRIMARY KEY (chat_id, day)
);
```

The roll is `INSERT … ON CONFLICT DO NOTHING` followed by `SELECT`. Two people typing
`/pidor` in the same second therefore get one winner and no lock: whoever loses the insert
reads the winner the other wrote. This mirrors how `_claim` in `handlers.py` already
avoids an `asyncio.Lock`.

The day boundary is Kyiv midnight, computed the same way `handlers.handle_message`
computes `local_midnight` — UTC midnight would roll the game over at 03:00 local.

**Anti-repeat:** yesterday's winner is dropped from the pool when the pool without them
still holds at least `pidor_min_players` candidates; otherwise they stay in and can win
again. Without that guard a 29-person chat still produces visible repeats, and a repeat
reads as a bug rather than as chance.

### 2.3 The show

Three messages, ~1.5 s apart: two warm-up lines and the verdict with a mention. A second
`/pidor` on the same day replies with a single line naming the existing winner and skips
the show, which doubles as the anti-spam measure.

**Mentions need a schema change.** `users` stores `display_name` and `alias` but not
`username`, so there is nothing to build an `@` mention from. Add `username` via
`store.MIGRATIONS` and populate it in `handlers.persist`. Where a username exists the
verdict uses `@username`; where it does not it uses an HTML text mention,
`<a href="tg://user?id=…">name</a>`, with the name HTML-escaped and `parse_mode="HTML"`
passed on that single call. The bot's global default stays `parse_mode=None`.

### 2.4 Commands

* `/pidor` — roll or show today's winner
* `/pidorstats` — leaderboard for the current year and all time, straight out of
  `pidor_days`

Both are open to everyone in an enabled chat. Both are registered with `setMyCommands` so
they appear in the input-field menu, along with the digest commands from §3.

Where `pidor_enabled = 0`, or the chat is not on the whitelist, both commands are silently
ignored — the same treatment `handle_message` gives a chat that was never switched on.
The admin screen's "розіграти зараз" announces the existing winner if the day is already
decided; it never re-rolls, because a re-rollable winner is not a winner.

Command routing: the game router is registered **before** the chat router, so a handled
command stops propagation. It calls `handlers.persist` itself, because history with holes
is exactly what `handle_message` goes out of its way to avoid. `OWN_COMMANDS` in
`handlers.py` gains the new names so `gate.foreign_command` does not read them as another
bot's commands.

### 2.5 Automatic announcement

If nobody has rolled by `pidor_announce_hour` (default 13, Kyiv), the bot rolls and
announces on its own. The check rides the existing `proactive.loop` tick (600 s), which
already runs inside the bot process and already reads per-chat config. It respects the
chat mute — a chat that asked for silence gets silence — and ignores quiet hours, which
are meaningless for a configurable midday event.

### 2.6 Config keys

| Key | Default | Meaning |
|---|---|---|
| `pidor_enabled` | `1` | Feature on/off, per chat |
| `pidor_window_days` | `30` | How far back a message counts as "present" |
| `pidor_min_players` | `3` | Below this, refuse to roll |
| `pidor_announce_hour` | `13` | Kyiv hour for the automatic roll; `-1` disables |

---

## 3. Підрахуйка

A morning digest of verified enemy losses published by Угруповання СБС (Unmanned Systems
Forces) on their public killboard, plus a live command.

### 3.1 The data source, as verified on 2026-08-19

`https://sbs-group.army/api/public`, no authentication, `robots.txt` allows everything.

* `GET /periods` — every period for every subdivision. Fields used: `_id`, `periodType`
  (`daily`, `prev_day`, `monthly_*`, `yearly_*`, `custom`), and `subdivision.division_id`,
  where `"0"` is the whole grouping.
* `GET /statistics/{subdivisionId}/{periodId}` — one report:
  * `personnel: {killed, wounded}`
  * `flights: {strike, recon}`
  * `targetsByType: [{targetClassId, targetClass, hit, destroyed}]` — 43 classes
  * `totalTargetsHit`, `totalTargetsDestroyed`, `totalPersonnelCasualties`
  * `status` — `completed` or `not_collected`
  * `lastUpdated`, `dataCollectedAt`

A live sample: 168 killed / 182 wounded, 1,873 hits, 645 destroyed for the day in
progress; the site polls this every 10 s.

Only the grouping total is used. Per-brigade figures exist but would cost ~17 requests per
digest for a line nobody asked for.

### 3.2 Module

`gryag/pidrahuika.py`, in three parts with one seam each:

* `fetch(session, subdivision, period)` — network, 10 s timeout, one retry
* `parse(payload) -> Report` — a frozen dataclass
* `render(report, previous) -> str` — pure, and therefore the part that gets tested

Period and subdivision IDs are resolved from `/periods` and cached in memory for 6 hours.
Hardcoding the IDs would work today and break silently whenever they rotate; a 404 from
`/statistics` drops the cache and retries once.

### 3.3 Output

Roughly twelve lines: personnel, total hit / destroyed, sorties (strike and recon), the
eight largest categories by `destroyed`, the `lastUpdated` timestamp, and one line from a
static phrase pool. The delta against the previous day is shown where a previous day is
stored.

The API serves only named periods, so arbitrary-date comparison is impossible through it.
Each rendered report is therefore snapshotted locally:

```sql
CREATE TABLE pidrahuika_days (
    day        TEXT PRIMARY KEY,   -- Kyiv calendar day the figures cover
    fetched_at TEXT NOT NULL,
    payload    TEXT NOT NULL       -- raw JSON, so a render change can be retro-applied
);

CREATE TABLE pidrahuika_posts (
    chat_id INTEGER NOT NULL,
    day     TEXT    NOT NULL,
    PRIMARY KEY (chat_id, day)
);
```

`pidrahuika_days` is chat-independent — the figures are the same for everyone — which is
why it has no `chat_id`. That makes it the one table `store.forget_chat` must **not**
touch.

### 3.4 Morning post and live command

The morning post fires at `pidrahuika_hour` (default 9, Kyiv) on the `proactive.loop`
tick, reading the `prev_day` period, in every enabled chat with `pidrahuika_enabled = 1`.
`pidrahuika_posts` stops a double post; a failed fetch writes nothing, so the next tick
tries again and a killboard outage at 09:00 costs ten minutes, not a day.

`/pidrahuika` (alias `/sbs`) reads the `daily` period. Responses are cached in memory for
60 s per chat, which is both the freshness the source offers and the anti-spam measure.

### 3.5 Failure modes

| Condition | Command | Morning post |
|---|---|---|
| `status: "not_collected"` | "ще не порахували" | skip, retry next tick |
| Timeout / 5xx / 403 | "табло не відповідає" | skip, retry next tick |
| Shape changed (missing key) | same as above, and log the payload | same |

The whole thing is wrapped so that no killboard failure can take down the proactive loop,
which is also responsible for the game announcement and for proactive speech.

### 3.6 Config keys

| Key | Default | Meaning |
|---|---|---|
| `pidrahuika_enabled` | `0` | Off until switched on per chat |
| `pidrahuika_hour` | `9` | Kyiv hour for the morning post |

---

## 4. Phrase pool

`eval/gen_phrases.py` calls Gemini 3.1 Pro once and writes `gryag/phrases.py`: warm-up
lines, verdict templates carrying a `{who}` placeholder, "already rolled today" lines, and
a deliberately dry pool of digest comments. The script stays in the repo so the pool can
be regenerated; the generated module is committed, so nothing at runtime depends on it.

Generating rather than hand-writing is the point: a pool large enough not to repeat inside
a month is ~40 lines per category, which is more than is worth writing by hand and exactly
what a model is good at.

Two constraints on the generated text:

* Verdict templates must contain `{who}` exactly once. The generator validates this and
  drops anything that fails, rather than shipping a template that throws at runtime.
* Digest comments must not be jokes about the casualty figures. They comment on the work,
  not on the dead.

---

## 5. Testing

Following the existing split, where `gate.py` is pure and tested exhaustively while the
network edges are thin:

| Unit | Test |
|---|---|
| `pidor.choose(candidates, previous, roll)` | Pure. Anti-repeat, min-players, single-candidate, empty. |
| `pidor_days` insert race | Two concurrent rolls yield one winner. |
| Day boundary | 23:59 and 00:01 Kyiv land on different days; 01:00 Kyiv (22:00 UTC) lands on the Kyiv day. |
| `pidrahuika.parse` | Real captured payload, plus `not_collected`, plus a payload missing a key. |
| `pidrahuika.render` | Fixed input, asserted output; delta present and absent. |
| `menu.SCREENS` | Every screen reachable from root; every settings key exists in `config.DEFAULTS`. |
| `phrases` | Every verdict template formats with `{who}`; no pool is empty. |

The killboard is never called from a test. The captured payload lives in the test file.

---

## 6. Order of work

1. **Menu hub.** Nothing depends on it functionally, but both features hang screens off
   it, and doing it last would mean building those screens twice.
2. **Phrase pool.** One offline call; both features consume it.
3. **Підарас дня.** Schema migration for `username`, `pidor_days`, roll, show, stats,
   announcement, menu screen.
4. **Підрахуйка.** Client, render, snapshot tables, morning post, command, menu screen.

Each step leaves the bot working. The migration in step 3 is additive and the two new
tables in step 4 are independent of everything already stored.
