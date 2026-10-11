#!/bin/bash
# =============================================================================
#  golden-check.sh -- one command that says whether this node is still GOLDEN
# =============================================================================
#  Checks the SPEC-infra-setup.md §6 invariants (G1-G10) plus the infrastructure
#  invariants discovered on 2026-09-14 that the spec did not know about.
#
#  usage:
#     bash golden-check.sh              # fast checks only (~10 s)
#     bash golden-check.sh --deep       # + build an engine and generate (~3 min)
#     bash golden-check.sh --json       # machine-readable summary line
#
#  Read-only: it starts a temp engine in the deep tier and stops it again. It
#  never mutates the venv, the system, or the models.
#
#  Exit codes: 0 all pass · 1 at least one FAIL · 2 cannot start
# =============================================================================
set -uo pipefail

# NOTE (added 2026-09-14 by the executing agent, SPEC §19 P6)
# PER-NODE tool. Run it ON a node. One command that says whether the node still
# satisfies §6 G1-G10 plus the host-environment invariants the SPEC does not know
# about (nvcc host compiler, flashinfer JIT `ninja`, offline embedding model,
# sqlite FTS5+trigram). Read-only unless --deep.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 2026-09-17: this block used to sit ABOVE the shebang, which put `#!/bin/bash`
# on line 7 — inert, so a direct `./golden-check.sh` fell back to /bin/sh — and
# shifted the `--help` range off the header it was written for. It is now the
# first block of the body, so line 1 is the shebang again and the header keeps
# its original numbering. Text unchanged; only its position moved.

VENV="${VENV:-$HOME/vllm-env}"
PY="$VENV/bin/python"
MODEL="${MODEL_PATH:-$HOME/models/Qwen2.5-VL-7B-Instruct-GPTQ-Int4}"
# Image de test -- meme resolution que les deux autres outils per-noeud. Les trois
# sont deployes SEPAREMENT dans $HOME (aucun n'a de checkout du depot), donc la
# liste est repetee : les garder en phase. 2026-09-28 : les octets sont versionnes
# (infra/assets/test-images/, sha256 ca07ce15...) et l'image est resolue au lieu
# d'etre devinee -- le seul chemin connu etait /tmp, qui se vide au redemarrage.
if [ -z "${TEST_IMAGE:-}" ]; then
  for TEST_IMAGE in \
      "$(dirname "$0")/../assets/test-images/device_clean.jpg" \
      "$HOME/infra/assets/test-images/device_clean.jpg" \
      "$HOME/vlm-test-images/device_clean.jpg" \
      /tmp/vlm-test-images/device_clean.jpg; do
    [ -f "$TEST_IMAGE" ] && break
  done
fi
IMAGE="$TEST_IMAGE"
PORT="${PORT:-8000}"
DEEP=0
JSON=0
for a in "$@"; do
  case "$a" in
    --deep) DEEP=1 ;;
    --json) JSON=1 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "argument inconnu: $a" >&2; exit 64 ;;
  esac
done

PASS=0; FAIL=0; WARN=0
declare -a ROWS

ok()   { ROWS+=("PASS|$1|$2"); PASS=$((PASS+1)); }
bad()  { ROWS+=("FAIL|$1|$2"); FAIL=$((FAIL+1)); }
warn() { ROWS+=("WARN|$1|$2"); WARN=$((WARN+1)); }

# ---------------------------------------------------------------------------
hr() { printf '\n%s\n' "---- $* ----"; }

STATUS_HEADER=$(printf '%-7s %-38s %s' "RESULT" "CHECK" "DETAIL")
hr "golden-check -- $(hostname) -- $(date -Is)"
[[ "$DEEP" = 1 ]] && echo "mode : DEEP (construit un moteur)" || echo "mode : FAST (aucun moteur construit)"

# ===================== G1 : venv, profile, dependency integrity ============
hr "G1 -- venv, profil, integrite des dependances"
if [[ -x "$PY" ]]; then ok "venv python executable" "$VENV/bin/python"; else bad "venv python executable" "absent"; fi
if [[ -x "$VENV/bin/vllm" ]]; then ok "binaire vllm" "$VENV/bin/vllm"; else bad "binaire vllm" "absent"; fi

UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
if [[ -x "$UV" ]]; then
  OUT="$("$UV" pip check --python "$PY" 2>&1)"; rc=$?
  if [[ $rc -eq 0 ]]; then ok "uv pip check" "$(echo "$OUT" | tail -1 | cut -c1-60)"
  else bad "uv pip check" "$(echo "$OUT" | grep -iE 'requires|incompat' | head -2 | tr '\n' ' ' | cut -c1-90)"; fi
else
  warn "uv pip check" "uv introuvable"
fi

# ===================== G2 : the stack is actually usable ==================
hr "G2 -- torch / CUDA / vLLM"
read -r TORCH VER CUDA AVAIL GPU <<<"$("$PY" - <<'PY' 2>/dev/null
import torch, vllm
print(torch.__version__, vllm.__version__, torch.version.cuda,
      torch.cuda.is_available(), (torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-"))
PY
)"
[[ -n "${TORCH:-}" ]] && ok "torch" "$TORCH cuda=$CUDA" || bad "torch" "import echoue"
[[ "${AVAIL:-False}" == "True" ]] && ok "torch.cuda.is_available()" "$GPU" || bad "torch.cuda.is_available()" "False"
[[ "${VER:-}" == "0.29.0" ]] && ok "vllm" "$VER" || warn "vllm" "${VER:-?} (profil attendu 0.29.0)"

# real kernel, not just is_available()
if "$PY" - <<'PY' >/dev/null 2>&1
import torch
a = torch.ones(512, device="cuda"); b = torch.ones(512, device="cuda")
assert float((a + b).sum()) == 1024.0
PY
then ok "kernel CUDA reel" "somme = 1024.0"; else bad "kernel CUDA reel" "echec d'execution"; fi

# ===================== INFRA : the two 2026-09-14 discoveries ==============
hr "INFRA -- invariants decouverts le 2026-09-14 (absents du SPEC)"
SC="$("$PY" -c 'import site;print(site.getsitepackages()[0])' 2>/dev/null)/sitecustomize.py"
if [[ -f "$SC" ]] && grep -qE 'vllm-(host-compiler|venv-environment)' "$SC" 2>/dev/null; then
  # the point of sitecustomize: it must work with NO shell involved at all
  V="$(env -u NVCC_PREPEND_FLAGS -u CUDAHOSTCXX -u PATH "$PY" -c 'import os;print(os.environ.get("NVCC_PREPEND_FLAGS") or "")' 2>/dev/null)"
  if [[ "$V" == *ccbin* ]]; then
    ok "correctif nvcc independant du shell" "shell nu -> $V"
  else
    bad "correctif nvcc independant du shell" "sitecustomize present mais sans effet"
  fi
else
  bad "correctif nvcc independant du shell" "sitecustomize.py absent -- le JIT flashinfer echouera sans shell interactif"
fi

# The same JIT shells out to `ninja`, which ships ONLY as $VENV/bin/ninja. A
# process started as `nohup $VENV/bin/vllm ...` never activates the venv, so
# PATH is the SSH default. Measured 2026-09-14 through vllm-service.sh: the
# engine captured its CUDA graphs, then died with
#   FileNotFoundError: 'ninja' -> Engine core initialization failed.
NJ="$(env -u NVCC_PREPEND_FLAGS -u CUDAHOSTCXX -u PATH "$PY" -c 'import shutil;print(shutil.which("ninja") or "")' 2>/dev/null)"
if [[ -n "$NJ" ]]; then
  ok "ninja visible sans activation" "shell nu -> $NJ"
else
  bad "ninja visible sans activation" "PATH sans $VENV/bin -- le JIT flashinfer echouera (FileNotFoundError: ninja)"
fi

# flashinfer needs it only when a NEW jit op is compiled, so the cache masks it
JITC="$HOME/.cache/flashinfer"
if compgen -G "$JITC/*/*/cached_ops/*" >/dev/null 2>&1; then
  ok "cache JIT flashinfer" "$(find "$JITC" -name '*.so' 2>/dev/null | wc -l) .so compile(s)"
else
  warn "cache JIT flashinfer" "vide -- la 1re generation declenchera une compilation"
fi

# offline claim (docs/01 A8) needs every model present
ML="$HOME/.cache/huggingface/hub"
if compgen -G "$ML/models--sentence-transformers--all-MiniLM-L6-v2" >/dev/null 2>&1; then
  ok "all-MiniLM-L6-v2 en cache" "recherche CPE hors-ligne possible"
else
  bad "all-MiniLM-L6-v2 en cache" "ABSENT -- la claim A8 (sans reseau) echouera"
fi

# D3/D5 require FTS5 with the trigram tokenizer
FT="$("$PY" - <<'PY' 2>/dev/null
import sqlite3
c = sqlite3.connect(":memory:")
try:
    c.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize=trigram)")
    print("OK")
