# Gryag V3 — Design Spec

**Date:** 2026-08-19
**Status:** built and running. Phases 1–3 are implemented; phase 3 ships switched off.
**Supersedes:** `HANDOFF.md` (deleted; its surviving content is folded in below)
**Last synced with the code:** 2026-08-19, after the phase 3 deploy.

Sections 1–4 are the evidence the design rests on and have not changed. Sections 5 onward
describe what is actually running, including several things the original design did not
anticipate — tools, images, bans — and several places where a measurement in production
overruled a decision made on paper. Those are called out where they occur.

---

## 1. What this is

A Telegram group-chat bot with a specific Ukrainian persona ("гряг"), rebuilt from
scratch. Two previous attempts exist in `ThatHunky/gryag`: branch `legacy` (a working
Python bot, expensive) and branch `main` (a Python + Go + Postgres + Redis architecture
that was never finished and is deliberately discarded).

V3's governing rule, inherited from the plan and unchanged by anything measured since:

> **The LLM is called only when the bot speaks.** The decision to speak is plain code.
> All background work is one call per day per chat.

Legacy violated this — it called the model on every message for fact extraction, episode
grouping and self-learning. In a chat of 3,000 messages a day that is thousands of calls
for a bot that says forty things.

---

## 2. Evidence base

Every number below was measured during design, not estimated. Two sources:

**A real Telegram export** — `чат матсурі`, 2026-08-17..18, 6,573 messages. Kept locally
in `chat_exports/`, gitignored: it contains real names, photos, voice and video.

**Live API measurements** — 16 test cases mined from that export, run against the Gemini
API on 2026-08-18.

### 2.1 What the chat actually looks like

| | |
|---|---|
| Messages, 2 days | 6,573 (6,174 human, 399 from three other bots) |
| Human messages per day | **~3,087** |
| Unique humans | 27 |
| Median message length | **19 characters** (p90: 64) |
| Media-only messages | 1,038 — **17%** of human traffic |
| Replies | 2,378 — **39%** |
| Text volume per day | **~28,500 tokens** |

The plan assumed 800 messages/day. The real figure is **3.9× higher**.

### 2.2 Velocity and reply structure

Median gap between messages: **6 seconds** (p75 13s, p90 33s, p95 70s). Over two days
there were only 66 gaps longer than 5 minutes, 18 longer than 15 minutes, 4 longer
than an hour. The chat is effectively one continuous stream.

Consequence: a fixed window of N messages covers very little wall-clock time.

| N messages | wall clock | tokens | share of replies whose target is inside |
|---|---|---|---|
| 20 | 3.0 min | 330 | 94% |
| **30** | **4.4 min** | **480** | **~96%** |
| 50 | 7.6 min | 780 | 98% |
| 120 | 22 min | 1,830 | 99% |

Reply depth is shallow: median **3 messages back**, p90 12, p95 22, p99 123.
Beyond N=30 you pay double for 2% more coverage.

### 2.3 Daily rhythm

```
22:00 ████████████████████████ 958   peak
19:00 █████████████████ 693
00:00 ██████████████ 593
23:00 ██████████████ 562
14:00 ████████████ 505
03:00–07:00                    0–11  dead zone
```

### 2.4 Token cost of context

~16 tokens per rendered message line. Since the median message is 19 characters
(~7 tokens), **the speaker name costs more than the message**. Worst offenders:
`٠࣪𝒎𝒂𝒕𝒔𝒖𝒓𝒊۶ৎ ˚.` = 16 tokens, `артемопокалипсис/локшина малинова` = 15,
`Vsevolod Dobrovolskyi` = 12.

Replacing display names with short stable aliases saves **13–18%** of the whole context
block, for free.

---

## 3. Corrected findings

Three findings shaped the original plan. Two survive; one was wrong.

### 3.1 SURVIVES — the LLM must not run on every message

Unchanged and now better supported: at 3,087 messages/day, a per-message call is
three times worse than the plan feared.

### 3.2 SURVIVES — Flash-Lite is ruled out on persona quality

Established from running legacy. Treat as a hard floor for the *speaking* model.

Refinement: this ruling is about **persona**, not about summarisation. The daily digest
job has no voice requirements, so it runs on Flash-Lite deliberately (§9).

### 3.3 SURVIVES, and is the biggest lever — summaries dominated the prompt

Measured from the production dump: 6,962 tokens per call, of which 4,270 were the 7-day
and 30-day summaries, against **665 tokens of actual live conversation**.

V3 caps every block hard (§7).

### 3.4 WRONG — "the newest Flash is the cheapest Flash"

The plan claimed Gemini 3.7 Flash costs $0.375/$1.88, cheaper than 3.6 Flash. That number
came from OpenRouter. Verified against Google's own pricing page on 2026-08-18:

