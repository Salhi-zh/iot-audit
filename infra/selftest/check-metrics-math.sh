#!/bin/bash
# =============================================================================
# check-metrics-math.sh -- verification HORS LIGNE du decoupage serveur
# =============================================================================
# node_gpu_bench.sh lit les histogrammes Prometheus de /metrics pour repartir une
# requete en FILE D'ATTENTE / PREFILL / DECODE, et publie la moyenne et l'intervalle
# de quantile de chacune. Trois fonctions font ce calcul : metrics_delta (difference
# de deux instantanes), metrics_mean, metrics_qbracket.
#
# Pourquoi ce fichier existe : ce calcul ne se voit pas dans la sortie. Un decoupage
# faux -- moyenne prise sur une mauvaise fenetre, quantile lu dans le mauvais
# intervalle -- s'imprime exactement comme un decoupage juste. La seule facon de le
# savoir est de le confronter a une verite calculee AUTREMENT.
#
# Le test est donc DIFFERENTIEL et inter-langage : le code teste est de l'awk, la
# verite est calculee en Python (tri + index), qui ne partage ni l'algorithme ni la
# bibliotheque. Les fonctions sont EXTRAITES de node_gpu_bench.sh, jamais recopiees :
# un test qui teste sa propre copie ne prouve rien.
#
# Les cas ont trois endpoints, comme la grappe reelle -- l'agregation sur N endpoints
# fait partie de ce qu'il faut verifier, et un cas mono-endpoint ne l'exercerait pas.
# Chaque cas est decrit UNE fois (passe de chaque endpoint, valeurs du palier, presence
# ou non dans l'instantane avant) ; les deux instantanes, le multiset du delta et la
# verite en sont DERIVES, et leur coherence arithmetique est verifiee avant d'ecrire
# quoi que ce soit. C'est precisement la faute qui avait produit le premier jeu de cas :
# un instantane ecrit a la main qui ne correspondait pas a sa propre verite, donc un
# test qui mesurait son erreur.
#
# Cas concus (un par propriete) :
#   uniform-1-3        l'exemple publie : 100 valeurs uniformes dans [1,3] s
#   baseline-zero      serveur demarre a l'instant du premier instantane
#   baseline-large     100 000 requetes deja comptees : le delta doit les ignorer
#   single-request     un seul cas
#   no-new-requests    aucun cas nouveau -> NA, jamais 0
#   beyond-last-bound  une valeur au-dela de la derniere borne finie -> intervalle ouvert
#   on-a-bound         des valeurs EXACTEMENT sur les bornes
#   long-tail          queue epaisse
#   ttft-bounds        la MEME logique contre la liste de bornes de TTFT (23 bornes
#                      resserrees, jusqu a 0,001 s) : les bornes sont lues sur le reseau,
#                      elles ne sont pas supposees
#   empty-before       instantane AVANT vide : le piege que `FNR == NR` ne distingue pas
#   partial-before     un seul endpoint dans l'instantane AVANT
#   counter-reset      serveur redemarre entre les deux instantanes -> RESET 1
# Plus 300 cas aleatoires (graine fixe), repartis entre les deux listes de bornes.
#
# Les bornes sont celles que /metrics publiait le 2026-09-28, ETIQUETTE POUR ETIQUETTE
# (l'echantillon brut est conserve avec la passe : evidence/2026-09-28/
# instrument-v5-metrics-wire/metrics-sample.txt). L'etiquette compte : vLLM ecrit
# « 1.0 », pas « 1 », et l'instrument convertit cette etiquette en nombre. Le
# generateur ecrit les memes octets, donc le test traverse le meme chemin.
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BENCH="${BENCH_SCRIPT:-$ROOT/infra/scripts/node_gpu_bench.sh}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

[ -f "$BENCH" ] || { echo "instrument introuvable : $BENCH" >&2; exit 2; }

