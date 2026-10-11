#!/bin/bash
# =============================================================================
#  gpu-bench-node.sh -- PARALLELISME et USAGE GPU reels (2026-09-15)
# =============================================================================
#  Pourquoi ce banc existe
#  -----------------------
#  Tout ce qui etait publie avant etait cote CLIENT :
#     - latency-node.sh  -> latence p50/p95 SEQUENTIELLE, prefixe CHAUD
#     - V11a/V11b        -> 57,9 req/s agreges, p95 ~0,29 s
#  Ces deux chiffres ne decrivent PAS la charge reelle du projet (une photo +
#  une sortie JSON courte, ~1,3 s par requete). Aucune mesure n'existait non
#  plus de la SATURATION DES GPU. Ce banc mesure les deux.
#
#  Modes (NON DESTRUCTIFS : aucun redemarrage de service, aucune ecriture hors $HOME) :
#     MODE=sample   echantillonne nvidia-smi en arriere-plan, rend la main
#     MODE=load     charge concurrente a concurrence FIXE (peut etre limitee par le client)
#     MODE=sweep    BALAYAGE de concurrence -> trouve le genou. Echantillonne pendant,
#                   et publie le decoupage serveur (file / prefill / decode).
#     MODE=collect  imprime l'echantillon + resume + arguments de lancement vLLM
#
#  usage (SUR UN NOEUD) :
#     MODE=collect|sample|load|sweep bash gpu-bench-node.sh
#     Un MODE inconnu sort en erreur 2 (avant : il tombait dans le bloc `collect`
#     et imprimait un rapport plausible).
#     La topologie (endpoints) est lue dans infra/config/cluster.env ; URLS=... prime.
#
#  2026-09-28 (v3) -- corrections de MESURE, toutes dans run_level / load :
#     * le debit et p50/p95 ne comptent plus que les reponses HTTP 200. Avant,
#       une requete en echec (ou un timeout de 120 s) entrait dans le debit ET
#       dans les percentiles : au palier sature -- celui que le balayage cherche
#       -- le debit etait gonfle et p95 fixe par le timeout.
#     * l'echantillonneur GPU couvre TOUT le palier (fichier d'arret cree apres le
#       dernier travailleur). Avant il s'arretait a t echantillons : la ligne
#       « GPU : » ne decrivait que le PREFIXE du palier, jamais sa queue.
#     * le nombre de noeuds n'est plus code en dur (c*3, /3) : il est compte dans
#       URLS. Les adresses suivaient la config, l'arithmetique non.
#     * le nom servi vient de cluster.env (QWEN_SERVED_NAME), comme dans les deux
#       scripts per-noeud voisins ; le litteral du 2026-09-15 reste le repli.
#     Et : repli de config desormais BRUYANT, code mort de MODE=sample retire,
#     p50/p95 a 0 (au lieu de vide) quand un palier ne rend aucune reponse.
#     Sortie d'un palier : « %5d ok » remplace « %5d req » -- le nombre compte
#     desormais des succes, pas des tentatives.
#
#  2026-09-28 (v4) -- la ligne « GPU : » d'un palier ne compte plus que les
#  echantillons PRIS DANS l'intervalle mesure [start, end], et publie la MEDIANE.
#     L'echantillonneur est lance juste AVANT que `start` soit releve : sa premiere
#     lecture decrit donc un GPU encore au repos (le palier precedent vient de
#     rendre ses dernieres requetes), et l'ancien code la comptait comme un
#     echantillon du palier. Or, a 16 requetes par noeud, le SM vaut 100 % pendant
#     TOUT le palier : ce seul echantillon a ~0 % etait la seule chose que la
#     moyenne mesurait vraiment, et il la deplaqait de 100/n points -- 8,3 a T=12,
#     soit exactement le « +/- 8 points » releve plus tot le meme jour. Ce n'etait
#     pas du bruit : c'etait un artefact QUANTIFIE, un nombre entier
#     d'echantillons faux, jamais une fraction.
#     Mesure directe -- sonde independante horodatee a 1 Hz, plus un exemplaire
#     instrumente qui conserve le fichier brut : un palier produit 13 echantillons
#     dont l'un, a 1,4 ms AVANT `start`, lit 0 % / 12,7 W (GPU au repos) ; les 12
#     autres lisent 100 %. 12*100/13 = 92,3 % -- la valeur observee. Le filtre
#     [start, end] retire ce treizieme echantillon et la moyenne passe a 100,0 %.
#     Il subsiste une course de ~2 ms entre le `date` de l'echantillonneur et celui
#     de run_level : si la premiere lecture tombait APRES `start`, elle serait
#     conservee (moyenne 91,7 %, min 0 %). D'ou la MEDIANE, publiee a cote :
#     insensible a 1-2 echantillons parasites, elle vaut 100 % dans les deux cas.
#     Une divergence moy/med signale que l'artefact est encore la.
#     (Mediane par histogramme : utilization.gpu est un entier 0..100, et `asort`
#     est une extension gawk absente de mawk, l'awk installe sur les noeuds.)
#
#  2026-09-28 (v5) -- deux changements, tous deux de PROVENANCE plus que de calcul :
#     * la charge utile (prompt, max_tokens, temperature) est lue dans cluster.env, comme
#       les endpoints et le nom servi. Elle etait jusque-la recopiee en clair dans ce
#       fichier ET dans vllm-service.sh (226 octets identiques) : editer l'une faisait
#       diverger SANS AUCUN SIGNAL ce que `health` valide de ce que le banc mesure.
#       Le squelette JSON reste en code ; infra/selftest/check-payload-consistency.sh
#       echoue si les deux copies cessent d'etre identiques. collect/load/sweep impriment
#       desormais la charge et sa source.
#     * sweep publie un decoupage COTE SERVEUR sur la MEME fenetre que le debit et le
#       p50 : file d'attente, prefill, decode, inference, TTFT et e2e, lus dans les
#       histogrammes Prometheus de /metrics sur les trois serveurs, differenties entre un
#       instantane pris avant les requetes du palier et un pris apres. Un decoupage qui ne
#       s'applique pas a la meme fenetre ne serait pas une mesure : c'est pourquoi il vit
#       ici et non dans un outil separe. Il imprime aussi l'ecart entre le nombre de
#       requetes vues par le SERVEUR et le nombre de 200 vus par le CLIENT -- un ecart
#       large veut dire que les deux lignes ne parlent pas des memes requetes.
#       Les MOYENNES sont exactes (SUM/COUNT, entiers du serveur). Les QUANTILES sont
#       rendues comme l'INTERVALLE DE BUCKET qui les contient, jamais interpolees :
#       `histogram_quantile` de Prometheus suppose une repartition uniforme dans le
#       bucket, ce qui est faux pour celui qui porte la queue -- mesure sur une
#       distribution synthetique connue, il rendait 4,500 s la ou le vrai p95 valait
#       2,909 s. Le bracket contient la valeur et dit a quelle resolution on la connait.
#       Trois proprietes de ce decoupage sont SURVEILLEES a chaque palier, et n'apparaissent
#       que si elles manquent : sur COMBIEN d'endpoints il porte (`grep -c` par instantane,
#       un serveur publiant une occurrence), si les compteurs etaient MONOTONES (RESET 1 =
#       serveur redemarre entre les deux instantanes), et si le compte serveur colle au
#       compte client. Un decoupage calcule sur deux endpoints sur trois serait
#       silencieusement un decoupage d'une AUTRE grappe.
#
#  2026-09-28 (v6) -- la FILE d'attente cesse d'etre publiee comme une seule moyenne.
#     Mesure du 2026-09-28 : a 32/48/64 req/noeud, `file moy=0.0001s` pendant que
#     `num_requests_waiting` restait a 0 -- file effectivement vide. Mais a 96 et 128,
#     des requetes ATTENDENT (jusqu'a 26 en attente, cache KV plein a 100 %) et la
#     moyenne ne bouge presque pas : 0.0002 puis 0.0017 s. Une moyenne par requete
#     dilue un pic court -- elle repond « combien de temps perdu en moyenne », jamais
#     « quelqu'un a-t-il attendu ». Deux nombres levent cela, tous deux GRATUITS :
#       * `total` = SUM, la somme EXACTE des attentes. Toute attente etant >= 0, aucune
#         requete ne peut depasser le total : c'est une borne superieure RIGOUREUSE du
#         maximum, et elle ne suppose rien sur la forme de la distribution.
#       * `max` = l'intervalle de bucket qui contient le maximum observe, et `>0.3s` =
#         combien de requetes ont franchi la plus petite borne finie que vLLM publie
#         pour cette metrique (0,3 s, releve sur /metrics). Sous 0,3 s, les buckets ne
#         resolvent plus rien : c'est `total` qui encadre.
#     Le decoupage file/prefill/decode n'est pas touche -- seule la file gagne sa forme.
#
#  2026-09-28 (v7) -- EN-TETE SEUL : aucun calcul ne change. Ce qui change est ce que
#  l'en-tete AFFIRME, apres deux mesures du meme jour
#  (evidence/2026-09-28/risk-probes/kv-peak-and-decomposition/).
#     * PROVENANCE DU TAUX DE CACHE. Le « 98,1 % de touches de cache de prefixe » cite
#       dans le bloc v6 est le taux PAR PALIER du palier 96 (153 408 / 156 416 = 0,9808),
#       calcule par analyse-jauges.py. Ce n'est PAS le `mm_cache` (embeddings visuels)
#       du 2026-09-15, qui vaut la meme chose par coincidence ; le taux CUMULE depuis le
#       demarrage du serveur, lui, vaut 97,2 %. Deux nombres, deux questions : ne pas
#       les confondre, et ne pas « corriger » l'un par l'autre.
#     * LE MODELE KV(n) = P + n.g EST EXACT, ET C'EST UNE PROPRIETE DES BLOCS. Le cache
#       publie 9 104 jetons = 569 blocs de 16. Sur les 6 paliers non satures 4..64, les
#       pics echantillonnes a 23 Hz SUR le noeud sont EXACTEMENT alignes (residu nul) :
#       P ~ 51 blocs, g ~ 6 blocs par requete. Un ajustement qui inclut un point proche
#       de la saturation (le 96 de la journee) part ailleurs -- P ~ 1 047 jetons, g ~ 85.
#       C'est le CHOIX DES PALIERS qui porte l'incertitude, pas la frequence : passer de
#       1 Hz a 23 Hz ne deplace les limites que de ~0,8 requete, ajouter le palier 96
#       deplace P de +28 %. Le chiffre ROBUSTE est donc en blocs : 569 / (51 + 6) ~ 10
#       requetes simultanees par serveur quand chaque prefixe est paye.
#     * LA MEMOIRE COUTE DEUX FOIS, PAS UNE. SOUS la limite, des prefixes distincts
#       remplissent le cache KV (4,4x des 8 req/noeud) sans changer le debit. AU-DESSUS,
#       l'admission plafonne (~10 mesurage direct : `num_requests_running` = 10 que l'on
#       offre 16 ou 32) ET le cache de PREFIXE s'EFFONDRE A ZERO (prefix_cache 0 %,
#       `prompt_tokens_cached` +0), donc chaque requete ADMISE refait tout son prefixe --
#       inference moyenne x4,7 en passant de 8 a 10 requetes en cours. Le cache
#       MULTIMODAL, lui, reste a 100 % des deux cotes : le surcout n'est PAS l'encodeur
#       visuel. Un rapport de debit A/B (6x a 16 req/noeud) ne mesure donc ni le cout de
#       calcul d'un prefixe distinct, ni un simple rapport de concurrence.
#
#  2026-09-28 (v8) -- trois ajouts, tous OPT-IN : sans les nouveaux boutons, le banc se
#  comporte exactement comme en v7 (meme corps JSON, memes corps par travailleur).
#     * `MAXTOK_SET="32 96 192 320"` -- plusieurs PALIERS de longueur de reponse. Jusqu'ici
#       max_tokens etait une seule valeur, donc g -- le cout KV d'une requete -- etait une
#       CONSTANTE, et la pente KV (96,2 tok/req) a ete lue comme « g = 96 jetons = 6 blocs
#       = max_tokens » (note : la mesure v9 montre ~73 jetons moy, fin EOS, et non 96 ; la
#       pente n'etait qu'une coincidence de TAILLE DE BLOC, corrigee en v9). MAXTOK_SET
#       casse cette constante : chaque travailleur recoit un palier, et le faisceau de
#       mesures tiercees a REVELE la coquille -- le probe de gen-tokens montre que la
#       longueur reelle suit EOS avant le plafond, pas max_tokens.
#       C'est un test du modele HORS de son calibrage. Sans MAXTOK_SET, le corps envoye
#       reste exactement celui de cluster.env, donc celui que health valide (voir
#       infra/selftest/check-payload-consistency.sh : ce controle porte sur le DEFAUT).
#     * `VARY_ROTATE=1` -- avec VARY_PREFIX=1, l'image est FIXEE par travailleur, donc le
#       jeu de prefixes en circulation vaut la CONCURRENCE. VARY_ROTATE=1 fait avancer
#       chaque travailleur d'un corps par requete : le jeu de prefixes devient `NBODIES`
#       quelle que soit la concurrence, et l'on peut demander au cache COMBIEN de prefixes
#       distincts il retient, au lieu de combien de requetes il admet.
#     * `KV_SAMPLE=1` (defaut) -- un echantillonneur de jauges tourne PENDANT chaque palier
#       et lit les trois endpoints : le PIC de `kv_cache_usage_perc`, l'`en cours` et
#       l'`en attente` max deviennent une COLONNE du palier, sur la MEME fenetre que le
#       debit. Jusqu'ici il fallait lancer un echantillonneur a part pour les avoir.
#       Le taux de reutilisation du cache de prefixe, lui, se lit sans rien lancer de plus :
#       il sort des deux instantanes /metrics deja pris. `KV_SAMPLE_S` regle la periode.
#
#  2026-09-28 (v9) -- le modele n'a plus besoin d'assumer la longueur generee.
#  La longueur REELLEMENT generee est publiee par palier, avec sa REPARTITION :
#  moyenne (`request_generation_tokens`), p50 et max (brackets), et la part de requetes
#  finies sur le plafond `max_tokens` (`request_success_total{finished_reason="length"}`),
#  le tout sur la MEME fenetre que le pic KV, le debit et les latences. La v8 avait
#  revele que g n'etait pas max_tokens : a max_tokens=96 la charge prefixe-identique
#  genere 73,00 jetons moy avec 0 % AU PLAFOND -- le plafond etait inerte, et l'egalite
#  « g = max_tokens » une coincidence numerique.
#  La loi mesuree (cf. tiered-and-retention/) est PAR REQUETE :
#     blocs KV = ceil(g/16) + 1     -> jetons de KV = 16 x (ceil(g/16) + 1)
#  avec g = jetons REELLEMENT generes. Elle rend 96,0 / 84,0 / 72,0 / 40,0 jetons par
#  requete contre 96,2 / 84,3 / 71,8 / 38,2 mesures sur quatre regimes distincts, alors
#  que le modele « g = max_tokens » du §10 ne rendait ni T160 ni T64. Le « +1 bloc »
#  n'est PAS un reliquat de prompt : le prompt fait 832 jetons = 52 blocs exactement
#  (mesure `request_prompt_tokens`), et deux lois qui coincidaient pour g = 16..73 ont
#  ete separees par MAXTOK_SET="8 24" (38,2 mesures contre 40 pour « +1 bloc » et 24
#  pour la loi « reliquat de prompt »).
#  Un avertissement PALIERS_LONGUEURS dit quand un palier MESURE une repartition de
#  longueurs : la pente KV(n) = P + n.g est l'ajustement d'un workload a longueur
#  CONSTANTE, elle ne decrit pas un palier a longueurs melangees.
#
#  2026-09-28 (v10) -- une seule correction, sur une AFFIRMATION FAUSSE publiee en v9.
#  La ligne de longueur portait une colonne « plafond demande max=... », alimentee par
#  `request_max_num_generation_tokens`. Un probe de la meme passe a montre que cette
#  metrique rend EXACTEMENT la meme valeur que `request_generation_tokens` sur vLLM
#  0.29.0 -- memes somme, compte et buckets, meme sous MAXTOK_SET ou les plafonds
#  demandes valent 16/48/80/112 alors que la somme vaut 6300, soit les jetons PRODUITS.
#  La colonne a ete SUPPRIMEE (le plafond demande se lit dans l'en-tete du balayage).
#  `request_success_total{finished_reason="length"}`, lui, se comporte correctement
#  (0 % a max_tokens=96 inerte, 50 % sous les paliers 16/48/80/112) et reste publie.
#  Les sorties v9 qui portent la colonne sont conservees en superseded/ (R7).
#
#  2026-09-28 (v11) -- deux lignes de ROBUSTESSE, aucune ligne publiee ne change.
#  La longueur generee n'est publiee que si le compteur AVANCE (`g >= 0`) : un serveur
#  redemarre entre les deux instantanes fait RECULER `generation_tokens_total`, ce qui
#  aurait publie une longueur moyenne NEGATIVE -- un nombre, exactement le genre de
#  chiffre faux mais plausible que cette passe corrige ailleurs. Le fait est deja
#  signale par l'avertissement RESET de la meme ligne de palier : on refuse d'inventer
#  une valeur, on ne cache pas l'incident. Les cinq balayages v10 restent valides pour
#  ces octets : aucun RESET n'y a eu lieu (verifie sur les logs), donc la garde y est
#  inerte -- un balayage de confirmation a ete refait sur les octets finaux.
#
#  2026-09-28 (v12) -- TAILLE DU JEU DE PREFIXES a concurrence FIXE (VARIANT_COUNT).
#  Meme mecanisme que VARY_ROTATE, mais un bouton separe, parce que la question posee
#  etait « la retention chute-t-elle parce que le JEU grandit, ou parce que la place
#  libre diminue ? ». La passe precedente faisait varier la concurrence (donc la place)
#  a jeu constant ; celle-ci fait l'inverse. VARIANT_COUNT=1 est LEGAL (un seul prefixe
#  en rotation = le regime a prefixe partage) : c'est un point de controle. Aucune ligne
#  publiee ne change quand le bouton vaut 0. Le controle hors-ligne gagne la section qui
#  verifie que le jeu de N corps est un SOUS-ENSEMBLE ORDONNE du jeu complet, par
#  empreinte -- sinon on ne saurait pas QUELLE variante entre dans un jeu limite.
#
#  2026-09-28 (v13) -- GEOMETRIE DU PARTAGE (VARY_STRIDE), et un defaut du controle
#  hors-ligne. Le pas de rotation devient reglable : avec un pas S, deux travailleurs
#  tombent sur le meme prefixe seulement si leur ecart est un multiple de S (modulo le
#  jeu). Un pas egal a la concurrence par noeud rend donc les classes DISJOINTES -- aucun
#  travailleur ne peut plus tomber sur un prefixe qu'un autre tient -- ce qui teste si la
#  reutilisation exige un PORTEUR VIVANT (v13 : la touche tombe a exactement 0,00 %, a
#  occupation inchangee). VARY_STRIDE=1 ne change rien au defaut. Le meme lot corrige un
#  defaut du controle : la section de geometrie de `check-bench-variants.sh` passait par un
#  TUYAU, donc une section qui s'arretait en route ne publiait ni OK ni ECHEC et le script
#  annoncait VERDICT : OK sur des controles qui n'avaient PAS eu lieu ; la section ecrit
#  desormais dans un fichier et son code de retour est verifie (controle negatif fait).
# =============================================================================
set -u

