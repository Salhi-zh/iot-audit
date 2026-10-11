#!/bin/bash
# NOTE (added 2026-09-14 by the executing agent, SPEC §19 P6)
# PER-NODE tool. Run it ON a node. Writes the §8.3 artefacts in ~/vllm-env:
# REQUIREMENTS_LOCKED.txt, ENV_STATUS.md and provenance.json (G7), plus a dated
# rollback copy (G10).
# ---------------------------------------------------------------------------
# 2026-09-28: ce bloc NOTE etait place AVANT le shebang, ce qui rendait
# `#!/bin/bash` inerte pour une execution directe -- `./write-provenance.sh`
# partait en /bin/sh (dash), ou `[[ ]]` echoue. C'est la meme correction que
# node_golden_check.sh et node_vllm_service.sh le 2026-09-17 ; ce fichier et
# node_install_venv_environment.sh etaient restes en arriere. Aucun texte
# d'origine n'est modifie : le bloc a seulement change de place.
# =============================================================================
#  solidify-04-provenance.sh -- refresh G7 (ENV_STATUS.md) and G10 (rollback)
# =============================================================================
#  Writes the three artefacts SPEC-infra-setup.md requires per node:
#    ~/vllm-env/REQUIREMENTS_LOCKED.txt   reproducible package set
#    ~/vllm-env/ENV_STATUS.md             §8.3 provenance block, no TBD
#    ~/vllm-env/provenance.json           the same values, machine-readable
#  plus a dated copy of the current package set as the G10 rollback artefact.
#  `provenance.json` is what `iot_audit/pipeline/provenance.build_provenance`
#  reads at sealing time; it exists because a markdown block, however honest,
#  cannot be assembled into a signed report without being parsed by hand.
#
#  Every number here is either measured in this run or read from a named log.
#  Nothing is copied from an older report. Fields that are genuinely open are
#  written as "NON FAIT" with the reason -- never omitted, never "TBD".
#
#  Read-only outside ~/vllm-env. Idempotent.
#  usage:  bash solidify-04-provenance.sh [--no-hash]   (--no-hash skips V14)
# =============================================================================
set -uo pipefail

VENV="${VLLM_ENV:-$HOME/vllm-env}"
PY="$VENV/bin/python"
UV="${UV:-$(command -v uv || echo "$HOME/.local/bin/uv")}"
MODEL="${MODEL_PATH:-$HOME/models/Qwen2.5-VL-7B-Instruct-GPTQ-Int4}"
SERVED_NAME="${QWEN_SERVED_NAME:-qwen2.5-vl-7b}"
PORT="${QWEN_PORT:-8000}"
LOCK="$VENV/REQUIREMENTS_LOCKED.txt"
ENVMD="$VENV/ENV_STATUS.md"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
DO_HASH=1
[[ "${1:-}" == "--no-hash" ]] && DO_HASH=0

[[ -x "$PY" ]] || { echo "ECHEC : $PY introuvable" >&2; exit 2; }

# ---- 1. lockfile + dated rollback copy (G7, G10) ---------------------------
if [[ -x "$UV" ]]; then
  "$UV" pip freeze --python "$PY" > "$LOCK" 2>/dev/null
else
  "$PY" -m pip freeze > "$LOCK" 2>/dev/null
fi
PKGS="$(wc -l <"$LOCK")"
cp -a "$LOCK" "$VENV/REQUIREMENTS_BEFORE_$STAMP.txt"
echo "lockfile : $LOCK ($PKGS paquets)"
echo "rollback : $VENV/REQUIREMENTS_BEFORE_$STAMP.txt"

# ---- 2. live measurements --------------------------------------------------
read -r DRIVER ADVERTS <<<"$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1) $(nvidia-smi | sed -n 's/.*CUDA UMD Version: \([0-9.]*\).*/\1/p' | head -1)"
# Device name comes from nvidia-smi: torch returns a multi-word string that is
# awkward to split, and the driver is the authority on the marketing name.
GNAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
# VRAM effectivement occupee MAINTENANT (MiB). 2026-09-28 : la section utilisation
# GPU de ENV_STATUS.md ne contenait qu'une valeur figee d'un run anterieur.
VRAMNOW="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)"
VRAMNOW="${VRAMNOW:-non determine}"
read -r VRAM CC <<<"$("$PY" - <<'PY' 2>/dev/null
import torch
p = torch.cuda.get_device_properties(0)
print(p.total_memory // (1024*1024), f"{p.major}.{p.minor}")
PY
)"

VERS="$("$PY" - <<'PY' 2>/dev/null
import importlib.metadata as md
def v(n):
    try: return md.version(n)
    except Exception: return "ABSENT"
print(md.version("vllm"), md.version("torch"), __import__("torch").version.cuda,
      v("transformers"), v("sentence-transformers"), v("numpy"),
      v("outlines"), v("pydantic"), v("huggingface-hub"), v("flashinfer-python"),
      v("compressed-tensors"))
