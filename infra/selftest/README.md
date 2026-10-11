# Offline self-test harness

A fake `ssh` (and `rsync`) so the cluster scripts can be executed end-to-end
**without touching the real nodes**. Useful when editing the scripts.

```bash
cd iot-audit/infra
export PATH="$PWD/selftest/bin:$PATH"
export STUB_STATE="$PWD/selftest/state.json"
export STUB_LOG="$PWD/selftest/ssh.log"
rm -f "$STUB_STATE" "$STUB_LOG"

./scripts/cluster_status.sh
./scripts/sync_models.sh --dry-run
./scripts/start_qwen_all.sh
./scripts/stop_qwen_all.sh
./scripts/start_llama_all.sh
./scripts/stop_llama_all.sh
./scripts/run_benchmark.sh --model qwen --images assets/test-images --output selftest/out.json
```

(`--images` used to point at `selftest/images`, which `.gitignore` excludes and which does
not exist, so the example could not run. `assets/test-images` — paths here are relative to
`infra/` — is the versioned image directory added on 2026-09-28; see
`assets/README.md`.)

Knobs:

- `STUB_CURL_FAIL=1` — simulate every `/v1/models` probe failing (exercises the
  "server refused to start / did not come up" paths).
- `STUB_LOG` — every remote command the scripts issued, in order.

The stub models: zabeth23 has the Qwen dir and port 8000 occupied; zabeth22 has
the GGUF + `llama.cpp/build/bin`; zabeth21 starts empty. `rsync` marks the
destination as having the artifact, so the post-sync integrity check passes.

## Checks that are not about the stubs

Nine checks test arithmetic, duplication, queue shape, blast radius, the `MAXTOK_SET` knobs,
the generated-length reading, the service's own telemetry, and caller-safe kill scoping (twice: on a node
and on the local tunnel) rather than the cluster scripts.
All are deterministic, need no node, and exit non-zero on failure.

```bash
bash selftest/check-payload-consistency.sh   # the bench and `health` must send the SAME request
bash selftest/check-metrics-math.sh          # the server-side split must compute what it claims
bash selftest/check-queue-shape.sh           # the queue's total and max must be what they claim
bash selftest/check-stop-scope.sh            # `stop` must not see, or kill, its own caller
bash selftest/check-cluster-kill-scope.sh    # cluster-level kill_by_pattern must not terminate caller
bash selftest/check-tunnel-scope.sh          # `tunnel_vllm.sh stop` must not kill its own caller
bash selftest/check-bench-variants.sh        # what the OPT-IN knobs claim, they must do
bash selftest/check-gen-length.sh            # the published generated length must be read, not invented
bash selftest/check-no-vllm-telemetry.sh     # the service must not post to stats.vllm.ai at startup
```

`check-no-vllm-telemetry.sh` (2026-09-29) — the service script must keep vLLM's usage-stats
opt-out **inside its launch path**, by variable (`VLLM_NO_USAGE_STATS=1`) and by file
(`$HOME/.config/vllm/do_not_track`, which an exported variable cannot cover for a hand-run
`vllm`). It exists because the property was measured, not assumed: with an emitter-attribution
instrument that records *(destination · port · **emitting uid**)*, a **real** service restart
under a cut of everything outside the campus recorded `uid 10131` — the service's own account
— opening `stats.vllm.ai:443`. The package names it: `vllm/envs.py:36` sets the server,
`vllm/usage/usage_lib.py:268` posts, by default, at engine start. The check asserts position,
not just presence (both opt-out lines must sit between the `PATH` export and the `nohup
setsid` that starts the engine), and it carries the **negative control** this directory
always asks for: on a copy of the script with the opt-out deleted, the same analysis must
**fail**. See `../README.md`, the 03h section, and `evidence/2026-09-28/risk-probes/SUMMARY.md`
§24.3.

`check-payload-consistency.sh` — the measurement payload is duplicated in two per-node
scripts (they are deployed as separate files into `$HOME`, so there is nowhere shared to
put it). The drift it risks is silent and one-sided: if `health` stops posting what the
bench posts, `health` keeps printing OK while validating something else.

`check-metrics-math.sh` — `MODE=sweep` reads vLLM's Prometheus histograms to split a
request into queue / prefill / decode, and **a wrong split prints exactly like a right
one**. So the test is *differential and cross-language*: the awk under test is **extracted
from `node_gpu_bench.sh`** (never copied — a test that tests its own copy proves nothing),
and the truth is computed in Python by sorting and indexing. 312 cases (12 designed + 300
random with a fixed seed), across the **real** bucket labels (`1.0`, not `1` — vLLM writes
the float form) and **both** bucket lists (e2e has 21 finite bounds, TTFT has 22 and goes
down to 0.001 s), because the bounds are read off the wire and not assumed.

It also guards itself two ways, and both were earned:

- snapshots and expected values are **derived from one description**, and their arithmetic
  is asserted before anything is written. The first version of the fixture wrote deltas
  where Prometheus writes absolute cumulative counters, so it disagreed with its own
truth; a test that measures its own error passes and means nothing.
- a **negative control** re-derives the pre-2026-09-28 `metrics_delta` (which picked the
  baseline with `FNR == NR`, an idiom that assumes the first file is non-empty) and asserts
  the two behave *differently* on an empty `before` snapshot. Without it, a test that passes
  on the broken code as readily as on the fixed code proves nothing about that case.

It fails loudly and by name if the extracted functions are not valid shell — the cause is
almost always an ASCII apostrophe inside a single-quoted awk program (see the ninth pass
in `infra/README.md`).