MODE="${MODE:-collect}"
HOST="$(hostname)"
# Image de test. 2026-09-28 : le litteral unique `/tmp/vlm-test-images/...` etait a
# la fois le seul chemin connu ET un repertoire VOLATIL -- les noeuds avaient
# redemarre, /tmp etait vide, et `load`/`sweep` sortaient en erreur 1 sur un
# cluster sain. Les octets sont desormais versionnes dans le depot
# (infra/assets/test-images/, sha256 ca07ce15...), avec la raison pour laquelle il
# faut versionner les OCTETS et non regenerer le fichier (voir infra/assets/README.md).
# L'image est donc RESOLUE, comme les endpoints : TEST_IMAGE=... prime ; si aucun
# candidat n'existe la variable s'arrete sur le dernier, pour que le message
# « image absente » continue de nommer le chemin historique.
if [ -z "${TEST_IMAGE:-}" ]; then
  for TEST_IMAGE in \
      "$(dirname "$0")/../assets/test-images/device_clean.jpg" \
      "$HOME/infra/assets/test-images/device_clean.jpg" \
      "$HOME/vlm-test-images/device_clean.jpg" \
      /tmp/vlm-test-images/device_clean.jpg; do
    [ -f "$TEST_IMAGE" ] && break
  done
fi
IMG="$TEST_IMAGE"
# Prefixe VARIABLE -- 2026-09-28 (v6). Le banc n'envoyait qu'UNE image et un prompt fixe,
# donc UN PREFIXE IDENTIQUE a chaque requete. `enable_prefix_caching=True` etant actif,
# ce prefixe etait calcule une fois et PARTAGE : mesure, le cache KV ne coutait par requete
# que ses ~92 a 109 jetons GENERES (98,1 % de touches de cache de prefixe), et il fallait
# monter a 96 requetes simultanees pour que la file s'ouvre. Or une charge reelle envoie
# des images DIFFERENTES. VARY_PREFIX=1 fait envoyer a chaque travailleur une image
# distincte : le prefixe cesse d'etre partage, et le cache KV se charge par le PREFIXE.
# Sans VARY_PREFIX, le banc se comporte exactement comme avant -- les nombres deja publies
# restent comparables.
VARY_PREFIX="${VARY_PREFIX:-0}"
# TAILLE DU JEU DE PREFIXES (v12). 0 = toutes les variantes deployees.
# VARY_ROTATE=1 fixe le jeu de prefixes au nombre de corps construits, QUELLE QUE SOIT la
# concurrence ; ce bouton sert donc a faire varier la TAILLE DU JEU a concurrence fixe, ce
# que la rotation seule ne permet pas. C'est la seule facon de separer deux causes que la
# passe precedente avait mesurees ensemble : la retention du cache chute-t-elle parce que
# le jeu de prefixes GRANDIT, ou parce que la place LIBRE diminue ? La passe precedente
# faisait varier la concurrence (donc la place) a jeu constant ; celle-ci fait l'inverse.
# VARIANT_COUNT=1 est LEGAL et utile : un seul prefixe en rotation est exactement le regime
# a prefixe partage, avec le meme mecanisme -- un point de controle, pas un cas casse.
VARIANT_COUNT="${VARIANT_COUNT:-0}"
# PAS DE LA ROTATION (v12). 1 = un corps de plus par requete (comportement v8).
# Ce bouton existe pour TESTER, et non pour charger differemment : avec un pas S, deux
# travailleurs bw et bw' tombent sur le meme prefixe seulement si (bw - bw') est un
# multiple de S (modulo le jeu). Le pas decide donc QUI peut partager un prefixe EN MEME
# TEMPS. Avec S egal a la concurrence par noeud, les classes sont disjointes : aucun
# travailleur d'un serveur ne tombe jamais sur un prefixe qu'un autre tient, et si la
# reutilisation vient bien d'un porteur VIVANT (et non d'une memoire du cache), le taux de
# touche doit s'effondrer a zero -- a occupation inchangee. C'est l'experience qui
# falsifie l'explication du voisinage ; VARY_STRIDE=1 ne change rien au defaut.
VARY_STRIDE="${VARY_STRIDE:-1}"
case "$VARY_STRIDE" in
  ''|*[!0-9]*) echo "VARY_STRIDE_INVALIDE : '$VARY_STRIDE' n'est pas un entier >= 1" >&2; exit 2 ;;
