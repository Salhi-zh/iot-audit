# JOURNAL — zabeth cluster orchestration & benchmark tooling

**Date:** 2026-09-14 (16:09–16:2x CEST)
**Scope:** produce the 6 requested orchestration scripts + config examples + usage
guide for the 3-node GPU cluster and the 2-model VLM benchmark.
**Status:** delivered and verified offline (see *Verification*).

---

## 1. Reconnaissance

Read before writing anything:

| Source | Finding |
|---|---|
| `/home/alex/CLAUDE.md` | Repo conventions: vault plans in `~/Obsidian/YourVault/Plans/`, notes in `## headers` |
| `~/zabeth22-vllm-repair/logs/uv-resolution-proof.txt` | **critical** — vLLM/CUDA resolution results (below) |
| `~/zabeth22-vllm-repair/logs/optionA-vllm0.29.0-cu130.txt` | full package set for the cu130 stack |
| `~/zabeth22-vllm-repair/logs/optionB-vllm0.8.5-cu124.txt` | full package set for the cu124 stack |
| `~/Obsidian/YourVault/Plans/` | no existing plan for this cluster — nothing to conflict with |
| `~/.ssh/config` | **absent** — no node aliases configured yet |
| local tooling | `ssh`, `sshpass`, `rsync`, `curl`, `python3` present; `shellcheck` absent |

### 1.1 vLLM 0.29.0 vs. the driver — unresolved (corrected, see §9)

The task brief says *"Serveur : vLLM 0.29.0"* and *"Driver CUDA : 12.4"*. The
user's own resolution logs show these cannot both hold:

```
vllm==0.29.0 --torch-backend=cu124   ->  UNSATISFIABLE
     (0.29.0 pins torch==2.13.0, which has no cu124 build)
vllm==0.29.0 --torch-backend=cu130   ->  torch==2.13.0+cu130, transformers==5.17.0
     (cu13 wheels need an NVIDIA driver >= 580)
vllm==0.8.5.post1 --torch-backend=cu124 -> torch==2.6.0+cu124, xformers 0.0.29.post2
     (the stack that MATCHES driver 12.4)
```

Handling:

- `start_qwen_all.sh` runs a **preflight** that prints each node's
  `vllm` / `torch` / `torch.version.cuda` / driver and **refuses to start** when
  the torch CUDA major exceeds what the driver supports (heuristic: cu13 ⇒
  driver ≥ 580; driver otherwise < 580 ⇒ hard fail).
- Escape hatch: `--skip-preflight`.
- Documented in `infra/README.md` §"Before Phase A".

**Correction (§9):** the first version of this file asserted "the nodes run a
12.4 driver, therefore `vllm==0.29.0` will not import". That conclusion is **not
established**. A concurrent session (`~/zabeth22-vllm-repair/logs/LOG.md`, F3)
reports driver **615.71.09** (CUDA 13.4-capable), which would make 0.29.0 the
*correct* choice. The two inputs are reconcilable if "12.4" denotes the installed
toolkit rather than the driver (the wheels bundle their own runtime, so only the
driver constrains anything). The preflight reads the real driver at run time and
is authoritative; no decision should be made from either document alone.

---

## 2. Design decisions

1. **The scripts address nodes only by the aliases `zabeth21/22/23`.** The same
   scripts therefore run from your workstation (via `ProxyJump portier`) or from
   inside a node (direct LAN) — only `~/.ssh/config` differs. Two config
   examples are provided.
2. **Access model matches what you actually do.** You currently hop
   *laptop → portier (port 2222) → 172.26.145.7x*. That is expressed as
   `ProxyJump` in `config/ssh_config.workstation.example`, with the node IPs
   (`71/72/73`) in per-host `HostName` blocks.
3. **No password is ever stored.** Every script uses `BatchMode=yes` (no
   interactive prompt); `bootstrap_ssh.sh` installs a key so this works. The
   password is read from `$ZABETH_SSH_PASS` or a chmod-600 `~/.zabeth_pass`,
   which is gitignored.
4. **rsync between two remote hosts is impossible** (`rsync a:b c:d` needs one
   local endpoint). So `sync_models.sh` runs rsync **on the source node**
   (node→node over the LAN) and, if the nodes cannot SSH each other, falls back
   to a **streaming `tar` relay** through the orchestrator (no local disk use).