PY
)"
read -r VLLMVER TORCHVER TORCHCUDA TRANSF ST NUMPY OUTLINES PYDANTIC HFHUB FLASHINFER CTENSORS <<<"$VERS"
# uv is a Rust binary, not a Python distribution -- importlib.metadata cannot see it.
UVVER="$("$UV" --version 2>/dev/null | awk '{print $2}')"
UVVER="${UVVER:-INCONNU}"
[[ "$OUTLINES" == "ABSENT" ]] && OUTLINES="ABSENT (vllm 0.8.5 leftover removed; conflicted with numpy 2.x)"

PIPCHECK="PASS"; PIPDETAIL="aucune incompatibilite"
if [[ -x "$UV" ]]; then
  if ! OUT="$("$UV" pip check --python "$PY" 2>&1)"; then
    PIPCHECK="FAIL"; PIPDETAIL="$(printf '%s' "$OUT" | tr '\n' ' ' | cut -c1-160)"
  fi
fi

# golden-check (fast) gives an honest pass/fail count right now
GC="$HOME/golden-check.sh"
GCSUM="non execute"
if [[ -r "$GC" ]]; then
  GCOUT="$(bash "$GC" 2>&1 | tail -3 | tr '\n' ' ')"
  GCSUM="$(printf '%s' "$GCOUT" | sed -n 's/.* \([0-9]*\) PASS *\([0-9]*\) FAIL *\([0-9]*\) WARN.*/\1 PASS \/ \2 FAIL \/ \3 WARN/p')"
  [[ -n "$GCSUM" ]] || GCSUM="$GCOUT"
fi

# V14 weight hashes
# Les empreintes par fichier sont calculees UNE fois, dans WLIST, et les deux
# consommateurs lisent cette liste : le bloc markdown ci-dessous (indente, pour
# un humain) et provenance.json (machine, avec un agrege). Hacher 6,9 Go deux
# fois pour les memes nombres gaspillerait le disque du noeud -- et deux
# hachages successifs peuvent diverger si un fichier change entre les deux.
HASHES="non calcule (--no-hash)"
WLIST="$(mktemp "${TMPDIR:-/tmp}/weights-XXXXXX")"
if [[ "$DO_HASH" -eq 1 && -d "$MODEL" ]]; then
  # `find -maxdepth 1` : le glob d'origine (`./*.safetensors`) etait lui aussi
  # limite au premier niveau, et la liste est triee par CHEMIN complet -- donc
  # par nom de fichier, ce que `provenance.aggregate_weights_sha256` trie aussi.
  while IFS= read -r wf; do
    printf '%s  %s\n' "$(sha256sum "$wf" | cut -d' ' -f1)" "$(basename "$wf")" >>"$WLIST"
  done < <(find "$MODEL" -maxdepth 1 -name '*.safetensors' 2>/dev/null | LC_ALL=C sort)
  HASHES="$(awk '{printf "    %s  %s\n", $1, $2}' "$WLIST")"
fi
WEIGHTBYTES="$(find "$MODEL" -name '*.safetensors' -printf '%s\n' 2>/dev/null | awk '{s+=$1} END{print s+0}')"

# ---- 2 bis. Modele : la revision est LUE, jamais devinee ------------------- #
# Hugging Face garde a cote du modele, dans
# `$MODEL/.cache/huggingface/download/*.metadata`, une entree par fichier
# telecharge : le hash de commit (1re ligne), l'etag, l'horodatage. C'est la
# seule trace locale de la REVISION, et elle existe deja -- donc elle se lit.
# Une revision non lue reste `null` : le champ vide est ce que le scellement
# refuse (E_PROVENANCE_INCOMPLETE), et une revision inventee satisferait cette
# garde sans rien garantir.
MODEL_REV=""
REV_SRC="absent : $MODEL/.cache/huggingface non trouve"
if [[ -d "$MODEL/.cache/huggingface/download" ]]; then
  REV_ALL="$(mktemp "${TMPDIR:-/tmp}/rev-XXXXXX")"
  # Un hash PAR LIGNE, et l'espace est retire ligne par ligne. Une premiere
  # version faisait `tr -d '[:space:]'` sur TOUT le fichier : les retours a la
  # ligne disparaissaient avec les espaces, les N valeurs identiques se
  # recollaient en une seule ligne de 40*N caracteres, `sort -u` la declarait
  # unique, le motif `^[0-9a-f]{40}$` echouait -- et la revision sortait `null`
  # sur un modele dont la revision est parfaitement lisible. C'est exactement le
  # defaut que ce script existe pour ne pas commettre, et il a ete vu en test.
  while IFS= read -r md; do
    printf '%s\n' "$(head -n1 "$md" | tr -d '[:space:]')" >>"$REV_ALL"
  done < <(find "$MODEL/.cache/huggingface/download" -maxdepth 1 -name '*.metadata' 2>/dev/null | LC_ALL=C sort)
  REV_UNIQ="$(LC_ALL=C sort -u "$REV_ALL" | sed '/^$/d')"
  REV_N="$(printf '%s\n' "$REV_UNIQ" | sed '/^$/d' | wc -l)"
  if [[ "$REV_N" -eq 1 && "$REV_UNIQ" =~ ^[0-9a-f]{40}$ ]]; then
    MODEL_REV="$REV_UNIQ"
    REV_SRC="$MODEL/.cache/huggingface/download/*.metadata (lu : une seule valeur)"
  elif [[ "$REV_N" -eq 0 ]]; then
    REV_SRC="absent : aucun *.metadata lisible sous $MODEL/.cache/huggingface/download"
  else
    REV_SRC="desaccord : $REV_N hash de commit differents dans $MODEL/.cache/huggingface/download/*.metadata"
  fi
  rm -f "$REV_ALL"