esac
[ "$VARY_STRIDE" -ge 1 ] || { echo "VARY_STRIDE_INVALIDE : '$VARY_STRIDE' vaut moins de 1" >&2; exit 2; }
if [ -z "${VARIANT_DIR:-}" ]; then
  for VARIANT_DIR in \
      "$(dirname "$0")/../assets/test-images/prefix-variants" \
      "$HOME/infra/assets/test-images/prefix-variants"; do
    [ -d "$VARIANT_DIR" ] && break
  done
fi
# Paliers de longueur de reponse (v8). Vide = une seule valeur, celle de cluster.env :
# le defaut est inchange, et le controle de charge utile porte sur ce defaut.
MAXTOK_SET="${MAXTOK_SET:-}"
# Rotation des prefixes (v8). 0 = image fixee par travailleur (comportement v6/v7).
VARY_ROTATE="${VARY_ROTATE:-0}"
# Echantillonneur de jauges pendant le palier (v8) : periode en secondes, et interrupteur.
KV_SAMPLE="${KV_SAMPLE:-1}"
KV_SAMPLE_S="${KV_SAMPLE_S:-0.2}"
# Nom servi. Chaine vide ici : il est resolu plus bas, depuis cluster.env
# (QWEN_SERVED_NAME), exactement comme les endpoints. Voir le bloc dedie.
SERVED="${SERVED:-}"

# MODE valide -- 2026-09-17. `collect` est le bloc de FIN du script, pas un `else` :
# toute valeur inconnue (faute de frappe : MODE=swep) imprimait donc un rapport de
# collecte plausible et sortait avec 0 au lieu d'echouer. Valide ici, avant toute
# sonde, pour que l'erreur soit immediate.
case "$MODE" in
  sample|load|sweep|collect) ;;
  *) echo "MODE inconnu : '$MODE' (attendu : sample | load | sweep | collect)" >&2
     echo "usage : MODE=sweep bash gpu-bench-node.sh   (SUR UN NOEUD)" >&2
     exit 2 ;;
esac

# Endpoints -- 2026-09-17. La topologie vit dans infra/config/cluster.env
# (NODE_IPS + QWEN_PORT). Ce banc en portait une DEUXIEME copie silencieuse : si
# l'adresse d'un noeud changeait, les scripts du cluster suivaient la config et le
# banc continuait a mesurer l'ancien hote. La config est lue quand elle est
# joignable (checkout du depot, ou CLUSTER_ENV=<chemin>) ; les adresses relevees le
# 2026-09-15 ne sont plus qu'un repli, pour rester utilisable depuis $HOME seul
# (les noeuds n'ont pas de checkout). URLS=... reste prioritaire sur tout.
CLUSTER_ENV="${CLUSTER_ENV:-}"
if [ -z "$CLUSTER_ENV" ]; then
  for c in "$(dirname "$0")/../config/cluster.env" "$HOME/infra/config/cluster.env"; do
    [ -f "$c" ] && { CLUSTER_ENV="$c"; break; }
  done
fi
urls_from_config() {   # $1 = cluster.env ; stdout = endpoints separes par une espace
  ( set -u
    . "$1" >/dev/null 2>&1 || exit 1
    [ -n "${NODE_IPS[*]:-}" ] || exit 1
    for ip in "${NODE_IPS[@]}"; do printf 'http://%s:%s ' "$ip" "${QWEN_PORT:-8000}"; done )
}
served_from_config() {  # $1 = cluster.env ; stdout = QWEN_SERVED_NAME
  ( set -u
    . "$1" >/dev/null 2>&1 || exit 1
    printf '%s' "${QWEN_SERVED_NAME:-}" )
}
DEFAULT_URLS="${DEFAULT_URLS:-http://172.26.145.71:8000 http://172.26.145.72:8000 http://172.26.145.73:8000}"
DEFAULT_SERVED="qwen2.5-vl-7b"
URLS_SOURCE=""
if [ -n "${URLS:-}" ]; then
  URLS_SOURCE="URLS= (explicite)"
else
  URLS="$DEFAULT_URLS"; URLS_SOURCE="repli 2026-09-15"
  if [ -n "$CLUSTER_ENV" ]; then
    # `${_cfg% }` : la substitution de commande retire les sauts de ligne, pas les
    # espaces -- sans cela URLS gardait une espace finale et `echo "endpoints : $URLS"`
    # differait d'un caractere du chemin de repli (le decoupage en mots l'ignore, mais
    # la sortie du banc doit etre identique dans les deux cas).
    if _cfg="$(urls_from_config "$CLUSTER_ENV")" && [ -n "$_cfg" ]; then
      URLS="${_cfg% }"; URLS_SOURCE="config $CLUSTER_ENV"
    else
      # 2026-09-28 : un repli SILENCIEUX sur des adresses figees est le pire
      # comportement possible pour un instrument de mesure -- c'est precisement le
      # defaut que la resolution par config etait censee supprimer. On crie.
      echo "AVERTISSEMENT : $CLUSTER_ENV trouve mais inexploitable -- repli sur les adresses du 2026-09-15" >&2
    fi
  fi
fi
# Nom servi : meme regle que les endpoints (voir bloc ci-dessus).
if [ -z "$SERVED" ]; then
  SERVED="$DEFAULT_SERVED"
  if [ -n "$CLUSTER_ENV" ]; then
    _s="$(served_from_config "$CLUSTER_ENV")" && [ -n "$_s" ] && SERVED="$_s"
  fi
fi
# Payload de mesure. Meme regle que les endpoints et le nom servi : la valeur vit dans
# cluster.env, le litteral du 2026-09-15 n'est qu'un repli. Ce bloc existe parce que le
# MEME JSON etait recopie mot pour mot ici ET dans vllm-service.sh (226 octets
# identiques) : editer l'un faisait diverger, SANS AUCUN SIGNAL, ce que `health` valide
# de ce que le banc mesure. Le squelette JSON reste en code -- identique dans les deux
# fichiers, tenu par infra/selftest/check-payload-consistency.sh -- les VALEURS sont ici.
DEFAULT_PROMPT='Identify the device: brand, model, category.'
DEFAULT_MAX_TOKENS=96
DEFAULT_TEMPERATURE=0
PROMPT="$DEFAULT_PROMPT"; MAXTOK="$DEFAULT_MAX_TOKENS"; TEMPER="$DEFAULT_TEMPERATURE"
PAYLOAD_SOURCE="repli 2026-09-15"
payload_from_config() {  # $1 = cluster.env ; stdout = 3 lignes : prompt, max_tokens, temperature
  ( set -u
    . "$1" >/dev/null 2>&1 || exit 1
    printf '%s\n%s\n%s\n' "${VLM_PROMPT:-}" "${VLM_MAX_TOKENS:-96}" "${VLM_TEMPERATURE:-0}" )
}
if [ -n "$CLUSTER_ENV" ]; then
  # Une config sans VLM_PROMPT ne doit pas passer pour un payload resolu : c'est le
  # meme piege que le repli silencieux des endpoints, corrige en v3.
  if _pl="$(payload_from_config "$CLUSTER_ENV")" && [ -n "$(printf '%s' "$_pl" | sed -n 1p)" ]; then
    PROMPT="$(printf '%s\n' "$_pl" | sed -n 1p)"
    MAXTOK="$(printf '%s\n' "$_pl" | sed -n 2p)"
    TEMPER="$(printf '%s\n' "$_pl" | sed -n 3p)"
    PAYLOAD_SOURCE="config $CLUSTER_ENV"
  else
    echo "AVERTISSEMENT : $CLUSTER_ENV trouve mais sans VLM_PROMPT -- repli sur la charge du 2026-09-15" >&2
  fi
fi
# Le prompt est interpole dans du JSON : refuser vaut mieux que mesurer autre chose.
if printf '%s' "$PROMPT" | grep -q -e '[\\"]' -e '[[:cntrl:]]'; then
  echo "VLM_PROMPT invalide : ni guillemet double, ni antislash, ni caractere de controle" >&2
  echo "  (il est interpole dans le corps JSON : le serveur repondrait 400 sur chaque requete)" >&2
  exit 2
fi

# Nombre d'endpoints REELLEMENT interroges. L'arithmetique par noeud du banc
# divisait par 3 en dur : les adresses suivaient la config, le compte non.
NENDPOINTS=0
for _u in $URLS; do NENDPOINTS=$((NENDPOINTS + 1)); done
CONC="${CONC:-8}"              # requetes simultanees PAR NOEUD (mode load)
REQ="${REQ:-5}"                # requetes par travailleur (mode load)
LEVELS="${LEVELS:-4 8 16 24 32}"   # concurrence PAR NOEUD, en mode sweep
T="${T:-12}"                   # duree de chaque palier du balayage, en secondes
SAMPLE_F="$HOME/.gpu-sample-$HOST.csv"
# Seuil « attente visible ». vLLM publie `request_queue_time_seconds` avec 0,3 s comme
# plus petite borne FINIE (releve sur /metrics, 2026-09-28) : c'est la plus petite valeur
# ou un bucket peut dire quelque chose. Le seuil n'est pas suppose etre une borne --
# metrics_over() prend la plus grande borne qui ne le depasse pas, et le dit.
QUEUE_EDGE_S="${QUEUE_EDGE_S:-0.3}"

# Sonde UNE fois : clocks.sm n'est pas expose par tous les pilotes. Les colonnes
# sont TOUJOURS normalisees a 5 (SM%, MEM%, VRAM Mio, W, MHz).
if nvidia-smi --query-gpu=clocks.sm --format=csv,noheader,nounits >/dev/null 2>&1; then
  QUERY='utilization.gpu,utilization.memory,memory.used,power.draw,clocks.sm'
  NORM='{ print }'
else
  QUERY='utilization.gpu,memory.used,power.draw'
  NORM='{ print $1 ", 0, " $2 ", " $3 ", 0 }'
