# zabeth cluster — 3-node GPU orchestration & distributed VLM benchmark

> **2026-09-17 — this tooling was executed against the live cluster through the
> bastion.** See "AMENDMENT 2026-09-17" at the end of this file for what was
> verified, the two defects it exposed (both fixed), and the drift it found.
> The topology, workflow and "Before Phase A" sections below were not left stale
> by that run — but the **Phase B (llama.cpp) column no longer exists on the
> machines**; read the amendment before planning a Llama benchmark.

Tooling to replicate models across three identical RTX 3060 nodes and benchmark
two VLM serving stacks against the same images and prompt:

- **Phase A** — `Qwen2.5-VL-7B-Instruct-GPTQ-Int4` on **vLLM**, port **8000**
- **Phase B** — `Llama-3.2-11B-Vision-Instruct` (GGUF Q4_K_M + mmproj) on
  **llama.cpp `llama-server`**, port **8001**

Both phases drive the same client, `benchmark_distributed.py`.

---

## Topology & access

```
 your workstation
     │  ssh -p 2222  (portier gateway)
     ▼
 portier.polytech-lille.fr
     │  ssh (LAN 172.26.145.0/24)
     ├──► zabeth21   172.26.145.71
     ├──► zabeth22   172.26.145.72
     └──► zabeth23   172.26.145.73
```

Every node is Devuan 6 (no systemd): servers are launched with `nohup` and
stopped by PID/port, never with `systemctl`.

Two ways to run the tooling, both supported by the same scripts:

| Run from | SSH config to use | Notes |
|---|---|---|
| Your workstation | `config/ssh_config.workstation.example` | Uses `ProxyJump portier`; one config file |
| A cluster node  | `config/ssh_config.node.example` | Direct LAN; enables fast node→node rsync |

The scripts only ever address nodes by the aliases `zabeth21/22/23`, so the
**same scripts work from either place** — only `~/.ssh/config` differs.

---

## One-time setup

1. **Install the key** (removes password prompts — the scripts require
   passwordless, non-interactive SSH):
   ```bash
   cd iot-audit/infra/scripts
   ./bootstrap_ssh.sh          # dry-run, shows the plan
   ./bootstrap_ssh.sh --yes    # creates ~/.ssh/id_zabeth and installs it
   ```
   Password source: `$ZABETH_SSH_PASS`, or `~/.zabeth_pass` (chmod 600).
   It is never written into this repo.

2. **Install the SSH config**: copy `config/ssh_config.workstation.example`
   (or `…node.example`) into `~/.ssh/config`, then `chmod 600 ~/.ssh/config`.

3. **Verify**:
   ```bash
   ssh zabeth21 'hostname; nvidia-smi --query-gpu=name --format=csv,noheader'
   ```

---

## Scripts

| Script | Purpose |
|---|---|
| `scripts/sync_models.sh` | Replicate Qwen (from z23), GGUF + `llama.cpp/build/bin` (from z22) to all nodes; verify by size + file count |
| `scripts/start_qwen_all.sh` | Start vLLM on all 3 nodes (port 8000); preflight + wait for `/v1/models` |
| `scripts/stop_qwen_all.sh` | Stop vLLM, verify port 8000 released |
| `scripts/start_llama_all.sh` | Start `llama-server` on all 3 nodes (port 8001) |
| `scripts/stop_llama_all.sh` | Stop `llama-server`, verify port 8001 released |
| `scripts/run_benchmark.sh` | Run `benchmark_distributed.py` for `qwen` or `llama`, save + summarize |
| `scripts/cluster_status.sh` | Live dashboard: SSH, GPU, ports, processes, models, disk |
| `scripts/bootstrap_ssh.sh` | One-time key installation |

All scripts are idempotent, `set -euo pipefail`, and **never start a server on a
port that is already occupied** or on a node without enough free VRAM
(`QWEN_MIN_FREE_VRAM_MB` / `LLAMA_MIN_FREE_VRAM_MB` in `config/cluster.env`).

---

## Standard workflow

```bash
cd iot-audit/infra/scripts

# 0. see everything
./cluster_status.sh

# 1. replicate artifacts (idempotent — safe to re-run)
./sync_models.sh
./sync_models.sh --dry-run            # or --force / --artifact qwen

# 2. Phase A — Qwen on vLLM
./start_qwen_all.sh
./run_benchmark.sh --model qwen  --images ~/datasets/bench --output ~/bench/qwen.json
./stop_qwen_all.sh

# 3. Phase B — Llama on llama.cpp
./start_llama_all.sh
./run_benchmark.sh --model llama --images ~/datasets/bench --output ~/bench/llama.json
./stop_llama_all.sh
```

Logs land on each node at `~/logs/qwen_<hostname>.log` and
`~/logs/llama_<hostname>.log`.

---

## ⚠️ Before Phase A — resolve the vLLM/CUDA question (NOT yet resolved)

Two inputs in this project **contradict each other**, and the contradiction is
not cosmetic — it decides which vLLM you install:

| Source | Says | Implies |
|---|---|---|
| The benchmark brief | "Driver CUDA : 12.4" | cu13 wheels unusable → use `vllm==0.8.5.post1` |
| `~/zabeth22-vllm-repair/logs/LOG.md` (F3) | driver **615.71.09**, CUDA 13.4-capable | cu13 is fine → `vllm==0.29.0` is correct |

Both are reconcilable only if "12.4" refers to the installed **toolkit**, not the
driver — the wheels bundle their own CUDA runtime, so the toolkit is irrelevant.
**Do not act on either claim until the real driver is read off the machine.**

What the resolution logs do prove (independently of the driver):

| Request | Result |
|---|---|
| `vllm==0.29.0 --torch-backend=cu124` | **unsatisfiable** — 0.29.0 pins `torch==2.13.0`, which has no cu124 build |
| `vllm==0.29.0 --torch-backend=cu130` | resolves, `torch==2.13.0+cu130` — needs a CUDA-13 driver (≥ 580) |
| `vllm==0.8.5.post1 --torch-backend=cu124` | resolves, `torch==2.6.0+cu124` — the only way to get torch 2.6.0 |

`start_qwen_all.sh` therefore does **not** hardcode a conclusion: its preflight
prints each node's `vllm` / `torch` / `torch.version.cuda` / driver and refuses
to start only if the torch CUDA major exceeds what that node's driver supports.
The runtime read is authoritative; this document is not. Force a start with
`./start_qwen_all.sh --skip-preflight`.

### **VERIFIED: the three nodes do NOT have the same driver** (2026-09-14 16:34–16:38)

Read directly off the machines:

| Node | NVIDIA driver | Advertised CUDA | cu13 wheels? |
|---|---|---|---|
| zabeth21 | **550.163.01** | **12.4** | ❌ no |
| zabeth22 | **615.71.09** | **13.4** | ✅ yes |
| zabeth23 | **550.163.01** | **12.4** | ❌ no |

**The brief's "Driver CUDA 12.4 (aligné sur les 3 machines)" is half right:** 12.4
for z21/z23, but **z22 is two branches ahead**. Consequences, all of them
load-bearing:

1. **A venv built for `cu13x` works on z22 and fails on z21/z23.** The repaired
   `~/vllm-env` on z22 (`torch 2.13.0+cu132`) is therefore **valid on 1 node of 3**
   and must not be replicated as-is.
2. **This is why `config/cluster.env` treats `VLLM_ENV` per-node and why D1 exists** — a
   single version pin cannot be correct for all three machines at once.
3. `start_qwen_all.sh`'s preflight is exactly the right guard and would catch this:
   torch `cu132` + driver `550` ⇒ **refuse to start**; torch `cu132` + driver `615`
   ⇒ proceed.

### **AMENDMENT 2026-09-16 — the driver question is resolved (append, not rewrite)**

The table above is a dated reading of **2026-09-14** and is kept as-is on purpose
(project rule R7: amend, never rewrite). It no longer describes the cluster:

* all three nodes now report driver **615.71.09** and run `vllm 0.29.0` /
  `torch 2.13.0+cu132` — the `vllm==0.8.5.post1` / `torch 2.6.0+cu124` fallback is
  **not in use**;
* consequently the preflight in `start_qwen_all.sh` passes on all three nodes;
* evidence: `evidence/2026-09-15/SUMMARY.md` (driver row `615.71.09 ×3`) and
  `evidence/2026-09-16/cluster-golden-recheck/SUMMARY.md` (fast **and** deep golden,
  `NOEUD DORÉ ×3`) — run against the real machines, unlike `selftest/`.

The preflight *code* is unchanged and remains correct: it reads the runtime, never
this document. Only its printed advice string still names the cu12 fallback.

Either align the drivers on z21/z23 (needs root, `apt`, reboot), or give those two
nodes a `cu12.x` build (`cu129` was being tested at 16:36).

### Other verified facts

Devuan GNU/Linux **6 (excalibur)**, kernel `6.12.107+deb13-amd64` (z22) /
`6.12.95+deb13-amd64` (z21, z23), OpenSSH `10.0p2`, glibc 2.41, RTX 3060 `sm_86`,
`uv` **absent** on the nodes (`~/.local/bin/uv` present for user `msalhi` on z22
once installed), `sudo` requires a password on all three, `dkms` absent, Xorg
running. Gateway `portier` = hostname **`arsenal`**, kernel `6.12.90+deb13-amd64`,
**no `sshpass`**, and its keys are **not** authorised on the inner hosts.

---

## Assumptions to confirm once

1. **`benchmark_distributed.py` CLI** — `run_benchmark.sh` passes
   `--urls <list> --images <dir> --output <file>`. Check with
   `python3 ~/benchmark_distributed.py --help` and adjust `BENCH_URLS_FLAG` in
   `config/cluster.env` and the client invocation if the flags differ.
2. **Endpoint SEPARATOR** — endpoints are joined with `,` (`BENCH_URLS_SEP`).
3. **Client location** — `BENCH_MODE=remote` (default) runs the client on
   `zabeth22`, which can reach all three nodes on the LAN. Set
   `BENCH_MODE=local` only if this host has direct routes to the nodes.
4. **GGUF / mmproj filenames** — auto-detected with `*Q4_K_M*.gguf` and
   `*mmproj*.gguf` inside `$LLAMA_DIR`; override the globs in `config/cluster.env`.
5. **Hostnames** — the log-file hint uses the node's real `hostname`; it should
   equal the alias. Verify with `cluster_status.sh`.

---

## Configuration

Everything lives in `config/cluster.env` (paths, ports, IPs, thresholds, timeouts) and
can be overridden per-run from the environment or from a gitignored
`$HOME/.iot-audit-infra.env` (set `IOT_AUDIT_INFRA_ENV` to move it). That file is
sourced **first, by `cluster.env` itself**, so every script under `scripts/` sees the
override. It did not before 2026-09-28: nothing in `scripts/` read it at all, and
`NODES`, `NODE_IPS`, `QWEN_PORT`, `LLAMA_PORT`, `QWEN_SOURCE_NODE` and
`LLAMA_SOURCE_NODE` could not be overridden even then. See the eighth pass below.
Useful knobs:

```bash
GPU_MEM_UTIL=0.85 QWEN_MAX_LEN=4096 ./start_qwen_all.sh
BOOT_TIMEOUT=600 ./start_qwen_all.sh
BENCH_MODE=local ./run_benchmark.sh --model qwen --images ./imgs --output ./q.json
```

## Troubleshooting

- **`Permission denied` / hangs** → keys not installed. Run
  `bootstrap_ssh.sh --yes`, or check `chmod 600 ~/.ssh/config`.
- **`Host zabethNN not found`** → SSH config not installed (~/.ssh/config).
- **`port 8000 already in use`** → a server is already running; stop it first.
  The scripts will not start a second one.
- **Startup fails, no output** → `./cluster_status.sh`, then
  `ssh zabeth22 'tail -n 50 ~/logs/qwen_zabeth22.log'`.
- **`sync_models.sh` relays through this host** → nodes cannot SSH each other;
  install the key on all nodes (`bootstrap_ssh.sh`) for direct LAN transfers.

---

## AMENDMENT 2026-09-17 — first execution against the real machines (append, not rewrite)

**How.** Run from a workstation with no `~/.ssh/config` and no installed key, through
the bastion (`portier` :2222, user `msalhi`) using the `SSH_ASKPASS_REQUIRE`
transport of `~/zabeth22-vllm-repair/remote.sh`. The scripts themselves were executed
**unmodified** — a shim named `ssh`, first on `PATH`, mapped `ssh zabethNN <cmd>` onto
that transport (the same pattern `selftest/bin/ssh` already uses, pointed at the real
cluster instead of a fake). **No server was started or stopped during this run.**

**Verified live, all three nodes** — agrees with `evidence/2026-09-15/SUMMARY.md` and
`evidence/2026-09-16/cluster-golden-recheck/SUMMARY.md`:

| probe | result |
|---|---|
| driver | `615.71.09` ×3 |
| `torch` / `vllm` | `2.13.0+cu132` / `0.29.0` ×3 |
| service `:8000` | UP ×3, `/v1/models` → `qwen2.5-vl-7b` |
| real inference | the repo's own `measure.PROMPT` + `VLM_SCHEMA` (guided JSON, `temperature=0`, `seed=1234`, `max_tokens=256`) on a real corpus image, ×3 nodes: HTTP 200, schema-valid JSON, 0.98–2.92 s |
| `start_qwen_all.sh` | exit 0 — preflight prints `0.29.0 / 2.13.0+cu132 / 13.2 / 615.71.09` ×3, then "already serving on 8000 — skip" ×3 |
| `cluster_status.sh` | `qwen=yes` ×3, `llama-gguf=no` ×3, ports + PIDs correct, disks 131/140/401 GB |

**Two defects found by running it — both fixed in this session**

1. **`lib_cluster.sh` probed readiness on loopback, the deployed service does not listen
   there.** `api_ok` / `wait_api` used `http://127.0.0.1:$port/v1/models`, but
   `node_vllm_service.sh` — the launcher actually in production — binds
   `--host <node LAN IP>`, where loopback is refused. Measured on every node:
   `http://172.26.145.NN:8000/v1/models` → exit 0, `http://127.0.0.1:8000/…` →
   **curl exit 7**. `start_qwen_all.sh` therefore saw a *healthy* cluster as down and
   then aborted with the misleading "port 8000 already in use". The offline
   `selftest/` stub answers 0 to any `curl`, which is exactly why it never caught this.
   Both helpers now probe the node's LAN address first and fall back to loopback, which
   is correct for `0.0.0.0`, LAN-IP and loopback binds alike.
2. **`cluster.env` built node-side paths from the local `$HOME`.** Run from a
   workstation (the documented primary mode), `$QWEN_MODEL_DIR` resolved to a path that
   exists on no node, so `path_exists` answered `no` for a model that is present on all
   three — `cluster_status.sh` printed `models: qwen=no` and `sync_models.sh` would have
   reported `SOURCE MISSING` against a perfectly healthy cluster. Every node-side path
   now derives from `NODE_HOME` (`/home/$NODE_USER`); run *on* a node as `msalhi`,
   `NODE_HOME == $HOME` and behaviour is unchanged.

**Drift found — annotated, deliberately not "fixed"**

* **Phase B does not exist on the machines.** No `~/llama.cpp`, no `llama-server`, no
  `*.gguf` and no `*mmproj*` under `~/models` on any node; port 8001 free ×3.
  `LLAMA_SOURCE_NODE` named `zabeth22`, which holds **no** Llama artifact at all — the
  only Llama checkpoint is the non-GGUF `Llama-3.2-11B-Vision-Instruct-W4A16` on
  zabeth21/zabeth23. Per `SPEC-infra-setup.md` §C11 the `LLAMA_*` keys are kept
  (llama.cpp is the only path in this repo that could serve that checkpoint); they now
  carry the measurement. Assumption 4 above (GGUF/mmproj globs) is moot until then.
* **No benchmark client.** `~/benchmark_distributed.py` is absent on all three nodes,
  so `run_benchmark.sh` cannot run as configured; `~/datasets` and `~/bench` are empty.
  The harness that *does* exist on the cluster is `~/v11-bench.py` (on zabeth22).

**Observations left open (reported, not changed)**

* `VLM_SCHEMA` declares `evidence_image_region`, but it is **not** in `required[]`, the
  model never emitted it in 12/12 live responses, and nothing reads it (`contracts.py`
  also declares the field). Dormant surface, not a bug — but it is the only schema
  property with no producer.
* With `temperature=0`, `seed=1234`, identical image bytes and an identical stack,
  zabeth22 and zabeth23 agreed on every image tried while zabeth21 differed on one
  (`Echo Dot (2nd Gen)` vs `(3rd Gen)`). Cross-node token-level determinism is
  therefore **not** guaranteed and should not be claimed.
* The nodes are not identical: zabeth23's root filesystem is 889 GB against 221 GB on
  zabeth21/zabeth22 (see the note under the `cluster.env` header).

**Still not covered by this run**: V12 egress (the firewall block needs its own
300 s test), and anything that would require starting or stopping a server.

### Second pass, same day — the infrastructure's own acceptance test

Method unchanged (shim `ssh` on `PATH` → bastion transport; no server started or
stopped; ports 8000/8001 and the three PIDs verified unchanged before and after).