5. **The benchmark client runs on a node, not the laptop.** The nodes are on a
   private LAN and are not reachable from behind the gateway, so the client
   cannot run locally. `BENCH_MODE=remote` runs it on `zabeth22` and addresses
   the endpoints by **LAN IP** (`http://172.26.145.71:8000/v1`, …). `--mode
   local` exists for the case where the orchestrator does have routes.
6. **Idempotency & safety rails** (`set -euo pipefail` throughout):
   - never start a server on an occupied port (`ss` check → refuse);
   - never start without enough free VRAM (`nvidia-smi`, thresholds in config);
   - never sync onto a node with < 25 GB free;
   - re-running `start_*` on a node already serving is a no-op;
   - `stop_*` falls back from PID → `pkill` if the PID is not visible.
7. **GGUF/mmproj auto-detection** (`*Q4_K_M*.gguf`, `*mmproj*.gguf`) instead of
   hardcoding filenames, and `--no-webui` is added only if the local llama.cpp
   build advertises it.

---

## 3. Deliverables

```
iot-audit/infra/
├── SPEC-infra-setup.md                  infra handoff specification
├── config/cluster.env                   shared config (IPs, ports, paths, thresholds)
├── lib_cluster.sh                       ssh wrappers, probes, wait/kill helpers
├── lib_serve.sh                         parallel launch/wait/stop orchestration
├── README.md                            usage guide, workflow, troubleshooting
├── JOURNAL.md                           this file
├── .gitignore
├── config/
│   ├── ssh_config.workstation.example   ProxyJump via portier
│   ├── ssh_config.node.example          direct LAN, run from a node
│   └── hosts.example                    optional /etc/hosts entries
├── scripts/
│   ├── sync_models.sh                   replicate 3 artifacts + verify
│   ├── start_qwen_all.sh                vLLM Qwen, port 8000 (+ stack preflight)
│   ├── stop_qwen_all.sh
│   ├── start_llama_all.sh               llama-server, port 8001
│   ├── stop_llama_all.sh
│   ├── run_benchmark.sh                 drive benchmark_distributed.py
│   ├── cluster_status.sh                live dashboard (+ --watch)
│   └── bootstrap_ssh.sh                 one-time key install (dry-run by default)
└── selftest/                            offline stub harness (dev only)
```

Artifacts replicated by `sync_models.sh`:

| Artifact | Source | Destinations |
|---|---|---|
| `Qwen2.5-VL-7B-Instruct-GPTQ-Int4` | zabeth23 | zabeth21, zabeth22 |
| `llama-3.2-vision-gguf/` | zabeth22 | zabeth21, zabeth23 |
| `llama.cpp/build/bin/` (`llama-server` + its `.so` libs) | zabeth22 | zabeth21, zabeth23 |

> Note: the whole `build/bin` directory is copied, not just the `llama-server`
> binary — llama.cpp links `libggml*.so` / `libllama.so` from the same directory,
> so copying the binary alone would produce a non-runnable `llama-server`.

---

## 4. Verification

### 4.1 Static
```
bash -n  ->  OK for config/cluster.env, lib/lib_*.sh and all 8 scripts
```
(`shellcheck` is not installed on this host; not installed to avoid touching the
system.)

### 4.2 Bugs found and fixed during verification
1. `sync_models.sh` used `local` at **script scope** (illegal — runtime error not
   caught by `bash -n`). Removed.
2. `sync_models.sh` relied on `return $?` after a command that `set -e` would
   abort on; every remote call is now guarded by `if … then return 0; else
   return 1; fi`.
3. Unguarded `$(ssh_out …)` assignments could abort a script on an unreachable
   node; all probes now use `|| true` / explicit checks.
4. Cosmetic: trailing space in the "port already in use (pid …)" message.

### 4.3 Functional (offline, against a stateful fake `ssh`/`rsync`)
Executed the real scripts with a stub transport (`selftest/`, ~25 remote
commands per run). Results:

| Scenario | Outcome |
|---|---|
| `cluster_status.sh` | 3-node dashboard rendered correctly, including a simulated occupied port 8000 on zabeth23 and per-node model/disk/GPU lines |
| `sync_models.sh --dry-run` | probed the cluster, took the **direct rsync** path, verified byte size + file count, `synced=6 failed=0`, summary table correct |
| `start_qwen_all.sh` | stack preflight table printed; already-serving nodes skipped; wait-all table all `OK`; exit 0 |
| `start_qwen_all.sh` (servers down, port busy) | zabeth21/22 launched, **zabeth23 refused** with `port 8000 already in use (pid 5412)`; exited 1 — correct |
| `start_qwen_all.sh --skip-preflight` | preflight skipped, proceeded straight to launch |
| `stop_qwen_all.sh` | freed the busy port on zabeth23, reported the others already free; exit 0 |
| `start/stop_llama_all.sh` | launched/wait table/stopped; exit 0 |
| `run_benchmark.sh` (remote) | preflight OK on all 3, staged images, ran client on zabeth22, fetched result, verified all nodes still up, parsed and printed the JSON summary; exit 0 |
| Argument validation | `--model bogus` and a missing `--images` dir both fail **before** any SSH; exit 1 |