fi
# Echantillonne jusqu'a l'apparition du fichier d'arret. 2026-09-28 : remplace
# une variante bornee a N echantillons, qui ne couvrait que le PREFIXE du palier
# alors que la duree du debit, elle, court jusqu'a la derniere requete en vol.
# Utilise par run_level (arret apres le dernier travailleur) et par MODE=sample
# (arret apres DUR secondes, via un sous-processus « sleep »).
# Echantillonneur de jauges PENDANT le palier (v8). Le banc ne lisait /metrics qu'AVANT
# et APRES, serveur au repos : ces deux lectures ne peuvent montrer ni un PIC de cache ni
# une profondeur de file. Cette boucle lit les TROIS endpoints, horodate chaque lecture (le
# taux atteint est donc mesurable, pas suppose), et n'ecrit rien d'autre -- elle ne touche
# aucun serveur. La periode est reglable (KV_SAMPLE_S) ; KV_SAMPLE=0 la desactive.
kv_sample_until() {   # $1 = fichier, $2 = fichier d'arret
  local f="$1" s="$2" ts u
  : > "$f"
  while [ ! -e "$s" ]; do
    ts="$(date +%s.%N)"
    for u in $URLS; do
      curl -s -m 2 "$u/metrics" 2>/dev/null | awk -v ts="$ts" -v ep="$u" '
        /^vllm:kv_cache_usage_perc\{/  { kv   = $NF }
        /^vllm:num_requests_running\{/ { run  = $NF }
        /^vllm:num_requests_waiting\{/ { wait = $NF }
        END { if (kv != "") printf "%s\t%s\t%.6f\t%d\t%d\n", ts, ep, kv + 0, run + 0, wait + 0 }' \
        >> "$f"
    done
    sleep "$KV_SAMPLE_S"
  done
}
# Reduit l'echantillon a ce qui se publie : le pic de cache KV (et l'endpoint qui l'a
# donne), le max d'`en cours`, le max d'`en attente`, le nombre de lectures et le taux
# REELLEMENT atteint. La fenetre [t0,t1] est celle du debit et du p50 : un pic mesure sur
# une autre fenetre ne serait pas comparable.
kv_peak_report() {   # $1 = fichier, $2 = t0, $3 = t1 -> "PIC ENDPOINT ENCOURS ATTENTE N HZ"
  awk -F'\t' -v t0="$2" -v t1="$3" '
    BEGIN { ep = "?" }
    { if ($1 + 0 < t0 + 0 || $1 + 0 > t1 + 0) next
      n++
      if ($3 + 0 > mx) { mx = $3 + 0; ep = $2 }
      if ($4 + 0 > mr) mr = $4 + 0
      if ($5 + 0 > mw) mw = $5 + 0
      if (n == 1) first = $1 + 0
      last = $1 + 0 }
    END {
      if (n == 0) { print "NA NA 0 0 0 0"; exit }
      span = last - first
      hz = (n > 1 && span > 0) ? (n - 1) / span : 0
      printf "%.6f %s %d %d %d %.1f\n", mx, ep, mr, mw, n, hz }' "$1"
}

sample_until() {   # $1 = fichier, $2 = fichier d'arret
  local f="$1" s="$2" ts
  : > "$f"
  while [ ! -e "$s" ]; do
    # 2026-09-28 (v4) : l'horodatage est ecrit AVEC la ligne (6e colonne, epoch).
    # Sans lui, run_level ne peut pas savoir quels echantillons tombent dans son
    # intervalle mesure et doit les compter tous -- y compris celui-ci, pris avant
    # que la charge soit appliquee. Voir l'en-tete du fichier.
    ts="$(date +%s.%N)"
    nvidia-smi --query-gpu=$QUERY --format=csv,noheader,nounits 2>/dev/null \
      | awk -F', *' "$NORM" \
      | awk -v ts="$ts" '{ print $0 ", " ts }' >> "$f"
    sleep 1
  done
}

# ------------------------------------------------------------------ utilitaire
# Resume l'echantillon. Colonnes normalisees : SM%, MEM%, VRAM MiB, W, MHz, puis
# l'horodatage epoch (6e colonne, ajoutee en v4 -- la resume ci-dessous l'ignore,
# seuls $1..$5 sont lus).
gpu_summary() {
  local f="$1"
  if [ ! -s "$f" ]; then echo "  (aucun echantillon)"; return; fi
  awk -F', *' '
    { sm += $1; mu += $2; vr += $3; pw += $4; ck += $5; n++
      if ($4+0 > pwmax) pwmax = $4+0
      if ($5+0 > ckmax) ckmax = $5+0
      if ($1+0 > smmax) smmax = $1+0 }
    END {
      if (n == 0) { print "  (echantillon vide)"; exit }
      printf "  n=%-3d | SM util moy=%5.1f%% (max %5.1f%%) | MEM util moy=%5.1f%% | VRAM moy=%6.0f Mio\n", \
             n, sm/n, smmax, mu/n, vr/n
      printf "         | puissance moy=%6.1f W  (max %6.1f W / limite 170 W) | SM clock moy=%5.0f MHz (max %5.0f / 2100 MHz)\n", \
             pw/n, pwmax, ck/n, ckmax
    }' "$f"
}

# ---------------------------------------------------------------- MODE=sample
if [ "$MODE" = "sample" ]; then
  DUR="${DUR:-45}"
  # 2026-09-28 : meme echantillonneur que run_level (sample_until), plus de boucle
  # inline dupliquee. Deux details morts retires au passage (ils etaient de la meme
  # famille que le IP_LOCAL supprime en v2) : `SAMPLE_F='...'` n'etait jamais relu,
  # et `. /dev/null` ne faisait rien. La fonction est transmise par l'environnement
  # (export -f) ; QUERY et NORM le sont aussi, elle s'en sert.
  stopf="$SAMPLE_F.stop"
  rm -f "$stopf"
  setsid bash -c "sleep $DUR; : > '$stopf'" </dev/null >/dev/null 2>&1 &
  export -f sample_until
  export QUERY NORM
  setsid bash -c "sample_until '$SAMPLE_F' '$stopf'" </dev/null >/dev/null 2>&1 &
  sleep 0.6
  echo "sample demarre sur $HOST : $DUR echantillons (~${DUR}s), requete=$QUERY -> $SAMPLE_F"
  exit 0
fi

# -------------------------------------------------------------- utilitaire body
# Le squelette JSON est IDENTIQUE a celui de node_vllm_service.sh::cmd_health : c'est ce
# qui rend les deux mesures comparables. Ne le modifier que PAR PAIRE, et verifier avec
# infra/selftest/check-payload-consistency.sh. Les valeurs viennent de cluster.env.
#
# Le squelette est ecrit UNE fois, dans build_body_for(). build_body() en est le cas a une
# seule image : c'est ce qui permet a VARY_PREFIX de changer l'image sans creer une
# DEUXIEME definition de la charge utile -- celle qui deriverait en silence.
build_body_for() {   # $1 = image ; $2 = max_tokens (defaut $MAXTOK) -> corps JSON (ou IMAGE_ABSENTE)
  # Le diagnostic va sur STDERR, comme les autres. Sur stdout il etait avale par le
  # `>/dev/null` des appelants (`build_bodies >/dev/null || { echo "charge utile
  # indisponible" ...; }`) : l'operateur voyait « charge utile indisponible » et jamais
  # le nom de ce qui manquait. La v8 publie le message, pas seulement le code de retour.
  [ -f "${1:-}" ] || { echo "IMAGE_ABSENTE" >&2; return 1; }
  local mt="${2:-$MAXTOK}" b64
  b64="$(base64 -w0 "$1")"
  printf '{"model":"%s","temperature":%s,"max_tokens":%s,"messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,%s"}},{"type":"text","text":"%s"}]}]}' \
         "$SERVED" "$TEMPER" "$mt" "$b64" "$PROMPT"
}
build_body() { build_body_for "$IMG"; }
# Quel corps pour ce travailleur, a cette requete ? Une SEULE formule, dans une SEULE
# fonction : c'est elle qui decide du regime de prefixe, et une formule recopiee dans
# chaque boucle deriverait sans signal. Hors rotation ($2 = 0 en permanence) elle redonne
# exactement l'ancien `wi % NVARIANTS`. Le resultat sort par la variable BIDX et non par
# stdout : la boucle de requete l'appelle a chaque tour, un sous-shell par requete serait
# du travail de client mesure en meme temps que le serveur.
BIDX=0
body_index() {   # $1 = indice de base du travailleur, $2 = n de requete, $3 = NBODIES -> BIDX
  # UNE SEULE formule, ici : c'est elle qui decide du regime de prefixe. Elle etait
  # recopiee dans chaque boucle ; une recopie derivant d'un seul cote changerait le
  # regime mesure sans que rien ne le dise. Le pas est applique au NUMERO DE REQUETE et
  # non a l'indice : au tour 0 les deux valent 0, donc le pas ne deplace pas le premier
  # corps d'un travailleur -- seul l'enchainement change.
  BIDX=$(( ($1 + $2 * VARY_STRIDE) % $3 ))
}

# Corps par travailleur. Hors VARY_PREFIX, un seul corps, comme avant. Avec VARY_PREFIX,
# un corps par variante : les travailleurs les parcourent en boucle, et le nombre de
# PREFIXES DISTINCTS simultanes vaut alors min(concurrence, nombre de variantes).
BODIES=()
NBODIES=0        # nombre de CORPS construits (images x paliers)
NVARIANTS=0      # nombre d'IMAGES distinctes (0 = une seule) -- ce n'est pas NBODIES
build_bodies() {   # remplit BODIES ; NBODIES = corps, NVARIANTS = images distinctes
  BODIES=(); NBODIES=0; NVARIANTS=0
  local imgs=() tiers=() i t b
  # 1. les images. En mode prefixe varie, le corps de device_clean.jpg n'est PAS ajoute a
  #    la liste : un 33e prefixe qui ne serait envoye par personne sauf le premier
  #    travailleur rendrait la concurrence inegale entre prefixes et le compte faux.
  if [ "$VARY_PREFIX" = "1" ]; then
    [ -d "$VARIANT_DIR" ] || {
      echo "PREFIXE_VARIE_IMPOSSIBLE : $VARIANT_DIR introuvable (VARY_PREFIX=1)" >&2
      return 1
    }
    for i in "$VARIANT_DIR"/v*.jpg; do [ -f "$i" ] && imgs+=("$i"); done
    # Ordre deterministe : le glob est trie, et la troncature prend donc toujours les
    # MEMES variantes. Un jeu qui changerait d'un run a l'autre rendrait la courbe de
    # retention dependante de quelles images ont ete tirees, pas de combien.
    local avail=${#imgs[@]}
    case "$VARIANT_COUNT" in
      ''|*[!0-9]*) echo "VARIANT_COUNT_INVALIDE : '$VARIANT_COUNT' n'est pas un entier >= 0" >&2; return 1 ;;
    esac
    if [ "$VARIANT_COUNT" -gt 0 ]; then
      [ "$VARIANT_COUNT" -le "$avail" ] || {
        echo "JEU_DE_PREFIXES_IMPOSSIBLE : $VARIANT_COUNT variante(s) demandees, $avail disponible(s) dans $VARIANT_DIR" >&2
        return 1
      }
      imgs=("${imgs[@]:0:$VARIANT_COUNT}")
    elif [ "$avail" -lt 2 ]; then
      # Sans VARIANT_COUNT, exiger 2 variantes est un controle de DEPLOIEMENT : une seule
      # fichier deploye veut dire un envoi incomplet, pas un regime de mesure.
      echo "PREFIXE_VARIE_IMPOSSIBLE : $avail variante(s) dans $VARIANT_DIR (2 au moins)" >&2
      return 1
    fi
  else
    [ -f "$IMG" ] || { echo "IMAGE_ABSENTE" >&2; return 1; }
    imgs=("$IMG")
  fi
  # 2. les paliers de longueur de reponse. UN SEUL (celui de cluster.env) par defaut :
  #    ce n'est que sous MAXTOK_SET que le payload de mesure s'ecarte de celui que `health`
  #    valide, et le defaut de MAXTOK reste celui de cluster.env (le controle de charge
  #    utile porte la-dessus).
  if [ -n "$MAXTOK_SET" ]; then
    for t in $MAXTOK_SET; do
      case "$t" in
        ''|*[!0-9]*) echo "PALIERS_MAXTOK_INVALIDES : '$t' n'est pas un entier positif" >&2; return 1 ;;
      esac
      [ "$t" -gt 0 ] || { echo "PALIERS_MAXTOK_INVALIDES : '$t' vaut 0" >&2; return 1; }
      tiers+=("$t")
    done
  else
    tiers=("$MAXTOK")
  fi
  # 3. le produit, IMAGE-MAJOR. Avec un seul palier cela redonne exactement la liste
  #    d'images de la v6 ; avec plusieurs paliers, l'ordre fait tourner les paliers entre
  #    travailleurs concurrents -- ce qui est le but recherche.
  for i in "${imgs[@]}"; do
    for t in "${tiers[@]}"; do
      b="$(build_body_for "$i" "$t")" || return 1
      BODIES+=("$b")
    done
  done
  NBODIES=${#BODIES[@]}
  [ "$NBODIES" -ge 1 ] || { echo "AUCUN_CORPS_CONSTRUIT" >&2; return 1; }
  if [ "$VARY_PREFIX" = "1" ]; then NVARIANTS=${#imgs[@]}; else NVARIANTS=0; fi
  return 0
}

# ------------------------------------------------------------------ metriques vLLM
# Le serveur publie lui-meme les histogrammes qui separent une requete en FILE
# D'ATTENTE, PREFILL et DECODE (/metrics, format Prometheus). Ils sont CUMULATIFS depuis
# le demarrage du serveur : la difference entre deux instantanes decrit exactement les
# requetes du palier -- mais seulement si les deux encadrent le MEME intervalle que le p50
# cote client. C'est pourquoi ce calcul vit ici et non dans un outil separe : un decoupage
# qui ne s'applique pas a la meme fenetre n'est pas une mesure.
metrics_scan() {   # $1 = fichier de sortie ; stdout = nb d'endpoints qui ont repondu
  local u
  : > "$1"
  for u in $URLS; do
    # `--retry` : curl rejoue de lui-meme un delai d'attente depasse (exit 28), ce qui
    # est precisement le mode d'echec sous charge. Les echecs definitifs restent
    # visibles par le comptage ci-dessous, jamais avales.
    curl -s -m 10 --retry 1 --retry-delay 1 "$u/metrics" >> "$1" 2>/dev/null || true
  done
  # Nombre d'endpoints qui ont livre la metrique : chaque serveur en publie
  # EXACTEMENT une occurrence. Un instantane PARTIEL (un des trois endpoints muet)
  # donnerait un decoupage et un « ecart client/serveur » calcules sur un
  # sous-ensemble de la grappe, sans que rien ne le signale -- c'est ce nombre qui
  # le signale. Le compter coute un grep sur un fichier deja en memoire.
  # `|| true` est DANS la substitution : sans lui, un instantane sans la metrique
  # (grep sort 1) ferait sortir la fonction en echec, et `grep -c || echo 0` en
  # dehors imprimerait DEUX « 0 » -- un compte de deux lignes.
  local n
  n="$(grep -c '^vllm:e2e_request_latency_seconds_count' "$1" 2>/dev/null || true)"
  printf '%s\n' "${n:-0}"
}
# Delta d'une famille d'histogrammes, sur les N endpoints AGREGES.
# stdout : "COUNT <n>" / "SUM <s>" / "LE <borne> <delta cumule>" / "RESET 0|1"
metrics_delta() {  # $1 = avant, $2 = apres, $3 = metrique sans suffixe
  awk -v m="$3" -v f_av="$1" -v f_ap="$2" '
    function le(l,   x) { if (match(l, /le="[^"]*"/)) return substr(l, RSTART + 4, RLENGTH - 5); return "" }
    # Les deux passes sont designees par NOM de fichier, et non par `FNR == NR`.
    # Cet idiome identifie la premiere passe par le fait que son numero de ligne
    # globale egale son numero de ligne locale -- ce qui suppose cette passe NON VIDE.
    # Un instantane avant vide (curl en echec, ou `-m 10` expire sous saturation)
    # faisait alors lire la SECONDE passe comme une passe de reference : deltas
    # negatifs, et AUCUNE borne imprimee (la boucle parcourt les bornes de la seconde
    # passe, restees vides). Le resultat etait un rapport plausible avec des nombres
    # faux ou absents, sans un mot. Le nom de fichier, lui, ne depend pas de ce qui a
    # ete lu.
    FILENAME == f_av {
      if      ($1 ~ "^vllm:" m "_bucket") { bb[le($1)] += $2 }
      else if ($1 ~ "^vllm:" m "_sum")    { bsum += $2 }
      else if ($1 ~ "^vllm:" m "_count")  { bcnt += $2 }
      next
    }
    FILENAME == f_ap {
      if      ($1 ~ "^vllm:" m "_bucket") { ab[le($1)] += $2 }
      else if ($1 ~ "^vllm:" m "_sum")    { asum += $2 }
      else if ($1 ~ "^vllm:" m "_count")  { acnt += $2 }
      next
    }
    END {
      # RESET 1 : un compteur CUMULATIF qui recule, donc un serveur redemarre entre les
      # deux instantanes. Les deltas sont ramenes a 0 pour ne pas propager de valeurs
      # negatives, mais le fait est publie -- sans cela un redemarrage se lisait comme
      # un palier vide (COUNT < 0 -> moyenne et quantiles NA) sans que rien ne dise
      # pourquoi. Limite connue : un serveur qui redemarre ET resert assez de requetes
      # pour que le delta redevienne positif passe ici ; le controle « n serveur contre
      # ok client » de run_level attrape celui-la, pas ce test de monotonie.
      if (acnt < bcnt || asum < bsum) neg = 1
      printf "COUNT %.0f\n", acnt - bcnt
      printf "SUM %.6f\n",   asum - bsum
      for (l in ab) { d = ab[l] - bb[l]; if (d < 0) { d = 0; neg = 1 }
                      printf "LE %s %.0f\n", l, d }
      printf "RESET %d\n", neg + 0
    }' "$1" "$2"
}
metrics_mean() {   # $1 = avant, $2 = apres, $3 = metrique -> moyenne, ou NA
  metrics_delta "$1" "$2" "$3" \
    | awk '/^COUNT /{c = $2 + 0} /^SUM /{s = $2 + 0} END { if (c > 0) printf "%.4f", s / c; else printf "NA" }'
}
# Compteur SIMPLE, pas un histogramme. `metrics_delta` cherche _bucket/_sum/_count et ne
# voit donc PAS les compteurs nus du cache -- or les deux caches de vLLM en sont :
#   prefix_cache_hits_total / prefix_cache_queries_total   le KV de prefixe
#   mm_cache_hits_total     / mm_cache_queries_total       les embeddings visuels
# Ce sont des compteurs CUMULATIFS : leur difference entre deux instantanes decrit la
# fenetre, exactement comme celle des histogrammes. Le `split` sur « { » separe le nom des
# etiquettes -- comparer $1 tel quel ne marcherait pas, il porte les etiquettes.
metrics_counter_delta() {   # $1 = avant, $2 = apres, $3 = nom complet -> delta
  # Meme instantane des deux cotes : le delta est nul PAR DEFINITION. Sans ce garde,
  # l'awk ci-dessous teste `FILENAME == fa` en premier ; sur deux fois le meme chemin,
  # toutes les lignes tombent dans la branche « avant », y reste a 0 et le delta sort
  # NEGATIF (-2x la valeur). Le cas ne se produit pas dans le banc (les deux instantanes
  # sont deux fichiers distincts), mais il se produit des qu'on teste la fonction -- et
  # c'est exactement ce que le harnais fait.
  [ "$1" != "$2" ] || { printf '0\n'; return 0; }
  awk -v m="$3" -v fa="$1" -v fb="$2" '
    { split($1, a, "{"); if (a[1] != "vllm:" m) next
      if (FILENAME == fa) x += $2; else if (FILENAME == fb) y += $2 }
    END { printf "%.0f", y - x }' "$1" "$2"
}
# Taux de reutilisation d'un cache -> "HITS QUERIES PCT" (PCT = NA si aucune requete).
# Publie a cote du pic KV : c'est lui qui dit si le cache TRAVAILLE, pas seulement s'il est
# plein. Mesure du jour : 98,08 % sous la limite, puis 0,00 % des que le cache KV est plein
# -- le prefixe n'est alors plus retenu du tout, et chaque requete admise le refait.
metrics_cache_rate() {   # $1 = avant, $2 = apres, $3 = prefixe (ex: prefix_cache)
  awk -v h="$(metrics_counter_delta "$1" "$2" "$3"_hits_total)" \
      -v q="$(metrics_counter_delta "$1" "$2" "$3"_queries_total)" '
    BEGIN { if (q + 0 > 0) printf "%.0f %.0f %.2f", h, q, 100.0 * h / q; else printf "%.0f %.0f NA", h, q }'
}
# Quantile rendu comme l'INTERVALLE DE BUCKET qui le contient, jamais comme une valeur
# interpolee. Prometheus (`histogram_quantile`) interpole lineairement DANS le bucket, ce
# qui suppose une repartition uniforme a l'interieur -- faux par construction pour le
# bucket qui porte la queue. Mesure sur une distribution synthetique connue (100 valeurs
# uniformes dans [1,3] s, buckets vLLM) : le vrai p95 vaut 2,909 s et l'interpolation en
# rend 4,500 s, soit +55 %, un nombre qui a l'air precis et qui est faux. Le bracket, lui,
# CONTIENT toujours la valeur -- et il dit franchement a quelle resolution on la connait.
# Les bornes +Inf ne sont pas interpolables non plus : le bracket est alors ouvert (" >a ").
# Somme EXACTE des valeurs observees (SUM du serveur, pas une interpolation). Sur une
# metrique a valeurs positives elle BORNE le maximum : SUM = a1 + ... + an >= max(a_i).
# Publier le total a donc plus de force qu'il n'y parait -- il interdit toute attente
# isolee superieure a lui-meme, ce qu'une moyenne par requete ne fait pas.
metrics_sum() {   # $1 = avant, $2 = apres, $3 = metrique -> somme exacte
  metrics_delta "$1" "$2" "$3" | awk '/^SUM /{printf "%.6f", $2 + 0}'
}
# Bracket du MAXIMUM observe -> "(a;b]" ou ">a". Meme construction que metrics_qbracket
# (tri par insertion : mawk n'a pas `asort`), mais sur le DERNIER echantillon au lieu d'un
# quantile. La resolution est celle des bornes publiees par le serveur : 0,3 s au minimum
# pour la file, donc un maximum en dessous n'est pas resolu plus finement -- c'est
# metrics_sum() qui l'encadre.
metrics_maxbracket() {   # $1 = avant, $2 = apres, $3 = metrique -> "(a;b]" ou ">a"
  metrics_delta "$1" "$2" "$3" | awk '
    /^COUNT / { n = $2 + 0; next }
    /^LE / {
      if ($2 == "+Inf") { inf = $3 + 0; next }
      k = $2 + 0
      if (!(k in seen)) { seen[k] = 1; nk++; ks[nk] = k }
      cum[k] = $3 + 0
      next
    }
    END {
      if (n <= 0 || nk == 0) { print "NA"; exit }
      for (i = 2; i <= nk; i++) { v = ks[i]; j = i - 1
        while (j >= 1 && ks[j] > v) { ks[j + 1] = ks[j]; j-- }
        ks[j + 1] = v }
      ple = 0
      for (i = 1; i <= nk; i++) {
        k = ks[i]; c = cum[k] + 0
        if (c >= n) { printf "(%.3f;%.3f]", ple, k; exit }
        ple = k
      }
      if (inf >= n) { printf ">%.3f", ple; exit }
      print "NA"
    }'
}
# Part des requetes AU-DESSUS d'un seuil -> "OVER <n>" et "PCT <p>".
# Le seuil est encadre par la plus grande borne publiee qui ne le depasse pas : le compte
# est EXACT quand le seuil tombe sur une borne, et un MAJORANT de la part reelle sinon
# (les requetes comptees comme « au-dessus » le sont alors d'une valeur plus petite que le
# seuil demande). Pour la file, passer 0,3 s -- la plus petite borne -- est donc exact.
metrics_over() {   # $1 = avant, $2 = apres, $3 = metrique, $4 = seuil -> OVER / PCT
  metrics_delta "$1" "$2" "$3" | awk -v b="$4" '
    /^COUNT / { n = $2 + 0; next }
    /^LE / { if ($2 != "+Inf") cum[$2 + 0] = $3 + 0; next }
    END {
      if (n <= 0) { print "OVER NA"; print "PCT NA"; exit }
      t = b + 0; best = -1
      for (k in cum) { kk = k + 0; if (kk <= t && kk > best) best = kk }
      c = (best >= 0) ? cum[best] + 0 : 0
      o = n - c
      printf "OVER %.0f\n", o
      printf "PCT %.2f\n", 100.0 * o / n
    }'
}
metrics_qbracket() {   # $1 = avant, $2 = apres, $3 = metrique, $4 = quantile -> [a;b] ou >a
  metrics_delta "$1" "$2" "$3" | awk -v q="$4" '
    /^COUNT / { n = $2 + 0; next }
    /^LE / {
      if ($2 == "+Inf") { inf = $3 + 0; next }
      k = $2 + 0
      if (!(k in seen)) { seen[k] = 1; nk++; ks[nk] = k }
      cum[k] = $3 + 0
      next
    }
    END {
      if (n <= 0 || nk == 0) { print "NA"; exit }
      for (i = 2; i <= nk; i++) { v = ks[i]; j = i - 1
        while (j >= 1 && ks[j] > v) { ks[j + 1] = ks[j]; j-- }
        ks[j + 1] = v }
      target = q * n; ple = 0
      for (i = 1; i <= nk; i++) {
        k = ks[i]; c = cum[k] + 0
        if (c >= target) { printf "[%.3f;%.3f]", ple, k; exit }
        ple = k
      }
      if (inf > 0) { printf ">[%.3f]", ple; exit }
      print "NA"
    }'
}

# Somme des DELTAS d'un COMPTEUR simple, avec un filtre de ligne optionnel.
# `metrics_delta` ne convient pas : il ne connait que les suffixes _bucket/_sum/_count
# d'un HISTOGRAMME. Ici la metrique est un compteur a etiquettes, dont on veut la somme
# de toutes les series (ou d'une seule, designee par `$4`).
# Deux usages, tous deux nes du meme constat (v8/v9) : la longueur de reponse etait
# SUPPOSEE egale a max_tokens. `generation_tokens_total` donne les jetons REELLEMENT
# produits, `request_success_total{finished_reason=...}` dit combien de requetes se sont
# arretees sur le plafond et combien ont fini d'elles-memes : leur rapport est la longueur
# moyenne REELLE, mesuree sur la meme fenetre que le debit.
# Le nom est suivi de `{` ou de la fin du nom pour qu'un prefixe commun ne soit pas
# compte deux fois (un `..._total` ne doit pas attraper un `..._total_extra`).
# Borne d'un intervalle textuel publie par metrics_*bracket : "(a;b]", "[a;b]" ou ">a".
# Sert a COMPARER deux intervalles entre eux -- ce que metrics_*bracket ne fait pas seul.
# Ex. brack "(1.000;2.500]" hi -> "2.500" ;  ">0.300" lo -> "0.300".
bracket_bound() {  # $1 = intervalle, $2 = lo|hi -> borne ou NA
  local s="${1:-__NA__}" w="$2"
  awk -v s="$s" -v w="$w" 'BEGIN{
    if (s == "__NA__" || s == "NA" || s == "") { print "NA"; exit }
    gsub(/^[([]/, "", s); gsub(/^[>]/, "", s); gsub(/[\]]$/, "", s)
    n = split(s, f, ";")
    if (n < 1 || f[1] == "") { print "NA"; exit }
    v = (w == "hi" && n >= 2) ? f[n] : f[1]
    sub(/^[^0-9.]+/, "", v); sub(/[^0-9.]+$/, "", v)
    if (v !~ /^[0-9]+(\.[0-9]+)?$/) { print "NA"; exit }
    print v }'
}

metrics_counter() {  # $1 = avant, $2 = apres, $3 = metrique, $4 = filtre optionnel -> entier
  awk -v m="$3" -v filt="${4:-}" -v f_av="$1" -v f_ap="$2" '
    function hit() { return ($1 ~ ("^vllm:" m "([{ ]|$)")) && (filt == "" || index($0, filt) > 0) }
    FILENAME == f_av { if (hit()) b += $NF; next }
    FILENAME == f_ap { if (hit()) a += $NF; next }
    END { printf "%.0f\n", a - b }' "$1" "$2"
}

# ------------------------------------------------------------------------------ 
# Mesure une charge : $1 = concurrence PAR NOEUD, $2 = duree en secondes.
run_level() {
  # nb_av / nb_ap sont declares ICI et pas plus bas : en bash, `local x` sur une
  # variable deja locale la REINITIALISE a vide. Les declarer dans le bloc du
  # decoupage serveur, apres leur affectation (les deux instantanes /metrics), effacait
  # donc la couverture deja mesuree -- `set -u` faisait ensuite avorter le palier, mais
  # AVANT ce correctif, une seconde declaration du meme genre aurait pu laisser passer
  # un simple 0 (la valeur d'un sous-ensemble pris pour la grappe entiere).
  local c="$1" t="$2" d start end n p m_ok nb_av nb_ap
  local wpids=() wi=0 b bw
  d="$(mktemp -d)"
  build_bodies >/dev/null || { echo "  (charge utile indisponible : palier saute)"; rm -rf "$d"; return 1; }
  # Echantillonnage GPU PENDANT ce palier, et pendant TOUT le palier : sans cela
  # on ne saurait pas a quelle concurrence le GPU sature reellement. L'arret est
  # commande APRES le dernier travailleur (2026-09-28) -- l'ancienne version
  # s'arretait a t echantillons et ne voyait donc que le prefixe du palier.
  local stopf="$d/stop" kvf="$d/kv" kvstopf="$d/kvstop"
  sample_until "$d/gpu" "$stopf" &
  # Echantillonneur de jauges (v8), sur la MEME fenetre que le debit : sans lui la ligne
  # du palier ne pouvait donner ni le pic de cache KV ni la profondeur de file.
  [ "$KV_SAMPLE" = "1" ] && kv_sample_until "$kvf" "$kvstopf" &
  local deadline=$(( $(date +%s) + t ))
  start="$(date +%s.%N)"
  # Instantane /metrics AVANT la premiere requete du palier. Les compteurs sont cumulatifs
  # depuis le demarrage du serveur : la difference avec celui pris apres ne compte donc que
  # les requetes de CE palier.
  nb_av="$(metrics_scan "$d/m.before")"
  for u in $URLS; do
    for w in $(seq 1 "$c"); do
      # Corps du travailleur : `wi % NBODIES` donne a chaque travailleur simultane un corps
      # DIFFERENT (tant que la concurrence ne depasse pas le nombre de corps, ce que le
      # palier annonce). Trois regimes, un seul mecanisme :
      #   VARY_PREFIX=0            -> 1 corps           (prefixe identique)
      #   VARY_PREFIX=1            -> NVARIANTS corps  (une image par travailleur)
      #   MAXTOK_SET=...           -> x T paliers      (un palier de longueur par travailleur)
      #   VARY_ROTATE=1            -> le travailleur AVANCE d'un corps par requete, donc
      #                               le jeu de prefixes en circulation vaut NBODIES quel
      #                               que soit le nombre de travailleurs simultanes.
      body_index "$wi" 0 "$NBODIES"; b="${BODIES[$BIDX]}"
      bw="$wi"
      wi=$((wi + 1))
      (
        _i=0
        while [ "$(date +%s)" -lt "$deadline" ]; do
          [ "$VARY_ROTATE" = "1" ] && { body_index "$bw" "$_i" "$NBODIES"; b="${BODIES[$BIDX]}"; }
          curl -s -o /dev/null -m 120 -w '%{time_total} %{http_code}\n' \
            "$u/v1/chat/completions" -H 'Content-Type: application/json' \
            -d "$b" >> "$d/lat" 2>/dev/null
          _i=$((_i + 1))
        done
      ) &
      wpids+=("$!")
    done
  done
  # On n'attend QUE les travailleurs : le premier `wait` sans argument attendrait
  # aussi l'echantillonneur, qui attend le fichier d'arret -> interblocage.
  for p in "${wpids[@]}"; do wait "$p"; done
  end="$(date +%s.%N)"
  : > "$stopf"; : > "$kvstopf"; wait
  # Instantane APRES : pris une fois le dernier travailleur sorti, donc toutes les requetes
  # du palier sont comptabilitees cote serveur. `end` est deja releve -- les ~30 ms que
  # prennent ces appels n'entrent pas dans l'intervalle mesure.
  nb_ap="$(metrics_scan "$d/m.after")"
  n="$(wc -l < "$d/lat" 2>/dev/null || echo 0)"
  # Longueurs REELLEMENT produites, mesurees ici et pas dans le bloc d'affichage : elles
  # servent a l'avertissement PALIERS_LONGUEURS ci-dessous, qui doit tomber AVANT que
  # quoi que ce soit du palier soit imprime.
  local sgen scap ssucc sp50 spmx l50 lmx
  sgen="$(metrics_counter  "$d/m.before" "$d/m.after" generation_tokens_total)"
  scap="$(metrics_counter  "$d/m.before" "$d/m.after" request_success_total 'finished_reason="length"')"
  ssucc="$(metrics_counter "$d/m.before" "$d/m.after" request_success_total)"
  # `request_generation_tokens` est un HISTOGRAMME publie par le serveur : il donne la
  # repartition des longueurs, pas seulement leur somme. `request_max_num_generation_tokens`
  # donne la meme chose pour le PLAFOND DEMANDE -- publier les deux separe ce qui a ete
  # demande de ce qui a ete produit.
  sp50="$(metrics_qbracket  "$d/m.before" "$d/m.after" request_generation_tokens 0.5)"
  spmx="$(metrics_maxbracket "$d/m.before" "$d/m.after" request_generation_tokens)"
  # --- Le faisceau de longueurs est-il REEL ? (v9) -----------------------------
  # KV(n) = P + n.g est l'ajustement d'un workload a longueur CONSTANTE. Des qu'un palier
  # melange les longueurs, cette pente ne le decrit plus -- et un seul nombre (la moyenne)
  # ne le dirait pas. Le test est MESURE, pas deduit du fait d'avoir passe MAXTOK_SET :
  # la borne INFERIEURE du maximum observe depasse-t-elle la borne SUPERIEURE de la
  # mediane ? Deux intervalles disjoints disent une distribution etalee, sans rien
  # supposer d'autre -- et un workload constant y repond non.
  l50="$(bracket_bound "$sp50" hi)"
  lmx="$(bracket_bound "$spmx" lo)"
  case "$l50:$lmx" in ''|*[!0-9.:]*) ;; *)
    if awk -v a="$l50" -v b="$lmx" 'BEGIN{ exit !(b > a) }'; then
      echo "      SERVEUR : ATTENTION PALIERS_LONGUEURS -- longueurs generees ETALEES (mediane plafonnee a $l50, maximum au-dela de $lmx) : la pente KV(n)=P+n.g calibree sur une longueur CONSTANTE ne decrit pas ce palier"
    fi ;;
  esac
  # 2026-09-28 : SEULES les reponses 200 entrent dans le debit et les percentiles.
  # Le nombre « erreurs » reste imprime ; les tentatives valent m + err.
  awk '$2 == 200 {print $1}' "$d/lat" 2>/dev/null | sort -n > "$d/t"
  m_ok="$(wc -l < "$d/t" 2>/dev/null || echo 0)"
  local errs; errs="$(awk '$2 != 200' "$d/lat" 2>/dev/null | wc -l)"
  awk -v t0="$start" -v t1="$end" -v c="$c" -v tot="$n" -v ne="$NENDPOINTS" -v err="$errs" '
    { a[NR] = $1; s += $1 }
    END {
      m = NR
      d = t1 - t0
      if (d <= 0) d = 0.000001
      if (m > 0) { p50 = a[int((m+1)*0.5)]; p95 = a[int((m+1)*0.95)] } else { p50 = 0; p95 = 0 }
      printf "  conc/neud=%3d (total %3d) | %5d ok / %5d tentatives | %6.1f req/s agrege | %5.1f req/s/neud | p50=%.3fs p95=%.3fs | erreurs=%d\n", \
             c, c*ne, m, tot, m/d, (m/d)/ne, p50, p95, err
    }' "$d/t"
  # GPU pendant ce palier uniquement -- et, depuis v4 (2026-09-28), SEULEMENT les
  # echantillons pris dans [start, end]. La PREMIERE lecture de l'echantillonneur est
  # prise ~2 ms avant `start`, GPU au repos (le palier precedent vient de finir) :
  # comptee, elle fait lire 92 % a un palier sature a 100 % (voir l'en-tete).
  # `NF >= 6` : un echantillon sans horodatage (vieux fichier) est conserve plutot
  # que silencieusement ecarte.
  if [ -s "$d/gpu" ]; then
    awk -F', *' -v c="$c" -v t0="$start" -v t1="$end" '
      NF >= 6 && ($6+0 < t0+0 || $6+0 > t1+0) { next }
      { v = $1+0; h[v]++
        sm += $1; vr += $3; pw += $4; ck += $5; n++
        if (n == 1 || v < smmin) smmin = v
        if (v > smmax) smmax = v
        if ($4+0 > pwmax) pwmax = $4+0 }
      END {
        if (n == 0) { printf "      GPU : aucun echantillon dans [start, end] -- palier plus court que la periode de 1 s ?\n"; exit }
        # Mediane par histogramme. Deux raisons de la publier a cote de la moyenne :
        # utilization.gpu est un entier 0..100, donc un histogramme suffit (et asort
        # est une extension gawk absente de mawk, awk par defaut sous Devuan) ; et un
        # unique echantillon parasite -- celui pris avant que la charge soit
        # appliquee -- deplace la moyenne de 100/n points mais pas la mediane. Une
        # divergence entre les deux signale que cet echantillon est encore present.
        med = 0; k = 0
        for (i = 0; i <= 100; i++) { k += h[i] + 0; med = i; if (k * 2 >= n) break }
        printf "      GPU : SM moy=%5.1f%% med=%5.1f%% (min %5.1f%% / max %5.1f%%) | VRAM=%6.0f Mio | puissance moy=%6.1f W (max %5.1f W) | n=%d\n", \
                 sm/n, med, smmin, smmax, vr/n, pw/n, pwmax, n }' "$d/gpu"
  fi
  # ------------------------------------------------------------------ cote serveur
  # Decoupage d'une requete en file d'attente / prefill / decode, calcule sur la MEME
  # fenetre que le debit et le p50 ci-dessus -- c'est tout l'interet de le faire ici.
  if [ -s "$d/m.before" ] && [ -s "$d/m.after" ]; then
    local sq sp sd st sinf se se50 se95 st50 sn sdelta sreset _pf _mm
    sq="$(metrics_mean     "$d/m.before" "$d/m.after" request_queue_time_seconds)"
    sp="$(metrics_mean     "$d/m.before" "$d/m.after" request_prefill_time_seconds)"
    sd="$(metrics_mean     "$d/m.before" "$d/m.after" request_decode_time_seconds)"
    sinf="$(metrics_mean   "$d/m.before" "$d/m.after" request_inference_time_seconds)"
    st="$(metrics_mean     "$d/m.before" "$d/m.after" time_to_first_token_seconds)"
    se="$(metrics_mean     "$d/m.before" "$d/m.after" e2e_request_latency_seconds)"
    se50="$(metrics_qbracket "$d/m.before" "$d/m.after" e2e_request_latency_seconds 0.5)"
    se95="$(metrics_qbracket "$d/m.before" "$d/m.after" e2e_request_latency_seconds 0.95)"
    st50="$(metrics_qbracket "$d/m.before" "$d/m.after" time_to_first_token_seconds 0.5)"
    sn="$(metrics_delta      "$d/m.before" "$d/m.after" e2e_request_latency_seconds | awk '/^COUNT /{print $2}')"
    # Un compteur cumulatif qui recule = serveur redemarre entre les deux instantanes.
    # Les moyennes et les quantiles sont alors NA (delta < 0), ce qui ne dit pas
    # POURQUOI : ce drapeau le dit, et interdit de lire la ligne comme un palier vide.
    sreset="$(metrics_delta   "$d/m.before" "$d/m.after" e2e_request_latency_seconds | awk '/^RESET /{print $2}')"
    # n cote SERVEUR (requetes terminees) contre ok cote CLIENT (HTTP 200). Un petit
    # ecart est normal : un palier qui se termine laisse des requetes en vol qui
    # aboutissent apres `end`. Un ecart LARGE veut dire que les deux lignes ne parlent
    # pas des memes requetes, et alors le decoupage ne s'applique pas au debit affiche.
    sdelta="?"
    case "$sn" in ''|*[!0-9]*) ;; *) sdelta=$((sn - m_ok)) ;; esac
    printf '      SERVEUR : n=%s (ok client=%s, ecart=%s) | file moy=%ss | prefill moy=%ss | decode moy=%ss | inference moy=%ss\n' \
           "$sn" "$m_ok" "$sdelta" "$sq" "$sp" "$sd" "$sinf"
    # --- FORME de la file, et pas seulement sa moyenne (v6) ----------------------
    # Voir l'en-tete, v6 : une moyenne par requete dilue un pic court. `total` est la
    # somme EXACTE, donc un plafond dur du maximum ; `max` et `>seuil` sortent des
    # buckets et ne valent que ce que leur resolution vaut.
    local sq_total smax sover spct _ov
    sq_total="$(metrics_sum        "$d/m.before" "$d/m.after" request_queue_time_seconds)"
    smax="$(metrics_maxbracket "$d/m.before" "$d/m.after" request_queue_time_seconds)"
    _ov="$(metrics_over         "$d/m.before" "$d/m.after" request_queue_time_seconds "$QUEUE_EDGE_S")"
    sover="$(printf '%s\n' "$_ov" | awk '/^OVER /{print $2}')"
    spct="$(printf '%s\n' "$_ov" | awk '/^PCT /{print $2}')"
    printf '      SERVEUR : file total=%ss (plafond dur du max) | max=%s | >%ss : %s req (%s %%)\n' \
           "$sq_total" "${smax:-NA}" "$QUEUE_EDGE_S" "${sover:-?}" "${spct:-?}"
    # La file ne peut pas etre lue comme « vide » quand elle ne l'est pas : les deux
    # nombres ci-dessus peuvent diverger sans se contredire (peu de requetes, brievement),
    # et une requete ayant franchi 0,3 s est exactement ce qu'une moyenne cacherait.
    case "${sover:-}" in ''|*[!0-9]*) ;; *)
      [ "$sover" -gt 0 ] && \
        echo "      SERVEUR : la file a REELLEMENT fait attendre $sover requete(s) au-dela de ${QUEUE_EDGE_S}s -- la moyenne seule ne le montrait pas" ;;
    esac
    # --- PIC du cache KV, profondeur de file, et taux des deux caches (v8) ------
    # Ces nombres n'existaient pas dans la ligne d'un palier : il fallait lancer un
    # echantillonneur a part, sur une AUTRE fenetre. Le pic est pris ici sur la MEME
    # fenetre [start, end] que le debit et le p50.
    if [ -s "$kvf" ]; then
      kv_peak_report "$kvf" "$start" "$end" | awk '
        {
          if ($1 == "NA") { print "      SERVEUR : PIC cache KV -- aucun echantillon dans la fenetre"; exit }
          printf "      SERVEUR : PIC cache KV=%.2f %% (%s) | en cours max=%d | en attente max=%d | %d lectures a %.1f Hz\n", $1 * 100, $2, $3, $4, $5, $6
          if ($4 + 0 > 0) printf "      SERVEUR : ADMISSION ATTEINTE -- %d requete(s) en attente au pic\n", $4 + 0
        }'
    fi
    # Les deux caches, lus dans les instantanes DEJA pris : pas une lecture de plus.
    # `mm_cache` est le cache des embeddings visuels ; `prefix_cache` celui du KV. Les
    # separer est ce qui distingue « le prefixe n'est plus reutilise » de « l'encodeur
    # visuel est recalcule » -- deux causes que le debit seul ne departage pas.
    _pf="$(metrics_cache_rate "$d/m.before" "$d/m.after" prefix_cache)"
    _mm="$(metrics_cache_rate "$d/m.before" "$d/m.after" mm_cache)"
    awk -v p="$_pf" -v m="$_mm" 'BEGIN{
      split(p, a, " "); split(m, b, " ")
      printf "      SERVEUR : cache prefixe %s %% (%s/%s jetons) | multimodal %s %% (%s/%s)\n", a[3], a[1], a[2], b[3], b[1], b[2]
    }'
    # --- LONGUEUR REELLEMENT GENEREE (v9) ---------------------------------------
    # Jusqu'ici la longueur generee etait SUPPOSEE egale a max_tokens. La v6/v7 en a
    # deduit « g = 96 jetons = 6 blocs », identite qui a servi de reference a un modele
    # KV(n) = P + n.g. Un palier a max_tokens VARIE (v8) a montre que cette egalite
    # n'etait qu'une coincidence du workload a longueur CONSTANTE : la pente mesuree
    # (84 jetons/requete pour des paliers de moyenne 160) s'en ecarte. Le serveur publie
    # de quoi trancher -- jetons generes, et repartition des fins de requete. C'est cette
    # mesure, prise sur la MEME fenetre que le debit, qui doit servir de reference.
    local sgen scap ssucc
    sgen="$(metrics_counter  "$d/m.before" "$d/m.after" generation_tokens_total)"
    scap="$(metrics_counter  "$d/m.before" "$d/m.after" request_success_total 'finished_reason="length"')"
    ssucc="$(metrics_counter "$d/m.before" "$d/m.after" request_success_total)"
    # p50 / max de la longueur generee, plus le plafond DEMANDE (tiers) : trois choses qui
    # ne sont pas deduites l'une de l'autre. Une moyenne de 73 n'exclut pas un max au
    # plafond (320), et des tiers melanges n'impliquent pas une distribution etalee si
    # EOS y domine. Ce sont les HISTOGRAMMES qui le disent -- et la moyenne seule ne le
    # cache pas.
    # PAS de colonne « plafond demande » : elle a existe en v9, alimentee par
    # `request_max_num_generation_tokens`, et un probe de la meme passe a montre que
    # cette metrique rend EXACTEMENT la meme chose que `request_generation_tokens` sur
    # cette version de vLLM (memes somme, meme compte, memes buckets, y compris sous
    # MAXTOK_SET ou les plafonds demandes sont 16/48/80/112 alors que la somme vaut
    # 6300 = les jetons PRODUITS). L'afficher comme « le plafond demande » etait donc
    # une affirmation fausse. Ce qui a ete demande se lit dans l'en-tete du balayage
    # (MAXTOK_SET), pas dans /metrics ; voir probe-gen-distribution.log.
    local _sqm
    _sqm="$(metrics_mean "$d/m.before" "$d/m.after" request_generation_tokens)"
    # `g >= 0` en plus de `s > 0` : un compteur qui RECULE (serveur redemarre entre les
    # deux instantanes) rend une longueur negative, qui serait publiee comme un nombre.
    # Le fait est deja signale par l'avertissement RESET de la meme ligne de palier ; on
    # n'invente pas de valeur ici, on refuse de la publier.
    awk -v qm="$_sqm" -v p50="$sp50" -v mx="$spmx" -v c="$scap" -v s="$ssucc" -v g="$sgen" 'BEGIN{
      if (s + 0 > 0 && g + 0 >= 0) {
        printf "      SERVEUR : longueur GENEREE moy=%s/req | p50=%s | max=%s | fin sur plafond max_tokens : %.1f %% (%s/%s requetes)\n",   qm, p50, mx, 100*c/s, c, s
      } else {
        print "      SERVEUR : longueur generee NON mesuree (aucune fin de requete comptee dans la fenetre)"
      }
    }'
    printf '      SERVEUR : TTFT moy=%ss p50=%s | e2e moy=%ss p50=%s p95=%s   [e2e ~= file + inference]\n' \
           "$st" "$st50" "$se" "$se50" "$se95"
    # Les trois avertissements suivants ne s'impriment QUE si la propriete qu'ils
    # surveillent manque : un palier sain reste a deux lignes, et un palier douteux
    # ne peut pas etre lu comme un palier sain. Le `true` final donne au bloc un
    # statut nul -- les tests `[ ]` seuls sortent en 1 quand ils sont FAUX, c'est-a-dire
    # dans le cas NORMAL.
    [ "${nb_ap:-0}" -lt "$NENDPOINTS" ] && \
      echo "      SERVEUR : ATTENTION /metrics obtenu de $nb_ap / $NENDPOINTS endpoints -- decoupage et ecart calcules sur un SOUS-ENSEMBLE de la grappe"
    [ "${nb_av:-0}" -lt "$NENDPOINTS" ] && \
      echo "      SERVEUR : ATTENTION instantane AVANT incomplet ($nb_av / $NENDPOINTS) -- les deltas des endpoints muets comptent depuis LEUR demarrage, pas depuis ce palier"
    [ "$sreset" = "1" ] && \
      echo "      SERVEUR : ATTENTION compteurs reinitialises entre les deux instantanes (serveur redemarre) -- le decoupage NE decrit PAS ce palier"
    true
  else
    echo "      SERVEUR : /metrics indisponible -- decoupage file/prefill/decode NON mesure"
  fi
  rm -rf "$d"
}

