#!/bin/bash
# =============================================================================
# check-payload-consistency.sh -- the bench and `health` must send the SAME request
# =============================================================================
# The measurement payload is duplicated in two per-node scripts. That is not an
# oversight: they are deployed as two separate files into $HOME and there is nowhere
# shared to put it, and `evidence/2026-09-28/instrument-v4-and-config/` records the
# decision to keep the JSON skeleton in code rather than in cluster.env (a printf format
# in a config file fails silently — too few arguments and printf just repeats the
# format).
#
# Duplication is therefore accepted, and made safe here. The drift it risks is silent and
# one-sided: if `health` stops posting what the bench posts, `health` keeps printing OK
# while validating something else — the one thing a health check must not do. This check
# turns that into a failure in the repo, before anything is deployed.
#
# Checks:
#   1. the two JSON skeletons are byte-identical
#   2. both spell the same default values, and those equal cluster.env's
#   3. the skeleton still carries every field the measurement depends on
#   4. neither script's fallback can produce invalid JSON for the default prompt
#
# usage: bash infra/selftest/check-payload-consistency.sh      (exit 1 on any failure)
# =============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

python3 - "$ROOT" <<'PY'
import re, sys, hashlib

root = sys.argv[1]
paths = {
    "bench": f"{root}/infra/scripts/node_gpu_bench.sh",
    "health": f"{root}/infra/scripts/node_vllm_service.sh",
    "config": f"{root}/infra/config/cluster.env",
}
src = {}
for k, p in paths.items():
    try:
        src[k] = open(p, encoding="utf-8").read()
    except OSError as e:
        print(f"FAIL  cannot read {p}: {e}")
        sys.exit(1)

fails, notes = [], []

# --- 1. the JSON skeletons --------------------------------------------------
tpl = {}
for k in ("bench", "health"):
    m = re.search(r"printf '(\{\"model\".*?\})'", src[k], re.S)
    if not m:
        fails.append(f"{k}: no JSON skeleton found (expected a single-quoted printf starting with {{\"model\")")
        continue
    tpl[k] = m.group(1)

if len(tpl) == 2:
    if tpl["bench"] == tpl["health"]:
        notes.append(f"skeleton identical: {hashlib.sha256(tpl['bench'].encode()).hexdigest()[:16]} ({len(tpl['bench'])} bytes)")
    else:
        fails.append("skeletons DIFFER -- the bench and health would send different requests")
        for i, (a, b) in enumerate(zip(tpl["bench"], tpl["health"])):
            if a != b:
                fails.append(f"  first difference at byte {i}: bench={a!r} health={b!r}")
                fails.append(f"  bench : ...{tpl['bench'][max(0,i-40):i+40]}...")
                fails.append(f"  health: ...{tpl['health'][max(0,i-40):i+40]}...")
                break

# --- 2. the values ----------------------------------------------------------
# The three scripts name the value differently on purpose -- cluster.env and the bench
# spell it VLM_PROMPT / DEFAULT_PROMPT, and vllm-service uses short local names fed from
# the VLM_* one (PROMPT="${VLM_PROMPT:-...}"). So the left-hand name and the name inside
# the expansion are separate arguments. Looking for `VAR="${VAR:-...}"` instead silently
# captured `"${VLM_PROMPT:-Identify` as the prompt and made this check fail always, i.e.
# made it useless.
VALUES = (
    ("prompt",      "VLM_PROMPT",      "DEFAULT_PROMPT",      "PROMPT"),
    ("max_tokens",  "VLM_MAX_TOKENS",  "DEFAULT_MAX_TOKENS",  "MAXTOK"),
    ("temperature", "VLM_TEMPERATURE", "DEFAULT_TEMPERATURE", "TEMPER"),
)

def grab_default(text, lhs, ref=None):
    """Default written for `lhs`, whether as lhs="${ref:-X}", lhs='X' or lhs=X."""
    ref = ref or lhs
    m = re.search(r'^' + re.escape(lhs) + r'="\$\{' + re.escape(ref) + r':-([^}]*)\}"', text, re.M)
    if m:
        return m.group(1)
    m = re.search(r'^' + re.escape(lhs) + r"='([^']*)'", text, re.M)
    if m:
        return m.group(1)
    m = re.search(r'^' + re.escape(lhs) + r'=(\S+)', text, re.M)
    return m.group(1) if m else None

want, got = {}, {"bench": {}, "health": {}}
for key, cfg_var, bench_var, svc_var in VALUES:
    want[key] = grab_default(src["config"], cfg_var)
    got["bench"][key] = grab_default(src["bench"], bench_var)
    got["health"][key] = grab_default(src["health"], svc_var, cfg_var)

for key, _cfg_var, _bench_var, _svc_var in VALUES:
    if want[key] is None:
        fails.append(f"cluster.env: default for {key} not found")
        continue
    for k in ("bench", "health"):
        if got[k][key] is None:
            fails.append(f"{k}: default for {key} not found")
        elif got[k][key] != want[key]:
            fails.append(f"{key}: {k} default {got[k][key]!r} != cluster.env {want[key]!r}")
if not fails:
    notes.append(f"values agree: prompt={want['prompt']!r} max_tokens={want['max_tokens']} temperature={want['temperature']}")

# --- 3. the fields the measurement depends on -------------------------------
if "bench" in tpl:
    for field in ('"model":"%s"', '"temperature":%s', '"max_tokens":%s',
                  '"type":"image_url"', '"type":"text"', '"text":"%s"'):
        if field not in tpl["bench"]:
            fails.append(f"skeleton is missing {field!r} -- the measurement changed meaning")
    if tpl["bench"].count("%s") != 5:
        fails.append(f"skeleton has {tpl['bench'].count('%s')} %s placeholders, expected 5 "
                     "(model, temperature, max_tokens, base64, prompt)")

# --- 4. the default prompt must survive JSON interpolation ------------------
# Both scripts refuse a prompt containing a double quote, a backslash or a control
# character (they would corrupt the body). A default that trips its own guard would make
# every run in fallback mode exit 2.
if want["prompt"]:
    bad = [c for c in want["prompt"] if c in '"\\' or ord(c) < 0x20]
    if bad:
        fails.append(f"cluster.env default prompt contains characters the scripts reject: {bad!r}")

print("check-payload-consistency")
for n in notes:
    print(f"  ok    {n}")
for f in fails:
    print(f"  FAIL  {f}")
print("  VERDICT:", "OK" if not fails else f"{len(fails)} FAILURE(S)")
sys.exit(1 if fails else 0)
PY
