# The local tunnel becomes a repo artifact (2026-10-06)

This file exists because of a housekeeping defect, not a technical one. The two
sections below were first written *inside* `infra/README.md` and
`infra/selftest/README.md`, both of which already carried a large body of
uncommitted work at the time. New content living in a file that is already
pending has no way to be committed on its own: `git diff infra/README.md` stood
at **1559 added lines, 60 of which were this one**.

Rather than commit someone else's unreviewed work to get at my own, the sections
were moved here on 2026-10-06. The text is byte-verbatim; the only edits are the
two named below.

1. The bracket paragraph used to end by citing `../README.md`, which no longer
   carries the text it cited — it now says "the section above".
2. `selftest/README.md` keeps its **one-line entry** for `check-tunnel-scope.sh`
   in the list of nine checks, because that list is shared; the prose that
   described the check lives here.

Everything else — the tunnel wrapper, the systemd unit, the installer, the
scope check — is committed work; see `scripts/tunnel_vllm.sh`,
`systemd/iot-audit-tunnel.service`, `scripts/install_tunnel_autostart.sh` and
`selftest/check-tunnel-scope.sh`.

---

### Maintenance actions, 2026-10-06 — the local tunnel becomes a repo artifact, and it had a blast-radius defect

**What was wrong.** Every "live" benchmark in the repo opened its docstring by telling the reader to type
the tunnel by hand:

```bash
ssh -fN -L 18000:172.26.145.71:8000 zabeth21
```

That line was copied into four scripts (`live_vlm_orchestrator`, `live_cross_node`,
`live_specificity_protocol`, `live_specificity_smoke`) with options that had already **diverged** — two of
them carried `-o ServerAliveInterval=15`, the others nothing at all. Nothing relaunched it. The portier
gateway drops the forwarding connection **several times an hour** (measured across the 2026-10-05/06
sessions), and the failure is *misread*: a benchmark that cannot reach the model looks exactly like a
benchmark that ran and produced nothing. On the day of writing, the tunnel had in fact been dead for hours
behind a hand-started relaunch loop that no longer belonged to anyone.

**The fix.** `infra/scripts/tunnel_vllm.sh` — `start` / `stop` / `status` / `restart`, with `--node`,
`--port` and `--foreground`. Defaults come from `cluster.env` (first of `NODES`, its `NODE_IPS` entry,
`QWEN_PORT`), and the local port stays **18000** because that is the `--endpoint` default baked into every
benchmark. The four docstrings now point at the script instead of at `ssh`.

**Behaviours that were measured, not assumed.**

| observation | consequence in the script |
|---|---|
| A dead remote leaves the local **listener** alive; a new `ssh -L` then dies with `bind: Address already in use` under `ExitOnForwardFailure` | `start` clears non-answering holders of the port **before** rebinding |
| `status` on a listener alone reports a healthy tunnel | `status` issues a real HTTP `GET /v1/models` and prints the model it got back |
| The portier drop is routine | `start` runs a **relaunch loop**, not a one-shot `ssh -fN`. Verified by killing only the ssh child: `3480014` → relaunch → `3480232`, endpoint answering again |
| `pkill -f "L 18000"` kills the shell that runs it, because the pattern is on that shell's own command line | the pattern is **bracketed** (`18000` → `1800[0]`), and the kill set is filtered by ancestry — see below |

**The defect the new check found, on its first run.** The first version of the selection excluded only
`$$` and `$PPID`. `selftest/check-tunnel-scope.sh` drives the selection from inside a wrapper whose own
argument vector carries the forwarding pattern — the shape this is supposed to survive — and showed the
caller's **grandparent** being selected: a signalling that would have taken down the agent or CI job that
invoked `stop`. The real thing happened twice in the writing session: a cleanup `pkill -f -- "-L 18999:..."`
killed the very pipeline it was part of, twice, silently (no output at all from the command).

The fix is an **ancestry exclusion** (`ancestor_pids`: nothing can be its own ancestor), plus a precise
kill set — `forwarder_pids` selects by **executable** (`/proc/<pid>/comm == ssh`), not merely by the text on
the command line, so a wrapper shell that happens to mention the tunnel is not a candidate. `holder_pids`
(every carrier) is used only when the port is *still* held after the forwarders are gone, which is the
signature of a foreign relaunch loop that would otherwise respawn what we just stopped; that step is
**announced** because it is the only one that signals a non-`ssh` process.

The bracket is **defence in depth, not the guard**: the negative control in the selftest shows the naive
`pgrep -f` selecting the ancestor just the same. The ancestry exclusion is what makes `stop` safe.

**Verification.**

```
bash selftest/check-tunnel-scope.sh                                  -> VERDICT : OK (21 controls, exit 0)
infra/scripts/tunnel_vllm.sh status                                  -> OK  service reachable - model 'qwen2.5-vl-7b'
infra/scripts/tunnel_vllm.sh stop                                    -> port :18000 free, caller alive
infra/scripts/tunnel_vllm.sh start                                   -> pid recorded, endpoint answering
infra/scripts/tunnel_vllm.sh start --node zabeth22 --port 18002      -> coexists with :18000, answers
./.venv-core/bin/python benchmarks/live_vlm_orchestrator.py           -> 8/8 controls against the REAL vLLM
```

---

`check-tunnel-scope.sh` (2026-10-06) — `scripts/tunnel_vllm.sh stop` has to find and signal the SSH
forwarder for its port, and the naive way to do it (`pkill -f "L 18000"`) kills the shell that runs it,
because the pattern is on that shell's **own** command line. That is not hypothetical: it happened twice in
the writing session — a cleanup `pkill` took down the pipeline it belonged to, and the command produced no
output at all, so the loss was silent. The check **extracts** the selection functions from the real script
(never a copy) and drives them from inside a wrapper whose argument vector carries the pattern, then
asserts: a real forwarder is selected, the driver is not, **and neither is its parent**. The "forwarder" is
a copy of `sleep` named `ssh`, so `/proc/<pid>/comm` is genuinely `ssh` without a connection; everything
runs on port 18999 so the live tunnel on 18000 is never touched. The **negative control** is that the naive
`pgrep -f` *does* select the parent — which is exactly the defect the ancestry exclusion exists to prevent,
and it is what caught the first version of the script selecting the caller's **grandparent**.

The bracket in the pattern (`18000` → `1800[0]`) is tested here too, and the section above is
explicit that it is **defence in depth, not the guard**: the ancestral exclusion is what makes `stop` safe.