# ---------------------------------------------------------------- MODE=load
if [ "$MODE" = "load" ]; then
  build_bodies >/dev/null || { echo "charge utile indisponible : $IMG"; exit 1; }
  echo "==== charge concurrence FIXE -- $(date -Is) ===="
  echo "endpoints : $URLS   [source: $URLS_SOURCE]"
  echo "modele    : $SERVED   ($NENDPOINTS endpoints)"
  echo "charge    : temperature=$TEMPER max_tokens=$MAXTOK   [source: $PAYLOAD_SOURCE]"
  if [ -n "$MAXTOK_SET" ]; then
    echo "longueurs : max_tokens VARIE par travailleur -- $MAXTOK_SET"
    echo "            -> HORS du payload que health valide (le DEFAULT reste $DEFAULT_MAX_TOKENS)"
  fi
  if [ "$VARY_ROTATE" = "1" ]; then
    echo "rotation  : ACTIVEE -- un corps different par requete (jeu de prefixes = $NBODIES)"
  fi
  echo "prompt    : $PROMPT"
  if [ "$NVARIANTS" -gt 0 ]; then
    echo "prefixe   : VARIE -- $NVARIANTS images distinctes ($VARIANT_DIR)"
  else
    echo "prefixe   : IDENTIQUE -- $IMG"
  fi
  echo "note      : pas de ligne 'SERVEUR :' dans ce mode -- elle demande un instantane"
  echo "            /metrics de part et d'autre d'une fenetre bornee, donc MODE=sweep"
  # charge longue : boucle jusqu'a epuisement de REQ par travailleur
  d="$(mktemp -d)"; start="$(date +%s.%N)"
  wi=0; b=""; bw=0
  for u in $URLS; do
    for w in $(seq 1 "$CONC"); do
      body_index "$wi" 0 "$NBODIES"; b="${BODIES[$BIDX]}"
      bw="$wi"
      wi=$((wi + 1))
      ( for r in $(seq 1 "$REQ"); do
          [ "$VARY_ROTATE" = "1" ] && { body_index "$bw" "$((r - 1))" "$NBODIES"; b="${BODIES[$BIDX]}"; }
          curl -s -o /dev/null -m 120 -w '%{time_total} %{http_code}\n' \
            "$u/v1/chat/completions" -H 'Content-Type: application/json' \
            -d "$b" >> "$d/lat" 2>/dev/null
        done ) &
    done
  done
  wait
  end="$(date +%s.%N)"
  # 2026-09-28 : comme run_level, seules les reponses 200 sont comptees.
  awk '$2 == 200 {print $1}' "$d/lat" 2>/dev/null | sort -n > "$d/t"
  n="$(wc -l < "$d/lat" 2>/dev/null || echo 0)"; errs="$(awk '$2 != 200' "$d/lat" 2>/dev/null | wc -l)"
  awk -v t0="$start" -v t1="$end" -v tot="$n" -v ne="$NENDPOINTS" -v err="$errs" '
    { a[NR] = $1; s += $1 }
    END {
      m = NR
      d = t1 - t0
      if (d <= 0) d = 0.000001
      if (m > 0) { p50 = a[int((m+1)*0.5)]; p95 = a[int((m+1)*0.95)] } else { p50 = 0; p95 = 0 }
      printf "\nDEBIT    : %d OK en %.2f s (%d tentatives)  =>  %.1f req/s AGREGE (%.1f /noeud)\n", m, d, tot, m/d, (m/d)/ne
      printf "LATENCE  : p50=%.3fs p95=%.3fs min=%.3fs max=%.3fs moyenne=%.3fs\n", p50, p95, a[1], a[m], s/m
      printf "ERREURS  : %d requete(s) hors HTTP 200\n", err
    }' "$d/t"
  rm -rf "$d"
  exit 0