# ------------------------------------------------------------------ extraction
# Une fonction va de « nom() { » a la premiere ligne qui vaut exactement « } ».
# Les programmes awk qu'elles embarquent sont INDENTES, donc leur accolade fermante
# n'est jamais en colonne 0 : la premiere ligne « } » brute termine bien la fonction.
extract() {  # $1 = nom de fonction
  awk -v f="$1" '
    $0 ~ "^" f "\\(\\)" { on = 1 }
    on { print }
    on && $0 == "}" { exit }' "$BENCH"
}
FUNCS="$TMP/funcs.sh"
: > "$FUNCS"
for f in metrics_delta metrics_mean metrics_qbracket; do
  extract "$f" >> "$FUNCS"; echo >> "$FUNCS"
  grep -q "^$f()" "$FUNCS" || { echo "extraction : $f absente de $BENCH" >&2; exit 2; }
done
# Les fonctions extraites doivent etre du shell valide AVANT de mesurer quoi que ce
# soit. Sans ce controle, un instrument casse ne produit que des champs vides et le
# rapport parle de nombres qui ne correspondent pas -- alors que la cause est unique et
# nommable : les programmes awk sont entre GUILLEMETS SIMPLES, donc une apostrophe
# ASCII dans un commentaire ecrit en francais a l'interieur du programme termine la
# citation, et la suite du programme est lue comme du shell.
if ! bash -n "$FUNCS" 2> "$TMP/funcs.err"; then
  echo "INSTRUMENT INVALIDE : les fonctions extraites ne sont pas du shell valide" >&2
  sed 's/^/  /' "$TMP/funcs.err" >&2
  echo "  cause la plus probable : une apostrophe ASCII dans un commentaire a l interieur" >&2
  echo "  d un programme awk (programme entre guillemets simples). bash -n sur l instrument" >&2
  echo "  le dit aussi, plus tot." >&2
  exit 2
fi
echo "instrument : $BENCH"
echo "extrait    : 3 fonctions, $(wc -l < "$FUNCS") lignes"

# Controle negatif : la variante HISTORIQUE de metrics_delta, qui designait « le
# premier fichier » par `FNR == NR`. Elle doit se comporter DIFFEREMMENT sur
# l'instantane vide -- un test qui passerait sur l'ancien code comme sur le nouveau
# ne prouverait rien sur ce cas.
sed 's/FILENAME == f_av/FNR == NR/; s/FILENAME == f_ap/1/' "$FUNCS" > "$TMP/funcs-old.sh"

# ------------------------------------------------------------------ generateur
python3 - "$TMP" <<'PY'
import os, random, sys

OUT = sys.argv[1]
# Listes REELLES de bornes, telles que /metrics les publie (2026-09-28). Deux listes
# differentes : l'e2e a 21 bornes larges, le TTFT en a 22 et va jusqu'a 0,001 s.
E2E = ["0.3", "0.5", "0.8", "1.0", "1.5", "2.0", "2.5", "5.0", "10.0", "15.0", "20.0",
       "30.0", "40.0", "50.0", "60.0", "120.0", "240.0", "480.0", "960.0", "1920.0", "7680.0"]
TTFT = ["0.001", "0.005", "0.01", "0.02", "0.04", "0.06", "0.08", "0.1", "0.25", "0.5",
        "0.75", "1.0", "2.5", "5.0", "7.5", "10.0", "20.0", "40.0", "80.0", "160.0",
        "640.0", "2560.0"]
METRIC = "e2e_request_latency_seconds"
Q = [0.5, 0.95, 0.99]
NEP = 3


def counters(labels, base_n, samples, base_mean):
    """Compteurs CUMULATIFS absolus d'un endpoint, au format de /metrics.

    `base_n` requetes deja terminees AVANT l'instantane, toutes de latence `base_mean`
    (donc dans le premier bucket) : une grappe au repos a un passe, et ce passe doit
    s'annuler dans le delta. Les valeurs sont ecrites en flottants, comme Prometheus.
    """
    return {
        "buckets": {b: base_n + sum(1 for x in samples if x <= float(b)) for b in labels},
        "inf": base_n + len(samples),
        "count": base_n + len(samples),
        "sum": base_n * base_mean + sum(samples),
    }