**Reproduced the published golden result.** `node_golden_check.sh` **shipped from this
repo** (not the node's own copy), run on all three nodes: `17 PASS / 0 FAIL / 2 WARN`
and `RESULTAT : NOEUD DORE` **on each** — identical to
`evidence/2026-09-16/cluster-golden-recheck/SUMMARY.md`. The two WARNs are the
documented ones (egress reachable outside a V12 test; port 8000 busy with production).
It also confirms independently: `torch 2.13.0+cu132`, `vllm 0.29.0`, real CUDA kernel,
nvcc/`ninja` fixes effective with **no shell** involved, `all-MiniLM-L6-v2` cached
(claim A8), `sqlite 3.53.1` with FTS5 **+ trigram**, weights `6 928 523 704 B`.

**Fix — `sync_models.sh` could never report the Qwen artifact as complete.** Its
integrity check compared raw directory bytes and file counts, but Hugging Face keeps
`<model>/.cache/huggingface/download/*.metadata` beside the weights, recording commit
hash, etag and the download timestamp **as a float whose textual length varies**
(16 vs 17 characters). Live: `6 944 521 923 B` on zabeth23 vs `6 944 521 924 B` on
zabeth21/22 — *every* difference inside those files, while both safetensors hashed
identically (`25aab8ca…`, `d380b110…`) on all three. So `--dry-run` exited 1 with
`INTEGRITY ERROR` and a real run would have re-copied **6.9 GB every time**.
`path_size_bytes`/`count_files` now measure the payload (`SYNC_EXCLUDE`, default
`.cache`); with it excluded all three nodes agree exactly — `6 944 517 710 B`, 16 files.
Note the internal inconsistency this exposed: `node_golden_check.sh` compares only
`*.safetensors` and therefore said "golden", while `sync_models.sh` compared the whole
tree and said "mismatch" — two tools, two definitions of "same".

**Fix — `bootstrap_ssh.sh` could not install the key it exists to install.** It used
`sshpass -e … -o ProxyJump=…`. sshpass answers the first prompt it sees (the gateway's);
the second ssh — the one that reaches the node — never gets the secret. Measured from
the workstation: `sshpass -e ssh -o ProxyJump=… msalhi@172.26.145.72 hostname` →
**rc=5, no output**, identically with `PreferredAuthentications=password`; while the
same two-hop driven by `SSH_ASKPASS_REQUIRE=force` → **rc=0 on all three nodes**. The
node loop now uses that mechanism (the one `remote.sh` already used), which also drops
the `sshpass` dependency and keeps the secret out of `argv`. Verified without mutating
anything, via `ssh-copy-id -n` (authenticates, installs nothing): rc=0 on all three.
Side effect worth knowing: the bastion intermittently answers `Connection reset by
193.48.57.57 port 2222` under rapid repeated connections — one z23 attempt failed,
the retry succeeded. Many small `ssh` calls are exactly what these scripts do, which is
what `ZABETH_SSH_MUX=1` is for.

**Fix — `bootstrap_ssh.sh --dry-run` demanded the secret.** The password check ran
*before* the DRY RUN branch, so the documented "just shows the plan" invocation died
with `no password` and printed nothing (verified: exit 1). The check now happens after
the plan; the plan reports whether a password is available.

**Fix — `start_llama_all.sh` reported the wrong blocker.** It probed launch readiness
before the artifacts, so with no llama.cpp anywhere the failure read
`NOT starting — only 2983 MiB VRAM free (< 8000 required)` — pointing at the GPU when
the binary simply does not exist. Artifact checks now run first; the message is
`/home/msalhi/llama.cpp/build/bin/llama-server missing or not executable`.

**Found, not changed**

* **Nothing supervises the service and nothing restores it after a reboot.** No
  crontab entry, no `init.d` script, no user unit, and `/etc/boot.d` (which
  `/etc/rc.local` runs via `run-parts`) is **empty on all three nodes**. All three
  servers started `2026-09-16 19:42:04–05` by hand and have run since. A reboot
  silently empties the cluster until someone re-runs the launcher.
* **The nodes cannot SSH each other** (all six node→node probes failed), so
  `sync_models.sh` will always take the relay path — a 6.9 GB stream through the
  orchestrator over the bastion, not the documented fast LAN rsync. Installing the key
  on all nodes (`bootstrap_ssh.sh --yes`) is the documented prerequisite and is unmet.
* **The per-node tools are installed only on zabeth22.** zabeth21/zabeth23 have a lone
  `~/gpu-bench-node.sh`; `node_golden_check.sh`, `node_vllm_service.sh`,
  `node_install_venv_environment.sh`, `node_write_provenance.sh` are absent there and
  have to be piped in per run. Where they do exist they are **identical to the repo**
  apart from the `# NOTE …` header this repo prepends — so no functional drift, but the
  note sits *above* the shebang, which makes `#!/bin/bash` inert for direct execution;
  run them as `bash <file>`, as this README already says.
* **Stale PID/log files.** Every node carries a `~/logs/qwen_zabeth71.pid` (and a
  166-byte `qwen_zabeth71.log`) holding a **dead** PID, next to the correct
  `qwen_zabeth<NN>.pid`. Harmless for the port-based stopper, misleading for a human.
* `stop_llama_all.sh` on a cluster with no llama.cpp is correctly idempotent (`port
  8001 already free` ×3, exit 0); `run_benchmark.sh` correctly refuses to start when
  the client is missing; `sync_models.sh --artifact llama` fails cleanly with
  `SOURCE MISSING` and does not half-copy.

**Not attempted**: the `--deep` golden tier and V12 egress, both of which need a
maintenance window (they stop the production service / cut the network). The deep tier's
G3/G4 is nevertheless covered from the outside: see the end-to-end inference in the
section above, which uses the repo's real prompt and schema on real corpus images
through the running service.

### Third pass, same day — SSH key installed, node-to-node transfers enabled

**Done** (this is a change to the machines, not just to the repo):

| Where | What |
|---|---|
| workstation | zabeth `Host` blocks appended to `~/.ssh/config` (previous file kept as `config.bak-<timestamp>`) |
| gateway + all 3 nodes | `id_zabeth.pub` added to `authorized_keys` |
| all 3 nodes | `id_zabeth` (private) at `~/.ssh/id_zabeth`, mode 600 (previous node config kept as `config.bak-bootstrap`) |
| all 3 nodes | client config covering the aliases **and** the LAN addresses |

Result: passwordless `ssh zabeth21/22/23` from the workstation, **all six node→node
directions verified**, and `sync_models.sh` now prints `zabeth23 -> zabeth21 : direct
rsync (LAN)` instead of relaying through the orchestrator. The relay path is no longer
taken; the 6.9 GB Qwen artifact is copied over the LAN.

**Four things had to be fixed for that to work at all.**

1. `bootstrap_ssh.sh` could not install the key — `sshpass` + `ProxyJump`, see the
   second pass above. Fixed; the run now completes and verifies.
2. **`ssh_config.node.example` could never have worked for its stated purpose.** It
   declared `Host zabeth21/22/23` only, but `sync_models.sh` builds its peer command
   from `node_ip` and always addresses `msalhi@172.26.145.NN`. ssh applies
   `IdentityFile`/`IdentitiesOnly` only to a Host pattern that *matches*, so the inner
   ssh fell back to the default identities, the reachability test failed, and the script
   silently relayed — the exact opposite of the file's purpose. The IP patterns are now
   in the example, with the measurement in the comment.
3. **`cluster.env` resolved `SSH_KEY` from `$HOME`, but ssh resolves `~` from the passwd
   entry.** When `$HOME` is overridden (container, `sudo`, wrapper) the key is written
   where ssh never looks and the config appears silently ignored. Hit for real here: the
   dry run planned `$HOME/.ssh/id_zabeth` while ssh read `/home/alex/.ssh/config`.
   `SSH_KEY` now derives from the account home (`getent passwd`), guarded with `||` so a
   host without `getent` cannot abort a `set -euo pipefail` caller.
4. **The README's "install the key on all nodes (`bootstrap_ssh.sh`) for direct LAN
   transfers" was not achievable with `bootstrap_ssh.sh`.** Authorising the public key
   is enough for host→node but never for node→node: the pushing node needs the *private*
   key, and its client config must cover the LAN addresses. Added an explicit, opt-in
   `--node-to-node` step that does both and then verifies all six pairs.

```bash
./bootstrap_ssh.sh --node-to-node              # dry run, prints the plan
./bootstrap_ssh.sh --yes --node-to-node        # performs it
```

**Security cost, stated plainly.** `--node-to-node` puts the same private key on four
machines: anyone who can read `~/.ssh/id_zabeth` on any node can log into all of them.
It is off by default for that reason. The alternative is per-node keys (more
bookkeeping, and `sync_models.sh` would need an `-i` per peer), or accepting the relay.

**Now worth doing:** the password is no longer needed for any script — every one of them
runs on the key. It is still sitting in plaintext in `~/.bash_history` (as literal
`sshpass -p …` lines) and is reused across three machines, which the project's own SPEC
C2/§12.1 prohibits. Rotate it, and the history entry becomes worthless.

### Fourth pass, same day — the per-node tools are now on all three nodes

The second pass recorded that `node_golden_check.sh` and `node_vllm_service.sh` existed
**only on zabeth22**; zabeth21/zabeth23 had nothing but `gpu-bench-node.sh`. That is now
fixed, and it also closes a gap the SPEC had already logged.

| On-node path | Source in this repo | sha256 |
|---|---|---|
| `~/golden-check.sh` | `infra/scripts/node_golden_check.sh` | `26882b72…` |
| `~/vllm-service.sh` | `infra/scripts/node_vllm_service.sh` | `3afe171f…` |
| `~/gpu-bench-node.sh` | `infra/scripts/node_gpu_bench.sh` | `8e774069…` (v2 — see §Sixth pass) |

All three nodes now hold **byte-identical** copies (hash matches the repo file exactly),
mode 755. The on-node names are deliberate: `golden-check.sh` / `vllm-service.sh` are the
names the scripts use for themselves, what zabeth22 already had, and what
`node_write_provenance.sh` looks for (`GC="$HOME/golden-check.sh"`). Installing them
under the repo's `node_*` names would have created redundant copies and left that path
broken.

**A wart fixed while installing them.** Both files carried the “added by the executing
agent” NOTE block **above the shebang**, which put `#!/bin/bash` on line 7 (golden) and
line 13 (vllm-service). Two consequences, both real: the shebang was inert, so a direct
`./golden-check.sh` was handed to `/bin/sh`; and `golden-check.sh`'s `--help` does
`sed -n '2,18p' "$0"`, a range written for the original layout, so it printed the NOTE
block and the shebang line instead of the usage header. The block now sits at the top of
the body, right after `set -uo pipefail`. Verified: **line 1 is the shebang, `--help`
prints the real header, `bash -n` is clean, and the diff against the previously deployed
copy is a pure addition — no original line was changed or lost.** Previous copies were
kept as `~/golden-check.sh.bak-20260917` / `~/vllm-service.sh.bak-20260917` on z22.

**Verified on all three nodes, running the installed files:**

```
~/golden-check.sh --json   ->  17 PASS   0 FAIL   2 WARN   RESULTAT : NOEUD DORE
~/vllm-service.sh status   ->  correct PID / port / bind host / GPU / log, per node
```

`$HOME/golden-check.sh` now exists on every node, so the **SPEC §C30** provenance defect
("`solidify-04-provenance.sh` looked for the checker in the wrong place … the
`verification suite` field read `non execute` on z21 and z23") is closed at the path
level: both the script's original path and the alternative one now resolve.

### Fifth pass, same day — `gpu-bench-node.sh` now has a tracked source

The fourth pass left one asymmetry: `~/gpu-bench-node.sh` existed on all three nodes but
had **no counterpart in this repo** — it was the only per-node artifact whose source lived
solely in the sibling folder `~/zabeth22-vllm-repair/`. It is now tracked as
`infra/scripts/node_gpu_bench.sh`.

**Imported byte-identical, deliberately not "improved".** This is the one per-node tool
whose content is pinned by published evidence:

```
evidence/2026-09-15/genou-fine.json
  "banc": "gpu-bench-node.sh (sha256 bfe192a8c3e8f98a sur les 3 noeuds)"
evidence/2026-09-15/parallelisme-gpu.json
  "instrument": "zabeth22-vllm-repair/gpu-bench-node.sh"
```

That record names **both the filename and the hash of the instrument that produced the
knee measurement**. Renaming the file or touching a byte would invalidate the
cross-reference and create drift between this repo and the four deployed copies. So the
import was exact — `bfe192a8c3e8f98a79baffd810349a6faf8ba71a4422c9d029284c4f77ac23a4`,
9 230 bytes — and all five copies agreed. (Reading it then exposed three defects; see
§Sixth pass for the correction and the dated record that re-establishes the instrument's
identity as v2.)

| Copy | sha256 at import | sha256 now (v2) |
|---|---|---|
| `infra/scripts/node_gpu_bench.sh` | `bfe192a8…` | `8e774069…` |
| `~/zabeth22-vllm-repair/gpu-bench-node.sh` (origin, v1) | `bfe192a8…` | `bfe192a8…` (untouched) |
| zabeth21 / zabeth22 / zabeth23 `~/gpu-bench-node.sh` | `bfe192a8…` | `8e774069…` |

The repo name follows the `node_*` convention used by the three other on-node scripts
(`node_golden_check.sh` → `~/golden-check.sh`); the **on-node name stays
`gpu-bench-node.sh`** because that is what evidence cites.

**Verified live, running this repo's bytes on zabeth22** (`MODE=collect`, the read-only
mode — piped straight from the repo file):

```
launch args : .../vllm-env/bin/vllm serve .../Qwen2.5-VL-7B-Instruct-GPTQ-Int4
              --served-model-name qwen2.5-vl-7b --host 172.26.145.72 --port 8000
GPU         : RTX 3060, 12288 MiB total, 8962 MiB used, 2994 MiB free, 0 %, 170 W cap
sample      : n=80 | SM moy 76.2% (max 100%) | VRAM moy 8962 Mio | 129.7 W moy
```

Exit 0. The `load`, `sweep` and `sample` modes were **not** exercised: they put real
concurrent load on the production service, which nothing here authorised.

**Three defects found while reading it**, listed here because they are what the sixth pass
went on to fix:

1. **`IP_LOCAL` is dead code** (line 26). It runs `hostname -I | awk '{print $1}'` on
every invocation and the value is used nowhere — so every mode pays for a subprocess
that no output consumes, and it fails noisily on hosts without `hostname -I`.
2. **The endpoints are hardcoded** (line 30): `URLS` defaults to the exact three
   addresses that `infra/config/cluster.env:21` already declares as `NODE_IPS`. The
   bench therefore carries a second, silent copy of the topology — if a node's address
   changes, `cluster_status.sh` follows the config and this bench keeps measuring the
   old host. The override (`URLS=…`) exists, but the *default* is the thing that lies.
3. **`MODE` is never validated.** There is no `else` arm: `collect` is the trailing block,
   so a typo (`MODE=swep`) prints a plausible collect report and exits 0 instead of
   failing. Every other mode tests `[ "$MODE" = … ]` and falls through.

### Sixth pass, same day — the three defects fixed, instrument re-dated as v2

**The method problem, stated before the fix.** Every one of those three fixes changes the
hash that `evidence/2026-09-15/` cites as *the instrument that produced the knee
measurement*. Two options: rewrite the 2026-09-15 records (**forbidden** — R7, a dated
record is not rewritten), or fix the instrument and **produce a new dated record**, keeping
the bytes of the version that measured. The second was done.

| | sha256 | bytes | lines | where |
|---|---|---|---|---|
| **v1** — measured 2026-09-15 | `bfe192a8…` | 9 230 | 205 | `evidence/2026-09-17/gpu-bench-instrument/gpu-bench-node.v1-bfe192a8.sh`, `~/zabeth22-vllm-repair/gpu-bench-node.sh`, `~/gpu-bench-node.sh.bak-20260917` ×3 |
| **v2** — corrected | `8e774069…` | 11 481 | 248 | `infra/scripts/node_gpu_bench.sh`, `~/gpu-bench-node.sh` ×3 |

**The three fixes.** `diff` v1→v2: **3 deletions, 44 additions** — the deletions are exactly
the three defects, no other original line was touched.

1. `IP_LOCAL` removed (nothing read it).
2. `URLS` is now **derived from `cluster.env`** (resolved next to the script, or via
   `CLUSTER_ENV=<path>`, or `$HOME/infra/config/cluster.env`); the 2026-09-15 addresses
   survive only as `DEFAULT_URLS` so the bench still runs from `$HOME` alone, which is the
   case on the nodes. `URLS=…` still overrides everything.
3. A `case` guard at the top of the script: `sample|load|sweep|collect` pass, anything else
   prints to stderr and exits **2**.

**Proved equivalent, not assumed.** `MODE=collect` run with v1 then v2 on zabeth22 produced
**identical output** (masking only the timestamp and the live power/clock readout), exit 0
both — the sole raw difference being `19.56 W` vs `19.55 W` idle, which drifts physically.
Endpoint resolution was checked by **observing the value of `URLS`** (a probe appended to a
throwaway copy), including the decisive case: a config with a node moved to `10.0.0.9`
**is followed**, while a config without `NODE_IPS`, an unreadable one, or `NODE_IPS=()` all
fall back to the recorded triple. `QWEN_PORT` is read from the config too.

**Deployed with backups**, all four copies now `8e774069…`, mode 755 (was 644; the scripts
are run as `bash <file>`, so this is alignment, not a requirement).

**`load` / `sweep` / `sample` were still not run** — they put real concurrent load on the
production service. Their acceptance was verified by pointing at a missing test image,
which stops the script at the image probe, i.e. before any request.

Full record: `evidence/2026-09-17/gpu-bench-instrument/` (`instrument-repin.json`, the
preserved v1 bytes, and `SUMMARY.md`).

### Seventh pass, 2026-09-28 — v2 audited, four measurement defects fixed, benchmarked live

This pass did what the two before it could not: it **ran the instrument against the real
cluster**. The service was left alone (listener PIDs `17752 / 3399 / 17359` identical before
and after; `golden-check.sh` = `NOEUD DORE ×3` at the end of the session).

**Found while reading v2, fixed as v3.** v2's three fixes were all *hygiene*; the defects
that mattered were in the measurement arithmetic, and they only appear when something
fails — which is exactly the regime a saturation sweep is built to enter.

| # | defect | effect | proof |
|---|---|---|---|
| 1 | the rate and p50/p95 counted **failed** requests (`n` = all lines; a curl timeout writes `120.000 000`) | throughput is attempts/s, and at the knee p95 is set by the timeout | local fixture, 1 good + 1 refused endpoint: v2 `538.1 req/s` vs v3 `278.6 req/s` — **v2 overstated by ~93 %** |
| 2 | the GPU sampler ran `t` **iterations** (~1.04 s each), not for the measured interval (`t` + tail) | the two lines of one level describe different intervals, in a direction that depends on `T` (they cross near `T ≈ 40 s`) | A/B at 16/n: perf identical (29.9 vs 30.0 req/s), GPU mean 91.7 vs 99.8 % |
| 3 | node count hardcoded (`c*3`, `/3`, `total %3d`) while the **list** came from config | N≠3 nodes ⇒ per-node rate divided by 3 | fixture with 2 endpoints: v2 `total 6`, v3 `total 4` |
| 4 | served model name hardcoded, ignoring `QWEN_SERVED_NAME` — the only per-node script that did | a renamed served model 404s every request | config with `QWEN_SERVED_NAME=my-served` is followed |

Plus: a config fallback is now **loud** on stderr and each mode prints `source: config …` /
`repli 2026-09-15` / `URLS= (explicite)`; `MODE=sample`'s two dead statements are gone (same
family as the `IP_LOCAL` v2 removed); `m=0` no longer prints an empty `p50`; `MODE=collect`
now states the target it would measure. Output labels changed from `%5d req` to
`%5d ok / %5d tentatives`, because the number now counts **successes**.

**One of my own predictions was wrong, and the A/B says so.** I expected the fixed window to
*lower* the GPU mean. It rose (91.7 → 99.8 %). The arithmetic rules the window out: over
~12 vs ~14 samples, going from 91.7 to 99.8 % would need the two extra samples to average
148 %. The gap is **run-to-run variance**. Three v3 runs at the same level gave 100.0 /
92.3 / 99.8 %. So at `T=12`, 1 Hz, the SM mean carries roughly **±8 points** of noise, and
`sm_max = 100 %` is the only saturation claim these measurements support. This is recorded
in `sweeps.json → gpu_utilization_precision` rather than smoothed over.

**Benchmarked, and the 2026-09-15 record reproduced.** Two sweeps from zabeth22 (image
`ca07ce15…`, identical to the 2026-09-15 file):

| conc/node | 09-15 req/s · p50 | 09-28 req/s · p50 | requests |
|---|---|---|---|
| 8 | 17.4 · 1.316 | 18.0 · 1.313 | 216 = 216 |
| 12 | 24.8 · 1.435 | 24.7 · 1.433 | 324 = 324 |
| 16 | 30.3 · 1.555 | 30.1 · 1.573 | 384 = 384 |
| 18 | 25.8 · 2.056 | 25.9 · 2.062 | 324 = 324 |
| 20 | 28.0 · 2.094 | 28.2 · 2.095 | 360 = 360 |
| 24 | 32.0 · 2.209 | 32.1 · 2.189 | 432 = 432 |

The knee is reproduced where it was put: **16 → 18 costs +31.1 % latency and −14.0 %
throughput** (09-15 measured +32.2 % / −14.9 %), and request counts match to a percent at
every common level. 13 days later, different server PIDs, a corrected instrument — same
numbers. That is what makes the original measurement worth citing.

**Two things the cluster told us that the repo did not.**

* **`infra/config/cluster.env` is absent from every node**, confirmed live. So the v2 fix
  that made `URLS` config-derived **does not reach the deployed instrument**: on a node the
  resolution falls back to `DEFAULT_URLS`. v3 now *prints* `source: repli 2026-09-15`
  instead of being silent, but the fix only becomes real once `cluster.env` is shipped
  beside the script. `MODE=collect` is the one-command check.
* **The test image is not in the repo and lives in `/tmp`.** `/tmp/vlm-test-images/`
  `device_clean.jpg` was absent on all three nodes at the start of this pass (the nodes had
  rebooted), so `MODE=load` and `MODE=sweep` exited 1 on a healthy cluster. It was restored
  from `~/zabeth22-vllm-repair/device_clean.jpg`. Until that file is versioned, any
  reproduction of the sweep depends on a file outside the repo.

**Five more defects, outside the instrument** (full detail in
`evidence/2026-09-28/infra-hardening/fixes.json`):

1. `lib_cluster.sh::node_ip` **aborted its caller** under `set -u` when `NODE_IPS` was
   shorter than `NODES` (`unbound variable`, exit 127) — every consumer is `set -euo
   pipefail`. It now falls back to the alias, as its comment always claimed.
2. `cluster_status.sh` printed **hardcoded** `8000/8001` labels while probing the configured
   ports, and `port_state` already returned `port:pid`, so it rendered `8000[8000:21573]`.
3. `cluster_status.sh`'s `procs` probe **matched itself** (`pgrep -af` run through `bash -c`),
   inventing a process per node.
4. `node_write_provenance.sh` and `node_install_venv_environment.sh` still had their
   `# NOTE …` block **above the shebang** — the wart fixed for `golden-check`/`vllm-service`
   on 09-17, left in place for these two. All 13 `infra/scripts/*.sh` now start with a
   shebang.
5. `node_write_provenance.sh` **hardcoded `latency_p50_s: 0.414 / images_measured: 12`** into
   a dated artifact whose header promises "Nothing is copied from an older report". It now
   writes `NON FAIT` with a pointer, and measures `vram_used_mib` in the run. Verified live
   on all three nodes (previous `ENV_STATUS.md` backed up as `.bak-20260928`); the weight
   hash `25aab8ca…` came back identical ×3, re-confirming byte-identical weights.

`bootstrap_ssh.sh`'s node `~/.ssh/config` backup was also made **rolling** (it was one-shot,
so a second run overwrote the live config keeping only the first version). Analysis only —
the step is opt-in and was not run.