---

## 5. Assumptions still to confirm (one-time)

1. **`benchmark_distributed.py` CLI** — assumed `--urls <list> --images <dir>
   --output <file>`. Run `python3 ~/benchmark_distributed.py --help`; if the
   flags differ, change `BENCH_URLS_FLAG` in `config/cluster.env` and the invocation in
   `run_benchmark.sh` (marked with a `NOTE:` comment).
2. **Endpoint separator** — comma (`BENCH_URLS_SEP`).
3. **Client host** — `BENCH_HOME_NODE=zabeth22`.
4. **llama.cpp build** — `~/llama.cpp/build/bin/llama-server` (as stated in the
   brief); GGUF + mmproj glob-matched under `~/models/llama-3.2-vision-gguf/`.
5. **Node hostnames** — the log-file hint assumes the node's `hostname` equals its
   alias (`zabeth21/22/23`). Confirm with `cluster_status.sh`.
6. **User account** — `msalhi` on gateway and nodes (`NODE_USER`/`GATEWAY_USER`).

## 6. Not done (deliberately)

- **No connection to the real machines was attempted.** The brief asked for the
  scripts + configs + guide; installing keys (`bootstrap_ssh.sh`) or starting
  services on your infrastructure are actions to run yourself when ready.
- Nothing was written to the Obsidian vault; everything is local as requested.

## 7. Suggested next steps

1. `./scripts/bootstrap_ssh.sh` (dry-run) then `--yes`, and install the SSH config.
2. Decide the vLLM pin (§1.1) and make `start_qwen_all.sh` pass preflight.
3. `./scripts/cluster_status.sh` to confirm real cluster state matches the brief
   (esp. model locations and free disk).
4. Confirm the `benchmark_distributed.py` flags, then run Phase A end-to-end.

## 9. Addendum — concurrent session detected, and a corrected claim

Found *after* the initial delivery, by checking the filesystem rather than
trusting my recon snapshot:

- A **second Freebuff agent is running right now** (PID 3934765, instance
  literally named `vLLM`, started 16:05) working the same problem.
- The folder I read during recon **changed underneath me**: at 16:15–16:17 it
  gained `LOG.md`, `rehearsal/` and `from-zabeth72/`.
- Its `LOG.md` stated "Target machine was not contacted", but `from-zabeth72/`
  shows it moving to actually connecting: `step1-hop1` (16:16:30, bastion OK),
  `step2-hop2` (16:16:39, **`Permission denied (publickey,password)`**), then
  `step3-hop2-working` (16:17:17, second hop established).

### Consequences

1. **My recon was a snapshot of a moving target.** Facts about the cluster taken
   from `~/zabeth22-vllm-repair/` may already be stale, and no machine state here
   is independently verified by me.
2. **Overlap risk.** That session has produced `fix_vllm_env.sh`,
   `verify_vllm_env.sh` and a 0.29-vs-0.8 decision doc. My tooling must not run
   concurrently with it: its repair **uninstalls before reinstalling** the vLLM
   stack, which would break my preflight mid-flight, and its access work touches
   the same `~/.ssh/authorized_keys` my `bootstrap_ssh.sh` would rewrite.
3. **Corrected claim.** The §1.1 conclusion was wrong to state as fact; the
   driver version is the open variable. `infra/README.md` and §1.1 are now corrected.

### Newly verified facts (from the other session, not by me)

zabeth22: Devuan 6 (excalibur), kernel `6.12.107+deb13-amd64`, OpenSSH `10.0p2`,
`nvidia-smi` at `/usr/bin/nvidia-smi`, `python3` at `/usr/bin/python3`,
**`uv` ABSENT**. Gateway `portier` hostname `arsenal`/`arsenic`,
kernel `6.12.90+deb13-amd64`, `sshpass` **absent** on the bastion.