def render(state, labels):
    """Rend un etat agrege comme vLLM le publie (famille e2e_request_latency)."""
    out = ['vllm:%s_bucket{engine="0",le="%s",model_name="m"} %s'
           % (METRIC, b, str(float(round(state["buckets"][b], 6)))) for b in labels]
    out.append('vllm:%s_bucket{engine="0",le="+Inf",model_name="m"} %s'
               % (METRIC, str(float(round(state["inf"], 6)))))
    out.append('vllm:%s_sum{engine="0",model_name="m"} %s' % (METRIC, str(state["sum"])))
    out.append('vllm:%s_count{engine="0",model_name="m"} %s'
               % (METRIC, str(float(round(state["count"], 6)))))
    return "\n".join(out) + "\n"


def add(a, b, labels):
    return {"buckets": {k: a["buckets"][k] + b["buckets"][k] for k in labels},
            "inf": a["inf"] + b["inf"], "count": a["count"] + b["count"],
            "sum": a["sum"] + b["sum"]}


def zero(labels):
    return {"buckets": {k: 0 for k in labels}, "inf": 0, "count": 0, "sum": 0.0}


def build(eps, labels):
    """(instantane avant agrege, instantane apres agrege, multiset du delta).

    `eps` : une entree par endpoint, (base_n, valeurs_du_palier, dans_l_instantane_avant).
    Le multiset du delta est la liste des valeurs dont l'histogramme vaut exactement
    `apres - avant` : les valeurs du palier de TOUS les endpoints, plus la passe des
    endpoints ABSENTS de l'instantane avant (leur passe ne s'annule pas).
    """
    base_mean = float(labels[0]) / 2      # dans le premier bucket, par construction
    before, after, pooled = zero(labels), zero(labels), []
    for base, lvl, in_before in eps:
        after = add(after, counters(labels, base, lvl, base_mean), labels)
        if in_before:
            before = add(before, counters(labels, base, [], base_mean), labels)
        else:
            pooled += [base_mean] * base
        pooled += list(lvl)
    # Coherence : la description et l'arithmetique des instantanes doivent dire la meme
    # chose. Si elles divergent, la verite est celle d'un AUTRE cas.
    assert len(pooled) == after["count"] - before["count"], "delta : compte incoherent"
    assert abs(sum(pooled) - (after["sum"] - before["sum"])) < 1e-6, "delta : somme incoherente"
    return before, after, pooled


def le_truth(before, after, labels):
    """Lignes « LE » attendues : cumul par borne apres soustraction, +Inf inclus.

    Les deltas negatifs sont ramenes a 0, comme dans l'instrument : un compteur
    cumulatif ne recule que si le serveur a redemarre, et ce fait est publie a part
    (RESET) plutot que propage dans les nombres.
    """
    pairs = ["%s=%d" % (b, max(0, round(after["buckets"][b] - before["buckets"][b])))
             for b in labels]
    pairs.append("+Inf=%d" % max(0, round(after["inf"] - before["inf"])))
    return ",".join(pairs)


