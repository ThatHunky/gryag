#!/usr/bin/env python3
"""Blind persona test: run every candidate model over the same cases.

Produces a scoring sheet with model names hidden behind stable labels (A, B, C…)
and the display order shuffled per case, so neither identity nor position can
bias the scoring. The label→model mapping is written to a separate key file that
you should not open until after scoring.

Usage:
    python eval/run_blind.py
    python eval/run_blind.py --cases eval/cases.yaml --repeat 2
    python eval/run_blind.py --only "Gemini 3.7 Flash,Gemini 2.5 Flash"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import string
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
    from dotenv import load_dotenv
    from openai import AsyncOpenAI
except ImportError as exc:  # pragma: no cover
    sys.exit(f"Missing dependency: {exc.name}. Run: pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent

# Every provider below speaks the OpenAI chat-completions dialect, including
# Gemini via its compatibility endpoint. One client class covers all of them.
PROVIDERS = {
    "gemini": (
        "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1"),
    "moonshot": ("MOONSHOT_API_KEY", "https://api.moonshot.ai/v1"),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com"),
    "dashscope": (
        "DASHSCOPE_API_KEY",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    ),
}

# Gemini 3.x and 2.5 are thinking models: reasoning tokens are drawn from this
# same budget and billed as output, but never appear in the reply. Measured on
# the provocation case, 2.5 Flash spent 380 reasoning tokens and got cut off
# mid-word at 400, while 3.7 Flash spent 208. A tight ceiling therefore scores
# truncation as bad writing. Keep this generous — brevity is judged on the
# scoresheet, not enforced by the cap.
MAX_TOKENS = 1500
CONCURRENCY = 4
ATTEMPTS = 3


@dataclass
class Candidate:
    name: str
    provider: str
    model: str
    price_in: float
    price_out: float
    note: str = ""
    label: str = ""


@dataclass
class Result:
    case_id: str
    label: str
    text: str
    latency_s: float
    tokens_in: int = 0
    tokens_out: int = 0
    error: str = ""


@dataclass
class RunStats:
    calls: int = 0
    failures: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    latencies: list[float] = field(default_factory=list)

    @property
    def p50(self) -> float:
        if not self.latencies:
            return 0.0
        ordered = sorted(self.latencies)
        return ordered[len(ordered) // 2]


def resolve(models_cfg: list[dict], only: set[str]) -> tuple[list[Candidate], list[str]]:
    """Pick a reachable provider for each model based on which keys are present."""
    chosen: list[Candidate] = []
    skipped: list[str] = []

    for entry in models_cfg:
        name = entry["name"]
        if entry.get("enabled") is False and name not in only:
            continue
        if only and name not in only:
            continue

        price = entry.get("price", {})
        native = entry.get("native") or {}
        native_provider = native.get("provider")

        if native_provider in PROVIDERS and os.getenv(PROVIDERS[native_provider][0]):
            chosen.append(
                Candidate(name, native_provider, native["model"],
                          price.get("in", 0.0), price.get("out", 0.0),
                          entry.get("note", ""))
            )
        elif entry.get("openrouter") and os.getenv(PROVIDERS["openrouter"][0]):
            chosen.append(
                Candidate(name, "openrouter", entry["openrouter"],
                          price.get("in", 0.0), price.get("out", 0.0),
                          entry.get("note", ""))
            )
        else:
            need = PROVIDERS.get(native_provider, ("OPENROUTER_API_KEY",))[0]
            skipped.append(f"{name} (needs {need} or OPENROUTER_API_KEY)")

    return chosen, skipped


def build_messages(persona: str, case: dict) -> list[dict]:
    parts = []
    if case.get("context"):
        parts.append("Попередні повідомлення в чаті:\n" + case["context"].strip())
    parts.append(case["message"].strip())
    return [
        {"role": "system", "content": persona},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


async def ask(client: AsyncOpenAI, cand: Candidate, case: dict,
              persona: str, sem: asyncio.Semaphore) -> Result:
    messages = build_messages(persona, case)
    last_err = ""

    async with sem:
        for attempt in range(1, ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                resp = await client.chat.completions.create(
                    model=cand.model,
                    messages=messages,
                    max_tokens=MAX_TOKENS,
                )
                elapsed = time.perf_counter() - started
                usage = getattr(resp, "usage", None)
                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    last_err = "empty response"
                    continue
                return Result(
                    case_id=case["id"],
                    label=cand.label,
                    text=text,
                    latency_s=elapsed,
                    tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
                    tokens_out=getattr(usage, "completion_tokens", 0) or 0,
                )
            except Exception as exc:  # noqa: BLE001 — report, never crash the run
                last_err = f"{type(exc).__name__}: {exc}"
                if attempt < ATTEMPTS:
                    await asyncio.sleep(1.5 * attempt)

    return Result(case["id"], cand.label, "", 0.0, error=last_err)


async def main() -> int:
    ap = argparse.ArgumentParser(description="Blind persona test for gryag")
    ap.add_argument("--persona", default=str(ROOT / "persona.txt"))
    ap.add_argument("--cases", default=str(ROOT / "cases.yaml"))
    ap.add_argument("--models", default=str(ROOT / "models.yaml"))
    ap.add_argument("--out", default=str(ROOT / "out"))
    ap.add_argument("--repeat", type=int, default=1,
                    help="samples per case — >1 exposes run-to-run variance")
    ap.add_argument("--only", default="",
                    help="comma-separated model names to include")
    args = ap.parse_args()

    load_dotenv(PROJECT / ".env")

    persona = Path(args.persona).read_text(encoding="utf-8").strip()
    cases = yaml.safe_load(Path(args.cases).read_text(encoding="utf-8")) or []
    models_cfg = yaml.safe_load(Path(args.models).read_text(encoding="utf-8")) or []
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    candidates, skipped = resolve(models_cfg, only)
    if not candidates:
        print("No reachable models. Set GEMINI_API_KEY (or OPENROUTER_API_KEY) in .env.",
              file=sys.stderr)
        for line in skipped:
            print(f"  skipped: {line}", file=sys.stderr)
        return 1

    # Stable anonymous label per model for the whole run.
    labels = list(string.ascii_uppercase)
    random.shuffle(candidates)
    for i, cand in enumerate(candidates):
        cand.label = labels[i]

    print(f"Models:  {len(candidates)}  ·  cases: {len(cases)}  ·  repeat: {args.repeat}")
    for line in skipped:
        print(f"  skipped: {line}")

    clients = {
        p: AsyncOpenAI(api_key=os.environ[env], base_url=url)
        for p, (env, url) in PROVIDERS.items()
        if os.getenv(env)
    }
    sem = asyncio.Semaphore(CONCURRENCY)

    tasks, meta = [], []
    for rep in range(args.repeat):
        for case in cases:
            for cand in candidates:
                tasks.append(ask(clients[cand.provider], cand, case, persona, sem))
                meta.append((rep, case, cand))

    print(f"Running {len(tasks)} calls…")
    results = await asyncio.gather(*tasks)

    stats: dict[str, RunStats] = {c.label: RunStats() for c in candidates}
    for res in results:
        st = stats[res.label]
        st.calls += 1
        if res.error:
            st.failures += 1
        else:
            st.tokens_in += res.tokens_in
            st.tokens_out += res.tokens_out
            st.latencies.append(res.latency_s)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    by_case: dict[tuple[int, str], list[Result]] = {}
    for (rep, case, _cand), res in zip(meta, results):
        by_case.setdefault((rep, case["id"]), []).append(res)

    # ── blind sheet ──────────────────────────────────────────────────────
    sheet = [
        f"# Blind persona test — {run_id}",
        "",
        f"{len(candidates)} models · {len(cases)} cases · {args.repeat} sample(s) each.",
        "",
        "Score each response 1–5 on four axes, then fill `scores.csv`:",
        "",
        "| Axis | 1 | 5 |",
        "|---|---|---|",
        "| **sarcasm** | flat, polite, assistant-like | lands, sharp, actually funny |",
        "| **ukrainian** | stiff, translated-sounding | natural colloquial Ukrainian |",
        "| **brevity** | essay when a line would do | length matches the moment |",
        "| **character** | breaks frame, hedges, apologises | stays gryag under pressure |",
        "",
        "Do not open `key.json` until the scoresheet is filled.",
        "",
        "---",
        "",
    ]

    for rep in range(args.repeat):
        for case in cases:
            items = list(by_case.get((rep, case["id"]), []))
            random.shuffle(items)  # kill positional bias, labels stay stable
            title = case["id"] if args.repeat == 1 else f"{case['id']} · sample {rep + 1}"
            sheet.append(f"## {title}")
            if case.get("probes"):
                sheet.append(f"*probes: {case['probes']}*")
            sheet.append("")
            if case.get("context"):
                sheet.append("```")
                sheet.append(case["context"].strip())
                sheet.append("```")
            sheet.append(f"**→ {case['message'].strip()}**")
            sheet.append("")
            for res in items:
                sheet.append(f"### [{res.label}]")
                sheet.append("")
                if res.error:
                    sheet.append(f"> ⚠️ failed: {res.error}")
                else:
                    sheet.append("```")
                    sheet.append(res.text)
                    sheet.append("```")
                sheet.append("")
            sheet.append("---")
            sheet.append("")

    (out_dir / "blind.md").write_text("\n".join(sheet), encoding="utf-8")

    # ── scoresheet template ──────────────────────────────────────────────
    rows = ["case,sample,label,sarcasm,ukrainian,brevity,character,notes"]
    for rep in range(args.repeat):
        for case in cases:
            for cand in sorted(candidates, key=lambda c: c.label):
                rows.append(f"{case['id']},{rep + 1},{cand.label},,,,,")
    (out_dir / "scores.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    # ── key + measured cost ──────────────────────────────────────────────
    key = {}
    for cand in sorted(candidates, key=lambda c: c.label):
        st = stats[cand.label]
        # Extrapolate the plan's workload: 3.3M input + 0.16M output per month.
        avg_in = st.tokens_in / max(st.calls - st.failures, 1)
        avg_out = st.tokens_out / max(st.calls - st.failures, 1)
        monthly = (3.3 * cand.price_in) + (0.16 * cand.price_out)
        key[cand.label] = {
            "name": cand.name,
            "provider": cand.provider,
            "model": cand.model,
            "note": cand.note,
            "price_per_1m": {"in": cand.price_in, "out": cand.price_out},
            "measured": {
                "calls": st.calls,
                "failures": st.failures,
                "avg_tokens_in": round(avg_in, 1),
                "avg_tokens_out": round(avg_out, 1),
                "latency_p50_s": round(st.p50, 2),
            },
            "projected_monthly_usd_no_cache": round(monthly, 2),
        }
    (out_dir / "key.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    failures = sum(s.failures for s in stats.values())
    print(f"\n✓ {out_dir}")
    print(f"  blind.md   — score this, {len(cases) * args.repeat} cases")
    print(f"  scores.csv — fill in 1–5 per axis")
    print(f"  key.json   — do not open until scored")
    if failures:
        print(f"  ⚠️ {failures} call(s) failed — see blind.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