fi

# ---------------------------------------------------------------- MODE=sweep
if [ "$MODE" = "sweep" ]; then
  build_bodies >/dev/null || { echo "charge utile indisponible : $IMG"; exit 1; }
  echo "==== BALAYAGE DE CONCURRENCE -- $HOST -- $(date -Is) ===="
  # Le prefixe envoye n'est pas un detail de confort : c'est lui qui decide si le cache
  # de prefixe partage ou non. La ligne le dit, parce qu'un balayage « prefixe identique »
  # et un balayage « prefixes distincts » ne mesurent pas la meme ressource.
  if [ "$NVARIANTS" -gt 0 ]; then
    echo "workload  : $NVARIANTS images DISTINCTES ($VARIANT_DIR) + reponse courte"
    if [ "$VARIANT_COUNT" -gt 0 ]; then
      echo "jeu       : LIMITE a $VARIANT_COUNT variante(s) sur $(ls -1 "$VARIANT_DIR"/v*.jpg 2>/dev/null | wc -l) deployee(s)"
      echo "            -> a concurrence FIXE, c'est ce nombre qui fait varier la taille du"
      echo "               jeu de prefixes : la retention se lit en fonction de la TAILLE DU JEU"
    fi
    echo "            -> le cache de prefixe ne peut PAS partager : le cache KV se charge"
    echo "               par le PREFIXE, comme sur une charge reelle"
  else
    echo "workload  : 1 image ($IMG) + reponse courte"
    echo "            -> prefixe IDENTIQUE pour toutes les requetes : le cache de prefixe"
    echo "               le partage, et le cache KV ne coute que les jetons GENERES"
  fi
  echo "charge    : temperature=$TEMPER max_tokens=$MAXTOK   [source: $PAYLOAD_SOURCE]"
  if [ -n "$MAXTOK_SET" ]; then
    echo "longueurs : max_tokens VARIE par travailleur -- $MAXTOK_SET"
    echo "            -> HORS du payload que health valide (le DEFAULT reste $DEFAULT_MAX_TOKENS)"
  fi
  if [ "$VARY_ROTATE" = "1" ]; then
    echo "rotation  : ACTIVEE -- un corps different par requete (jeu de prefixes = $NBODIES)"
  fi
  echo "prompt    : $PROMPT"
  echo "endpoints : $URLS   [source: $URLS_SOURCE]"
  echo "modele    : $SERVED"
  echo "paliers   : concurrence PAR NOEUD = $LEVELS ; duree = ${T}s par palier"
  if [ "$NVARIANTS" -gt 0 ]; then
    if [ "$VARY_ROTATE" = "1" ]; then
      # Avec la rotation, le jeu de prefixes ne depend PAS de la concurrence : c'est le
      # nombre de corps construits. La ligne « min(concurrence, variantes) » serait fausse.
      if [ "$VARIANT_COUNT" -gt 0 ]; then
        echo "prefixes  : ROTATION -- jeu de $NBODIES corps (limite a $VARIANT_COUNT images), independant de la concurrence"
      else
        echo "prefixes  : ROTATION -- jeu de $NBODIES corps, independant de la concurrence"
      fi
      if [ "$VARY_STRIDE" != "1" ]; then
        echo "partage   : PAS de rotation = $VARY_STRIDE -- deux travailleurs ne partagent un"
        echo "            prefixe que si leur ecart est un multiple de $VARY_STRIDE ; un pas egal a"
        echo "            la concurrence par noeud rend les classes DISJOINTES (aucun partage en"
        echo "            meme temps), ce qui teste si la reutilisation a besoin d'un porteur vivant"
      fi
    else
      echo "prefixes  : min(concurrence par noeud, $NVARIANTS) prefixes distincts simultanes"
      for c in $LEVELS; do
        [ "$c" -gt "$NVARIANTS" ] && echo "            ATTENTION au palier $c : la concurrence depasse les $NVARIANTS" \
          && echo "            variantes -- $(( c - NVARIANTS )) travailleurs partagent leur prefixe"
      done
    fi
  fi
  echo
  for c in $LEVELS; do run_level "$c" "$T"; done
  echo
  echo "-- Lecture : latence PLATE = le serveur n'est pas le facteur limitant."
  echo "   Au-dela du genou la LATENCE monte ; le debit, lui, peut remonter (le serveur"
  echo "   groupe davantage de requetes par pas). Le genou se lit donc sur la latence :"
  echo "   le SM vaut deja 100 % des 4 requetes par noeud, il ne le localise pas."
  echo "-- Le GPU est echantillonne PAR PALIER (ligne 'GPU :'), jamais en moyenne"
  echo "   sur le balayage : une moyenne melangerait un palier leger et un palier sature."
  echo "-- Les lignes 'SERVEUR :' viennent des histogrammes /metrics des serveurs,"
  echo "   differenties sur la MEME fenetre que le debit et le p50 de leur palier."
  echo "   Moyennes exactes ; les quantiles sont des INTERVALLES de bucket [a;b], pas des"
  echo "   valeurs interpolees : le p95 cote client (exact) et le bracket cote serveur"
  echo "   doivent etre lus ensemble, pas confondus."
  exit 0