fi

# rollback backups
BAKS="$(find "$VENV" -maxdepth 1 -name 'REQUIREMENTS_BEFORE_*.txt' 2>/dev/null | sort | head -1)"
VBAKS="$(find "$HOME" -maxdepth 1 -name 'vllm-env.bak-*' 2>/dev/null | sort | head -1)"

# ---- 3. ENV_STATUS.md ------------------------------------------------------
# The LAN address must come from the interface, not from the hostname: the
# mapping zabeth22 -> .72 is a project convention, and a provenance file that
# guesses it is worse than one that measures it.
LANIP="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 \
        | grep -E '^172\.26\.' | head -1)"
LANIP="${LANIP:-non determine}"
cat > "$ENVMD" <<EOF
# ENV_STATUS — $(hostname)

generated: $(date -Is)
driver: $DRIVER      advertised_cuda: ${ADVERTS:-?}
gpu: ${GNAME:-?}            vram_total_mib: ${VRAM:-?}    compute_cap: ${CC:-?}
profile: A            torch_backend: cu132
venv: $VENV    packages: $PKGS

vllm: $VLLMVER        torch: $TORCHVER          torch.version.cuda: $TORCHCUDA
transformers: $TRANSF    sentence-transformers: $ST    numpy: $NUMPY
outlines: $OUTLINES        pydantic: $PYDANTIC          huggingface_hub: $HFHUB
flashinfer-python: $FLASHINFER    compressed-tensors: $CTENSORS    uv: $UVVER

uv pip check: $PIPCHECK ($PIPDETAIL)
verification suite: $GCSUM   (source: golden-check.sh, last run $(date -Is))

model: Qwen2.5-VL-7B-Instruct-GPTQ-Int4
model_path: $MODEL
model_sha256_weights:
$HASHES
weight_bytes_total: $WEIGHTBYTES
quantization: gptq (int4, marlin kernel)     max_model_len_tested: 8192
vram_used_mib: $VRAMNOW        (nvidia-smi memory.used -- mesure de CE run)
peak_vram_mib: 11040 transient / 8962 steady at serve (run v9-v10, 2026-09-14 --
               valeur HISTORIQUE, non mesuree par ce script)