Full record: `evidence/2026-09-28/` (`gpu-bench-instrument/instrument-repin.json`,
`sweeps.json`, the preserved v2 bytes, three raw logs; `infra-hardening/fixes.json`).

### Eighth pass, same day — the image is versioned, the config reaches the nodes, and the GPU column was measuring the gap between levels

Second pass on 2026-09-28. It closes the three follow-ups the seventh pass left open, and closing the
third found a **measurement defect in v3**, so the instrument is now **v4** and the *“±8 points of
noise”* explanation published earlier the same day is **superseded** — the seventh pass's record is
left exactly as written (R7); both records are in `evidence/2026-09-28/`.

Nothing was restarted: listeners `17752 / 3399 / 17359` from the first probe to the last, and
`golden-check.sh` ended `NOEUD DORE ×3`.

**The test image is versioned** (follow-up 2). `infra/assets/test-images/device_clean.jpg`,
`ca07ce15…`, 38 937 B, with `infra/assets/README.md`. The three per-node scripts no longer assume one
path; they resolve `$TEST_IMAGE` → `<script dir>/../assets/test-images/` →
`$HOME/infra/assets/test-images/` → **`$HOME/vlm-test-images/`** → `/tmp/vlm-test-images/`. The fourth
is what the deploy installs, and it is the answer to the failure the seventh pass recorded: `/tmp` is
cleared on reboot. Precedence **proved** by running the real script through a fake `base64` that logs
which file was read, six cases, plus `TEST_IMAGE=` winning over all of them. The legacy `/tmp` copy
was then deleted on all three nodes so exactly one copy exists per node — and `vllm-service.sh
health` still prints `requete image : OK` on zabeth21, which it could not have before. The file is a
Pillow **drawing** of a `TP-Link TL-WR841N` label, not a photograph; because JPEG bytes depend on the
encoder version, the bytes are versioned rather than the generator re-run.

**`cluster.env` reaches the nodes** (follow-up 1). Shipped to `$HOME/infra/config/cluster.env`,
which is the second path the endpoint resolution already looked for. `MODE=collect` now prints
`source : config /home/msalhi/infra/config/cluster.env` on all three instead of
`repli 2026-09-15`. That it *drives* the target was checked three ways: a config with
`NODE_IPS=(10.0.0.1 …)` and `QWEN_PORT=9000` **is followed**, an unusable one is **loud** and falls
back visibly, and the unmodified config wins when nothing is overridden.

**The config was also lying about its own override mechanism.** Its header promises
`~/.iot-audit-infra.env`, and the *Configuration* section above repeats it — but `grep -l` matched
only `node_vllm_service.sh`, a per-node script: **no orchestrator script read the file at all**, and
`NODES`/`NODE_IPS`/`QWEN_PORT`/`LLAMA_PORT`/`QWEN_SOURCE_NODE`/`LLAMA_SOURCE_NODE` were bare
assignments that could not even be overridden from the environment. The override file is now sourced
first, so every guarded default keeps an override, and the six bare keys are guarded (`[ -n "${X+x}" ]
|| …` for the two arrays, which cannot use the `:-` idiom). Six cases verified, plus
`IOT_AUDIT_INFRA_ENV=… NODES=(stubA …) cluster_status.sh` now iterating `stubA`, plus the same
override moving the *node-side* measured target. The offline `selftest/` still exits 0 on all six
scripts.

**The GPU column was measuring the gap between levels** (follow-up 3). The seventh pass called the
spread “run-to-run noise, about ±8 points at `T=12`”. Repeating the level six times with **the same**
v3 bytes gave `92.3 92.1 92.1 92.3 92.3 92.3` — a spread of **0.2** points. An instrumented copy that
keeps the raw sample file plus an independent timestamped 1 Hz probe show what is happening:
`run_level` launches the sampler, *then* records `start`, so the sampler's **first** read lands ~2 ms
before `start` on a GPU whose previous level has just drained — and it was counted. Thirteen samples:
one at `0 % / 12.67 W`, twelve at `100 %`; `12×100/13 = 92.31 %`, the observed figure. A **quantised
artefact worth `100/T` points**, not noise.

v4 timestamps every sample (6th column), computes the level's `GPU :` line over `[start, end]` only,
and prints the **median** and **minimum** alongside the mean — the filter leaves a ~2 ms race, and the
median is immune to one or two stray samples where the mean is not. Median by histogram, because
`asort` is a gawk extension and the nodes run **mawk**; the program was run under both awks with
identical output, including the case where the stray sample is inside the window (`moy=83.3
med=100.0 min=0.0`).

| @ 16 req/node | v3 SM mean | v4 SM mean | v4 SM median |
|---|---|---|---|
| `T=12` ×6 | 92.1 – 92.3 | 99.0 – 100.0 | **100.0 ×6** |
| `T=30` ×4 | 93.3 – 96.7 | 99.9 – 100.0 | **100.0 ×4** |
| `T=60` ×3 | 96.6 – 98.3 | 99.9 – 100.0 | **100.0 ×3** |

The mean's spread falls **8.3 → 1.0 points**; the residual is the level's own ramp and drain, i.e.
physical. Throughput and latency are untouched (the change is confined to the `GPU :` line), so the
published 16→18 knee stands.

**And the corrected column changes what may be concluded.** `SM med = 100.0 %` at *every* level from
`4/n` upward, so on this cluster `utilization.gpu` is a **saturated boolean, not a graded signal**,
and this script's own reading note (*“latence qui MONTE + SM qui plafonne = on a passe le genou”*) is
not usable here. What separates the levels is **power** (152.6–153.8 W at 4–8/n against 165–170 W from
16/n up) and `p50`. The knee is a latency cliff, not an occupancy threshold.

**Two more defects found while reading, both fixed.** `run_benchmark.sh --mode local` validated
`$BENCH_SCRIPT`, which defaults to a *node*-side path, so the branch could never work and blamed the
missing client instead of the mode — it now says `BENCH_MODE=local needs a LOCAL client: set
BENCH_SCRIPT=<path>`. And `serve_wait_all` printed `~/logs/${label}_${ssh_alias}.log` while the
launcher writes `~/logs/${label}_$(hostname).log`: the two agree on this cluster, but assumption 5
below is a thing to *verify*, and the nodes still carry `qwen_zabeth71.*` from a period when they did
not — so the hint has already pointed at a file that does not exist. A new `serve_log_name` asks the
node for its own `hostname -s` and falls back to the alias when it is unreachable.

**Deployed — hash-verified against the repo on all three nodes**, `bash -n` clean, with the whole
instrument version chain preserved on every node:

| on-node | sha256 | bytes |
|---|---|---|
| `~/gpu-bench-node.sh` (**v4**) | `b995268116b05e93…` | 20 738 |
| `~/golden-check.sh` | `207304b5b115742e…` | 12 581 |
| `~/vllm-service.sh` | `0f9b2da3e635626a…` | 16 810 |
| `~/infra/config/cluster.env` | `f214b596fad4ae60…` | 9 389 |
| `~/vlm-test-images/device_clean.jpg` | `ca07ce152117395b…` | 38 937 |

The instrument's chain: v1 `bfe192a8…` (2026-09-15) · v2 `8e774069…` (2026-09-17) · v3 `bacb86c6…`
(2026-09-28, still cited by that morning's record — its bytes are preserved in the new pass's
evidence folder and as `~/gpu-bench-node.sh.bak-20260928T1658`) · v4 `b9952681…`.

A backup-naming incident worth recording: this pass's first backups were named `.bak-20260929` — the
wrong date, and for `gpu-bench-node.sh` a **collision with `.bak-20260928`, which already held v2**.
Writing that name would have destroyed the preserved v2 bytes. Caught before anything was lost and
renamed with a timestamp.

Full record: `evidence/2026-09-28/instrument-v4-and-config/` (`SUMMARY.md`,
`instrument-repin-v4.json`, the preserved v3 bytes, `live-verification.log`,
`config-override-tests.log`, `precision-z22/`).

---

### Ninth pass, same day — the server side of a request is measured, and the reboot hole is closed

v4 fixed *when* the GPU column is sampled. v5 answers a different question, one no client-side number
could: **where the time inside a request actually goes.** `MODE=sweep` now reads vLLM's Prometheus
histograms from `/metrics`, differing a snapshot taken before the level's requests against one taken
after — **the same window as the throughput and the client p50**, which is why it lives in the bench
and not in a separate tool.

zabeth22, `T=14`: (conc/noeud · req/s · p50 client · queue · prefill · decode · inference · W)

| conc | req/s | p50 | queue | prefill | decode | inference | W |
|---|---|---|---|---|---|---|---|
| 8 | 17.5 | 1.314 | 0.0000 | 0.0793 | 1.2041 | 1.2833 | 150.2 |
| 12 | 24.6 | 1.432 | 0.0000 | 0.1030 | 1.2890 | 1.3919 | 165.0 |
| 16 | **30.2** | 1.553 | 0.0000 | 0.1363 | 1.3753 | 1.5116 | 164.9 |
| 18 | 25.5 | 2.066 | 0.0000 | 0.1494 | **1.8619** | 2.0113 | 158.0 |
| 20 | 28.0 | 2.094 | 0.0000 | 0.1599 | 1.8819 | 2.0418 | 158.3 |
| 24 | 32.2 | 2.197 | 0.0000 | 0.1876 | 1.9512 | 2.1388 | 157.2 |

`inference = prefill + decode` holds to 4 decimals at all six levels, `n` (server) equals `ok`
(client) with a gap of **0**, and the client p50 lands inside the server bracket — the three relations
`make-sweep-json.py` checks before the numbers are quoted.

**What it shows, which no client number could.** Queue time is **0.0000 s at every level**, so vLLM's
"queue" carries no waiting here at all (continuous batching admits requests instead of queueing) — the
knee is therefore *not* a queueing threshold. It is entirely in **decode**: +14 % from 8/n to 16/n,
then +35 % from 16/n to 18/n, while prefill grows evenly and the SM is already 100 %. And **power rises
to the knee then falls** (150 → 165 → 165 → 158 → 157 W) while latency keeps climbing, so it is power,
not `utilization.gpu` (median 100.0 % everywhere), that tracks the phase change.

**Six defects fixed while closing this out**, each with the evidence that found it. (1) `metrics_delta`
decided which snapshot was the *baseline* with `FNR == NR`, which assumes the first file is **non-empty**:
an empty `before` snapshot (curl failure, or `-m 10` expiring under load) made it read the `after`
snapshot as the baseline — negative deltas and **no bucket lines at all**, silently. The two passes are
now named by file, and the offline test carries a negative control showing the old form is wrong
(`COUNT=-1506`, 0 buckets) where the new one is right (`COUNT=1506`, 22 buckets). (2) A cumulative
counter that went *backwards* (server restarted between snapshots) was clamped to 0 without a word —
it now publishes `RESET 1` and the level says so. (3) `metrics_scan` concatenates three `/metrics`
bodies; a **silent endpoint** produced a split and a client/server gap computed over a *subset of the
cluster*. It now returns how many endpoints answered and the level warns — measurably the right
control, because in a live 1-of-3 test the gap was still `0` and only the coverage line caught it.
(4) `local x` on an already-local variable **resets it**, so re-declaring the coverage variables inside
`run_level` wiped them and the first live level died with `nb_ap: unbound variable`; moved to the top of
the function. (5) An ASCII apostrophe inside a single-quoted awk program terminates the quote —
`bash -n` caught it. (6) `vllm-service.sh wait` was advertised in its usage line from the start and was
**not in the dispatch table** (`wait` fell into `*` and exited 64); it is implemented now, since
waiting for a server you did not start is a real need. A systematic pass over all ten scripts, comparing
each usage line against its implemented actions, found this as the only such gap.

**A new offline test exists: `infra/selftest/check-metrics-math.sh`.** This arithmetic is invisible in
the output — a wrong split prints exactly like a right one — so the test is *differential and
cross-language*: the awk under test is **extracted from the instrument** (never copied), the truth is
computed in Python by sorting and indexing. **312 cases** (12 designed + 300 random, fixed seed) across
the **real** bucket labels (`1.0`, not `1`) and **both** bucket lists (e2e 21 bounds, TTFT 22 bounds
down to 0.001 s), including an empty `before`, a partial `before`, a counter reset, a value past the
last finite bound, and a zero-traffic level that must read `NA` rather than 0. Snapshots and truth are
derived from **one** description and their arithmetic is asserted before anything is written — that is
exactly the bug that produced the first fixture, which disagreed with its own expected values.