`uv` absent on the nodes means a `uv`-based venv rebuild needs `uv` installed
first; `python3 -m venv` is the fallback.

### Recommendation

**Do not run any of this tooling until that session finishes.** Wait for its
`FIX-REPORT-*.md` / a quiet folder, then start with read-only recon
(`cluster_status.sh`) to establish ground truth — in particular the driver
version, which decides §1.1.

## 8. Security note

The SSH password given in the request is **not** stored anywhere in this folder.
Keep it only in `~/.zabeth_pass` (chmod 600) or `$ZABETH_SSH_PASS`, and prefer
key-based auth (`bootstrap_ssh.sh`), which the scripts require anyway.

## 10. Review of the concurrent session's output (2026-09-14 16:39)

Reviewed `~/zabeth22-vllm-repair/` after it reported completion. Five findings,
three of which change the plan.

### 10.1 The cluster is heterogeneous at the driver level — verified

| Node | NVIDIA driver | Advertised CUDA | cu13 wheels? |
|---|---|---|---|
| zabeth21 | 550.163.01 | 12.4 | **no** |
| zabeth22 | 615.71.09 | 13.4 | yes |
| zabeth23 | 550.163.01 | 12.4 | **no** |

Sources: `logs/driver-survey-all.log` (z21, z23), `logs/from-zabeth72/step10-launch-apply.log` (z22).
**The brief's "driver 12.4, aligned across all three" is wrong for z22**, and the
concurrent session's `01-VERSION-ANALYSIS.md` line *"Driver 615.71.09 is fine …
cu130 wheels are within range"* is true **for z22 only** — it never states that the
other two are on 550.163.01. Its repair is therefore **valid on one node of three**.

This **validates this folder's preflight design**: `start_qwen_all.sh` reads the
driver per node and refuses a cu13 torch on a 550 driver. It would have caught
this on z21/z23 and passed on z22.

### 10.2 The end-to-end test does not validate the project's model

`logs/from-zabeth72/e2e-test.sh` runs `Qwen/Qwen2.5-0.5B-Instruct` — a **0.5B
text-only** model. It proves the environment executes inference and serves an
OpenAI-compatible endpoint. It does **not** exercise Qwen2.5-VL-7B, GPTQ, vision
input, or `--limit-mm-per-prompt`. "vLLM works" ≠ "the project's model works".

### 10.3 The end-to-end test had not finished

The session reported completion, but at review time: the agent process was still
running (PID 3934765, 34 min elapsed, 52% CPU), `step19-launch-e2e.log` (16:38:40)
ends mid-download with the test process still alive, and nothing new appeared after
it. No e2e result is captured. `logs/from-zabeth71/` and `logs/from-zabeth73/`
are **empty** — the structure exists, the logs were never pulled.

### 10.4 Its record now contradicts its contents

`logs/LOG.md` still contains only session 1, which states: *"No SSH connection …
never opened"*, *"No command of any kind on zabeth21/22/23"*, *"`fix_vllm_env.sh
--apply` has never been run anywhere"*. Meanwhile `step10-launch-apply.log` shows
`--apply --yes` running and 5 `fix-*.log` runs exist, one ending `RESULTAT :
SUCCES`. The folder's own evidence log is stale and now false.

### 10.5 What it did well, and one thing I got wrong

Genuinely good: rollback artefacts captured before mutating the venv
(`REQUIREMENTS_BEFORE_*.txt`, `BROKEN-STATE-freeze-*.txt`); a real dependency
conflict found and fixed (`outlines` requires `numpy<2.0.0`, was on 2.3.5 — and
`outlines` is vLLM's structured-output backend, i.e. exactly what this project's
Guided Decoding needs); and `remote.sh`, which authenticates via
`SSH_ASKPASS_REQUIRE=force` + an env-backed helper so the password **never**
reaches a command line or a file.

**Correction to this folder:** `bootstrap_ssh.sh` originally used `sshpass -p "$PASS"`,
which puts the password in **argv** — readable by any local user via `ps auxww`.
Fixed to `SSHPASS="$PASS" sshpass -e`. Their askpass approach is better still.

### 10.6 Consequences for this tooling

1. `config/cluster.env` must not assume one `vllm-env` for all nodes; add a per-node
   profile if the drivers are not aligned.
2. The preflight is now a **required** step, not a nicety.
3. Do not replicate z22's `~/vllm-env` to z21/z23.
4. Nothing here was executed against the machines: the concurrent agent is still
   live and mid-work.