| Model | input / output per 1M | after 2027-01-01 | cache read | cache storage |
|---|---|---|---|---|
| Gemini 3.7 Flash | $0.75 / $3.75 (promo) | **$1.50 / $7.50** | $0.075 | $0.50 /1M/hour |
| Gemini 3.6 Flash | $0.75 / $3.75 (promo) | $1.50 / $7.50 | $0.075 | $0.50 /1M/hour |
| Gemini 2.5 Flash | $0.30 / $2.50 | unchanged, no promo | $0.03 | $1.00 /1M/hour |
| Gemini 2.5 Flash-Lite | $0.10 / $0.40 | unchanged | — | — |

3.7 Flash costs **exactly the same as 3.6**, and its price **doubles on 1 January 2027**.
Since the two are priced identically, 3.6 Flash is dominated on every axis and is dropped
from consideration entirely.

---

## 4. Findings discovered during design

### 4.1 The native endpoint caches; the OpenAI-compatible endpoint does not

Implicit cache hits, same prefix, back-to-back calls:

| endpoint | result |
|---|---|
| OpenAI-compat (`/v1beta/openai/`) | **1 hit in 37 calls** |
| Native, 2.5 Flash | 0% for 4 calls, then **92.7%** |
| Native, 3.7 Flash | **46.3%**, from the first call |

The native API is also the only one that reports `thoughtsTokenCount` — the telemetry the
admin menu and the alias-drift detector depend on.

**V3 uses the native `google-genai` SDK. This is not a preference; the compatibility layer
silently forfeits caching and telemetry.**

Caveat: those rates were measured in bursts. In a realistic run with varied prompts the
hit rate fell to **10.2% (2.5) and 0% (3.7)**, because every request had a different
prefix. Production calls are ~30 minutes apart, which is worse still. **Budget the
no-cache column.** Implicit caching is upside, never a plan.

Explicit caching is rejected: storage at $0.50–1.00 per 1M tokens per hour costs roughly
what it saves at ~2,700 cached tokens, and it delivers nothing implicit caching does not.

### 4.2 Thinking tokens cost 6–12× the visible answer

Reasoning tokens bill at the output rate and never appear in the reply.

| model | thinking tokens | visible tokens |
|---|---|---|
| 2.5 Flash | 566 | 53 |
| 3.7 Flash | 345 | 57 |
| 3.6 Flash | 636 | 54 |

2.5 Flash honours `thinking_budget: 0` completely — measured 0 thinking tokens. 3.x models do
not: with thinking nominally disabled they still spent **46 to 234 tokens** across runs, with
no stable value. Budget ~150 per reply for 3.x and treat any single measurement as noise.
This is also why the cost panel must report thinking tokens separately — on 3.x it is the
volatile part of the bill.

**V3 runs with thinking disabled.** On 3.7 the outputs were near-identical with and without
it; on a one-line chat persona there is nothing to reason about.

Corollary for the harness: a tight `max_output_tokens` is dangerous, because thinking draws
from the same budget. Measured: 2.5 Flash at 400 tokens spent 380 on thinking and was cut
off mid-word. Keep the ceiling generous; enforce brevity through the persona, not the cap.

### 4.3 `gemini-flash-latest` resolves to 3.7 Flash

The alias is opaque — the API echoes the alias back, and model metadata is byte-identical
across every Flash. It was identified behaviourally instead:

| | latency p50 | thinking | visible | $/mo |
|---|---|---|---|---|
| `gemini-flash-latest` | 2.81s | 341 | 55 | $3.89 |
| `gemini-3.7-flash` | 2.90s | 345 | 57 | $3.92 |

Google repoints the alias on every Flash release, possibly onto a preview build, with
2 weeks' email notice **only for breaking changes**. Their own docs say production apps
should pin a stable model.

The alias was chosen anyway, deliberately, to avoid forced migration when an older model
retires. That choice is only safe with two mitigations, both of which are in this design:
runtime model switching from the admin menu (§10) and the drift detector (§10.4).

### 4.4 The persona compresses by 69% with no loss

The legacy persona is 1,792 tokens. Composition:

| block | tokens | verdict |
|---|---|---|
| Memory Management | **723** | moves to the digest job — it is tool instructions, not voice |
| Bot Identity & Core Behavior | 322 | keep |
| User Relationships | 248 | keep |
| Available Tools | 137 | drop — V3 ships no tools at launch |
| Moderation | 109 | drop — depends on the dropped tools |
| Time handling | 93 | replace with an injected timestamp (~8 tokens) |
| Values & Stance | 88 | keep |
| Critical Rules | 46 | keep |
| Formatting Guidelines | 18 | keep |

The rewritten persona (`eval/persona-v3.txt`) is **547 tokens**. Measured effects:

- Replies got **closer to the room**: 2.5 Flash went from 205 to 41 characters average,
  3.7 from 162 to 58. Chat median is 19.
- The one format failure disappeared. With the legacy persona and thinking off, 2.5 Flash
  wrote other people's lines and labelled its own `[gryag]` in 1 case of 16. With an
  explicit speaker boundary in the compressed persona: **0 of 16**, both models.

