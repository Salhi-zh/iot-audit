# `benchmarks/` — les bancs du projet

Ce dossier porte **deux** bancs, et chacun produit l'artefact qu'une porte exige.
Règle commune : **tout chiffre publié est régénéré par un script**, jamais recopié.

| banc | script | artefact | sert à |
|---|---|---|---|
| **perception** — reconnaître l'objet | `run_identification.py` | `results.json` / `results.md` | `docs/07` §6, figure M1-M9 (porte **G6**) |
| **failles** — retrouver les CVE du produit | `run_cve.py` | `cve.json` / `cve.md` | porte **G1** (2ᵉ import, 60 cas, p95) |
| **écart d'une variante** | `run_variant_eval.py` | `recognition-<tag>.json` / `.md` | comparer un run à la référence gelée |
| **audit des figures** | `object_figures.py` | Markdown sur stdout | recalculer les figures objet d'une section de `docs/06` (`§20`, `§21`) |

```bash
.venv/bin/python      benchmarks/run_identification.py   # réécrit results.json + results.md
.venv-core/bin/python benchmarks/run_cve.py              # réécrit cve.json + cve.md
.venv-core/bin/python benchmarks/object_figures.py \
    --predictions evidence/2026-09-14/corpus/predictions-zabeth22.json --label "v1"
```

> **Deux venvs, et ce n'est pas un détail.** `run_cve.py` lit les flux NVD bruts en
> flux (``ijson``) : il doit tourner dans le venv de l'ingestion (`.venv-core`), qui
> est aussi celui des tests. `run_identification.py` n'a besoin que de `.venv`.

## 1. Le banc de perception (identification)

> `docs/07` §6 — *« Sortie : un ``benchmarks/results.json`` horodaté + ``benchmarks/results.md``
> lisible, **régénérés par un script** (donc citables dans le rapport). »*

## Ce que le banc publie

| Section de `results.md` | Ce que c'est | Définition de référence |
|---|---|---|
| §1 Image | identification (marque, modèle A **et** P) et classification, au niveau **image** | `docs/06` §5 |
| §2 **Objet** | **M1** = marque **et** modèle, agrégation **modale** des photos de l'objet — **importé de `iot_audit/corpus/metrics.py`**, jamais recalculé ici | `docs/06` §5, §8, **§19** |
| §3 Choix de la règle | sélection sur *train*, publication sur *eval*, découpage **gelé par hachage** | `docs/06` §16.2 |
| §4 Base | `label` (texte lu) vs `visual` (forme reconnue) — **est-elle informative ?** | `docs/06` §15 |
| §5 Classification | exactitude par catégorie + **matrice de confusion** | D12, `docs/06` §9.2 |
| §6 Strates / canal | contrôle de contamination + `text_visible` | M2, M3 |
| §7 Rejeu | accord entre deux exécutions indépendantes | **M9** |
| §8 Latence | p50 / p95 / p99 / max | **M8** |

## Les trois règles que ce banc respecte, et pourquoi

1. **Aucun chiffre saisi à la main.** La source est unique : le run **v4 gelé**
   (`evidence/2026-09-15/corpus/expanded/predictions-v4-shard{0,1,2}.json`, 144 images,
   48 objets) et le **barème gelé**. Le barème est désormais **dans le dépôt** —
   `iot_audit/corpus/audit_grading.py`, copie octet pour octet du fichier voisin à une
   ligne près (le chemin d'évidence). Provenance, deux `sha256`, le diff exact et les
   tests de dérive : `iot_audit/corpus/VENDORED-audit-grading.md`. Il était auparavant
   chargé depuis `../zabeth22-vllm-repair/`, c'est-à-dire depuis **hors du dépôt** — un
   risque de reproductibilité en soi.

   **M1 objet n'est pas calculé par ce banc.** Il l'**importe** de
   `iot_audit.corpus.metrics` (`object_results` + `summarize`). Un banc qui réimplémente
   la métrique qu'il prétend mesurer finit par en mesurer une autre : c'est arrivé ici,
   et c'est daté (`docs/06` §19.1 — le §2 de `results.md` notait `model_correct` **seul**
   sous l'étiquette « marque ET modèle », et publiait `8/48` là où M1 vaut `10/48`).
2. **`n` et intervalle obligatoires.** Tout taux passe par `wilson()` ; aucune ligne
   n'est publiée sans son `n` (`docs/07` : *« aucune ligne `MESURÉ` ne peut être publiée
   sans `n` et sans intervalle »*).