`check-bench-variants.sh` — the five OPT-IN knobs added on the day (`MAXTOK_SET`,
`VARY_PREFIX`, `VARY_ROTATE`, `VARIANT_COUNT`, `VARY_STRIDE`) are only safe if the **default** path is
unchanged, and only useful if they recreate the payload construction they claim to. It
extracts `build_body_for`, `build_body`, `build_bodies` and `body_index`, then asserts both
halves: with the knobs off the bodies are byte-identical to the pre-knob bench, and with them
on there are exactly `images x tiers` bodies, none duplicated, with the rotation advancing one
body per request while a worker's position stays fixed without it. It earned its keep
immediately: it caught **two real defects on its first run** — a specific diagnostic
(`PREFIXE_VARIE_IMPOSSIBLE`) swallowed by a `>/dev/null`, and negative deltas from two
identical snapshots.

`VARIANT_COUNT` is the knob where a *silent* wrong answer is most tempting, so its case is
narrower than the others: it asserts that limiting the working set to `N` yields the bodies
for the **first `N` variants in sorted order**, compared by hash against the full set. A
version that kept the right *number* of prefixes but not the right *ones* would make every
point of a retention curve incomparable with the others, and would do it without any
diagnostic at all.

`VARY_STRIDE` (fifteenth pass) is the knob that decides **which** workers can share a prefix
at the same instant, and section 9 computes that geometry from the bench's own bytes rather
than asserting it: for 4 workers on a set of 32 it prints the shareable fraction per stride
(`75 / 50 / 25 / 0 %`), and it fails by name if a stride equal to the concurrency left **any**
sharing possible — because then the run would not be the test it claims to be.

**But that computed fraction is a geometry assertion, not a prediction.** Section 9 originally
framed it as "the share the experiment predicts", and the same pass measured the prediction
false: a regime with `S = W` **does** drop to 0.00 %, yet so does a regime with *no sharing at
all* and a 32-prefix set — while a no-sharing regime with a 4-prefix set hits **95.8 %**. The
shareable fraction is **correlated** with the reuse distance here; it is not its cause. The
comment in section 9 now says so, and the check asserts only what it can: the geometry.

Section 9 also had a defect of the exact class this directory exists to catch, found while
adding the stride knob: its output went through a **pipe** (`( … ) | sed`), so a section that
aborted mid-way published neither `OK` nor `ECHEC`, `FAIL` stayed 0, and the script printed
`VERDICT : OK` over controls that had **not run**. It now writes to a file and checks the
section's return code, and a negative control proves the guard bites: an `exit 7` injected
inside the section yields `ECHEC la section 9 s'est arretee avant la fin (rc=7)` and exit 1,
where the piped form silently exited 0. The mechanism is reproduced in
`evidence/2026-09-28/risk-probes/tiered-and-retention/pipeline-vs-fichier.txt`.

`check-gen-length.sh` — the v9/v10 line publishes the length *actually* generated, and its
value is a **ratio of two counter deltas**: a wrong filter or a name collision prints a
plausible number rather than an error. It extracts `bracket_bound` and `metrics_counter` and
covers 19 cases, including the three ways this class of code has already gone wrong here: a
metric that has our metric's name as a **prefix** (`..._total` vs `..._total_extra`, which
must not be double-counted), an **empty `before` snapshot** (the `FNR == NR` idiom read it as
the baseline), and an unreadable bracket (which must render `NA`, never `0` — a zero is a
measurement, `NA` is the absence of one). See `infra/README.md`, fourteenth pass.

`check-stop-scope.sh` — measured on 2026-09-28, on zabeth23 with one live vLLM server and
one `EngineCore`, `pgrep -f` answered **3** for each of `stop`'s two name patterns: called
through a `bash -c`, the *caller's own command line* carries the pattern and counts itself
(plus the command-substitution subshell). That is a wrong number. It is worse than a wrong
number, because the same pattern was fed to `pkill -f`, so `stop` could signal the session
that launched it. The check launches one stray with the pattern on its own argv, from an
agent whose own line carries the pattern, and asserts four things: the historical form
miscounts (negative control — without it the fixed form's passing proves nothing), the
fixed `stray_by_name()` returns exactly the stray, killing exactly what it returned kills
the stray and leaves the agent running, and the historical `pkill -f` kills the agent.

The stray is started under `setsid` **on purpose**: the real service is, so it lives in its
own process group, and that is the invariant which makes it safe for the fix to discard its
own group. A test that ran the stray in our group would see the fix discard it and conclude
the function had gone blind. The check verifies the stray is its own group leader and exits
with an error if it is not.

`check-queue-shape.sh` — added on 2026-09-28 with instrument v6, when the published
`request_queue_time_seconds` split stopped being a single mean per request. A mean divides a
short peak by every request served, so it cannot answer "did anyone wait"; v6 also publishes
`total` (the **exact** SUM — an upper bound on the max, since every wait is ≥ 0 and no request
can exceed it) and the bucket interval / count above an edge. The script **extracts** the five
metric functions from `node_gpu_bench.sh` (never copies them), asserts they are valid shell
before running, and drives **206 cases** (6 designed + 200 random with a fixed seed, 20260928)
for **824 comparisons**. Two things it pins down: the edge is **strict** — 50 values exactly at
0.3 s give `OVER 0` (the negative control, and the only reading compatible with `(a;b]`
buckets, which is why a value *on* the edge must not be counted) — and the extraction fails
loudly by name if a function stops being valid shell (usually an ASCII apostrophe inside a
single-quoted awk program; see the ninth pass in `../README.md`). It exists because 0.3 s is the
smallest *finite* bound vLLM publishes for this metric, so below it the buckets resolve nothing
and only the total encases the truth.

**Never use the stub harness against real infrastructure.** It lives under `selftest/`
only for local verification.