The leak was a prompt bug, not a model defect. The 723 tokens of memory-tool instructions
were diluting the voice instructions.

---

## 5. Architecture

Two systemd units sharing one SQLite file.

```
gryag-bot.service      aiogram on a webhook, always running
gryag-digest.timer  →  gryag-digest.service    once a day at 04:00, exits
```

04:00 sits inside the measured dead zone (03:00–07:00, 0–11 messages/hour).

### 5.1 Modules

| module | responsibility | depends on |
|---|---|---|
| `handlers` | receive updates, persist messages, route a reply | everything below |
| `gate` | pure code: speak or not | nothing |
| `context` | assemble the prompt from its layers | — |
| `llm` | native Gemini call, tools, usage telemetry | — |
| `media` | detect, fetch and type attachments | — |
| `images` | Nano Banana generation and editing, whitelist | `llm` |
| `menu` | the admin menu's shape, as data | `config` |
| `admin` | inline keyboard, spend panel, `/nb`, `/unban` | `store`, `config`, `menu` |
| `digest` | daily job: summaries + fact extraction | `store`, `llm` |
| `proactive` | the loop that speaks into a silence | `store`, `llm` |
| `store` | SQLite, schema, migrations | — |
| `config` | layered settings, secrets | `store` |

`menu` exists apart from `admin` so the layout can be tested without a Telegram client;
a test asserts every menu entry names a real config key and every default is among the
offered choices.

`gate` has no network and no LLM access by construction. It is a pure function of config
and chat state, fully testable offline. This is the structural difference from legacy,
where deciding whether to answer itself cost money. It now carries fifteen reasons to stay
quiet and five to speak, and every one of them is covered by a table-driven test.

### 5.2 Message path

```
Telegram → Caddy → /webhook → aiogram
   ↓
persist row in messages   (always, even when the bot will stay silent)
   ↓
gate.should_speak() ── no ──→ done
   ↓ yes
claim the chat ── already claimed ──→ done
   ↓
build context → look at media if asked → draw, or generate → reply → persist + usage
```

Messages are stored **before** the gate decides. Otherwise history has holes exactly where
the bot stayed quiet, and the digest job summarises an incomplete day.

**The claim is not a lock, and that distinction cost a bug.** The first version checked an
`asyncio.Lock` while building the gate input and acquired it a dozen awaits later. A
restart replays the update backlog, so a batch all saw the chat free, queued on the lock,
and each produced a reply — five landed in the same second. It is now a set, checked and
added with no await in between, which on a single-threaded loop is atomic. Whoever loses
says nothing.

### 5.3 Configuration lives in the database

`.env` holds secrets only: `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `WEBHOOK_SECRET`.

Everything the admin changes with buttons — model, effort, ambient rate, quiet hours,
active chats, trigger keywords — lives in the `config` table and is read at decision time.
Otherwise the menu would require a restart, which defeats the point of controlling the bot
from a phone.

---

## 6. Data model

SQLite in WAL mode. Two processes touch one file, so transactions stay short and
`busy_timeout` is set.

```sql
chats       (chat_id PK, title, enabled, added_at)
users       (chat_id, user_id, display_name, alias, pronouns,
             PRIMARY KEY (chat_id, user_id))
messages    (chat_id, message_id, user_id, ts, text,
             media_kind, file_id, reply_to, is_bot, sender_is_bot,
             PRIMARY KEY (chat_id, message_id))
facts       (id PK, chat_id, user_id, text, source_day, created_at)
summaries   (chat_id, kind, period_start, period_end, text, tokens)
config      (scope, chat_id, key, value)
usage       (id PK, ts, chat_id, purpose, model, prompt_tok, cached_tok,
             visible_tok, thought_tok, latency_ms, cost_usd, searched)
bans        (chat_id, user_id, until_ts, reason, PRIMARY KEY (chat_id, user_id))
chat_state  (chat_id PK, last_spoke_ts, last_ambient_ts, muted_until)