**The reboot hole is closed.** Until now a reboot silently emptied the cluster: three servers gone, and
a client cannot tell an empty cluster from a saturated one. Devuan has no systemd and `sudo` needs a
password, so the only mechanism is a user `@reboot`:

```
@reboot /bin/bash /home/msalhi/vllm-autostart.sh --run >>/home/msalhi/logs/vllm-autostart.log 2>&1  # iot-audit:vllm-autostart
```

`node_vllm_autostart.sh` **never starts vLLM itself**: it waits for the driver and for a global IPv4
address, then delegates to `vllm-service.sh start`, which already owns the preflights, the occupied-port
refusal and the `/v1/models` wait. Reimplementing the launch would have created a second definition of
the service — the one that drifts. Verified on all three nodes by an 8-part battery
(`evidence/.../verify-autostart.sh`): a **live** service is never touched (rc=0, "already running"), a
missing one is started, a failing one is retried the advertised number of times, an invisible GPU stops
the script **before any call**, and `--uninstall` returns the crontab to empty with a dated backup.
The vLLM service did not move for the whole battery on any node. What the battery does **not** establish
is a real reboot — that stops the service and was not done; what is established instead is that `cron`
runs, is enabled at boot (`/etc/rc2.d/S05cron`), and the exact command line works. Two defects came out
of it: the script **replaced** `PATH` instead of extending it (so a binary placed in front of it to
force a failure path was ignored — a script you cannot make fail is a script whose failure path you
cannot verify), and `--status` looked for a daemon named `crond` when Devuan calls it `cron`.

**RULES FOR DEPLOYING TO A NODE — one of these was learned the expensive way this pass.**

1. **A backup name must be unique per invocation** (timestamp to the second), and **an existing backup
   must never be overwritten** — use `cp -n`, or check the name is free first. Two deploy runs the same
   hour with the same `T1747` stamp meant the second `cp -p` wrote over the backup holding **v4**, and
   `b9952681…` (20 738 bytes) is now **unrecoverable**: it was never preserved in the repo, and a
   size-and-hash sweep of the nodes found nothing. No published measurement is invalidated — v4's
   numbers are recorded with their values — but the "superseded instrument bytes are preserved" rule is
   broken for that one version and its hash can never be re-verified. The earlier `_backup_naming_incident`
   in the v4 record describes the *first* occurrence of the same hazard; prose alone did not stop it.
2. **Verify the sha256 on the node BEFORE swapping**, and **never use `ssh -n` for a transfer**
   (`-n` redirects stdin from `/dev/null`, so `ssh -n host "cat > f" < f` writes an empty file — the
   empty-file hash `e3b0c442…` was mistaken for a successful deploy on two nodes, and `--install` of an
   empty script exits 0 having done nothing).
3. Keep the superseded bytes: copy the replaced file into the pass's `evidence/…/superseded/`.

Deployed — hash-verified against the repo on all three nodes after the last swap:

| on-node | sha256 | bytes |
|---|---|---|
| `~/gpu-bench-node.sh` (**v5**) | `6f954091ee10f8ee…` | 36 993 |
| `~/vllm-service.sh` | `912934d8a0b4cda2…` | 20 370 |
| `~/vllm-autostart.sh` (new) | `c0b82d3bd4ee88f7…` | 10 479 |
| `~/golden-check.sh` | `207304b5b115742e…` | 12 581 |
| `~/infra/config/cluster.env` | `c7c3578975427da4…` | 10 743 |

The instrument's chain: v1 `bfe192a8…` · v2 `8e774069…` · v3 `bacb86c6…` · **v4 `b9952681…` — bytes lost
(see rule 1)** · v5 `6f954091…`. The payload (`VLM_PROMPT`, `VLM_MAX_TOKENS`, `VLM_TEMPERATURE`) now has
**one** home, `cluster.env`, read by the bench and by `health`, with
`infra/selftest/check-payload-consistency.sh` failing if the two JSON skeletons or their values diverge.

Cluster state after the pass: listeners **17752 / 3399 / 17359**, unchanged from the first reading of
the day, never restarted; `golden-check.sh --json` = `17 PASS / 0 FAIL / 2 WARN` on all three nodes.

Full record: `evidence/2026-09-28/instrument-v5-metrics-wire/` (`SUMMARY.md`, `sweep-v5-z22.log` and
`.json` with its verified relations, `make-sweep-json.py`, `sweep-partial-endpoints.log`,
`metrics-sample.txt`, `verify-metrics-math.log`, `verify-payload-consistency.log`,
`verify-autostart*.{sh,log}`, `golden-check-zabeth2*.log`, `superseded/`).

---

### Tenth pass, same day — the declared risks were probed, and `stop` was signalling its own caller

The ninth pass closed with a list of things it had *not* measured. A list of unmeasured risks is
a list of assumptions, so this pass takes each one to the hardware. Three closed with a number,
one turned out to hide a defect, and the rest are left open with the reason stated.

**A correction, recorded rather than edited (rule 1).** The ninth pass's deployment table above
lists `~/vllm-autostart.sh` as `c0b82d3bd4ee88f7…`. That same pass then added `--disable`/`--enable`
to the file and dogfooded the new bytes onto the nodes, so the footprint it left is
`dee8ac5563bb7216…`. The table is left exactly as written — it describes the file at the moment it
was written — and the on-node truth is stated here, dated. `~/vllm-service.sh` moved again in this
pass: `912934d8a0b4cda2…` → **`f778015c57153224…`**.

**The defect: `stop` could see — and kill — the session that launched it.** Measured on zabeth23
with one live server and one `EngineCore`, `pgrep -f` answered **3** for *each* of `stop`'s two name
patterns. Through a `bash -c` the caller's own command line carries the pattern, so it counts
itself. That is a wrong number, and it explains the "orphans" announced earlier the same day for a
perfectly clean shutdown (the verbatim output of an operator's `stop` names no orphan at all; the
same question asked with a bracket pattern that cannot self-match answers *no orphan*, and no
compute process on the GPU). It is worse than a wrong number: the same pattern fed `pkill -f`, so
`stop` could send `SIGTERM` to its caller, and with a short pattern like the model name, to any
monitoring tool that mentions it.

`node_vllm_service.sh` now has `own_group()` and `stray_by_name()`. `stray_by_name()` returns
PIDs, discards `$$`, `$PPID` and its **own process group**, and skips any PID that `ps` can no
longer read — a process already gone, whose number the kernel may have recycled (one such PID was
measured, already absent from `/proc`). `sweep 2` then stops **by PID, never by pattern**.
Discarding our own group cannot hide a real orphan: the service is launched under `setsid`, so its
group is its own and can never be ours.

`infra/selftest/check-stop-scope.sh` is new and asserts four measured things: the historical form
miscounts (the negative control — without it the fixed form passing would prove nothing), the fixed
`stray_by_name()` returns exactly the stray and not its caller, killing exactly what it returned
kills the stray and leaves the caller running, and the historical `pkill -f` **kills the caller**.
The stray is started under `setsid` on purpose, and the check verifies it is its own group leader:
run it in our group and the fix discards it, which would read as the function having gone blind.

The functions are exercised on the real path by fault injection: `kill -9` on the API server
reparents `VLLM::EngineCore` to init still holding 8 962 MiB, the pid file is removed (the case
`sweep 2` exists for), and `stop` names **exactly one PID** — the real EngineCore — and frees the
GPU. Honest scope: in *that* scenario the old code would have succeeded too, because the caller
`bash ~/vllm-service.sh stop` does not carry the `VLLM::EngineCore` pattern. What the injection
establishes is that the fix reaches the path and broke nothing; what needed fixing is the case
above, and it took a caller whose command line carried the pattern.

**Cold start, by the exact `@reboot` command, three times.** Run with cron's *exact* environment —
`env -i SHELL=/bin/sh HOME=/home/msalhi PATH=/usr/bin:/bin`, no `/usr/sbin`, no `/sbin`, no venv —
the service came up in **55 s** every time (18:23:52→18:24:47, 18:31:28→18:32:23,
18:36:35→18:37:30), first attempt, GPU and IPv4 waits returning in ~0 s. What this does **not** show
is the trigger: `@reboot` firing at a real boot needs a reboot, and none was authorised. Established
separately earlier the same day: cron *executes* this crontab (a temporary `* * * * *` line carrying
the same command ran at 18:14:01 and 18:15:01, `rc=0`).

**The `RESET` flag, on real bytes.** The restart provided the pair the synthetic fixture could not:
`/metrics` before (11 203 requests) and after (0). Fed to `metrics_delta` **extracted from the
deployed instrument**, it prints `COUNT -11203`, `RESET 1`, and `NA` for mean/p50/p95; the aggregate
of all three endpoints also raises the flag when only one node restarted; `run_level`'s warning
prints. The negative control is a real one — two snapshots of zabeth21 with five real `health`
requests between them give `COUNT 5`, `RESET 0`, mean 1.0837 s — so the test distinguishes a restart
from traffic instead of flagging both.

**The server-side split, four draws.** The knee's +35 % in decode (16/n → 18/n) was published on
one draw. Three repeats, same node and charge, per fresh pair of snapshots: decode spreads 0.61 %
at 16/n and 1.26 % at 18/n across four draws, so the knee is **28×** the run-to-run noise. Queue is
**0.0000 s in all eight draws** — the knee is not waiting, it is entirely decode — and server `n`
equals client `ok` in all eight.

> **SUPERSEDED 2026-09-29 — the "Still open" list below is closed.** The node password was supplied and
> `sudo -l` gives `(ALL : ALL) ALL`, so all three gated items were done: the `@reboot` **trigger** was proved
> on 3/3 nodes, the **deep tier** passes, and **V12 was executed**. See the section
> **"Maintenance actions, 2026-09-29"** at the end and `evidence/2026-09-28/risk-probes/SUMMARY.md` §20.
> The text below is kept as written (rule R7).

**Still open, each with what it would take:** the `@reboot` *trigger* (an authorised reboot);
`golden-check.sh --deep` and the V12 egress test (a window where the service may stop / the network
may be cut); a non-zero queue (a sweep at 32/48/64 per node); the test image being a Pillow drawing
(a real photo *and* a quality protocol — swapping it now would invalidate published latency
comparisons); and the `sshpass` secret in `/home/alex/.bash_history` (a user action: 7 lines, one
13-character value, mode 600, absent from the repo, `~/.ssh` and the sibling project, and **not
needed** — `portier` and `zabeth21` both answer under `BatchMode=yes`, so authentication is by key).

Cluster state after the pass: **zabeth21 17752** and **zabeth22 3399** untouched (the pass never
stopped them); **zabeth23 14799**, because the pass stopped and restarted that node three times on
purpose. `golden-check.sh --json` = `17 PASS / 0 FAIL / 2 WARN` on all three; 18/18 artefacts
identical between the repo and the nodes.