except Exception:
    print("NON")
PY
)"
[[ "$FT" == "OK" ]] && ok "sqlite FTS5 + trigram" "$("$PY" -c 'import sqlite3;print(sqlite3.sqlite_version)' 2>/dev/null)" \
                    || bad "sqlite FTS5 + trigram" "requis par D3/D5"

# ===================== G3/G7 : model + provenance =========================
hr "G3/G7 -- modele cible et provenance"
if [[ -d "$MODEL" ]]; then
  N=$(find "$MODEL" -name '*.safetensors' 2>/dev/null | wc -l)
  B=$(find "$MODEL" -name '*.safetensors' -printf '%s\n' 2>/dev/null | awk '{s+=$1} END{print s+0}')
  ok "modele present" "$(basename "$MODEL") -- $N fichier(s), $B octets"
else
  bad "modele present" "$MODEL ABSENT"
fi
if [[ -f "$VENV/ENV_STATUS.md" ]]; then ok "G7 ENV_STATUS.md" "$(wc -c <"$VENV/ENV_STATUS.md") octets";
else bad "G7 ENV_STATUS.md" "absent"; fi
if [[ -f "$VENV/REQUIREMENTS_LOCKED.txt" ]]; then ok "lockfile" "$(wc -l <"$VENV/REQUIREMENTS_LOCKED.txt") lignes";
else warn "lockfile" "REQUIREMENTS_LOCKED.txt absent"; fi
RB=$(find "$VENV" -maxdepth 1 -name 'REQUIREMENTS_BEFORE_*.txt' 2>/dev/null | wc -l)
[[ "$RB" -gt 0 ]] && ok "G10 artefact de rollback" "$RB fichier(s)" || bad "G10 artefact de rollback" "aucun REQUIREMENTS_BEFORE_*.txt"

# ---- souverainete reseau du noeud (capteur ajoute le 2026-09-29) ----------
# POURQUOI CE BLOC EXISTE. Le 2026-09-16, le rejeu de V12 a decouvert que
# zabeth23 heberge un `tailscaled` tiers. Le 2026-09-24 a 21h07, zabeth22 en a
# recu un a son tour -- et personne ne l'a vu pendant cinq jours, parce que ce
# script ne regardait pas. Les invariants G1-G10 ne parlent jamais des
# co-locataires reseau : un noeud pouvait donc etre declare DORE alors qu'un
# tiers ecrit sa configuration reseau (`/etc/resolv.conf` reecrit, DNS detourne
# vers 100.100.100.100) et maintient un tunnel sortant chiffre. Un audit qui ne
# peut pas voir un co-locataire ne certifie pas l'absence de co-locataire.
#
# POURQUOI WARN ET NON FAIL. Le SPEC §6 tranche explicitement l'autre question
# ("egress joignable" est l'etat permanent attendu) et G9 ne demande que
# l'inference survive au blocage -- ce qui est mesure et vrai. Aucun invariant
# ecrit n'interdit un co-locataire. Un FAIL serait donc une exigence inventee.
# Mais le WARN NOMME le co-locataire, pour que l'etat ne puisse plus deriver en
# silence entre deux audits.
COTENANTS=""
for p in tailscaled openvpn wireguard-go wg-quick zerotier-one nebula syncthing; do
  pgrep -x "$p" >/dev/null 2>&1 && COTENANTS="$COTENANTS $p"
done
TUN=""
for i in tailscale0 wg0 zt0 tun0; do
  ip link show "$i" >/dev/null 2>&1 && TUN="$TUN $i"
done
RESOLV_TIERS="non"
if grep -qiE 'generated by|DO NOT EDIT' /etc/resolv.conf 2>/dev/null; then RESOLV_TIERS="oui"; fi
if [[ -n "$COTENANTS" || -n "$TUN" ]]; then
  warn "souverainete reseau" "co-locataire tiers:${COTENANTS:- ?}${TUN:+ iface:$TUN} -- resolver tiers: $RESOLV_TIERS"
else
  ok "souverainete reseau" "aucun daemon VPN tiers, resolver non detourne"
fi