def truth(before, after, pooled, labels, reset_forced=None):
    """Verite du cas, calculee a partir des instantanes et du multiset -- jamais des
    compteurs cumules, qui sont justement l'algorithme soumis au test."""
    cnt = round(after["count"] - before["count"])
    s = after["sum"] - before["sum"]
    backward = (after["count"] < before["count"] or after["sum"] < before["sum"]
                or any(after["buckets"][k] < before["buckets"][k] for k in labels))
    exp = {"count": cnt, "sum": s, "reset": 1 if (reset_forced or backward) else 0,
           "le": le_truth(before, after, labels)}
    if cnt > 0 and len(pooled) == cnt:
        exp["mean"] = "%.4f" % (s / cnt)
        ordered = sorted(pooled)
        for q in Q:
            # L'awk teste `cum >= target` : le plus petit ENTIER de valeurs >= target.
            idx = min(max(int(-(-q * cnt // 1)) - 1, 0), cnt - 1)
            true = ordered[idx]
            hi = next((b for b in labels if float(b) >= true), None)
            if hi is None:
                exp["q%g" % (q * 100)] = ">[%.3f]" % float(labels[-1])
            else:
                j = labels.index(hi)
                lo = float(labels[j - 1]) if j > 0 else 0.0
                exp["q%g" % (q * 100)] = "[%.3f;%.3f]" % (lo, float(hi))
    else:
        # Aucun palier mesurable : l'instrument doit dire NA, jamais 0.
        exp.update(mean="NA", **{"q%g" % (q * 100): "NA" for q in Q})
    return exp


CASES = []


def emit(name, note, before, after, pooled, labels, reset_forced=None, before_raw=None):
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "before"), "w") as fh:
        fh.write(before_raw if before_raw is not None else render(before, labels))
    with open(os.path.join(d, "after"), "w") as fh:
        fh.write(render(after, labels))
    exp = truth(before, after, pooled, labels, reset_forced)
    cols = ["count", "sum", "reset", "mean", "q50", "q95", "q99", "le"]
    with open(os.path.join(d, "expected.tsv"), "w") as fh:
        fh.write(name + "\t" + "\t".join(str(exp[c]) for c in cols) + "\n")
    with open(os.path.join(d, "note.txt"), "w") as fh:
        fh.write(note + "\n")
    with open(os.path.join(d, "samples.txt"), "w") as fh:
        fh.write(" ".join("%g" % x for x in sorted(pooled)) + "\n")
    CASES.append(name)


def designed(name, note, eps, labels=E2E):
    before, after, pooled = build(eps, labels)
    emit(name, note, before, after, pooled, labels)


B = [1334, 1334, 1334]                              # passe courant d'une grappe servie
uni = [1.0 + 2.0 * i / 99 for i in range(100)]      # uniforme dans [1,3] s
designed("uniform-1-3", "100 valeurs uniformes dans [1,3] s ; 1334 requetes deja comptees",
         [(B[0], uni, True), (B[1], [], True), (B[2], [], True)])
designed("baseline-zero", "aucune requete avant le premier instantane",
         [(0, [1.2, 1.9, 2.3], True), (0, [], True), (0, [1.4], True)])
designed("baseline-large", "100 000 requetes deja comptees : le delta doit les ignorer",
         [(100000, [1.1, 1.4, 1.4, 2.9, 0.4], True), (100000, [], True), (100000, [], True)])
designed("single-request", "un unique cas, sur un seul endpoint",
         [(7, [1.35], True), (7, [], True), (7, [], True)])
designed("no-new-requests", "aucun cas pendant le palier : la moyenne doit valoir NA",
         [(900, [], True), (900, [], True), (900, [], True)])
designed("beyond-last-bound", "une valeur au-dela de la derniere borne : intervalle OUVERT",
         [(10, [9000.0, 1.5, 1.5], True), (10, [], True), (10, [], True)])
designed("on-a-bound", "valeurs exactement sur les bornes 1,0 / 2,0 / 2,5",
         [(50, [1.0, 2.0, 2.5], True), (50, [], True), (50, [], True)])
tail = ([1.7, 1.7, 2.0, 2.0, 2.0, 2.1, 2.2, 3.0, 4.9, 9.5] * 3)[:28]
designed("long-tail", "28 valeurs, queue jusqu'a 9,5 s",
         [(0, tail[:10], True), (0, tail[10:20], True), (0, tail[20:], True)])
# Meme instrument, AUTRE liste de bornes : TTFT va jusqu'a 0,001 s et une valeur peut
# depasser sa derniere borne finie (2560) -> intervalle ouvert.
designed("ttft-bounds", "la meme logique contre la liste de bornes de TTFT (0,001 s a 2560 s)",
         [(500, [0.004, 0.02, 0.09, 1.5, 3000.0], True), (500, [0.03, 0.5], True),
          (500, [0.0008, 0.001, 2.5], True)], labels=TTFT)

# Instantane AVANT vide : rien n'a ete lu (curl en echec). La difference vaut alors le
# compteur TOTAL de l'apres -- aucun passe n'est annulable -- et surtout PAS un compte
# negatif. C'est l'appelant qui refuse ce cas, en comparant le nombre d'endpoints vus
# dans l'instantane au nombre attendu. `in_before=False` partout : la passe reste dans
# le delta, et le fichier avant est ecrit VIDE, ce qui est exactement « aucun passe ».
b, a, p = build([(500, [1.1, 1.3], False), (500, [2.0], False), (500, [0.9, 1.0, 1.1], False)], E2E)
emit("empty-before", "instantane AVANT vide : aucun passe exploitable", b, a, p, E2E, before_raw="")

# Instantane AVANT partiel : un seul des trois endpoints. Le delta des deux autres est
# leur TOTAL depuis leur demarrage, pas leur palier -- c'est pour cela que l'instrument
# publie le nombre d'endpoints vus.
b, a, p = build([(400, [1.1, 1.3], True), (400, [2.0], False), (400, [], False)], E2E)
emit("partial-before", "instantane AVANT avec un seul endpoint sur trois", b, a, p, E2E)

# Compteurs reinitialises : le serveur a redemarre entre les deux instantanes. Attendu :
# RESET 1, deltas ramenes a 0, et NA partout -- jamais un nombre plausible.
stale = {"buckets": {b: 1000 for b in E2E}, "inf": 1000, "count": 1000, "sum": 0.2 * 1000}
fresh = counters(E2E, 0, [1.1] * 30, 0.15)
emit("counter-reset", "serveur redemarre entre les deux instantanes : RESET doit sortir",
     stale, fresh, [], E2E, reset_forced=1)

# --- 300 cas aleatoires, graine fixe : distributions, passes ET listes de bornes varies
rnd = random.Random(20260928)


def draw(kind, labels):
    n = rnd.choice([1, 2, 5, 17, 60, 200, 900, 2000])
    hi = float(labels[-1]) * 1.5
    lo = float(labels[0]) * 0.1
    if kind == 0:
        return [rnd.uniform(lo, hi / 4) for _ in range(n)]
    if kind == 1:
        return [rnd.expovariate(1.0 / (hi / 20)) for _ in range(n)]
    if kind == 2:
        return [rnd.choice([lo, lo, hi / 8, hi / 8, hi / 2]) for _ in range(n)]
    if kind == 3:
        return [rnd.uniform(lo, lo * 5) for _ in range(max(0, n - 3))] + \
               [rnd.uniform(hi / 3, hi * 2) for _ in range(min(3, n))]
    return [rnd.uniform(lo, hi) for _ in range(n)]


for i in range(300):
    labels = E2E if i % 2 == 0 else TTFT
    eps = [(rnd.choice([0, 1, 37, 1334, 99999]), draw(rnd.randrange(5), labels), True)
           for _ in range(NEP)]
    before, after, pooled = build(eps, labels)
    emit("rand-%03d" % i, "aleatoire (graine 20260928)", before, after, pooled, labels)

with open(os.path.join(OUT, "cases.txt"), "w") as fh:
    fh.write("\n".join(CASES) + "\n")
print("cas generes : %d (coherence arithmetique verifiee a la generation)" % len(CASES))
PY
gen_rc=$?
[ "$gen_rc" = 0 ] || { echo "GENERATION EN ECHEC (rc=$gen_rc) : la description d'un cas et son arithmetique divergent" >&2; exit 1; }

# ------------------------------------------------------------------- execution
# Le lanceur vit dans un fichier, pas dans une chaine : les programmes awk des
# fonctions contiennent guillemets simples et `$`, et les re-echapper dans une commande
# aurait fait courir un code DIFFERENT de l'instrument.
cat > "$TMP/run-one.sh" <<'EOS'
set -u
. "$FUNCS"
d="$1"
dd="$(metrics_delta "$d/before" "$d/after" e2e_request_latency_seconds)"
cnt="$(printf '%s\n' "$dd" | awk '/^COUNT /{print $2}')"
sum="$(printf '%s\n' "$dd" | awk '/^SUM /{print $2}')"
res="$(printf '%s\n' "$dd" | awk '/^RESET /{print $2}')"
les="$(printf '%s\n' "$dd" | awk '/^LE /{print $2 "=" $3}' | paste -sd, -)"
mean="$(metrics_mean "$d/before" "$d/after" e2e_request_latency_seconds)"
q50="$(metrics_qbracket "$d/before" "$d/after" e2e_request_latency_seconds 0.5)"
q95="$(metrics_qbracket "$d/before" "$d/after" e2e_request_latency_seconds 0.95)"
q99="$(metrics_qbracket "$d/before" "$d/after" e2e_request_latency_seconds 0.99)"
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
  "$(basename "$d")" "$cnt" "$sum" "$res" "$mean" "$q50" "$q95" "$q99" "$les"
EOS

: > "$TMP/actual.tsv"
while read -r c; do
  [ -n "$c" ] || continue
  FUNCS="$FUNCS" bash "$TMP/run-one.sh" "$TMP/$c" >> "$TMP/actual.tsv" || \
    echo "$c : le lanceur a echoue" >&2
done < "$TMP/cases.txt"
echo "cas executes : $(wc -l < "$TMP/actual.tsv")"

# -------------------------------------------------------------------- verdict
python3 - "$TMP" <<'PY'
import os, subprocess, sys

tmp = sys.argv[1]
DESIGNED = ["uniform-1-3", "baseline-zero", "baseline-large", "single-request",
            "no-new-requests", "beyond-last-bound", "on-a-bound", "long-tail",
            "ttft-bounds", "empty-before", "partial-before", "counter-reset"]
COLS = ["count", "sum", "reset", "mean", "q50", "q95", "q99", "le"]
# Colonnes comparees EXACTEMENT (chaines) : les intervalles de quantile sont des
# chaines (« [1.500;2.000] », « >[7680.000] », « NA ») et une tolerance numerique y a
# aucun sens. Seules la somme et la moyenne sont des nombres -- et la somme est ecrite
# par l'instrument avec 6 decimales, d ou la tolerance.
EXACT = {"count", "reset", "le", "q50", "q95", "q99"}


def delta_cum(case):
    """Delta cumule par borne, lu dans les deux fichiers du cas. Sert a mesurer l ecart
    de l INTERPOLATION de Prometheus, pas a valider l instrument."""
    cum = {}
    for f, sgn in (("before", -1), ("after", 1)):
        p = os.path.join(tmp, case, f)
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            continue
        for l in open(p):
            if "_bucket{" in l:
                k = l.split('le="')[1].split('"')[0]
                cum[k] = cum.get(k, 0) + sgn * float(l.split()[-1])
    return cum


exp = {}
for line in open(os.path.join(tmp, "cases.txt")):
    c = line.strip()
    if c:
        exp[c] = open(os.path.join(tmp, c, "expected.tsv")).read().rstrip("\n").split("\t")
act = {}
for line in open(os.path.join(tmp, "actual.tsv")):
    f = line.rstrip("\n").split("\t")
    act[f[0]] = f

fails = {}
for name in exp:
    if name not in act:
        fails[name] = "aucune sortie produite"
        continue
    e, a = exp[name], act[name]
    why = []
    for i, c in enumerate(COLS):
        ev, av = e[1 + i], a[1 + i]
        if c == "le":
            # Compare comme un ENSEMBLE : metrics_delta parcourt une table de hachage,
            # donc l ordre des bornes dans sa sortie n est pas defini.
            if sorted(ev.split(",")) != sorted(av.split(",")):
                missing = set(ev.split(",")) - set(av.split(","))
                extra = set(av.split(",")) - set(ev.split(","))
                why.append("le : %d manquante(s) %s, %d en trop %s"
                           % (len(missing), sorted(missing)[:4], len(extra), sorted(extra)[:4]))
            continue
        if c in EXACT or ev == "NA" or av == "NA":
            if ev != av:
                why.append("%s : attendu %s, obtenu %s" % (c, ev, av))
            continue
        tol = 1e-3 if c == "sum" else 2e-4
        try:
            if abs(float(ev) - float(av)) > tol:
                why.append("%s : attendu %s, obtenu %s" % (c, ev, av))
        except ValueError:
            why.append("%s : non numerique (%s / %s)" % (c, ev, av))
    if why:
        fails[name] = "; ".join(why)

for name in DESIGNED:
    note = open(os.path.join(tmp, name, "note.txt")).read().strip()
    print("  %s  %-17s %s" % ("ECHEC " if name in fails else "ok    ", name, note))
    if name in fails:
        fails[name] = fails[name] + " | " + note

# L'intervalle doit contenir le vrai quantile -- sinon il ne sert a rien -- et
# l'interpolation de Prometheus doit, elle, s'en ecarter franchement. C'est TOUT
# l'argument du refus d'interpoler : sur ce cas, le bucket qui porte le p95 est si large
# que supposer une repartition uniforme dedans rend 4,5 s au lieu de 2,899 s, un nombre a
# trois decimales qui a l'air exact et se trompe de 55 %.
cum = delta_cum("uniform-1-3")
n = round(cum.get("+Inf", 0))
target = 0.95 * n
true95 = float(open(os.path.join(tmp, "uniform-1-3", "samples.txt")).read().split()[int(-(-target // 1)) - 1])
prev, hi, c_prev = 0.0, None, 0
for b in sorted([k for k in cum if k != "+Inf"], key=float):
    if cum[b] >= target:
        hi = b
        break
    prev, c_prev = float(b), cum[b]
if hi is not None:
    interp = prev + (float(hi) - prev) * (target - c_prev) / max(1e-9, cum[hi] - c_prev)
    err = abs(interp - true95) / true95
    ok = err > 0.4
    print("  %s  %-17s vrai p95=%.4f s -> intervalle publie %s | interpolation=%.3f s "
          "(ecart %.0f %%)" % ("ok    " if ok else "ECHEC ", "interpolation", true95,
                               act["uniform-1-3"][6], interp, err * 100))
    if not ok:
        fails["uniform-1-3"] = ("l'interpolation est trop proche du vrai p95 pour que ce "
                                "cas documente le refus d'interpoler")

# --- controle negatif : l'ancien `FNR == NR` doit se tromper sur l'instantane vide.
old = os.path.join(tmp, "funcs-old.sh")
prg = ('set -u; . "$1"; metrics_delta "$2/before" "$2/after" e2e_request_latency_seconds '
       '| awk \'/^COUNT /{c=$2} /^LE /{k++} END{print c+0" "(k+0)}\'')
out = subprocess.run(["bash", "-c", prg, "x", old, os.path.join(tmp, "empty-before")],
                     capture_output=True, text=True).stdout.split()
print()
if len(out) == 2 and int(out[0]) < 0 and int(out[1]) == 0:
    print("  controle negatif ok : sur l'instantane vide, l'ancien idiome `FNR == NR` rend "
          "COUNT=%s et %s borne(s) -- il se trompe, et le test le distingue" % tuple(out))
else:
    print("  controle negatif ECHEC : l'ancien idiome rend %r -- le cas ne distingue plus rien" % (out,))
    fails["controle-negatif"] = "l'ancienne variante ne se distingue plus"

print()
if fails:
    print("VERDICT : ECHEC -- %d cas en defaut (sur %d)" % (len(fails), len(exp)))
    for n_, w in list(fails.items())[:25]:
        print("  %s : %s" % (n_, w))
    if len(fails) > 25:
        print("  ... et %d autres" % (len(fails) - 25))
    sys.exit(1)
print("VERDICT : OK -- %d cas (%d concus + 300 aleatoires), 0 defaut" % (len(exp), len(DESIGNED)))
PY