Full record: `evidence/2026-09-28/risk-probes/` — `SUMMARY.md`, `verify-all.log`,
`cold-start/` (down state, three cold starts with node timestamps, the `/metrics` pairs straddling
the restart, `probe-reset-live.sh` and its log), `sweep-repeat/` (three repeats, `spread.py` and the
`spread.txt` it derives), `repro-orphelins/` (the mis-count, the verbatim clean stop, the new
selftest's four cases, the deploy log and the superseded bytes), `orphan-fault-inject/`, and
`queue-sweep-high/`.

---

#### Tenth pass, addendum — the queue does open, and the reason is not the one the knee suggested

The open list above ended with "a non-zero queue (a sweep at 32/48/64 per node)". That was run, and
the answer needed one more step than expected.

At 32/48/64 the queue stays negligible — `file moy` goes from 0.0000 s to **0.0001 s per request**,
0.002 % of a 4.3 s request — while throughput saturates (39.1 → 41.7 → 43.2 req/s) and p50 doubles.
The bench only reads `/metrics` before and after a level, server idle: those two reads *cannot* show
a queue *depth*. So a 1 Hz sampler of the scheduler gauges ran alongside (741 lines), and it says
`num_requests_waiting` is **0** at every sample up to 64.

But `kv_cache_usage_perc` climbs — 41.7 %, 52.8 %, **76.6 %** — and that is what actually bounds
admission. The startup log gives its size: `GPU KV cache size: 9,104 tokens, Maximum concurrency
for 8,192 tokens per request: 1.11x`. That 1.11× describes a request holding all 8192 tokens; this
workload never does, because it is **one image and one prompt**, and `enable_prefix_caching=True`
**shares** the prefix (98.1 % of queries hit it). Each request's private cost is only its ~96
*generated* tokens, rounded to the KV block: ~92–109 tokens measured. The prefix is free; the
generated tokens fill the cache.

That reading puts saturation near **~84** concurrent per server. Pushing to 96 and 128:

| req/node | running | waiting (max) | `reason=capacity` | KV cache | preemptions |
|---|---|---|---|---|---|
| 96 | 96 | **8** | 8 | 96.83 % | 0 |
| 128 | 128 | **26** | 26 | **100.00 %** | 115 |

**The queue opens between 64 and 96 req/node**, and at 128 the KV cache is full: every wait is
`reason=capacity`, and the scheduler had to **evict 115 requests** to make room. The predicted ~84
sits inside the measured bracket — the estimate was usable and is now replaced by a measurement.

Two things this does *not* change. Queue **time** stays tiny (0.0002 s at 96, 0.0017 s at 128): few
requests wait, and briefly. The published split is a *mean per request*, so it dilutes a short peak
rather than showing it — the two numbers answer different questions and do not contradict. And
throughput **peaks at 64** (43.2 req/s) then falls (39.5, 38.0): past the knee, more concurrency only
makes requests longer. No HTTP errors at any concurrency (5 754 requests across the day's three
sweeps), and the service never moved — the same PIDs 17752 / 3399 / 14799 throughout.

One correction, recorded because it would have published the opposite conclusion: the first reading
treated `kv_cache_usage_perc` as a percentage, so `0.7658` read as "0.77 % of the cache in use" —
which implies the queue *cannot* fill, and the measurement says it does. It is a **ratio 0..1**: 76.58 %.
The analysis script converts it once, in one place.

The full 11-level table is derived from the three sweep logs by `queue-sweep-high/table-complete.py`
rather than transcribed — a hand-copied table is a second source of truth that cannot check itself.

---

#### Eleventh pass, same day — the queue's shape, and the prefix is the whole story

The addendum above left three follow-ups. All three are done, and the third changed its answer
while being run.

**1. The queue is no longer published as a single mean (instrument v6).** `file moy` stayed tiny
(0.0017 s) at the level where 26 requests waited, because a *mean per request* divides a peak by
the number of requests served. It answers "how much time was lost on average", never "did anyone
wait". Two free numbers fix that, read from the same histograms: **`total` = the exact SUM**, and
since every wait is ≥ 0 it is a **rigorous upper bound on the max** that assumes nothing about the
shape; and **`max` / `>0.3s`**, the bucket interval holding the observed maximum and how many
requests crossed the edge. The smallest *finite* bound vLLM publishes for
`request_queue_time_seconds` is **0.3 s** (read off `/metrics`, not assumed), so below that only
the total resolves anything. The motivating case is built and checked: **999 requests at 0 s and
one at 0.29 s** give a mean of `0.0003s` — indistinguishable from an empty queue — against a total
of `0.290000s`. What it buys, on real data: in the varied-prefix sweep below the same line reports
**74/86 requests** and **112/135 requests** waiting more than 0.3 s, which the mean never showed.

**2. The workload can load the KV cache through the prefix, not only through generated tokens**
(`VARY_PREFIX=1`). The bench sent one image and one prompt, so one prefix — and with
`enable_prefix_caching=True` it was *shared*. `VARY_PREFIX=1` makes each worker send a **distinct
image**; without it the bench behaves exactly as before, so published numbers stay comparable.
The images come from **`assets/make-prefix-variants.py`** (new): 32 deterministic variants of
`device_clean.jpg` — same 900x700 geometry, same fonts and positions, only the label text differs
— with a `MANIFEST.txt` of sha256s and a `--check`. The bytes are **versioned, not regenerated**
(the JPEG encoder depends on the Pillow/libjpeg version, as documented in `assets/README.md`).
A defect was found and fixed while building it: the varied branch was still prepending the
single-image body, giving **33 bodies** with a stray sent by nobody but the first worker — an
unequal prefix concurrency and a **wrong distinct-prefix count**.

The matched pair — same node, same charge, same levels, the two sweeps 41 seconds apart:

| 16 req/node | identical prefix | distinct prefixes |
|---|---|---|
| throughput | 28.8 req/s | **4.8 req/s** |
| p50 | 1.556 s | **8.414 s** |
| `file moy` | 0.0000 s | **3.2384 s** |
| `file total` / `>0.3s` | 0.013 s / 0 req | **278.5 s / 74 req (86 %)** |
| KV cache | 25.88 % | **95.77 %** |
| running / waiting | 16 / 0 | **10 / 12** (all `capacity`) |

At 32 offered the varied run is worse still (4.2 req/s, p50 19.6 s, `file moy` 10.6 s, KV 96.3 %,
**10 running and 28 waiting**): past ~10, offering the client more concurrency changes nothing.
Low-charge confirms the same switch — identical prefix at 4 and 8 req/node leaves the KV cache at
13.2 % and 17.4 % with zero waiting; distinct prefixes reach 38.6 % and **76.4 % with 4 waiting at
8 req/node**, where the queue opens.

**The model, and what it predicts.** The startup log gives the cache size
(`GPU KV cache size: 9,104 tokens`). With a shared prefix it is paid once, `KV(n) = P + n·g`; with
distinct prefixes each request pays its own, `KV(n) = n·(P + g)`. A least-squares fit over the **7
non-saturated identical-prefix levels** gives **g ≈ 85 generated tokens** and **P ≈ 975 prefix
tokens**. Admission limits: `(9104 − 975)/85 ≈ **96**` shared versus `9104/(975 + 85) ≈ **9**`
unshared. **Observed: 96 and ~10** — the model closes on both regimes at once.

Three reservations, because an agreement is only as good as its published residuals. **The varied
regime is *missed* by ~20 %** — those levels were not used to fit P and g, and they come out at
+20.8 % and +21.9 %; P is a prefix cost measured under *sharing*, and a distinct prefix is not
quite the same object. The model's 9 stays the right order, but the **robust** number is the
direct, measured ratio `9104 / ~875 ≈ 10.4`. **The “96” is in-sample**: level 96 is one of the
seven fitted points and is exactly where the cache saturates. The check that separates prediction
from interpolation is now in the script — drop that point, refit: P=823, g=92, and it predicts
**~90** shared and **~10** varied, so the prediction holds *without* the point it explains; the
genuinely out-of-sample number is the varied 9 predicted against 10 observed. **And the A/B pair
measures more than one cause**: the model quantifies KV *memory*, while B also pays a prefill of
1.29 s against A's 0.19 s (the vision encoder and prefix recomputed per request when unshared)
and a decode of 4.30 s against 1.38 s (batch cut to 10). The gain of sharing is memory *and*
compute; the “×6” throughput ratio mixes them, and only the memory half is modelled. It does not
touch the admission limit, which the gauges measure independently of what slows the server down.

**What that means for what is published.** The knee and thresholds measured today are conditioned
on a **shared prefix**: they describe a bench, not a workload with different images. A real
workload reaches the KV-cache admission limit near **10 concurrent per server**, not 96 — which is
the difference between a bench that never fills the queue and a real load that fills it from ten
requests per server. The ratio correction above (76.58 %, not 0.77 %) is what makes this readable.

**3. Past 128 req/node** was answered by the addendum above (queue opens at 96, KV full at 128,
26 waiting, **115 preemptions**, throughput peaks at 64 then falls). This pass adds the more useful
point: that limit at 96 was a property of the **single-image** bench. The distinct-prefix regime
moves it to ~10, and *that* is where eviction first bites — so looking for the cost of preemptions
under a shared prefix was looking in the wrong regime.

One incidental confirmation: the sampler wrapper for this work hit **the very defect**
`check-stop-scope.sh` measures — a `pkill -f /tmp/sampler.sh` matched the ssh command line itself
and killed the session before `cat` read the TSVs (0-line files). Fixed with
`pkill -f "[s]ampler.sh"`. Live corroboration that the pattern rides on its sender's own argv.

Instrument is **v6** (`0b9ca0e733b1b987`, 47 499 B), deployed on all three nodes and
hash-verified; the superseded **v5** bytes (`6f954091ee10f8ee`) are preserved in
`queue-shape-and-prefix/superseded/`. New offline check: `selftest/check-queue-shape.sh` (**206
cases, 824 comparisons**, extraction-based, with a strict-threshold negative control). No service
moved — same PIDs 17752 / 3399 / 14799 — and no HTTP errors across the four A/B/C/D sweeps.

Full record: `evidence/2026-09-28/risk-probes/queue-shape-and-prefix/` — `A-identique-16-32.*`,
`B-varie-16-32.*`, `C-identique-bas.*`, `D-varie-bas.*` (logs + 1 Hz gauge TSVs + derived
analyses), `sampler-jauges.sh`, `analyse-prefix.py` + `prefixe-analyse.txt`, `deploy-v6.log`,
`superseded/gpu-bench-node.sh.6f954091`.

---

#### Twelfth pass, same day — the KV peak measured properly, and where the A/B gap actually is

The eleventh pass left three review follow-ups. Two produced measurements; one produced an
instrument version. **One of the review's own objections is refuted by its experiment** — that is
the most useful result of the pass.

**1. The KV peak at 23 Hz: 1 Hz was not hiding anything.** The model rests on peaks of
`kv_cache_usage_perc`, which is a *gauge* — a 1 Hz maximum is only a *lower bound*. A sampler
running **on the node** (no ssh round-trip, `sampler-kv-hf.sh`) recorded the same 4→64 sweep at
**22.9 Hz** (2 468 timestamped reads), and the TSV was then re-sampled to **exactly 1 Hz** to ask
the question that matters: what would the old sampler have said? The peaks are the **same** (max
difference **+4.3 %** at level 16); P moves **+1.2 %** and the admission limits by **~0.8
request** (87.0 → 86.2 shared, 10.1 → 10.0 distinct). The sampling frequency was never the
uncertainty — a level's peak is a plateau, not a spike.

What the exact peak revealed instead: the six peaks are **exactly collinear** (R² = 1.0000, zero
residual), and that is a property of **block quantization**, not a success of the model — the
cache publishes **9,104 tokens = 569 blocks of 16**, and P and g land on near-integer block
counts (**P ≈ 51 blocks, g ≈ 6 blocks/request**). So a leave-one-out and a bootstrap on those
six points are **degenerate by construction** (removing a point from an exact line returns the
same line); the report prints them anyway, identical, with the explanation, because hiding them
would simulate an uncertainty. The real uncertainty is elsewhere — a single 16-token block is
**+16.6 % on g**, and adding the one near-saturated level (96) moves **P by +28.1 % and g by
−11.0 %**. That is where `P≈975/g≈85` (the eleventh pass) and `P≈817/g≈96` (this one) come from:
two correct fits of the same line over different level windows. The **robust** figure is in
blocks: **569 / (51 + 6) ≈ 10** concurrent per server when every prefix is paid.

**2. Where the A/B gap is: memory, compute, parallelism.** The review objected that the “×6”
throughput ratio mixed at least three causes — memory (admission), **compute** (a distinct image
re-running the vision encoder), and parallelism. Vary one thing at a time (`A-identique-4-64`,
`B-varie-8-32`, same node, same levels, back to back).

*At equal concurrency (8), below the limit:* A 17.9 req/s vs B **18.6 req/s (+3.9 %)** — the same
throughput, even though B already uses **4.4×** the KV memory. And the prefill surcharge is **not
the vision encoder**: `mm_cache` hits **100 % on both sides**, so no image was re-encoded. The
+0.133 s tracks the **prefix** cache, 98.08 % → 93.62 % (−6.4 % of tokens served from cache). It
is the un-reused *prefix* that costs, not the vision — and at 8 requests the GPU absorbs it.
*At rising offer:* A scales (17.9 → 30.2 → 39.5 req/s); B **collapses at the limit** (18.6 → 5.0 →
4.1), with `num_requests_running` pinned at **10** whether the client offers 16 or 32.
*And it is not just a concurrency cap.* The **prefix cache collapses to zero** once the KV cache
is full: `prompt_tokens_cached` is **+68,544** tokens at 8 req/node, then **+0** at 16 and **+0**
at 32, and `prefix_cache` goes 93.62 % → **0.00 %**. No prefix is retained, so every *admitted*
request re-prefills entirely: mean inference per admitted request goes **1.164 s → 5.504 s
(×4.7)** while concurrency only moved **8 → 10**. **Memory costs twice**, and the second time —
losing prefix reuse, the very thing that made the single-image bench fast — is the more violent.
The A/B throughput ratio is therefore neither a measure of a distinct prefix's compute cost nor a
simple concurrency ratio.

**3. Instrument v7 (header only).** `node_gpu_bench.sh` is now **v7 (`c79920c43b462263`, 49 757
B)**. The change is **28 lines, all comments** (verified by `diff` against the deployed bytes: no
code line): the header now carries the exact provenance of the cache-hit figure, the model's
exactness as a **block** property, and the fact that memory costs twice. The **v6** bytes
(`0b9ca0e733b1b987`) are preserved in `kv-peak-and-decomposition/superseded/`, the deploy left a
backup on each node, and v7 is hash-verified on all three, then smoke-swept and re-checked with
`golden-check.sh`: **17 PASS / 0 FAIL / 2 WARN** on all three.

**One incident worth citing, because it is the same demonstration again.** This pass's first PID
check read **17517** where the service runs under **17752**: `pgrep -f "vllm serve"` had matched
the **ssh command line itself** — exactly the defect `check-stop-scope.sh` measures and
`node_vllm_service.sh` fixed. With `pgrep -f "[v]llm serve"` the three PIDs are **17752 / 3399 /
14799**, unchanged all day. Deploying a bench script restarts nothing, and the check that seemed to
say otherwise was measuring itself.

Full record: `evidence/2026-09-28/risk-probes/kv-peak-and-decomposition/` —
`sampler-kv-hf.sh`, `run-kv-sweep.sh`, `A-identique-4-64.*`, `B-varie-8-32.*` (logs + 23 Hz TSVs),
`analyse-kv-regression.py` + `kv-regression.txt`, `decompose-ab.py` + `decomposition.txt`,
`deploy-v7.log`, `superseded/gpu-bench-node.sh.0b9ca0e7`.

#### Thirteenth pass, same day — `g` was never `max_tokens`: the per-request KV law, and a test built to separate it from its rival

The twelfth pass measured the KV **peak** properly and could only fit it: `KV(n) = P + n.g`, with
`g ≈ 85 tokens` on the shared-prefix workload, read against the one number that happened to match —
`max_tokens = 96` — from which the earlier passes concluded "g = max_tokens exactly". This pass
**measures** what it had been assuming, and the identity does not survive.

**1. The realised generation length is now a published column, and it is not the ceiling.**
`node_gpu_bench.sh` publishes, per level and on the same window as the peak, throughput and
latencies: `longueur GENEREE moy=... | p50=... | max=... | fin sur plafond max_tokens : x %`. Read
from vLLM's own histograms (`generation_tokens_total`, `request_generation_tokens`,
`request_success_total{finished_reason=...}`) — not from an assumption. On the shared-prefix
workload at `max_tokens=96` the charge generates **73.00 tokens per request with 0 % of requests
reaching the cap**: the ceiling is inert, and the charge stops by itself. The old "g = max_tokens"
was a **numeric coincidence** between 96 (the cap), 73 (the true length) and 16 (the block size).

**2. The law, per request.** `blocks = ceil(g/16) + 1`, with `g` the tokens *actually* generated —
one private block beyond the generated tokens. Three candidate laws were laid against four
independent regimes, chosen so they disagree:

| regime | tiers | measured slope (tok/req) | `g = max_tokens` | `ceil((P mod 16 + g)/16)` | `ceil(g/16) + 1` |
|---|---|---|---|---|---|
| shared prefix 4→48 | none (96 fixed) | **96.3** | 96.0 | 80.0 | **96.0** |
| shared prefix 4→48 | 32 96 192 320 | **84.3** | 160.0 | 68.0 | **84.0** |
| shared prefix 4→48 | 16 48 80 112 | **71.6** | 64.0 | 56.0 | **72.0** |
| shared prefix 4→48 | **8 24** | **40.1** | 24.0 | 24.0 | **40.0** |

The last row is a **test built for the purpose**: for `g = 16/32/48/73` all three laws return the
same numbers, and they diverge only for `g` small modulo 16. `MAXTOK_SET="8 24"` separates them and
the measured slope lands on `ceil(g/16) + 1` within **0.3 %**, against 40 % for the two rivals.

The rival that *a priori* looked right — "a prefix is shared by whole blocks, so each request keeps
the remainder of its prompt's last block" — is **killed by a measurement, not by an argument**:
`request_prompt_tokens` reads **832.00 tokens** over 120 requests, i.e. 52 blocks *exactly*, so
`P mod 16 = 0` and there is no remainder to keep. The `+1` block is structural (one private block
per sequence), which is why the fixed-`96` charge had the form it did. Note also that `P` is now
**read at the source** (832 tokens) instead of fitted, and it lands on the intercepts the twelfth
pass fitted (816–826) within 0.6–1.9 %.

**3. `VARY_ROTATE=1`, and the ~10 seen from the other side.** The new knob advances a worker by one
body **per request**, so the prefix working set becomes the number of bodies (32) rather than the
concurrency. The KV peak then counts **how many distinct prefixes the cache retains** instead of how
many requests it admits: 2.0 / 3.9 / 5.8 / 7.7 / **9.5** / 9.5 at 2/4/6/8/10/12 req per node. The
direct cost of a distinct-prefix request is **872 tokens (54.5 blocks)**, so `569 / 54.5 = 10.4`
admitted — the same number, read once as requests and once as prefixes. And the retention curve has
a measured knee: prefix-cache reuse holds ~78 % up to 8 in flight, then falls to **69 % (10)** and
**47 % (12)** while the admission queue grows from 0 to 7 waiting. When the room goes, the reuse
goes with it.

**4. Three defects found by the probes — two of them in this instrument, one of them silent.**

- **`MODE=load` had been dead since v6.** `local wi=0` was called at script level (`local` is
  function-only), so the run aborted before its first request with `local: can only be used in a
  function` / `wi: unbound variable`. Earlier passes ran it with `2>&1` and **deleted the output**.
  It was caught only because the probe **checks the request count before reading the value**: zero
  requests counted, run declared void.
- **`health` was being executed on every sweep.** A banner label sat in backticks inside a
  double-quoted `echo`, so the shell ran the command `health` and printed "HORS du payload que
  *valide*" — a sentence with the word naming *what validates* removed.
- **A false claim published in v9 and removed in v10.** A "requested ceiling max=..." column was fed
  by `request_max_num_generation_tokens`, which on vLLM 0.29.0 returns **exactly** the same value as
  `request_generation_tokens` (same sum, count and buckets — including under `MAXTOK_SET`, where the
  requested caps are 16/48/80/112 while the sum is 6 300, i.e. the tokens *produced*). The column is
  gone; what was requested reads off the sweep header.

**Instrument.** `node_gpu_bench.sh` is now **v11 (`cba1d4bb066a507d`)**. The chain this day: v6
`0b9ca0e7` → v7 `c79920c4` (comments only) → **v8** `1ed6ae30` (`MAXTOK_SET`, `VARY_ROTATE`,
in-bench gauge sampler) → **v9** `1c0c0871` (measured generation length + `PALIERS_LONGUEURS`
notice) → **v10** `a192a89f` (the false column removed) → **v11** `cba1d4bb` (two robustness lines:
the length is only published when the counter *advances*, so a server restart cannot publish a
negative length — the incident is already flagged by the `RESET` warning on the same line). No
`RESET` occurred in any of the five v10 sweeps, so that guard is provably inert for them; a
confirmation sweep on the final bytes reproduced them level for level.

**A note on the tests.** The v9 additions came with `infra/selftest/check-gen-length.sh` (**19
cases**) — the sixth offline check. It extracts `bracket_bound` and `metrics_counter` from the bench
(never copying them) and covers the three failure modes this codebase has already paid for: a metric
whose name is a **prefix** of ours (`..._total` vs `..._total_extra`, which must not be
double-counted), an **empty `before` snapshot** (the `FNR == NR` idiom read it as the baseline), and an
unreadable bracket (must render `NA`, never `0` — a zero is a measurement, `NA` is its absence).

**Final state.** `bash -n` clean everywhere; six checks green (19, 312, 824, payload skeleton
unchanged, stop-scope, knobs); `golden-check.sh` 17 PASS / 0 FAIL / 2 WARN on all three nodes; PIDs
**17752 / 3399 / 14799** unchanged, no service touched, no node-side temp files left. Existing passes
untouched, per the standing rule.

Full record: `evidence/2026-09-28/risk-probes/tiered-and-retention/` — `probe-gen-tokens.sh`,
`probe-gen-distribution.sh`, `analyse-tiers.py` + `analyse-tiers.txt`, `v10-*.log` + `-hf.tsv` (four
regimes + the rotation), `v8-*.log` + `-hf.tsv` (the first tiered runs on v8 bytes — where the slope
anomaly first appeared, before the length was a published column), `v11-CONFIRM-identique-4-48.*`,
`superseded/v9-*` (whose "requested ceiling" column is the false one),
`superseded/probe-gen-tokens*.log` (the two probe outputs from *before* the fixes, kept because that is
where the defects were seen), and the superseded instrument bytes
`superseded/gpu-bench-node.sh.{c79920c4,1ed6ae30,1c0c0871,a192a89f}` (v7, v8, v9, v10 — taken from
the on-node backups, since the repo file is overwritten in place).

#### Fourteenth pass, same day — the cache retains nothing, and the working set is what costs reuse

The thirteenth pass varied **concurrency** at a fixed prefix working set (32), so two causes stayed
fused: does reuse fall because the working set **grows**, or because free room **shrinks**? This pass
does the inverse — **concurrency fixed, working set varied** — via a new knob.

**1. `VARIANT_COUNT=N` (v12).** Limits the variants actually put in circulation to the **first N** in
sorted file order: a set that changed run to run would make the curve depend on *which* images were
drawn rather than *how many*. `check-bench-variants.sh` now asserts exactly that the N-set is an
**ordered subset** of the full set (by comparing the hashes of the constructed bodies), that
`VARIANT_COUNT=1` is legal (one prefix under rotation *is* the shared-prefix regime, with the same
mechanism — a control point, not a broken case), and that out-of-range values are refused loudly.

**2. The hit-rate ceiling is not 100 %.** A prefix is made of **whole blocks**, so the prompt's **last,
incomplete block can never be served from cache**. The ceiling is `(P − 16)/P`, and with `P = 832`
measured that is **98.08 %** — to the digit the number earlier passes published as "the prefix-cache
reuse rate". It must be read the other way round from what was implicit: **98.08 % is what *perfect*
reuse looks like**, not 98 % of perfect. Control measurement: at `V=1`, `c=8` the cache serves
**816.00 tokens of each request's 832** (52 of 53 blocks), and every request queries **832.00** tokens —
both exact over 360 requests.

**3. At fixed concurrency, occupancy saturates exactly when the working set reaches the concurrency.**