# ===================== non-fatals that matter operationally ================
hr "Exploitation"
if ping -c1 -W2 8.8.8.8 >/dev/null 2>&1; then
  warn "egress" "internet JOIGNABLE -- V12 ne peut pas passer tant que ce n'est pas coupe"
else
  ok "egress" "reseau externe injoignable (coherent avec V12/A8)"
fi
FREE=$(df -Pm "$HOME" | awk 'NR==2{print $4}')
[[ "$FREE" -gt 25000 ]] && ok "disque" "${FREE} MiB libres" || warn "disque" "${FREE} MiB libres (< 25 GB)"
if pgrep -f "vllm serve" >/dev/null 2>&1; then warn "port $PORT" "un serveur vllm tourne deja (le test profond echouera)";
else ok "port $PORT" "libre"; fi

# ===================== G3/G4 : DEEP tier ==================================
if [[ "$DEEP" = 1 ]]; then
  hr "G3/G4/V7 -- moteur + image + sortie structuree (DEEP)"
  if [[ ! -f "$IMAGE" ]]; then
    warn "image de test" "$IMAGE absent -- versionnee dans infra/assets/test-images/"
  else
    TMP="$(mktemp -d)/deep.py"
    cat > "$TMP" <<'PY'
import json, os, sys, time
import torch
from PIL import Image
from vllm import LLM, SamplingParams
from vllm.sampling_params import StructuredOutputsParams
MODEL, IMAGE = sys.argv[1], sys.argv[2]
SCHEMA = {"type": "object",
          "required": ["brand", "model", "category"],
          "additionalProperties": False,
          "properties": {"brand": {"type": "string"},
                         "model": {"type": "string"},
                         "category": {"enum": ["smart_plug","ip_camera","smart_bulb",
                                               "router_ap","smart_speaker","other"]}}}
llm = LLM(model=MODEL, max_model_len=4096, gpu_memory_utilization=0.90,
          limit_mm_per_prompt={"image": 1}, trust_remote_code=True, disable_log_stats=True)
img = Image.open(IMAGE).convert("RGB")
conv = [{"role": "user", "content": [{"type": "image_pil", "image_pil": img},
        {"type": "text", "text": "Identify the device: brand, model, category."}]}]
t = time.time()
sp = SamplingParams(temperature=0.0, max_tokens=200,
                    structured_outputs=StructuredOutputsParams(json=SCHEMA))
raw = llm.chat([conv], sampling_params=sp)[0].outputs[0].text
dt = time.time() - t
try:
    p = json.loads(raw)
    good = (not [k for k in SCHEMA["required"] if k not in p]
            and p.get("category") in SCHEMA["properties"]["category"]["enum"])
except Exception as e:
    print("DEEP|G4|FAIL|JSON invalide: %s" % e); sys.exit(1)
print("DEEP|G3|PASS|identification en %.2f s" % dt)
print("DEEP|G4|%s|%s" % ("PASS" if good else "FAIL", json.dumps(p, ensure_ascii=False)[:110]))
PY
    OUT="$("$PY" "$TMP" "$MODEL" "$IMAGE" 2>&1 | grep -E '^DEEP\|' )"
    if [[ -z "$OUT" ]]; then
      bad "G3 moteur + image" "aucune sortie exploitable (moteur ou infer en echec)"
    else
      while IFS='|' read -r _ id res det; do
        [[ "$res" == "PASS" ]] && ok "$id (deep)" "$det" || bad "$id (deep)" "$det"
      done <<< "$OUT"
    fi
  fi
fi

# ===================== summary ============================================
printf '\n%s\n' "==================================================================="
ROW_FMT="  [%-4s] %-38s %s\n"
idx=0
for r in "${ROWS[@]}"; do
  IFS='|' read -r st name det <<<"$r"
  printf "$ROW_FMT" "$st" "$name" "$det"
done
printf '%s\n' "==================================================================="
printf '  %d PASS   %d FAIL   %d WARN      (%d checks)\n' "$PASS" "$FAIL" "$WARN" "${#ROWS[@]}"
if [[ "$FAIL" -eq 0 ]]; then
  printf '  RESULTAT : NOEUD DORE\n'
else
  printf '  RESULTAT : %d echec(s) -- voir ci-dessus\n' "$FAIL"
fi
[[ "$JSON" = 1 ]] && printf 'JSON {"host":"%s","pass":%d,"fail":%d,"warn":%d,"deep":%s}\n' \
  "$(hostname)" "$PASS" "$FAIL" "$WARN" "$DEEP"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
