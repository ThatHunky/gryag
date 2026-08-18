#!/usr/bin/env python3
"""Performance + behaviour comparison across Gemini candidates.

Deliberately NOT the blind quality test — that is run_blind.py. This one talks
to the *native* endpoint, because the OpenAI compatibility layer was measured on
2026-08-18 to serve implicit cache hits once in 37 calls while native served
46-93%, and because only native reports thoughtsTokenCount. Cost numbers from
the compat layer are therefore not representative of production.
"""
import json, os, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent
KEY = os.environ["GEMINI_API_KEY"]
MAXTOK = 1500

# in / out / cached-in, USD per 1M tokens. Verified against Google's pricing
# page on 2026-08-18; 3.x rates are promotional and double on 2027-01-01.
PRICE = {
    "gemini-2.5-flash":    (0.30, 2.50, 0.03),
    "gemini-3.7-flash":    (0.75, 3.75, 0.075),
    "gemini-3.6-flash":    (0.75, 3.75, 0.075),
    "gemini-flash-latest": (0.75, 3.75, 0.075),
}

def call(model, system, user, effort=None):
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": MAXTOK},
    }
    if effort is not None:
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": effort}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={KEY}",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t = time.time()
    try:
        d = json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:200], "latency": time.time() - t}
    dt = time.time() - t
    u = d.get("usageMetadata", {})
    cand = (d.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    return {
        "text": text, "latency": dt,
        "prompt": u.get("promptTokenCount", 0),
        "cached": u.get("cachedContentTokenCount", 0),
        "out": u.get("candidatesTokenCount", 0) or 0,
        "thoughts": u.get("thoughtsTokenCount", 0) or 0,
        "finish": cand.get("finishReason"),
    }

def build(case):
    ctx = case.get("context") or ""
    return (f"{ctx}\n[CURRENT MESSAGE] {case['message']}" if ctx else case["message"])

def main():
    argv = sys.argv[1:]
    persona_file = "persona.txt"
    if "--persona" in argv:
        i = argv.index("--persona"); persona_file = argv[i + 1]; del argv[i:i + 2]
    think = None
    if "--think" in argv:
        i = argv.index("--think"); think = int(argv[i + 1]); del argv[i:i + 2]
    models = argv or list(PRICE)
    persona = (ROOT / persona_file).read_text()
    cases = yaml.safe_load((ROOT / "cases.yaml").read_text())
    jobs = [(m, c) for m in models for c in cases]
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda j: (j[0], j[1], call(j[0], persona, build(j[1]), think)), jobs))
    print(f"thinkingBudget = {think if think is not None else 'model default'}\n")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    outdir = ROOT / "out" / stamp
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "raw.json").write_text(json.dumps(
        [{"model": m, "case": c["id"], **r} for m, c, r in res], ensure_ascii=False, indent=1))

    print(f"{'model':<20}{'ok':>4}{'lat p50':>9}{'lat p90':>9}{'prompt':>8}{'cache%':>8}"
          f"{'visible':>9}{'thoughts':>9}{'$/1k replies':>14}{'$/mo':>8}")
    for m in models:
        rs = [r for mm, _, r in res if mm == m and "error" not in r]
        if not rs:
            print(f"{m:<20}   0   — all calls failed"); continue
        lat = sorted(r["latency"] for r in rs)
        p = lambda q: lat[min(len(lat) - 1, int(len(lat) * q))]
        avg = lambda k: sum(r[k] for r in rs) / len(rs)
        pin, pout, pcache = PRICE[m]
        cache_frac = avg("cached") / avg("prompt") if avg("prompt") else 0
        # cost of one reply at the measured cache rate and measured token mix
        cin = avg("prompt") * ((1 - cache_frac) * pin + cache_frac * pcache) / 1e6
        cout = (avg("out") + avg("thoughts")) * pout / 1e6
        per1k = (cin + cout) * 1000
        print(f"{m:<20}{len(rs):>4}{p(.5):>8.2f}s{p(.9):>8.2f}s{avg('prompt'):>8.0f}"
              f"{100*cache_frac:>7.1f}%{avg('out'):>9.0f}{avg('thoughts'):>9.0f}"
              f"{per1k:>13.2f}${(cin+cout)*1350:>7.2f}")
    errs = [(m, c["id"], r["error"]) for m, c, r in res if "error" in r]
    for m, cid, e in errs[:5]:
        print(f"  ERROR {m} {cid}: {e[:110]}")
    print(f"\nraw -> {outdir}/raw.json")

if __name__ == "__main__":
    main()