| set V | c=4 KV peak | c=4 hit | c=8 KV peak | c=8 hit | c=8 /ceiling |
|---|---|---|---|---|---|
| 1 | 13.23 % | **97.08 %** | 17.46 % | **98.08 %** | 100.0 % |
| 2 | 22.22 % | 95.67 % | 26.46 % | 97.26 % | 99.2 % |
| 4 | **39.44 %** | 95.73 % | 42.43 % | 96.73 % | 98.6 % |
| 8 | 39.26 % | 88.03 % | **77.99 %** | 95.19 % | 97.1 % |
| 12 | 39.33 % | 77.51 % | 77.46 % | 84.35 % | 86.0 % |
| 16 | 39.15 % | 77.64 % | 77.60 % | 85.77 % | 87.5 % |
| 24 | 39.15 % | 72.42 % | 76.94 % | 82.14 % | 83.8 % |
| 32 | 38.98 % | 67.39 % | 77.60 % | 78.17 % | 79.7 % |

Occupancy rises to `V = c` and then **stops moving** (39.2–39.4 % for all `V ≥ 4` at c=4; 76.9–78.0 %
for all `V ≥ 8` at c=8): at most `c` prefixes are in play at once, and adding prefixes beyond that does
not fill the cache — it only costs reuse. **Reuse keeps falling *after* occupancy stops moving**
(98.1 → 95.2 → 78.2 % at c=8), which is the answer the previous pass could not give: it is the size of
the working set, not the occupancy, that costs reuse. Throughput follows: 20.3 req/s at `V=8`, 13.0 at
`V=32`.

**4. The cache keeps nothing from a finished request.** Same load, same 32-prefix set, 60 s, only
concurrency differs:

| | c=1 | c=4 |
|---|---|---|
| requests | 132 | 476 |
| KV peak | **10.05 %** (57 blocks) | 39.33 % (224 blocks) |
| prefix-cache hits | **0.00 %** (0 of 109 824 tokens) | **74.22 %** |