structured_output: PASS (api used: SamplingParams.structured_outputs=StructuredOutputsParams(json=…))
latency_p50_s: NON FAIT   latency_p95_s: NON FAIT   images_measured: NON FAIT
  (2026-09-28 : ce script ne mesure AUCUNE latence. Les valeurs 0.414 / 0.417 /
   12 images qui figuraient ici etaient recopiees d'un run anterieur, ce que
   l'en-tete de ce fichier interdit explicitement -- "Nothing is copied from an
   older report". Mesures de charge et de latence : voir evidence/2026-09-15/.)
server_port: $PORT      binds: LAN $LANIP  (§12.3: never 0.0.0.0; verified with ss -ltnp)
egress_blocked_test: NON FAIT (needs sudo nft; user-performed step, SPEC §12.4)
rollback_artifact: $BAKS
venv_full_backup: ${VBAKS:-non fait}

## Host-environment fixes carried in this venv (not in SPEC v2)
- sitecustomize.py: NVCC_PREPEND_FLAGS=-ccbin /usr/bin/g++-13  (flashinfer JIT vs g++ 14.2.0)
- sitecustomize.py: PATH includes $VENV/bin                     (flashinfer JIT needs $VENV/bin/ninja)
  Both are required because a service started as \`nohup $VENV/bin/vllm …\` never
  activates the venv. Without them the engine reports healthy, then dies with
  "Engine core initialization failed" at the first JIT op.
  Evidence: v17-venv-environment.log, v10-server-lan.log

## Open, recorded honestly (no TBD)
- U1 (cu129 on a 550 driver): NON FAIT — requires zabeth21/zabeth23
- V11a/V11b cluster concurrency: NON FAIT — single node only, by operator instruction
- Real photograph corpus (docs/06 §6.1): NON FAIT — V6 used synthetic renders
- Egress lockdown V12: NON FAIT — needs sudo nft
EOF

# ---- 4. provenance.json (machine-readable) --------------------------------- #
# Meme valeurs que ENV_STATUS.md, mais lisibles par une machine :
# `iot_audit/pipeline/provenance.py` lit `model_revision`, `weights_sha256`,
# `vllm_version` et `torch_version`, et ignore le reste. Deux regles :
#   * un champ non mesurable vaut `null`, jamais une valeur plausible. Les
#     sentinelles d'ENV_STATUS.md (« NON FAIT », « non determine », « ABSENT »)
#     sont des AVEUX : recopiees dans un champ de version ou d'empreinte, elles
#     passeraient pour des valeurs renseignees, et le refus de scellement ne les
#     verrait pas ;
#   * chaque empreinte a sa definition ecrite. `weights_sha256` est le sha256 de
#     la concatenation des lignes « <sha256><2 espaces><nom de fichier> »
#     TRIEES par nom de fichier -- ce que `aggregate_weights_sha256` recalcule
#     de son cote, et qu'un `sha256sum < liste` verifie a la main.
PROVJSON="$VENV/provenance.json"
json_str() {   # <valeur> -> "valeur" ou null (sentinelle, vide, non mesuree)
  local v="${1:-}"
  v="$(printf '%s' "$v" | tr -d '"')"
  case "${v// /}" in
    ""|"NONFAIT"|"ABSENT"|"INCONNU"|"nondetermine"|"?") printf 'null' ;;
    *) printf '"%s"' "$v" ;;
  esac
}
OPENJSON="\"egress_blocked_test\", \"latency_p50_s\""
if [[ "$DO_HASH" -eq 0 ]]; then
  # --no-hash : les empreintes de poids ne sont pas mesurees, et le fichier le dit
  WFIELD="null"
  AGGJSON="null"
  OPENJSON="$OPENJSON, \"weights_hashing_skipped\""
elif [[ -s "$WLIST" ]]; then
  AGGJSON="\"$(sha256sum <"$WLIST" | cut -d' ' -f1)\""
  WFIELD="$(awk '{gsub(/"/, ""); printf "%s\"%s\": \"%s\"", (NR > 1 ? ", " : ""), $2, $1}' "$WLIST")"
  WFIELD="{ $WFIELD }"
else
  WFIELD="{}"
  AGGJSON="null"
  OPENJSON="$OPENJSON, \"weights_files_absent\""
fi
[[ "$MODEL_REV" =~ ^[0-9a-f]{40}$ ]] || OPENJSON="$OPENJSON, \"model_revision_not_established\""
PORTJSON="$PORT"
[[ "$PORTJSON" =~ ^[0-9]+$ ]] || PORTJSON="null"
cat > "$PROVJSON.tmp" <<EOF
{
  "generated": "$(date -Is)",
  "hostname": "$(hostname)",
  "model": "$(basename "$MODEL")",
  "model_path": "$MODEL",
  "model_revision": $(json_str "$MODEL_REV"),
  "model_revision_source": $(json_str "$REV_SRC"),
  "weights_files": $WFIELD,
  "weights_sha256": $AGGJSON,
  "weights_bytes_total": $WEIGHTBYTES,
  "vllm_version": $(json_str "$VLLMVER"),
  "torch_version": $(json_str "$TORCHVER"),
  "torch_cuda": $(json_str "$TORCHCUDA"),
  "gpu": $(json_str "$GNAME"),
  "driver": $(json_str "$DRIVER"),
  "served_model_name": "$SERVED_NAME",
  "port": $PORTJSON,
  "open": [ $OPENJSON ]
}
EOF
# Un JSON casse finirait dans un rapport signe : on le relit avant de publier,
# et un brouillon invalide n'est PAS publie (il reste a cote, pour la cause).
if ! "$PY" -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' \
      "$PROVJSON.tmp" 2>/dev/null; then
  echo "ECHEC : provenance.json invalide, non publie (brouillon : $PROVJSON.tmp)" >&2
  exit 3
fi
mv -f "$PROVJSON.tmp" "$PROVJSON"
rm -f "$WLIST"

echo "provenance : $ENVMD ($(wc -l <"$ENVMD") lignes)"
echo "provenance : $PROVJSON ($(wc -c <"$PROVJSON") octets, machine)"
echo
sed -n '1,20p' "$ENVMD"
echo "..."
printf '\nRESULTAT : provenance ecrite (uv pip check=%s, %s)\n' "$PIPCHECK" "$GCSUM"