3. **Sélection ≠ publication.** Une règle choisie sur *train* est publiée sur *eval*,
   jamais l'inverse, et le découpage est **par objet** (découper par image mettrait des
   photos du même objet des deux côtés).

## Ce que ce banc a validé en le construisant

Le banc **reproduit exactement** les figures déjà publiées du dossier sous le critère
**P** : exactitude totale `79/144 = 0,549`, base `label` `37/80 = 0,463`, base `visual`
`42/64 = 0,656`. C'est un contrôle : mêmes données, même barème, mêmes chiffres. La
branche `A` du même barème donne, elle, `64/144 = 0,444` — les deux critères sont
publiés côte à côte, comme le prescrit le module de notation.

## 2. Le banc des failles (porte G1)

`run_cve.py` produit la preuve de G1, et il la produit **sans jamais demander à la
base si la base a bien travaillé** : la vérité terrain est re-dérivée des flux
`.json.gz` **bruts**, par un lecteur écrit dans le banc, qui ne partage aucun code
avec `iot_audit.vuln.ingest` ni avec `iot_audit.vuln.search`. Un test qui interroge
la base pour vérifier la base ne prouve rien.

| section de `cve.md` | ce qu'elle établit |
|---|---|
| §1 La source | comptes de critères re-dérivés du brut, confrontés à `feed_versions.row_count` |
| §2 **Couverture** | ce que le filtre `part='h'` retire, par vendeur du corpus |
| §3 Idempotence | 3 passes (dont une **écriture forcée**), comptes de données identiques, 0 doublon |
| §4 Les 60 cas | strates, 0 faux négatif, faux positifs documentés, p95 |

Trois pièges que le banc évite, parce qu'ils lui ont coûté une itération chacun :

1. **Relancer le même fichier ne teste pas l'écriture.** L'empreinte du flux le fait
   sauter avant qu'une seule ligne soit écrite : cela prouve la *provenance*, pas
   l'idempotence du chemin d'écriture. D'où la passe 3, sur des copies renommées.
2. **`feed_versions` n'est pas une table de données.** Elle doit *grandir* à la
   passe 3 (4 lignes de provenance en plus) : comparer le dictionnaire de comptes
   entier ferait échouer la porte sur un comportement voulu.
3. **`product='*'` n'est pas un produit.** Le prendre comme cas de test produit une
   requête `search_cve(v, '*')` qui ne teste rien du chemin nominal.

> **Ce que la section 2 montre, et qui n'est pas un détail de banc** : le filtre
> `part='h'` de l'ingestion laisse la base avec **10 CVE sur 11 714** pour les
> vendeurs du corpus (0,09 %). Le banc peut donc être **vert** et la chaîne CVE
> **inutile pour l'audit**. La mesure est là pour que cette décision se prenne sur
> un chiffre (CDC §14.3.10) et non sur une impression.

## Le complément indispensable : `corpus/diagnose_identification.py`

Le banc ci-dessus dit **combien**. Il ne dit pas **pourquoi**. Le deuxième outil
répond à cette question — et c'est celui qui décide de la suite :

```bash
.venv/bin/python corpus/diagnose_identification.py --run v2   # run publié d'origine
.venv/bin/python corpus/diagnose_identification.py --run v4   # run gelé courant
```

Il confronte chaque échec au texte **réellement présent dans l'image**, lu par trois
instruments indépendants (deux OCR + la transcription `visible_text` du VLM) et
étiquette :