fi

# ---------------------------------------------------------------- MODE=collect
echo "==== collecte -- $HOST -- $(date -Is) ===="
echo
echo "-- 0. cible de mesure (resolue, pas deduite) --"
echo "  endpoints : $URLS"
echo "  source    : $URLS_SOURCE"
echo "  modele    : $SERVED   ($NENDPOINTS endpoints)"
echo "  image     : $IMG"
if [ "$VARY_PREFIX" = "1" ]; then
  echo "  prefixe   : VARIE -- VARY_PREFIX=1, repertoire $VARIANT_DIR"
  echo "              $(ls -1 "$VARIANT_DIR"/v*.jpg 2>/dev/null | wc -l) variante(s) disponible(s)"
else
  echo "  prefixe   : IDENTIQUE -- VARY_PREFIX=$VARY_PREFIX (1 = une image par travailleur)"
fi
echo "  charge    : temperature=$TEMPER max_tokens=$MAXTOK   [source: $PAYLOAD_SOURCE]"
echo "  prompt    : $PROMPT"
echo
echo "-- 1. arguments de lancement du service vLLM (lecture seule) --"
ps -eo args | grep -E 'vllm serve|vllm\.entrypoints' | grep -v grep | head -2 || echo "  (introuvable)"
echo
echo "-- 2. regime d'echantillonnage GPU --"
echo "  (colonnes normalisees SM%, MEM%, VRAM Mio, W, MHz, puis l'horodatage epoch)"
echo
echo "-- 3. etat GPU courant --"
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,power.draw,power.limit,clocks.current.sm,clocks.max.sm \
  --format=csv 2>/dev/null
echo
echo "-- 4. echantillon ($SAMPLE_F) --"
gpu_summary "$SAMPLE_F"
echo
echo "-- 5. 10 premiers echantillons bruts (SM%, MEM%, VRAM, W, MHz, epoch) --"
head -10 "$SAMPLE_F" 2>/dev/null | sed 's/^/  /'