At `c=1` one worker cycles all 32 images, so each image is re-requested 32 requests later — and the hit
rate is **exactly zero**. A finished request's prefix blocks are **not** retained; the KV cache holds
only what the live requests hold (57 blocks = 52 of prompt + `ceil(50.79/16)+1 = 5` generated = 912
tokens = 10.02 % of 9 104, measured 10.05 % — the twelfth pass's law, verified again at c=1). At c=4 the
same set hits 74 %: the reuse comes from **neighbouring** workers handing the same prefix to each other,
not from a durable cache. That is the mechanism missing from the twelfth pass: the "~10 distinct-prefix
requests" limit is not the size of a persistent cache, it is the number of **simultaneous holders** the
room allows. A distinct prefix is free only if another **live** holder already has it.

**5. A correction to the thirteenth pass, dated rather than rewritten.** §12.3 counted "retained
prefixes" as `(KV blocks − generated blocks)/52`, found 9.5, and read it as the same number as the 10.4
admitted requests. That count in fact returns **always ≈ the concurrency** (1.9 at c=2, 3.7 at c=4, 5.5
at c=6, 7.4 at c=8, 9.1 at c=10) — an **identity**, not an independent confirmation, and §13.4 is why.
What still holds from §12.3: the ~10 admission limit (read from the admission gauges, where `running`
pins at 10 while `waiting` grows, not from that count) and the direct cost of a distinct-prefix request
(872 tokens = 54.5 blocks, so 569/54.5 = 10.4 places). Both stand; their *agreement* meant nothing.

**Left open, and written as such.** The strict accounting leaves a residue of ~2.4 prefixes above the
live set at c=4 and ~2.5–4.7 at c=8. These instruments do not separate "a few recently-freed prefixes
stay cached" from "the scheduler's accounting includes a margin". The published figure is the measured
peak; the mechanism behind the residue is **not** settled.

**Instrument.** `node_gpu_bench.sh` is now **v12 (`28cc7563bd06c350`)**; v11 (`cba1d4bb`) preserved in
`superseded/`. Final state: `bash -n` clean; six checks green (the knobs check now carries 11 sections
including the ordered-subset assertion); stub harness untouched nodes; `golden-check.sh` 17 PASS / 0 FAIL
/ 2 WARN on all three; PIDs **17752 / 3399 / 14799** unchanged.

Full record: `evidence/2026-09-28/risk-probes/tiered-and-retention/working-set/` — 18 fixed-concurrency
sweeps (`v12-c{1,4,8}-V*.log` + `-hf.tsv`, two at 60 s) and `analyse-working-set.py` +
`analyse-working-set.txt`.

### Fifteenth pass — the neighbour-handoff explanation is FALSIFIED, and §13.4 was wrong

This pass set out to falsify the mechanism the fourteenth pass proposed — "reuse comes from a
**neighbouring live worker** handing the same prefix on" — by staggering the workers so that no two can
ever hold the same prefix at once (`VARY_STRIDE=S`, and `S = W` = concurrency per node). It achieved the
stagger, and the hit rate did collapse to **exactly 0.00 %** at `S = W`. **But that zero does not have the
cause it looked like**, and the matched control below shows why. Two of the fourteenth pass's sentences
have to go: *"the cache keeps nothing from a finished request"* is **false**, and *"the neighbour
explanation is not falsified"* is **false** as a mechanism.

**The control.** `S = W` with `V = W` makes each worker's body constant — `(bw + W·i) mod W = bw` — so
every worker re-asks **its own** prefix back-to-back and **no two workers ever share one**. The carrier
hypothesis predicts zero. It measures 95.8 %.

| regime | cross-worker sharing | set V | **hit rate** | KV peak | throughput |
|---|---|---|---|---|---|
| c=4, V=4, S=4 | **none** | 4 | **95.81 %** (207 264/216 320) | 39.08 % | 12.9 req/s |
| c=4, V=32, S=4 | **none** | 32 | **0.00 %** | 39.15 % | 3.6 req/s |
| c=8, V=8, S=8 | **none** | 8 | **95.46 %** (357 408/374 400) | 77.60 % | 21.4 req/s |
| c=8, V=32, S=8 | **none** | 32 | **0.00 %** | 77.25 % | 3.7 req/s |

Two rows share nothing and hit 95 %; two share nothing and hit nothing. **Sharing is not the variable.**
The only difference is the size of the working set. The orthogonal control agrees: at a fixed set of 4,
going from maximal sharing (`S=1`, 95.73 %) to **zero** sharing (`S=4`, 95.81 %) changes nothing.

**The real law — reuse distance against capacity.** At `c=1` no sharing is possible at all, so the only
variable is the **reuse distance** (how many distinct prefixes are asked between two uses of the same
one). The KV cache is **9 104 tokens = 569 blocks**; one prefix costs **832 tokens = 52 blocks** exactly,
so the predicted threshold is `569/52 = 10.94` prefixes.

| c | set V | duration | requests | blocks in the set | **hit rate** |
|---|---|---|---|---|---|
| 1 | 1 | 50 s | 137 | 52 | **97.36 %** (110 976/113 984) |
| 1 | 4 | 20 s | 71 | 208 | **98.08 %** (57 936/59 072) |
| 1 | 8 | 20 s | 76 | 416 | **98.08 %** (62 016/63 232) |
| 1 | 9 | 60 s | 216 | 468 | **98.08 %** steady (§17) |
| 1 | 10 | 60 s | 218 | 520 | **98.08 %** steady (§17) |
| 1 | 11 | 60 s | 170 | 572 | **34.62 %** steady (§17) |
| 1 | 12 | 60 s | 150 | 624 | **0.00 %** steady (§17) |
| 1 | 16 | **50 s** | 124 | 832 | **3.95 %** (4 080/103 168) |
| 1 | 32 | 60 s | 132 | 1 664 | **0.00 %** (0/109 824) |

**Provenance.** Eight of these rows were measured in this pass on the **v13** bytes (`89f87d93`); the
`V=32` row is reused from the thirteenth pass (`working-set/v12-c1-V32-long.log`, v12 bytes `28cc7563`)
because it closes the curve. The knob it exercises — one worker, `VARY_ROTATE` with `VARIANT_COUNT=1` —
is identical in v12 and v13. The `S=1, 95.73 %` point above is likewise from that pass. Those are the only
points borrowed from earlier bytes, and a curve with a borrowed point is only comparable if that is said.

The threshold falls **between 8 and 16 prefixes** on these five points; the dedicated trace below narrows
it to **between 10 and 11**, as `569/52 = 10.94` predicts. The totals decompose
request by request and exactly: at `V=1` over 50 s, `110 976 = 136 × 816` — **136 of 137 requests hit
816 of the 832 tokens**, i.e. the structural ceiling, with the 137th being the cold first request. At
`V=16` over 50 s, `4 080 = 5 × 816`: **5 of 124**, the tail of the start-up.

**So the corrected mechanism is: a prefix is reused iff its blocks are still cached when it is asked
again — i.e. iff its reuse distance stays under the 569-block capacity.** Not "who else holds it"
(§14, false) and not "nothing is retained" (§13.4, false). The fourteenth pass's `c=1` (0 %) vs `c=4`
(74 %) contrast at a 32-prefix set compared a reuse distance of 32 prefixes against one of ~1–4; it did
not compare "no memory" against "hand-off".

**A measurement trap found in this pass.** The same `c=1, V=16` point reads **38.86 % over 20 s** and
**3.95 % over 50 s**. Both are exact; the short run inherits the **pre-warmed cache** left by the
previous run, which 20 s does not flush. Short runs can therefore **overstate** reuse. Every point
carrying a conclusion above was re-run at 50–60 s; the 20 s runs are used only as **paired** comparisons
(same duration, same starting cache), where the bias cancels.

**What survives, untouched.** The structural ceiling `98.08 % = (P−16)/P` with `P = 832` (verified here
twice, exactly); the 832-token / 52-block cost of a distinct prefix; the KV peak's invariance under a
change of sharing (38.80 / 39.15 / 38.91 / 39.15 % at `c=4`; 77.46 / 77.25 % at `c=8`); and occupancy
saturating at `V = c`.

**The threshold, measured (`SUMMARY.md` §17).** First *bracketed* between 8 and 16 prefixes, now traced to a
single step: it falls **between `V=10` (98.08 %, the exact structural ceiling) and `V=11` (34.62 %)**,
against `569/52 = 10.94` predicted. The raw run averages were **non-monotonic** (`V=9` read *lower* than
`V=10`) — the warm-cache inheritance of the paragraph above, here quantified at +6.8 pp for `V=9` and
+9.7 pp for `V=11`. Only the **marginal** hit rate per time window, taken from the high-frequency
sampler, resolves it (`analyse-knee.py`). A side finding: `V=11` exceeds capacity by just **3 blocks of
569** and still loses about two thirds of its reuse — the over-subscription penalty is steep and
non-linear, and stable across windows (31–35 %), so it is the system's behaviour and not measurement
noise.

**The eviction order — resolved from the source, and confirmed by the plateau (`SUMMARY.md` §18).**
"Strict per-block LRU or free-queue FIFO" was a **false dichotomy**: vLLM 0.29.0 has one policy — LRU on a
FIFO queue. `block_pool.free_blocks()` appends **hashed** blocks to the tail (*"FIFO reuse of cached
blocks for LRU eviction behavior"*) and prepends unhashed ones (*"LIFO reuse of non-cached blocks for
better GPU locality"*); `touch()` removes a block from the free queue on a cache hit — that removal *is*
the LRU promotion; `get_new_blocks()` pops from the head and drops each block's hash, which is the
eviction. Within one request all prompt blocks are touched at the same instant, so LRU cannot order them
and the tie is broken by the free-list order — which the scheduler deliberately reverses
(`_drain_deferred_frees`: `free_blocks(reversed(blocks))`, *"so that the tail blocks are evicted first"*).

That is testable, and it is tested. Cached tokens per request in the steady window (`prompt_tokens_cached_total`)
come out as **exact integers of blocks** — 816.0 (51 blocks) at `V=9`/`V=10`, **288.0 (18 blocks)** at
`V=11`, 0 at `V=12` — and prefix matching always starts at block 0, so the `V=11` plateau is a
**contiguous 18-block head**, not a scattered set. An eviction that removed the *earliest-used* block
first would break that match at block 0 and give **exactly 0**, as at `V=12`. So the instruments *do*
separate the orders, and they point to the same thing the source says. The plateau was never a mystery:
it is the signature of tail-first eviction.

**Instrument.** `node_gpu_bench.sh` is now **v13 (`bbf72aa8f09d4767`)**, adding `VARY_STRIDE`; v12
(`28cc7563`) preserved in `superseded/`. The runs in this section were taken on the preceding v13 bytes
`89f87d93`, which differ from the deployed file **only by the v12/v13 ledger comment** added to the
header afterwards (`bash -n` clean, no behaviour touched) — those bytes are preserved in
`tiered-and-retention/superseded-late/`. The same pass wrote the two missing ledger entries into the
header, which is why the hash moved: the ledger had stopped at v11 while the file already carried the
v12 and v13 knobs. The same pass fixed a defect in the
offline check: section 9 of `check-bench-variants.sh` piped its geometry through a **pipe**, so a section
that aborted mid-way published neither OK nor FAIL — `FAIL` stayed 0 and the script printed
`VERDICT : OK` over controls that had **not happened**. It now writes to a file and checks the section's
return code, with a negative control (an injected abort yields a named `ECHEC` and exit 1).

Full record: `evidence/2026-09-28/risk-probes/SUMMARY.md` §14 (the stride run) and §15 (the falsification
and the corrected law); data in `tiered-and-retention/stride/` and `tiered-and-retention/selfhold/`.

### Maintenance actions, same day — the deep tier now passes, and two items leave the "still open" list

This updates the **"Still open"** list above (which says the `@reboot` trigger needs an authorised reboot,
and that `--deep` and V12 both need a window where the service may stop / the network may be cut). Two of
those three are now settled, and the third is settled differently than expected. Full detail:
`evidence/2026-09-28/risk-probes/SUMMARY.md` §18–§19.

**`golden-check.sh --deep` — DONE, and it passes.** The deep tier starts its own engine, so it needs port
8000 free; the fast tier's `[WARN] port 8000` is permanent while the service runs and its text says the deep
test will fail. Run on **zabeth22 only**: service stopped (`SIGTERM` to the group, port freed, **VRAM back to
38 MiB**), then

```
20 PASS   0 FAIL   1 WARN      (21 checks)
RESULTAT : NOEUD DORE
```

with `[PASS] G3 (deep) identification en 1.49 s` and `[PASS] G4 (deep)` returning valid JSON
(`{"brand": "TP-Link", "model": "TL-WR841N", "category": "router_ap"}`), and — the point of the exercise —
**`[PASS] port 8000 libre`** in deep mode, which proves the permanent WARN was the running service and
nothing else. The service came back `PRET en ~55s`; the fast tier then read 17/0/2 again.

**A restart was made, deliberately, so the PID lines change.** zabeth22 went **3399 → 12582**. Every
earlier "PIDs unchanged" statement in the passes above is true of the moment it was written and must not be
read as true now: zabeth21 (**17752**) and zabeth23 (**14799**) are untouched; zabeth22's current PID is
**12582**.

**`@reboot` — the body is verified on all three nodes; only the trigger is left, and it needs root.**
`@reboot` jobs run when the **cron daemon** starts, not only at machine boot, so a `cron restart` would
exercise the line without rebooting — and `vllm-autostart.sh --run` refuses to touch a live service
(*"service deja en cours — rien a faire"*), so the test cannot disturb anything. But `msalhi` (uid 10131)
has **no root**: `sudo` wants a password and even `kill -HUP` on cron returns `Operation not permitted`. What
*is* testable was tested: the exact crontab command, run in **cron's own minimal environment**
(`env -i` with only `HOME`, `LOGNAME`, `PATH`, `SHELL`), on zabeth21/zabeth22/zabeth23 → **rc=0 on all
three**, each appending `==== autostart -- <node> -- debut ====` and then declining to act. So the job body
is sound; what remains unproven is one line of cron's own behaviour. To close it, as root:

```bash
/etc/init.d/cron restart   # then: tail -1 ~msalhi/logs/vllm-autostart.log
```

**V12 egress — not a window problem: it is out of reach of this access.** `nft` is installed (`/usr/sbin/nft`)
and so is `iptables`, but **applying rules requires root**, which is exactly what we do not have. It is also
the one test of the three that could cut the ssh path itself if the bastion is not on the LAN, so it was not
attempted. It needs root on the node, with a scheduled rollback so access returns even if the rest fails.

> **THIS PARAGRAPH IS SUPERSEDED.** It was true of the access available then, not in itself. With the node
> password, V12 ran on 2026-09-29 — see the section below.

### Maintenance actions, 2026-09-29 — V12 executed, and a network co-tenant found on zabeth22

The node password was supplied; `sudo -l` gives `(ALL : ALL) ALL`. All three gated items are now closed,
and closing V12 turned up something that had nothing to do with V12. Full detail:
`evidence/2026-09-28/risk-probes/SUMMARY.md` §20.

**V12 — DONE, and it passes the clause that carries the claim.** Ran on zabeth22 against the deployed
bytes, with a **separate** `inet v12` table (never a global flush), detached, self-reverting, a detached
rollback armed first, payload 52 170 bytes of real image:

| step | rules | egress to `example.com` | inference |
|---|---|---|---|
| witness, before any rule | none | `http=200` | `http=200` t=1.909 s |
| **phase 1 — the SPEC's letter** | `drop`; allow `lo` + `172.26.145.0/24` | **`http=000`** | **`http=200` t=1.089 s** |
| **phase 2** | `drop`; + admin `172.26.16.4` | **`http=000`** | **`http=200` ×3** — 1.0885 / 1.0855 / 1.0854 s |
| rollback | table deleted | `http=200` | `http=200` t=1.086 s |

19/19 requests `200`, at steady-state latency. The rules used are **stricter** than the dossier's
(`docs/06 §11.2` allows `172.26/16` + campus DNS; this allowed only the node's own `/24` + loopback), so
campus DNS and NTP were blocked as well — and inference held anyway.

**The dropped-packet counter, and what it does *not* say.** The output hook drops non-LAN packets in every
window, idle included. Four equal 20 s windows, alternating idle/inference, run twice:

| run | idle | inference | idle | inference |
|---|---|---|---|---|
| 1st | 16 pkt | **234 pkt** | 27 pkt | 11 pkt |
| 2nd (with bytes) | 11 pkt / 900 B | 7 pkt / 564 B | 7 pkt / 914 B | 20 pkt / 2 514 B |

The two inference windows are identical in every respect (18–19 requests, all `200`) and give **234 then
7** — and in run 2 the inference window is *below* the idle window. **The inference path is not the
source.** Mean packet size **81–131 bytes**, where one leaked photo would be ~1 400-byte packets: **no bulk
payload was attempted.** Destinations are campus infrastructure (`172.26.189.28`), a few IPv6 addresses,
mDNS (`224.0.0.251`, `ff02::fb`) and SSDP (`239.255.255.250`) — and in the burst, `100.100.100.100` and
`fd7a:115c:a1e0::53`, which is **Tailscale's resolver**.

So the SPEC §9 V12 criterion reads *"inference completes; **0 packets to non-LAN IPs**"*. The first clause
is **met and measured**; the second is **false at the output hook** — but the traffic is host background,
not inference, and carries no payload.

**What the background turned out to be: a third-party co-tenant, now on a second node.** zabeth22 runs
`tailscaled` (PID 5281, `tailscale0` = `100.68.110.75/32`), its `/etc/resolv.conf` is **generated by
Tailscale**, and it carries **12 `ts-*` chains / 91 rules** — zabeth23's exact profile. Same tailnet
(`tail5481a4.ts.net`), same owner (`another cluster user`). `/etc/init.d/tailscale` on z22 is
dated **2026-09-24 21:08**. **zabeth21 is clean.** The 2026-09-16 conformity note declared *"zabeth21 and
zabeth22 are free of any network co-tenant"* — true then, **false since 2026-09-24** — and that note's
recommended Option B ("keep z21 + z22, the two clean nodes") would now keep the contaminated one. See
`cahiers/NOTE-CONFORMITE-z23-tailscale.md` §7.

**Why nobody saw it: the certification tool could not.** `golden-check.sh` had 19 checks and none asked
"who else writes on this machine" — so a node could read `NOEUD DORE` with a third party rewriting its
resolver. Fixed with a `souverainete reseau` sensor (7 VPN daemons, 4 tunnel interfaces, resolver
authority). **WARN, not FAIL, deliberately:** SPEC §6 states outright that reachable egress is the expected
permanent state, and G9 only asks that inference survive the block — which it does. No written invariant
forbids a co-tenant, so a FAIL would be an invented requirement. But the WARN **names** it.

Deployed to all three nodes, sha `6bec2aae…` **identical to the repo** (previous build `207304b5…`,
12 581 → 14 325 bytes):

| node | `souverainete reseau` | fast total |
|---|---|---|
| zabeth21 | **PASS** — no third-party VPN daemon, resolver not diverted | 18 PASS / 0 FAIL / **2 WARN** (20 checks) |
| zabeth22 | **WARN** — `co-locataire tiers: tailscaled iface: tailscale0 -- resolver tiers: oui` | 17 PASS / 0 FAIL / **3 WARN** (20 checks) |
| zabeth23 | **WARN** — same | 17 PASS / 0 FAIL / **3 WARN** (20 checks) |

The sensor's proof of function is not an injected test: it is **the cluster itself** — passing on z21 and
firing on z22 and z23. The deep tier was **re-run on the new build** so the published number matches the
deployed tool:

```
20 PASS   0 FAIL   2 WARN      (22 checks)      RESULTAT : NOEUD DORE
[PASS] port 8000      libre          <-- the permanent WARN was the service and nothing else
[PASS] G3 (deep)      identification en 1.48 s
[PASS] G4 (deep)      {"brand": "TP-Link", "model": "TL-WR841N", "category": "router_ap"}
```

**PIDs again.** zabeth22 was deliberately restarted a second time for that rerun: **12582 → 15680**.
zabeth21 (**17752**) and zabeth23 (**14799**) untouched.

**A hazard the dossier already documents.** `docs/06 §11.2` gives `nft flush ruleset` as V12's rollback —
the exact command that destroyed the third party's 91 rules on z23 on 2026-09-16. **Re-running that
documented procedure on zabeth22 today would repeat the incident**, since z22 now carries the same 12
chains. The V12 tools of this pass flush nothing: separate `inet v12` table, atomic `nft -f`, delete that
table only. After the tests: `tables inet v12 = 0`, **12 `ts-*` chains intact, 91 rules**. A non-atomic
first version was caught and fixed too — it raised the `policy drop` chain *before* its rules, so a mid-load
failure would have left the node dropping everything, with no way back.

**Still open:** the 234-packet burst is unexplained (not reproduced, not from inference; naming the emitting
process needs a `th dport` capture), and the golden-perimeter decision is now genuinely open — Option A
(purge), Option B revised (which leaves **z21 alone**), or explicit acceptance with a WARN. That is a
dossier decision, not a measurement. One more honest gap: `v12-egress-idle.sh` on the node is
`a21b8671…` (the version that ran) while the repo holds `6896a830…` (verdict corrected to refuse to
conclude) — a documented divergence, not a hidden one.

### Purge, 2026-09-29 — Option A executed, and the control that was missing

Decision: **purge**. Executed on zabeth22 and zabeth23 at 00:59 with root on the node, via a versioned,
**reversible** tool `purge-tailscale.sh` (sha `25dc1597c76b1f16`, repo and node identical), which backs the
prior state up to `/root/tailscale-prestate/` before `tailscale down`, stopping the service, and removing the
`rc*.d/S07tailscale` links. Full detail: `evidence/2026-09-28/risk-probes/SUMMARY.md` §21 and the conformity
note §8.

| fact | z22 before | z22 after | z23 before | z23 after |
|---|---|---|---|---|
| `tailscaled` | PID 5281 | **absent** | PID 3106 | **absent** |
| `tailscale0` | `100.68.110.75/32` | **absent** | `100.107.89.44/32` | **absent** |
| `/etc/resolv.conf` | Tailscale (`100.100.100.100`) | **campus** (`172.26.188.12`) | Tailscale | **campus** |
| nft `ts-*` chains | 12 (91 rules) | **0** | 12 | **0** |
| iptables rules | 91 lines | **0** | 91 | **0** |
| `rc*.d` symlinks | 4 | **0** | 4 | **0** |

resolv.conf was **not** hand-written: `tailscale down` restored it, and the result is zabeth21's file — the
node that was never contaminated. Six autostart mechanisms were checked (rc links, `inittab`, `rc.local`,
cron, systemd units, shell profiles): **zero** occurrences left. Not done, deliberately: the **package was
not uninstalled** (Option A was "disable the daemon"; disabling removes the fact and stays reversible for its
owner) and **`avahi`/`ntpd` were left alone** — they run on all three nodes including the clean reference, so
they are part of the golden baseline. Restoration is one line, recorded in `/root/purge-tailscale.log`.

**And the purge supplied the control the attribution could not build.** Same host, same deployed bytes, same
test — only co-residency changed:

| run | idle | inference | idle | inference | total |
|---|---|---|---|---|---|
| before (1st) | 16 | **234** | 27 | 11 | 288 |
| before (2nd) | 11 | 7 | 7 | 20 | 45 |
| **after** | **1** | **0** | **0** | **6** | **7** |

The surviving destinations are **link-local multicast only** (mDNS `224.0.0.251` and `ff02::fb`,
`224.0.0.106` and `ff02::6a`, IPv6 neighbour discovery `ff02::1:ff…`) — traffic z21 emits at rest too. The
234-packet burst **disappeared with the co-tenant**. So the pre-purge non-LAN traffic was the third party's,
and **inference emits zero non-LAN packets** — ENF1/P4 in its strongest form: not "it completes anyway" but
"it does not leave".

**A probe defect, found and fixed the same hour.** The canonical V12 run at 01:02 printed `http=000` at the
rollback, where 00:21 had printed `200`. Cause: **`nscd` runs on this node and caches resolution failures** —
a probe taken during or just after the block is served the negative answer in ~30 µs with no packet at all,
indistinguishable from a firewall refusal. The host was fine (`iptables` empty, no `v12` table, DNS 2 ms,
egress 37 ms). The defect was in *my probe*: one named request cannot separate "blocked" from "resolver
cache". It now makes **two** probes — a name (which goes through DNS) and a **bare IP with no DNS**; under a
`drop` policy both expire. The diagnostic also carries an **invalidation guard** that refuses to measure if
the block does not bite. That guard exists because an earlier version ran with `TABLE=inet v12` unquoted:
bash assigned `inet` and ran a command called `v12`, **no rule was ever applied**, and it still produced a
complete table of numbers — every one of them `200`, including in the section where `000` was required. A
vacuous measurement presented as a result; the tell was a value that was *impossible* in the control row.

**Certified state after purge:**

| | zabeth21 | zabeth22 | zabeth23 |
|---|---|---|---|
| `souverainete reseau` | **PASS** | **PASS** | **PASS** |
| fast tier | 18 PASS / 0 FAIL / **2 WARN** (20 checks) | 18 / 0 / 2 | 18 / 0 / 2 |
| deep tier (z22) | — | **21 PASS / 0 FAIL / 1 WARN** (22 checks) | — |
| service / `/health` | 17752 / 200 | 18329 / 200 | 14799 / 200 |

> **Superseded 2026-09-29 01h56** — the deep-tier pass below restarted **every** node: see
> "Maintenance actions (01h56)". Current PIDs are **22643 / 24616 / 23973**, and any earlier "unchanged
> throughout" statement is now false for all three, not just z22.

**The three nodes are homogeneous again, for the first time since 2026-09-16** — same 20 checks, same
verdict, no co-tenant. **Option B is moot**: there is no node left to exclude. The one remaining WARN is
`egress — internet JOIGNABLE`, which SPEC §6 itself calls the expected permanent state.

**Still open:** the *process* behind the 234-packet burst was never named by port capture (the *class* is
explained, the emitter is inferred); and the service has **not** been cold-started with egress cut — we know
inference needs no egress, not that the node can *boot* its service offline.

> **Both are closed, and the second one was closed wrongly — see the 03h section below.** The emitter is
> now named by **uid**, not inferred, and the sentence *"the service emits nothing off-LAN"* turns out to be
> true only of a **warm** service: a cold start does emit, as the service's own uid. The two claims below
> stay as they were written.
> **The second item is closed — see "Maintenance actions, 2026-09-29 (02h)" at the end of this file and
> `evidence/2026-09-28/risk-probes/SUMMARY.md` §22.** The service was cold-started under the cut, and then
> the **whole reboot scenario** was played: the real `@reboot` trigger, internet cut, trigger → inference.
> A node that reboots with no internet **does** bring its service up and serve (~20 s identity cost once).

One residual asymmetry, recorded rather than glossed over: the **package files remain on disk**
(`/usr/sbin/tailscale`, `/usr/sbin/tailscaled`, `/etc/init.d/tailscale`, and the `iptables` package that came
with them) on z22 and z23, and **not on z21** — which is why an `iptables-save` exists on two nodes and not
the third. It is **inert** (0 `-A` rules on all three, 0 `ts-*` chains, 0 daemons). So "the three nodes are
homogeneous" is true **in behaviour and verdict**, not yet in on-disk contents; an uninstall would close
that last gap.

### Maintenance actions, 2026-09-29 (02h) — a node that reboots with no internet still serves

Closes the last open item above. Three instruments, all in
`evidence/2026-09-28/risk-probes/tiered-and-retention/`, each self-validating (it refuses to conclude unless
the block actually bites) and self-reverting, with a detached backstop armed by the caller.

**`coldstart-egress.sh`** — the service started by hand, egress cut: `/v1/models` **200**, a real inference on
a 52 170-byte image **200 in 1.88 s**, both guard probes silent. **But my first reading of its own log was
wrong**: it printed *"durée jusqu'à disponibilité : 91 s"* against a ~55 s no-cut reference, and I attributed
the difference to the service. The timestamps contradict that — starter banner 01:25:58, first 200 01:26:53 →
**55 s, the reference exactly**. The missing ~36 s sit *before the starter's first word*, in the launch
wrapper, and are not the service's time at all.

**`nss-under-cut.sh`** — names it. The wrapper is `setpriv --init-groups`, and `initgroups()` is a **group
enumeration**. Under the cut (same policy as the cold start; the admin path is re-admitted here because the
question is a *timing*, not an isolation — which cannot make an NSS call faster):

| call under the cut | nscd cache warm | nscd cache invalidated |
|---|---|---|
| `getent passwd msalhi` / `getent group msalhi` / `id -G` / local control | 8 / 8 / 9 / 7 ms | 7 / 7 / 6 / 5 ms |
| **`getent group` (enumeration)** | **20 006 ms** | 5 ms |
| **`setpriv --init-groups true` (the wrapper)** | **15 085 ms** | 8 ms |

The cause is named and pre-existing: `group: files ldap` + `nslcd 0.9.13`, and **`172.26.189.28:389` is the
LDAP server** — five `ESTAB` sockets to it, and the same address/port appears in a **2026-09-14**
investigation. So the stall is a **one-time cost paid by the first identity lookup after connectivity is
lost**, not a persistent degradation. **Operational consequence:** `cron` calls `initgroups()` *before*
forking an `@reboot` job, so on a real reboot this delay lands on the daemon, not on the service.

**`reboot-sim-egress.sh`** — the whole scenario, with the **real trigger**: service stopped (as after a boot),
internet cut, then cron itself fired `@reboot` (marker + daemon restart; cron recreates the marker, so real
reboots remain correct).

```
01:37:07  cron[22342]: (CRON) INFO (Running @reboot jobs)     <-- triggered
01:37:27  ==== autostart -- zabeth22 -- debut ====             <-- the job writes
01:38:21  (APIServer pid=22488) Application startup complete.
```

| segment | measured | whose time it is |
|---|---|---|
| trigger → job's first line | **20 s** | the daemon + the identity switch above |
| job → model ready | **55 s** | **the service** — the reference |
| **total** | **75 s** | |

Inference under the still-active cut: **200 in 1.86 s**, PID **22488**, `wait_gpu` and `wait_net` both `~0s`.
So **yes — a node that reboots with no internet brings its service up and serves**, at a ~20 s identity cost,
once.

The one line that could have answered *"no"*: `vllm-autostart.sh`'s `wait_net()` waits on
`ip -4 -o addr show scope global` — the **presence of an interface address** (local), not connectivity. Had
it pinged or resolved a name, `@reboot` would have failed in exactly the case being tested.

Of the 29 non-LAN packets during the boot, every address is attributed except two: `1.1.1.1` and the four
Cloudflare addresses are **my own guard probes** (`example.com` resolves to exactly those four),
`172.26.188.12` / `193.48.57.48` are the node's own resolvers, `172.26.189.28` is LDAP. Two residential
addresses remain unexplained; best-supported reading is replies to sporadic inbound connections, since
`INPUT` is `ACCEPT` and two services listen on all interfaces (below). **The vLLM service holds no outbound
socket at all** — off-loopback only `nslcd`→LDAP ×5 and my own ssh appear.

Recorded, not pursued: **`x11vnc -autoport 5900 -nopw`** (VNC, *no password*) and SANE `*:6566` listen on
**all interfaces — identically on all three nodes**, so this is the installation state, not drift, and not a
consequence of this session. The one service SPEC §12.3 constrains (vLLM) binds `172.26.145.7x:8000` on all
three.

**Still open afterwards:** the two residential addresses; the 234-packet emitter; tailnet restoration.

> **Superseded by the 03h section below:** the two residential addresses are **ntpd's peers** (port 123, uid
> 0 — `ntpq -pn` names 82.66.203.162, 109.190.177.205 and 109.190.177.203), and the emitter is named and
> switched off. **Tailnet restoration** is the only one still open.

### Maintenance actions, 2026-09-29 (01h56) — the deep tier on all three nodes

The homogeneity claim ("the three nodes satisfy G1–G10") rested on a **deep** run on **one** node (z22); the
fast tier builds no engine, so it says nothing about G3/G4. `deep-tier-all.sh` (sha `eb5a81802b07`, identical
on the three, run in parallel, same build `6bec2aaef3fc75f6`) closes that:

| | z21 | z22 | z23 |
|---|---|---|---|
| verdict | **21 PASS / 0 FAIL / 1 WARN (22 checks) — NOEUD DORE** | same | same |
| `G3 (deep)` | 1.49 s | 1.47 s | 1.49 s |
| `G4 (deep)` | valid JSON | valid JSON | valid JSON |
| duration | 58 s | 58 s | 57 s |
| PID after restart | **22643** | **24616** | **23973** |

The only WARN is the same on all three (`egress — internet JOIGNABLE`, which SPEC §6 itself calls the
permanent expected state). **The identical G4 output** — `{"brand": "TP-Link", "model": "TL-WR841N",
"category": "router_ap"}`, character for character on the same image — is a behavioural equivalence, not
three ticks in a box: same model, same weights, same quantization, same answer.

The tool header says "~3 min"; measured here it is **57–58 s**, because the header describes the cold first
run. The **uniformity** is the result.

Run as **`msalhi`**, not root: deep mode resolves the model through `$HOME/models/...` and the venv through
`$HOME`, so as root it would report a failure that says nothing about the node. Each node arms a detached
idempotent `start` **before** stopping and disarms it only once `health=200` is back — and since `start`
refuses to touch a live service, the net cannot flatter the result. Six logs (wrapper + raw, per node) in
`evidence/2026-09-28/risk-probes/tiered-and-retention/deep-tier-logs/`.

**Every PID changed, on all three nodes, deliberately** — one stop/restart each: 17752 → **22643**,
18329/22488 → **24616**, 14799 → **23973**. Earlier lines quoting any of those numbers are stale, including
the "unchanged throughout" statements.

### Maintenance actions, 2026-09-29 (03h) — the co-tenant leaves the disk, the emitter is named, and the identity path is bounded

Three requests: *remove tailscale — is it needed?*; *fix or remove the packet emitter*; *settle the identity
path*. Answers below, each with its measurement. Full record: `evidence/2026-09-28/risk-probes/SUMMARY.md`
**§24**.

**Tailscale: no, it is not needed — and the certification tool says so itself.** `node_golden_check.sh`
carries the `souverainete reseau` sensor, which looks for `tailscaled`, five other VPN daemons, four tunnel
interfaces and a rewritten resolver, and raises a **WARN**. Its own comment fixes the authority: *"Aucun
invariant ecrit n'interdit un co-locataire."* Nothing requires it; the tool **detects** it. What was left was
not a package but a **hand-dropped set of three static binaries** (unowned by dpkg) plus, on z22/z23 only, the
`iptables` package that came with them. `remove-tailscale-final.sh` removed all of it, and the nodes are now
identical **in content**, not merely in verdict:

| | z21 | z22 | z23 |
|---|---|---|---|
| `tailscale`/`tailscaled` binaries | 0 | 0 | 0 |
| `iptables` package | 0 | 0 | 0 |
| nft tables / `iptables -A` rules | 0 / 0 | 0 / 0 | 0 / 0 |
| `souverainete reseau` | **PASS** | **PASS** | **PASS** |

One instrument defect fixed on the way: the first version split `ip filter` on whitespace, deleted `filter`
(the default `ip` family) and **left the three `ip6` tables** — while labelling them misleadingly in its own
log. Fixed per table, re-run. Restoration is one line, recorded in `/root/purge-tailscale.log`.

**The emitter had a uid, and the uid was the service's own.** `egress-attrib-uid.sh` records
*(destination · port · **emitting uid**)* for every packet that leaves the campus. Its first (strict) cut
allowed only loopback + LAN + admin — which **cut the directory**, because the directory is on the campus.
So window 2 died on `setpriv: uid 10131 not found`, the service was **never restarted**, and the log still
published a "window 2" with numbers in it. Admitting `172.26.0.0/16` makes the restart real, and the recorded
set keeps its exact meaning: **what leaves the campus**. With a real restart:

| run | window 2 (restart) | section "who is who" | total packets |
|---|---|---|---|
| **before**, 02h39:44 | `tcp6 2606:4700:3032::6815:58f5 . 443 . 10131` | `uid 0`, **uid 10131** | 34 |
| **after**, 02h48:08 | **no new tuple** | `uid 0` **only** | 24 |

All three nodes resolve `stats.vllm.ai` to **exactly** that address, and the package says it plainly:
`vllm/envs.py:36 VLLM_USAGE_STATS_SERVER = "https://stats.vllm.ai"`, `vllm/usage/usage_lib.py:268
client.post(_USAGE_STATS_SERVER, json=data)`. **vLLM posts a usage heartbeat at engine start, by default,
under the service's uid.** The fix is the package's own documented opt-out — `VLLM_NO_USAGE_STATS=1` in the
launch path of `node_vllm_service.sh`, plus `$HOME/.config/vllm/do_not_track` rewritten at each start (an
exported variable does not follow the user out of the script; the file covers a hand-run `vllm`). Verified
statically (`is_usage_stats_enabled()` → **False** on all three) and dynamically (the table above). Pinned by
`infra/selftest/check-no-vllm-telemetry.sh`, which carries a **negative control**: on a copy with the opt-out
removed, the analysis must fail. It is a **selftest, not an 11th gate** — the G-list belongs to the SPEC, and
inventing a G11 would move every published count.

**This corrects a published sentence.** §22's *"inference emits zero non-LAN packets"* was measured on a
service that had **already loaded its model**, i.e. in a window where the startup path never runs. The words
were wider than the measurement: true at rest and during inference of a warm service, false at cold start.

**Identity: the fault was in the *name*, not the account.** I had published that `msalhi` is a **local**
account. It is not — `grep -c '^msalhi:' /etc/passwd` is **0** on all three nodes; `getent passwd msalhi`
succeeds because `getent` consults the **directory**. Two consequences: `uri ldap://auth-v4.plil.info/`
needs **DNS** before the directory, and `nslcd`'s `timelimit` defaults to **0 = wait indefinitely**. Fix on all
three (revertible): `/etc/hosts` → `172.26.189.28 auth-v4.plil.info`, and `timelimit 5`,
`bind_timelimit 5`. Measured in three regimes:

| regime | cache | result |
|---|---|---|
| A — campus reachable (control) | warm / invalidated | 8–16 ms, `id=OK` |
| B — **DNS blocked, directory reachable** | warm | 8–13 ms, `id=OK` |
| B — same | **invalidated** | **9–15 ms, `id=OK`** ← DNS is out of the path |
| C — strict isolation | warm | `getent group` 16 024 ms, `id=OK` |
| C — strict isolation | **invalidated** | `getent passwd` 21 032 ms, **`setpriv --init-groups` FAILS** |

**Regime C took my access to the node, which is the most useful result of the night:** an `ssh` to z22
returned `msalhi@172.26.145.72: Permission denied (publickey,password)` — not a network failure (that times
out) but **sshd unable to resolve the account**. Recovery took ~75 s (`nscd`'s negative TTL), unattended. So
the §22 reboot proof was **cache-dependent**, and what is true now separates cleanly: with the directory up
(the real scenario — no Internet, campus standing) identity costs **milliseconds even from a cold cache**;
with the directory gone the service **cannot start as `msalhi`** and an administrator cannot log in as it.
The remedy that would close it — a local `msalhi` entry — **shadows the directory** under
`passwd: files ldap`, so a future LDAP change would silently stop applying. That is a decision about account
provenance, so it is named and not taken.

**Two things deliberately not done.** (1) The NVIDIA packaging really differs (`nvidia*`: **78 / 36 / 66**),
but the delta is `legacy`/`alternative` residue — z22 is the *cleanest*, nothing is on z22 without being on
z21, and the **driver in use is the same 615.71.09** on all three. What genuinely differs is **GPU
persistence** (Enabled on z21, Disabled on z22/z23) and the `nvpd` account (absent on z22). No gate reads
persistence, and reconciling would mean *adding* stale 550-era packages to a working node. (2) The last
off-campus poller is **NTP**, and it cannot be moved: `ntpd` is **ntpsec**, reading `/etc/ntpsec/ntp.conf`
(four `debian.pool.ntp.org`) — the file naming the campus server, `/etc/ntp.conf`, **is not read by it** — and
the campus server **answers nothing** (mode-3 probe, timeout on all three). Pointing ntpd at it would leave
the clock without a source, so the poll stays, consistent with SPEC §6.

**Certified state (2026-09-29 03h05).** `node_vllm_service.sh` `a3547903b312e158` repo and node identical on
the three; PIDs **25512 / 31770 / 27019**; `/v1/models` **200** on all three; fast tier **18 PASS / 0 FAIL /
2 WARN (20 checks) — NOEUD DORE** on all three, differing only by hostname and node-owned values (lockfile
208 vs 215 lines, 5 vs 7 G10 artefacts, free disk). Backups: `/root/infra-backups/vllm-service.sh.20260929`
(sha `f778015c57153224`, the original revision, identical on the three), the pristine `nslcd` configuration,
and `/root/tailscale-prestate/`. Logs: `evidence/2026-09-28/risk-probes/tiered-and-retention/souverainete-logs/`
(eight files, indexed).

**Still open, honestly:** tailnet restoration (§21.6); the residual NTP poll, **blocked upstream**; the z22
NVIDIA/persistence asymmetry; and the decision on the service account's provenance.

One measurement I am not dressing up: in the *after* run, 6 packets appeared in the restart window, to
tuples **already** recorded with **uid 0** (my own guard probes). No new tuple, and no uid other than root.
I attribute them to SYN retransmissions of those probes — **that attribution is an inference, not a
measurement**, and is recorded as such.

---

### Maintenance actions, 2026-09-29 (12h) — the identity defect was in my own instrument, and three asymmetries close

Three decisions were taken with the operator before anything on the nodes was touched, under one hard
constraint: **do not put any other user's login at risk.** Full record: `SUMMARY.md` **§25**.

**The identity defect was partly mine.** §22.1 blamed ~36 s of the boot delay on *"the launch wrapper
(`setpriv --init-groups` → NSS → nslcd → LDAP)"*. Two measurements made today reverse that: the boot trigger
is `@reboot /bin/bash /home/msalhi/vllm-autostart.sh --run`, run **already as `msalhi`** by cron, and that
script **never calls `setpriv`** — its only NSS call is a `getent` **fallback** for `$HOME` (cron always sets
it). The `setpriv --init-groups` belongs to the **probe harness** (`coldstart-egress.sh`,
`cold-backstop.sh`), which simulates a root→msalhi drop production does not do. And `nscd` — reported absent
at 03h — **is installed and running** (PID 2614); the earlier `which nscd` was a false negative (`/usr/sbin`
is not in an ordinary account's `PATH`, and Devuan has no `systemctl`).

**Why the obvious remedy was refused.** `nsswitch` is `passwd: files ldap` / `group: files ldap`, and the
account's groups are **directory** groups: `se4is` (2104, **~50 members**) and `se5is` (2106). A local
`/etc/passwd` entry for `msalhi` would **shadow the directory** on that node — and making
`setpriv --init-groups` work offline would mean copying those two groups locally, so a student added in LDAP
would **lose access on that node**. The fix would have been worse than the fault. Refused.

**What was done instead — three changes, no identity file touched by them.**

| # | change | tool | verified by |
|---|---|---|---|
| a | a **system** boot task `/etc/cron.d/iot-audit-vllm-autostart` dropping to **numeric** identity, so cron resolves only `root` | `infra/scripts/node_boot_drop_privilege.sh` | the exact command run as root → `rc=0`, *"service deja en cours"* (it **sees** PID 31770); a throwaway `/etc/cron.d` entry ran `date` at **12:15:01**, proving the mechanism on these nodes |
| b | **GPU persistence aligned** — z22/z23 now `Enabled` like z21 | `infra/scripts/node_nvidia_persistence.sh` | daemon running, `S02nvidia-persistenced`, `persistence_mode=Enabled` ×3 |
| c | the campus time server written **preferred, in IP, before the pool** | `infra/scripts/node_ntp_campus_preferred.sh` | campus peer present (`reach 0`, still silent), pool still syncing (`*62.210.102.72, offset −0.42 ms`) |

(a) is the point of the exercise: `setpriv --reuid=10131 --regid=2104 --groups=2104,2106` yields
`Uid: 10131  Gid: 2104  Groups: 2104 2106` — **identical to `id`**, with **zero** name lookups. The user's
existing `@reboot` line is **left in place** as the net; `vllm-autostart.sh` exits 0 when the service is
already running, so the two cannot start two servers.

(b) also corrects a packaging claim: the package is identical everywhere (`615.71.09-2`, same CUDA repo,
`dpkg -V` clean), but its **init script was present on z21 only** — z22/z23 had no
`/etc/init.d/nvidia-persistenced`, and z22 had no `nvpd` account. That is an *installation* divergence, not a
version one. The bytes were **vendored, not retyped** (`infra/assets/nvidia-persistenced.init.d`, sha256
`f8f4f988…`, identical to z21) and the installer refuses to proceed if the sha differs.

**Login safety, checked rather than asserted.** `/etc/nsswitch.conf` and `/etc/pam.d/*` are **untouched**
(mtime 2026-07-08 ×3). `/etc/passwd`/`group`/`shadow` on **z21 and z23 are untouched** (2026-09-15); on
**z22 they moved once** (12:16:41) to add the system account `nvpd`. That account is the only identity-file
change in this pass, and it collides with nothing: `getent passwd` enumerates **176** entries, the directory
uses uid **≥ 10000** and gid **≥ 2001**, and `nvpd` is the **only** entry at 996/998. `grep -c '^msalhi:'`
stays **0** in both files everywhere; `getent passwd msalhi` → `10131:2104` and `id` →
`groups=2104(se4is),2106(se5is)` are unchanged; the directory-only account `aaitifra` still resolves
(`10117:2401`); `root`, `msalhi`, `aaitifra` and `nvidia-persistenced` are all intact.

**Restore, one line per change:**

The three tools sit in the node's `$HOME` (like the other per-node tools), identical sha
`5e54035449377bd2bf118db58e66ecccb32c4e2b7a889135a5d5828110b415da` on all three:

```
rm /etc/cron.d/iot-audit-vllm-autostart                              # a)  one line, one file
sudo bash /home/msalhi/node_nvidia_persistence.sh remove               # b)  (the system account is left in place)
sudo bash /home/msalhi/node_ntp_campus_preferred.sh remove            # c)  (restores …/ntp.conf.iot-audit-20260929)
```

**Certified state (2026-09-29 12h19).** PIDs **25512 / 31770 / 27019**; `/v1/models` **200** ×3; fast tier
**18 PASS / 0 FAIL / 2 WARN (20 checks) — NOEUD DORE** on all three (same two expected WARNs: *egress
JOIGNABLE*, and *port 8000 already serving*). All seven repo selftests pass. Logs:
`…/souverainete-logs/zabeth2{1,2,3}-hardening-12h.log` and `…-golden-fast-12h.log`.

**Still open:** tailnet restoration (§21.6); the campus NTP server itself, **blocked upstream**; the z22
`legacy`/`alternative` package residue (78/36/66 — reported, deliberately not reconciled); and the optional,
no-longer-necessary migration of the service to a dedicated local account.

---

### Maintenance actions, 2026-09-29 (12h24–12h49) — the real reboot, and the two defects it found

**The reboot was not a formality: it found two defects, both in the change I had just made.** Full record:
`SUMMARY.md` **§26**.

**First, my "verified" claim was not a verification.** §25.3a said the boot job was verified by running the
exact command. It was run while the **service was already running**, so the script exited at *"service deja en
cours"* **before ever reaching a launch**. A test that never exercises the launch path proves nothing about
it.

**Defect 1 — the two triggers raced.** At the first reboot (zabeth21, boot 12:25:18) both jobs fired in the
same millisecond (`12:25:34.688` root, `.689` msalhi). Each passed the *"already running"* check before the
other had started anything, so **both launched vLLM** (PIDs 3164 and 3167). The loser died
(`EngineCore initialization failed`) and, dying, `vllm-service.sh` runs `rm -f "$PIDFILE"` — **deleting the
winner's pidfile**. The service served `200` **with no pidfile**, while the log announced *"ECHEC : le service
n'a pas demarre apres 3 essais"*. Fixed by a **single-instance lock** (`flock -n` on a shell fd) at the top of
`do_run()`: the loser logs one line and exits 0. Offline test, 8 concurrent runs: **1 winner, 7 clean exits,
one listener on 8000**.

**Defect 2 — the service started with `cwd=/root`.** On zabeth22 (boot 12:29:20) the lock worked, but the
service **never started** (`000`, no pidfile). Root cause, straight from the vLLM log:

```
  File ".../multiprocessing/spawn.py", line 235, in prepare
    os.chdir(data['dir'])
PermissionError: [Errno 13] Permission denied: '/root'
```

vLLM forks its EngineCore via `multiprocessing` (*spawn*), and **the child re-applies the parent's cwd**. cron
runs a job with the cwd of the **job's owner**: `/home/msalhi` for the user line, **`/root`** for a `/etc/cron.d`
job. `setpriv` changes uid/gid and **not the cwd**. So whenever the **root** instance won the lock, the service
ran with `cwd=/root` and died. That is also why zabeth21 *looked* healthy: there the **msalhi** instance had
won, and the root instance had lost **and died of this same defect** (PID 3164). Fixed in two places
(defence in depth): `cd "$HOME"` at the top of `vllm-autostart.sh`, and `cd /home/msalhi &&` at the head of the
system job. z22's service was restored by hand at 12:39:30 while the fix was prepared.

**The proof, after the fix — three real reboots, one node at a time:**

| | zabeth21 | zabeth22 | zabeth23 |
|---|---|---|---|
| new boot time | 12:47:21 | 12:42:29 | 12:45:05 |
| `(root) CMD … cd /home/msalhi && setpriv …` in syslog | yes | yes | yes |
| pidfile after boot | 3048 | 3189 | 3187 |
| process `user` / `cwd` | `msalhi` / **`/home/msalhi`** | `msalhi` / **`/home/msalhi`** | `msalhi` / **`/home/msalhi`** |
| `/v1/models` | 200 | 200 | 200 |
| `ECHEC` lines in that boot's log | **0** | **0** | **0** |
| GPU persistence after boot | Enabled, daemon running | idem | idem |
| fast tier | 18/0/2 — NOEUD DORE | idem | idem |

The cluster never had more than one node unavailable. **Lesson recorded:** the only valid verification of a
boot mechanism is a boot, and it must be done **per node** — at the first reboot the two racing instances
masked each other's failure, so a single "representative" node would have hidden defect 2.

**Versions / rollback.** `vllm-autostart.sh`: original `dee8ac5563bb7216` (backed up on all three as
`vllm-autostart.sh.bak-20260929`) → current `3c63e2dbbc5da45f`, **repo == node ×3**. Roll back **both** parts
at once:

```
install -m 755 /home/msalhi/vllm-autostart.sh.bak-20260929 /home/msalhi/vllm-autostart.sh
sudo rm /etc/cron.d/iot-audit-vllm-autostart
```

(restoring the old revision *while leaving both triggers* would recreate the race of defect 1). Logs:
`souverainete-logs/zabeth2{1,2,3}-reboot-proof.log` and `…-golden-fast-after-reboot.log`.