| étiquette | sens | actionnable ? |
|---|---|---|
| `reconnue` | marque et modèle corrects | — |
| `reference_lue_non_restituee` | la référence **est lisible** et n'est pas rendue | **oui** |
| `near_miss` | confusion d'un caractère (`HS110` → `HS105`) | **oui** |
| `modele_egale_marque` | le champ `model` recopie la marque | contrat |
| `vide` | refus devant une image muette | non |
| `sans_appui_textuel` | aucune des 3 lectures ne contient la référence | non (par le texte) |

Il **agrège ensuite la taxonomie au niveau objet**, parce que c'est le niveau qui
décide (M1) : parmi les objets ratés, combien ont au moins une photo où la référence
était lisible (donc récupérables) et combien n'en ont aucune. Cela donne le **plafond
exact** de toute action sur le prompt — et ce plafond ne suffit pas : voir `docs/06` §18.

> **Piège à connaître** : ne pas normaliser les chaînes *avant* de les confier au
> barème. Le barème normalise lui-même, et sa distinction A/P ne porte que sur le
> tiret/souligné : pré-normaliser efface la distinction qu'on cherche à mesurer
> (17/48 au lieu de 16/48 — défaut trouvé et corrigé le 2026-09-29, `docs/06` §18.4).

## La règle d'étiquetage : niveau × barème

Le dépôt porte **deux** barèmes et **deux** niveaux, et un chiffre n'a de sens que si
les deux sont nommés (`docs/06` §21). Toute figure publiée doit donc porter sa ligne
`niveau × barème` :

| barème | sémantique | où |
|---|---|---|
| `iot_audit.corpus.metrics` | sous-chaîne bidirectionnelle sur `normalise()` (tirets → espace) | M1 objet, canal `text_visible` au niveau image |
| `audit-grading` **A** / **P** | barème gelé ; A garde le tiret, P l'assimile à l'espace | figures image du §10 et du §14 |

Les figures de `object_figures.py` sont en **`metrics`**, au niveau **objet** — ce ne sont
donc **pas** les taux image du §10/§14, et les comparer revient à changer deux choses à la
fois. Le recoupement mesure les quatre combinaisons sur les trois exécutions de
2026-09-14 (`probe-niveau-bareme.py`, sortie dans l'évidence de l'audit) : c'est lui qui a
nommé la ligne `catégorie` du §10.2 (`metrics`) et celle du §14.1 (A).

## Limites, écrites pour ne pas les découvrir plus tard

- Le banc mesure **le modèle sur un corpus web** — pas des photos terrain, pas de
  version firmware (limites 1 et 2 de `docs/07` §8).
- `n` = 48 objets. À cette taille, **aucune règle d'agrégation n'est distinguable
  d'une autre** ; le banc l'écrit explicitement au §3 de `results.md` au lieu de
  désigner un « gagnant » qui serait du bruit. `oracle_any` (`17/48 = 0,354`) borne le
  problème **en amont** de l'agrégation : aucune règle ne peut dépasser ce plafond.
- **M1 dépend de la règle de consolidation, et les deux se publient** : `conservative`
  (l'abstention compte — c'est la règle des figures publiées) donne `10/48 = 0,208`,
  `answered` (l'abstention sort du vote) donne `15/48 = 0,312`. Le prompt du projet
  **ordonne** l'abstention, donc la première pénalise un modèle qui obéit. Aucune ligne
  de ce dépôt ne doit écrire « M1 » sans nommer sa règle (`docs/06` §19.2).
- **L'ordre des lignes ne doit pas compter.** `object_results` prescrit l'ordre
  `image_id` ; sans cela, deux consommateurs du même dépôt publient `10/48` et `11/48`
  pour la même donnée (`docs/06` §19.3). Le verrou est
  `tests/test_metrics_object.py::test_m1_ne_depend_pas_de_lordre_dappel`.
- Le banc **ne couvre pas** la chaîne CPE/CVE (c'est le chemin critique du plan, et un
  autre chantier).
