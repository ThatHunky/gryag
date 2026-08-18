# Gryag V3 — Design Spec

**Date:** 2026-08-19
**Status:** approved, ready for implementation planning
**Supersedes:** `HANDOFF.md` (deleted; its surviving content is folded in below)

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
| `handlers` | receive updates, persist messages | `store` |
| `gate` | pure code: speak or not | config, chat state |
| `context` | assemble the prompt from its layers | `store` |
| `llm` | native Gemini call, usage telemetry | — |
| `admin` | inline-keyboard menu | `store`, config |
| `digest` | daily job: summaries + fact extraction | `store`, `llm` |
| `store` | SQLite, schema, migrations | — |

`gate` has no network and no LLM access by construction. It is a pure function of config
and chat state, fully testable offline. This is the structural difference from legacy,
where deciding whether to answer itself cost money.

### 5.2 Message path

```
Telegram → Caddy → /webhook → aiogram
   ↓
persist row in messages   (always, even when the bot will stay silent)
   ↓
gate.should_speak() ── no ──→ done
   ↓ yes
context.build() → llm.generate() → send → persist reply + usage row
```

Messages are stored **before** the gate decides. Otherwise history has holes exactly where
the bot stayed quiet, and the digest job summarises an incomplete day.

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
             media_kind, file_id, reply_to, is_bot,
             PRIMARY KEY (chat_id, message_id))
facts       (id PK, chat_id, user_id, text, source_day, created_at)
summaries   (chat_id, kind, period_start, period_end, text, tokens)
config      (scope, chat_id, key, value)
usage       (id PK, ts, chat_id, purpose, model, prompt_tok, cached_tok,
             visible_tok, thought_tok, latency_ms, cost_usd)
chat_state  (chat_id PK, last_spoke_ts, last_ambient_ts, muted_until)

CREATE INDEX ON messages (chat_id, ts);
CREATE INDEX ON messages (chat_id, reply_to);
```

`summaries.kind` is `'day'` or `'week'`. `config.scope` is `'global'` or `'chat'`.
`usage.purpose` is `'reply'` or `'digest'`.

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
also **a human being** (`user6560599034`, 117 messages), and there the bot would answer
every mention of that person. Accepted deliberately — that chat is not a deployment target,
and where it becomes one, the keyword gets edited.

### 8.2 Ambient interjection — target ~10 per day

A die is rolled on each message, with the probability derived from the chat's measured
rate. A candidate then passes local filters, none of which call the model:

- not from a bot (three other bots produce 6% of traffic)
- not an empty media message (17%)
- text longer than 30 characters — at a median of 19 this discards "ага" and "в"
- not inside a rapid reply exchange between two other people
- at least 20 minutes since the bot last spoke

### 8.3 Proactive after silence

Speaks unprompted when the chat has been quiet for ≥3 hours, local time is inside the
allowed window, and it has not spoken proactively for ≥6 hours. Measured, this will fire
almost exclusively in the morning: only 18 gaps longer than 15 minutes occurred in two days.

### 8.4 Never speaks

Chat disabled, mute active, message from a bot, or a safety valve tripped.

### 8.5 Safety valves, separate from the logic

Ceilings per hour and per day (default 60 replies/day). These exist for bugs, not for
money: if the gate breaks and starts firing on everything, the ceiling stops it before
anyone wakes up. **Direct addresses count towards the ceiling too** — otherwise it is
trivially bypassed by everyone calling the bot at once.

### 8.6 Quiet hours

02:00–08:00 suppress **ambient and proactive only**. Direct address works around the clock:
if someone writes to the bot at three in the morning, silence is the wrong answer.

---

## 9. Daily digest job

Runs at 04:00 per active chat:

1. Read yesterday's messages (~28,500 tokens).
2. One call to a cheap model: today's summary plus extracted facts about participants.
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
replying; it receives finished facts in its prompt.

---

## 10. Model configuration

### 10.1 Default

Speaking model: `gemini-flash-latest` (currently 3.7 Flash), `thinkingBudget: 0`.
Digest model: `gemini-2.5-flash-lite`.

Both are `config` rows, changeable from the menu without a restart.

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

---

## 12. Testing

The gate is a pure function, so it carries most of the test value: a table of input states
against expected decisions, with no network, no database and no model. All of the
behavioural complexity lives there.

The context builder is tested against a fixture database **seeded from the real export** —
6,573 genuine messages already on disk. The central assertion: no block ever exceeds its
cap, at any slice of history.

The LLM layer is tested against recorded responses. No test makes a live call.

---

## 13. Deployment

- `gryag-bot.service` — systemd, webhook mode, restart on failure.
- Caddy terminates TLS on a new subdomain of `dobrovolskyi.com.ua` and reverse-proxies to
  the bot's local port. Caddy already serves a dozen subdomains on that domain.
- `gryag-digest.timer` — daily at 04:00, persistent so a missed run catches up.
- Python 3.13, `.venv` in place. New dependencies: `aiogram`, `google-genai`, `aiosqlite`.
  The current `requirements.txt` (`openai`, `pyyaml`, `python-dotenv`) serves the eval
  harness only.
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

1. **Phase 1** — one chat, direct address only, no ambient, no proactive. Includes
   `usage` telemetry and a model/effort switch, because §10.2 makes those the instruments
   the voice is judged with. Verify voice, cost and latency against the numbers in §14.
2. **Phase 2** — digest job, summaries, facts.
3. **Phase 3** — ambient and proactive triggers.
4. **Phase 4** — full admin menu, media on demand.

Phase 1 is deliberately the smallest thing that can be judged. Ambient interjection is the
feature most likely to annoy people, and it should not ship before the voice is known good.

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

The only genuinely unknown quantity left is whether the persona holds in live traffic —
which is, by construction, what phase 1 answers.

---

## 17. Live log

Every model or persona change, and what it did. Fill this in as phase 1 runs — without it,
"the voice got worse" is unattributable to anything.

| Date | Change | Replies/day | $/day | p50 latency | Verdict on the voice |
|---|---|---|---|---|---|
| | | | | | |