CREATE INDEX ON messages (chat_id, ts);
CREATE INDEX ON messages (chat_id, reply_to);
```

`summaries.kind` is `'day'` or `'week'`. `config.scope` is `'global'` or `'chat'`.
`usage.purpose` is `'reply'`, `'digest'`, `'image'` or `'proactive'`.

**`is_bot` and `sender_is_bot` are different questions**, and conflating them was a bug.
`is_bot` means "gryag said this" and drives the reply caps; `sender_is_bot` means the
author is any bot at all. Without the second, messages from the three other bots in the
chat were stored as human and the bot-to-bot loop guard could not see them. Added by
migration, since the table already had live data.

Migrations are a list of `ALTER TABLE` statements applied at connect and ignored when they
have already run. There is no version table: at this size, attempting each statement and
swallowing the duplicate-column error is less machinery than tracking which ran.

**Every message is kept forever.** At 3,087/day that is ~1.1M rows and 10–15 MB of text per
year — nothing for SQLite. The payoff is that summaries and facts can be regenerated from
history when the extraction prompt improves. A rolling window would forfeit that
permanently.

**Media files are not stored** — only Telegram's `file_id`, which is enough to fetch on
demand. The two-day export was 487 MB; storing media is not an option.

`users.alias` is the short stable name used in rendered context — the 16% saving from §2.4.

---

## 7. Prompt assembly

| block | cap | source |
|---|---|---|
| persona | 547 | file, hot-reloadable |
| header: current time, chat name | ~15 | generated |
| week summary | **400** | `summaries` |
| today summary | **300** | `summaries` |
| facts about people present in the window | **150** | `facts` |
| live context: 30 messages + reply chain | ~480 | `messages` |
| **total** | **~1,890** | legacy was 6,962 |

**Caps are enforced in code and logged when hit.** No block may grow silently. This is
precisely how legacy degraded: summaries crept to 65% of the prompt, leaving 665 tokens for
the conversation actually happening.

**Live context** is the last 30 messages after filtering out other bots and empty media,
plus the full reply chain of the triggering message even when it reaches outside the
window. The chain is cheap (median depth 3) and catches the ~4% of replies pointing far
back — p99 is 123 messages, which no fixed window would ever cover.

**Media appears as a marker** — `[фото]`, `[голосове]`, `[відео]`, `[кружок]`, `[стікер]` —
two tokens each, so the conversation does not look torn. When someone addresses the bot in
reply to a media message, that specific file is fetched by `file_id` and sent to the model:
photos, voice, video and video notes alike.

**Facts are selected by presence** — only about people appearing in the context window, not
all 27 participants. That is why 150 tokens is enough.

**A partial quote is rendered separately.** Telegram lets a person quote part of a message
when replying, and that selection is the whole point of the reply: somebody quoting two
words out of a long message is asking about those two words. Before this was handled the
model received the entire parent message and had to guess which fragment mattered.

**The context ends with an explicit boundary marker** after which the model writes only its
own next line: no name, no brackets, no continuation of the log. Without this marker, 1
reply in 16 was malformed (§4.4).

---

## 8. Trigger gate

### 8.1 Always speaks

- a mention of `@gryag_bot`
- a reply to one of the bot's own messages
- a **keyword** appearing in the text: `гряг` and its inflected forms (`гряга`, `грягу`,
  `грягом`, `грягові`…), matched case-insensitively on word boundaries

The keyword list is a per-chat config row seeded with that default, so it can be changed
from the menu without a deploy. It needs to be: in the export chat `чат матсурі`, "гряг" is
also **a human being** (a real person with 117 messages in the export), and there the bot would answer
every mention of that person. Accepted deliberately — that chat is not a deployment target,
and where it becomes one, the keyword gets edited.

### 8.2 Ambient interjection — target ~10 per day

**Built, and shipped switched off.** `ambient_enabled` defaults to `0`.

A die is rolled on each message. The probability is **derived per chat from the last 24
hours** rather than pinned to a constant: `ambient_per_day` divided by however many
messages that chat produced which were worth interrupting over. A constant would swamp a
quiet chat and vanish in a loud one. Measured on the live chat, that came to 63 candidates
a day and a probability of 0.159, which is the requested ten.

A candidate must pass filters, none of which call the model:

- not from a bot (three other bots produce 6% of traffic)
- not an empty media message (17%)
- text longer than 30 characters — at a median of 19 this discards "ага" and "в"
- not a reply to somebody else — two people mid-exchange are talking, not leaving a gap
  (39% of messages are replies)
- at least `ambient_cooldown` seconds since the bot last spoke, default 20 minutes

### 8.3 Proactive after silence

**Built, and shipped switched off.** `proactive_enabled` defaults to `0`.

Speaks unprompted when the chat has been quiet for ≥3 hours, local time is inside the
allowed window, and it has not spoken proactively for ≥6 hours. Measured, this will fire
almost exclusively in the morning: only 18 gaps longer than 15 minutes occurred in two days.

**This is the only path with a loop of its own.** Every other decision starts from an
incoming message, and here by definition none is arriving, so `proactive` ticks every ten
minutes and asks each enabled chat whether it has gone quiet. Quiet hours are evaluated in
**Kyiv time**, not UTC: the measured dead zone of 03:00–07:00 is local, and running it
against UTC would put the silence in the wrong part of the day.

### 8.4 Never speaks

The full list, each with a stable reason slug that appears in the log:

| reason | why |
|---|---|
| `chat_disabled` | the chat was never switched on |
| `chat_muted` | the admin told it to shut up for N hours |
| `sender_is_self` | its own message |
| `foreign_command` | a slash command belonging to one of the other bots |
| `user_banned` | it banned this person itself (§8.7) |
| `too_old` | a message replayed from the backlog after downtime |
| `busy` | already writing an answer in this chat |
| `daily_cap` / `hourly_cap` | safety valve |
| `throttled` | this person has been answered a lot, very recently |
| `bot_not_addressed` / `bot_exchange_limit` | another bot talking, or a loop forming |
| `quiet_hours` / `ambient_cooldown` / `not_worth_it` | ambient rules |
| `not_addressed` | nobody was talking to it |

**A safety valve firing is logged at warning level; `not_addressed` at debug.** The first
version logged everything at debug, so when the hourly cap silenced the bot there was no
line above debug to say why — from inside the chat it looked simply broken.

### 8.5 Safety valves, separate from the logic

Ceilings per hour and per day. These exist for bugs, not for rationing: a runaway gate
fires hundreds a **minute**, while people enjoying a new bot comfortably pass a hundred an
hour. **Direct addresses count towards the ceiling too** — otherwise it is trivially
bypassed by everyone calling the bot at once.

The defaults were wrong three times, each caught in production:

| set to | outcome |
|---|---|
| 60/day, 10/hour | silenced the bot within its first evening |
| 200/day, 30/hour | reached 24 within an hour of raising it |
| 800/day, 120/hour | hit outright the same evening |
| **1500/day, 300/hour** | current; roughly $0.42 in the worst hour |

The lesson is recorded in the code as a comment and a regression test, because the numbers
look arbitrary and invite being "tidied" back down.

### 8.6 Dynamic throttle, per person

The cap is a wall; this is the pacing. A person gets `throttle_after` replies free inside
a rolling window, after which each further reply demands a gap that grows by
`throttle_step`: 15s, 30s, 45s. Someone chatting never notices; someone hammering the bot
is answered more and more slowly and is never cut off entirely.

The first values — 3 free per 10 minutes with a 20s step — silenced normal conversation
within an evening, because one person easily earns five replies in ten minutes without
being a nuisance. Now 6 free per 5 minutes with a 15s step.

### 8.7 The bot can ignore someone itself

`ban_user(minutes, reason)` is the one client-side tool. The model decides who and for how
long; the two-day ceiling is not negotiable. A ban stops replies and nothing else — the
person's messages are still stored and still appear in the context window, so the
conversation reads correctly to everyone else. Being ignored is not being erased.

`/unban` in reply lifts it; `/unban` alone lists who is serving one.

### 8.8 Quiet hours

02:00–08:00 Kyiv time suppress **ambient and proactive only**. Direct address works around
the clock: if someone writes to the bot at three in the morning, silence is the wrong
answer. The window wraps midnight correctly, and setting both bounds equal disables it.

---

## 9. Daily digest job

Runs at 04:00 per active chat:

1. Read yesterday's messages (~28,500 tokens).
2. **Send them in ~2,000-token chunks**, each producing a partial summary and facts.
3. Regenerate the weekly summary **from the seven daily summaries, not from raw messages** —
   2,100 tokens of input instead of 200,000, a hundredfold cheaper and more stable, since it
   does not rewrite history from scratch each time.
4. Write results and a run-log row.

**The 30-day summary is abolished.** At this chat's volume it would compress ~850,000 tokens
into 800 — a ratio of 1000:1 that can only produce generalities the persona already
contains. It was measured as the single largest block of the legacy prompt, crowding out the
live conversation. Anything genuinely worth remembering from a month ago belongs in `facts`,
addressed and cheap.

**The digest runs on Flash-Lite.** Flash-Lite is ruled out for the persona, but summarising
has no voice requirement. At 0.86M tokens/month the difference is $0.64 on 3.7 Flash versus
**$0.09** on Flash-Lite — and the digest is easy to overlook precisely because it is one
call a day.

Memory extraction happens here and only here. The bot never calls memory tools while
replying; it receives finished facts in its prompt. Facts about **gryag itself** are
excluded: the persona already says who it is, and storing "гряг is sarcastic" would feed
the bot its own description as something to live up to.

### 9.1 Why the day is chunked

Sending a whole day at once was **refused outright**. The response carried no candidates
at all and `prompt_feedback.block_reason: PROHIBITED_CONTENT`. That filter is not
configurable — the `BLOCK_NONE` settings that make the persona possible do not touch it —
and it fires on the aggregate, which is why the reply path never trips it: a short window
wrapped in a persona passes where 8,000 tokens of raw transcript does not.

Chunking means a refused stretch costs that stretch. The live run put 5 of 6 chunks
through and produced a usable summary and twelve facts.

Two failures were found the same way, both silent:

- An empty response body was parsed as `{}` and stored as a blank summary, which the
  weekly pass then dutifully summarised — in English, reporting that there were no
  messages. **An empty body is now a failure, not an empty result.**
- A day where every chunk fails writes nothing rather than an empty summary.

---

## 9a. What the bot can do besides talk

Four capabilities were added after the original design. Three are **server-side Gemini
tools**, which matters: they cost nothing in the prompt, unlike the 137-token tool
manifest that was cut from the persona in §4.4.

| capability | how | cost |
|---|---|---|
| Google Search grounding | server-side tool | 5,000 free/month on 3.x, then $14/1,000 |
| Reading a URL | server-side tool | billed as input tokens, so a large page inflates the prompt |
| Running code | server-side tool | ordinary tokens |
| Banning someone | client-side function | a second round trip, only when it fires |
| Drawing and editing images | separate model call | per image, whitelist only |

**Mixing a client-side function with the server-side tools is refused** unless
`tool_config.include_server_side_tool_invocations` is set — the API says so in the error,
and it is the only reason the combination works.

**A tool call returns no text of its own.** The model asking to ban somebody produces an
empty reply, so the result is fed back and it gets a second turn to speak. That is the
only place in the reply path costing two round trips.

### 9a.1 Images

Nano Banana 2 (`gemini-3.1-flash-image`) generates and edits. Measured 2026-08-19:
generation ~8s, editing ~7s, ~900 KB per JPEG. Nano Banana Pro (`gemini-3-pro-image`)
takes ~16s for no visible gain at this size; Lite manages ~3s.

Billed per image rather than per token, so unlike the tools above it cannot be open to a
room of 33 people. The whitelist starts as the admin alone and is edited with `/nb` in
reply to somebody. Neither `/nb` nor `/unban` is registered with `setMyCommands`, so
neither appears in anyone's menu.

**Whether a message is a draw request is decided in plain code**, by looking for verbs
like `намалюй`. Routing it through the model would cost a round trip on every message to
answer a question that is almost always "no".

### 9a.2 Media the bot is asked to look at

Context always carries a two-token marker — `[фото]`, `[голосове]`, `[відео]`. Actually
looking is the expensive path and happens only when the bot is addressed about a specific
file, either attached to the triggering message or to the one it replies to.

Without this the model bluffs. Asked "як тобі" about a GIF it had never seen, it reviewed
it anyway, and then described its contents when pressed.

Animated stickers are refused: they are `.tgs`, a gzipped Lottie file, which no model
reads.

## 10. Model configuration

### 10.1 Default

Speaking model: `gemini-flash-latest` (currently 3.7 Flash), `thinking_budget: 0`.
Digest model: `gemini-2.5-flash-lite`. Image model: `gemini-3.1-flash-image`.

All are `config` rows. **Twenty-four settings now live there**, and the menu is generated
from a table of them, so adding a knob to the bot adds it to the menu. Nothing in the
running system requires a restart to change — including the persona, which is held in a
mutable box the menu can swap. Editing a voice and waiting for a deploy is how a voice
never gets tuned.

### 10.2 Quality is judged live, not blind

**Decided 2026-08-19: the blind test is not run.** The bot ships on the default
configuration and its voice is judged in the chat, by the people in it.

This is a deliberate trade. A blind scoresheet removes the scorer's bias about which model
they are reading; live testing does not, but it exercises the persona against real traffic
in real volume instead of 16 curated cases. Given that the design already rests on
measurements from that same chat, the second is the more honest test of the thing that
actually matters.

Two consequences follow, and both are load-bearing:

- **Switching models must be possible without a deploy.** Live comparison is only real if
  swapping the speaking model is a button press. This moves the model switch out of the
  admin menu's phase and into phase 1 (§15).
- **`usage` telemetry must exist from the first message**, or a switch cannot be evaluated
  against anything. Cost, latency and token mix per model are the only objective half of a
  judgement that is otherwise entirely subjective.

The candidates worth switching between are **configurations, not models**: (`flash-latest`,
thinking off) and (2.5 Flash, thinking off), both on the compressed persona. Measured, the
second costs about a third of the first.

The eval harness in `eval/` is kept but demoted. `cases.yaml` — 16 real cases — remains
useful as a regression fixture: after any persona edit, re-run it and check that replies
stay in voice, stay short, and never leak a speaker label. `run_blind.py` and `reveal.py`
are now vestigial.

### 10.3 Deprecation posture

`gemini-2.5-flash` has **no announced shutdown date** as of 2026-08-13, but it was released
2025-06-17 and is ~14 months old. For comparison, `gemini-2.0-flash` ran from 2025-02-05 to
2026-06-01 — about 16 months. The 1.5 family is already gone. Model choice must therefore
stay a config row, and the eval must stay reproducible, so a retirement notice costs one
evening rather than a rewrite.

### 10.4 Alias drift detector

Because `gemini-flash-latest` can be repointed silently, the cost panel compares this
week's mean `thought_tok` and latency against last week's and raises a warning on a step
change. This is the only available signal — the API will not tell us.

---

## 11. Error handling

**Gemini call fails** — two retries with backoff, then stay silent. The bot **never posts an
error message into the chat**; to the room it simply did not reply, which is normal human
behaviour.

**Empty response** — measured; happens when thinking consumes the output budget. Treated as
"said nothing", logged. `max_output_tokens` is **1500**: far above any reply the persona
should produce, chosen so that thinking can never crowd out the answer. Brevity is enforced
by the persona and judged on the scoresheet, never by the cap.

**Digest job fails** — logged, retried the next day. The weekly summary is built from
whichever daily summaries exist and does not fail on a missing day.

**SQLite locked** — WAL, short transactions, `busy_timeout`. Two processes on one file is
the only place they contend.

**Telegram send fails** — logged, not retried, to avoid duplicate posts.

**A prompt refused outright** — `PROHIBITED_CONTENT` with no candidates. Handled where it
happens: the digest drops that chunk (§9.1), an image request is dropped silently.

**Editing a menu message to identical content** — Telegram treats an edit that changes
nothing as an error, which tapping the section you are already in produces. Swallowed by
message, not by blanket catch.

**Deleted messages** — the Bot API sends ordinary bots no deletion update at all, so a
deleted message stays in the transcript forever and the bot may bring it up. This cannot
be fixed from here; it is a property of the platform worth knowing.

**Edited messages** — followed and applied to the stored text, but never answered.
Answering edits would let anyone re-trigger the bot by editing an old message.

---

## 12. Testing

190 tests, none of which make a live call.

The gate carries most of the value, as intended: 54 tests over a pure function, covering
every reason to speak and every reason not to. It has no network, no database and no
model, so the whole of the bot's behaviour can be exercised for free.

The context builder asserts that **no block ever exceeds its cap**, on any slice of
history. The LLM layer runs against fake clients, including one that returns a refusal
with no candidates and one that returns a tool call.

Three kinds of test exist here that are not about correctness in the usual sense, and each
was added after the mistake it now prevents:

- **Regression tests on defaults.** Reply caps and throttle thresholds are asserted to be
  at least as generous as the values production forced. The numbers look arbitrary and
  invite tidying.
- **A test on the menu's shape** — every entry names a real config key, every default is
  among its offered choices, and every label is short enough that Telegram will not
  ellipsise it. Menus fail visually, where no assertion normally looks.
- **A test that reads the entrypoint's source** to confirm the proactive loop is handed
  the objects it needs. It was once started with three names that did not exist there;
  the process died on boot and systemd restarted it into the same crash. No unit test
  catches that, because the wiring is the bug.

---

## 13. Deployment

**Live since 2026-08-19.**

- `gryag-bot.service` — systemd, webhook mode, restart on failure.
- `gryag.dobrovolskyi.com.ua` — A record to 152.53.101.121, proxied, created via the
  Cloudflare API. Caddy terminates TLS and reverse-proxies to **127.0.0.1:8137**.
- **The port is configurable and is not 8080 or 8081.** Both are held by docker-proxy on
  this host: binding failed, and Telegram meanwhile received a `302` from whichever
  container answered instead, which reads as a webhook fault rather than a port clash.
- `MODE=webhook|polling` in `.env`. Polling needs nothing external and is the fallback if
  DNS or TLS ever misbehave; at ~35 replies a day the difference is not observable.
- Verified end to end rather than by eye: a POST without the secret is refused with 401,
  one with the secret is accepted with 200, and the pending queue drained to zero.
- `gryag-digest.timer` — daily at 04:00, persistent so a missed run catches up.
- Python 3.13, `.venv` in place. `aiogram` 3.30, `google-genai` 2.18, `aiosqlite` 0.22,
  `pytest` 9 with `pytest-asyncio`.

**The update backlog is deliberately not dropped.** `drop_pending_updates=True` punched
11–16 message holes in the stored history at every restart; six restarts lost 81 of 329
messages, a quarter of the chat. Telegram holds updates for 24 hours, they are replayed
and stored, and `max_reply_age` is what stops the bot answering an argument that ended an
hour ago.
- Code lands on branch `main` of `ThatHunky/gryag`, overwriting the discarded V2
  architecture. `legacy` is left untouched.

### 13.1 Before the first push — privacy

`ThatHunky/gryag` is a public repository, and several files in this working directory carry
real personal data:

| path | contains |
|---|---|
| `chat_exports/` | 6,573 real messages, photos, voice and video — 491 MB |
| `eval/reference/production-prompt-2025-11-29.txt` | a real prompt dump: names, user IDs, stored memory facts |
| `eval/persona.txt`, `eval/persona-v3.txt` | real user IDs and nicknames of three people |
| `eval/cases.yaml` | verbatim real messages with real display names |
| `eval/out/` | model responses to all of the above |
| `.env` | API keys |

**Decided 2026-08-19: the chat history and the production prompt dump are never pushed.**
`chat_exports/`, `eval/reference/`, `eval/out/` and `.env` are gitignored accordingly.

Two files remain in the repository by necessity and still carry identities:
`persona.txt` / `persona-v3.txt` name three people with their user IDs, and `cases.yaml`
quotes real messages under real display names. The persona cannot be removed — the bot
needs it — so if that exposure ever matters, the fix is to move the three identities into a
gitignored include the code loads at startup, and to replace display names in `cases.yaml`
with the same short aliases the context builder already uses. Neither change affects
behaviour.

### 13.2 Related documents

`~/docs/gryag-v3-plan.md` and `~/docs/llm-providers-research-2026-08.md` hold the original
plan and the provider landscape. Both predate the measurements in §2–§4 and contain the
pricing error corrected in §3.4; read them for context, not for numbers.

---

## 14. Cost model

**The usage assumption was wrong, and by a lot.** The design assumed ~35 replies a day.
The first evening in the real chat produced 130, with 120 inside a single hour, because
people play with a new bot. Measured cost per reply is **$0.0014** at a ~1,460-token
prompt on `flash-latest`.

At a hundred replies a day that is ~$4.20/month; at three hundred, ~$12.60. The $10
prepaid covers weeks rather than months if the current pace holds. The two levers, in
order of size: switch the speaking model to 2.5 Flash from the menu (input 2.5× cheaper,
thinking 9× cheaper), or lower the hourly cap.

The table below keeps the original per-reply arithmetic, which is still correct — only the
volume assumption changed.

Assumptions: ~1,890-token prompt, ~35 replies/day (~1,100/month), thinking disabled,
no cache credit.

| | input | output | digest | **total/month** |
|---|---|---|---|---|
| 2.5 Flash | $0.62 | $0.04 | $0.09 | **~$0.75** |
| 3.7 Flash / `flash-latest` | $1.56 | $0.64 | $0.09 | **~$2.30** |
| 3.7 Flash from 2027-01-01 | $3.12 | $1.28 | $0.09 | **~$4.50** |

Against the $10 already prepaid: roughly 13 months on 2.5 Flash, 4 months on 3.7, dropping
to about 2 months once the promotional pricing ends.

Compression did most of this work. At the plan's original 3,700-token prompt the same
configuration on 3.7 Flash cost $4.41/month; at 1,890 tokens it costs $2.30. **The prompt
budget matters more than the model tier** — which is what finding §3.3 said before any of
this was measured.

---

## 15. Rollout

1. **Phase 1 — done.** Direct address, `usage` telemetry, model switch.
2. **Phase 2 — done.** Digest job, summaries, facts, on a daily timer.
3. **Phase 3 — built, switched off.** Ambient and proactive both default to `0`. They are
   the features most likely to annoy a room, and they should be turned on one at a time
   with somebody watching.
4. **Phase 4 — done.** Full menu, mute, persona hot reload, media on demand.

Delivered outside the plan, in response to what the chat actually needed: search, URL
reading and code execution; image generation and editing; the ban tool; partial quotes;
edit handling; ignoring other bots' commands; the per-person throttle; per-chat
serialisation.

**Everything above shipped in one session, which is why several defaults were wrong on
first contact.** The pattern is worth naming: every value that had to be guessed — reply
caps, throttle thresholds, `max_output_tokens` — was wrong the first time and was corrected
from production evidence within the hour. Each correction carries a comment and a
regression test, because the corrected values look arbitrary and invite being tidied back.

---

## 16. Resolved questions

All four open questions were closed on 2026-08-19.

1. **Blind test** — not run. Quality is judged live in the chat; see §10.2 and the two
   consequences it forces into phase 1.
2. **Trigger keywords** — `гряг` and its inflected forms, as a per-chat config row (§8.1).
   The collision with a human of that name in one chat is accepted.
3. **Ambient calibration** — the design as specified stands: ~10/day, derived from the
   observed rate, recalibrated after a week of real traffic.
4. **January 2027 pricing** — not planned around. A newer Flash is expected by then at
   broadly similar pricing, and the model is a config row either way. Note the practical
   effect: the balance drains roughly twice as fast from 1 January until the model is
   changed, so the cost panel is what should prompt the decision, not the calendar.

**Answered in production on 2026-08-19: the persona holds.** It stayed in voice across
war jokes, insults, provocations and a jailbreak attempt, picked up running threads from
the context window, and used search and code execution without narrating them. No refusals,
no moralising, no assistant drift.

What is genuinely open now:

1. **Ambient and proactive are untested with real people.** Both are off.
2. **Cost at the observed pace**, not the assumed one — see §14.
3. **The digest has never run on its own schedule.** Every run so far was manual; the first
   automatic one is at 04:00.
4. **The `PROHIBITED_CONTENT` refusal rate over time.** One chunk in six on the first day.
   If it climbs, the chunk size is the knob.

---

## 17. Live log

Every model or persona change, and what it did. Fill this in as phase 1 runs — without it,
"the voice got worse" is unattributable to anything.

| Date | Change | Replies | $/reply | p50 latency | Verdict |
|---|---|---|---|---|---|
| 2026-08-19 | Phase 1 live, `flash-latest`, thinking off | 130 first evening | $0.0014 | ~2.0s | In voice. Held under provocation. |
| 2026-08-19 | Compressed persona 1,792 → 637 tokens | — | — | — | Replies got shorter and sharper; the format leak disappeared. |
| 2026-08-19 | Phase 2, digest on Flash-Lite | 6 chunks/day | $0.0027/day | — | Usable summary, 12 facts, 1 chunk refused. |
| 2026-08-19 | Phase 3 built, left off | — | — | — | Untested with people. |
