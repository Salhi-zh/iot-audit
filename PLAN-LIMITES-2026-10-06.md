# Plan — fermer les cinq limites déclarées le 2026-10-06

Objet : comment lever, une par une, les limites annoncées honnêtement à la fin de
la session du 2026-10-06. Pour chacune : ce qui est **vrai aujourd'hui** (avec le
fichier et la ligne), la **cause racine**, les options avec leur coût, l'option
retenue, et le **critère d'acceptation chiffré** qui la clôt.

Règle de travail, la même que partout ailleurs dans ce dépôt : une mesure avant
une décision, et un refus honnête plutôt qu'une valeur inventée. Deux des cinq
limites se sont révélées **plus faciles** que déclaré (les données existent déjà) ;
une s'est révélée **plus dure** (un champ que le modèle ne renseigne pas comme le
document l'espère). Les deux cas sont écrits tels quels.

---

## 0. Résumé exécutable

| # | Limite | Verdict après enquête | État au 2026-10-06 |
|---|---|---|---|
| 4 | Retouches non commitées mêlées au travail en attente | **faisable maintenant**, 2 techniques | **fermée** — `b15a175` |
| 2a | `n_salient_objects` vaut 1 sans avoir été demandé | **défaut réel** : un non-vérifié lu comme un feu vert | **fermée** — `0b6c3de` |
| 1 | Le cadrage n'est pas demandé par le prompt v6 | faisable, ~5 min de GPU | **sonde faite** — détecte 47 %, donc **v7 non écrit** |
| 3 | Étiquette falsifiée non détectée | **mesurable hors GPU** : sorties réelles en réserve | **mesurée** — **0 détection** sur le corpus ; détecteur câblé pour son cas injecté |
| 2b | Aucun producteur de `Provenance` | butte sur un élément ouvert connu (`model_revision`) | **fermée** — `591bd9b` (station) + `c079209` (nœud), D1 = D1-a |
| 5 | `cahiers/ETAT-AVANCEMENT-2026-10-02.*` gelé | **pas une limite** : contrainte, rien à faire | respectée (mtime inchangé) |

L'inventaire **mesuré** de ce qui reste non commité (et de ce que j'avais mal estimé)
est dans `PLAN-LIMITES-2026-10-06-ANNEXE-RESIDUS.md`.

Ordre d'exécution : **4 → 2a → 1 → 3 → 2b** (les quatre premières sont faites ; le
journal d'exécution est au §9, et les chiffres que l'exécution a démentis sont
corrigés sur place). La raison n'est pas la difficulté :
la limite 4 est de l'hygiène qui rend les quatre autres lisibles (aujourd'hui un
`git diff` sur `infra/README.md` fait 1552 lignes dont 60 sont à moi), et la
limite 2a est un défaut de sincérité de l'affichage qu'il serait malhonnête de
laisser pendant qu'on travaille sur la limite 1, qui le concerne directement.

---

## 1. Limite 4 — les retouches non commitées sont mêlées au travail en attente

### Ce qui est vrai

* `infra/README.md` : **2 hunks** seulement, mais mon bloc est *dans* le hunk
  géant (`@@ -596,0 +602,1552 @@`, mon en-tête à la ligne 1519 des ajouts). Le
  hunk contient donc le travail de l'utilisateur **et** le mien, inséparables par
  sélection de hunk.
* `infra/selftest/README.md` : **3 hunks** (`@@ -19 +19 @@`, `@@ -21,0 +22,5 @@`,
  `@@ -32,2 +37,160 @@`), `+166/−3`, sur un fichier qui ne fait que **33 lignes**
  dans `HEAD` : la quasi-totalité du fichier est non commitée. Mon paragraphe
  `check-tunnel-scope.sh (2026-10-06)` est à la **ligne 56**, donc *à
  l'intérieur* du troisième hunk, dont le reste décrit huit contrôles plus anciens
  (`check-queue-shape.sh`, 2026-09-28…) — c'est-à-dire du travail en attente.
  Les hunks `@@ -19`/`@@ -21` (exemple `--images` → `assets/test-images` et sa
  justification) ne sont **pas** de moi. Voir **D2**.
* Le troisième hunk **reworde** aussi l'avertissement
  « Never use **this** against real infrastructure » en « Never use **the stub
  harness** against… » (le paragraphe survit à la ligne 195). Une extraction
  brutale du hunk le supprimerait ; il ne doit pas disparaître.
* `corpus/m4_bench_v2.py` : **4 hunks** (`@@ -46`, `@@ -70`, `@@ -241`, `@@ -262`).
  Les deux premiers sont miens (paragraphe de mesure + `j` en `def`), les deux
  derniers sont du travail antérieur. **Séparables par hunk.**

### Cause racine

J'ai ajouté des sections à des fichiers qui portaient déjà du travail non
commité, au lieu de créer un artefact à moi. Ce n'est pas un problème d'outil,
c'est une erreur de rangement : le contenu neuf n'a aucune raison de vivre dans
le fichier de quelqu'un d'autre.

### Option retenue

**Découpler plutôt que découper** pour les deux README, et **découper** pour le
script corpus.

1. Les deux blocs du 2026-10-06 partent dans un fichier neuf
   (`infra/MAINTENANCE-2026-10-06-tunnel.md`), qui est donc committable seul.
2. `infra/README.md` et `infra/selftest/README.md` retrouvent l'état où mon
   passage ne les a pas touchés. **Procédure** : sauvegarde préalable des deux
   fichiers dans `/tmp`, **retrait ligne à ligne de mes seuls blocs**, puis
   vérification que le diff restant ne contient plus une seule de mes phrases et
   que la perte d'octets est exactement celle de mes blocs.
   * Ce qui rend le retrait possible *malgré* un hunk de 1552 lignes : mon bloc
     d'`infra/README.md` est **délimité** par son titre
     (`### Maintenance actions, 2026-10-06 …`, ligne 2096), donc repérable ligne à
     ligne. La sélection de hunk n'est pas nécessaire — et c'est heureux, parce
     qu'elle ne saurait pas le faire.
   * En revanche, dans `infra/selftest/README.md` mon paragraphe voisine du texte
     en attente **dans le même hunk** : le découpage n'est pas mécanique.
3. `corpus/m4_bench_v2.py` : `git diff --unified=0` → ne garder que les hunks
   `@@ -46` et `@@ -70`, `git apply --cached --recount`, commit. Le fichier sur
   disque n'est pas touché et les hunks de l'utilisateur restent en attente.

### Décision à prendre — **D2**

Avant de toucher `infra/selftest/README.md`, il faut savoir lesquelles de ses
**166 lignes ajoutées** sont à moi. La règle que je propose, vérifiable et non
arbitraire : *est à moi ce qui décrit un artefact né le 2026-10-06*
(`check-tunnel-scope.sh`, l'unité systemd du tunnel, le script d'installation),
*le reste est en attente*. Application : je retire mon paragraphe (≈ 12 lignes
à partir de la 56) et **rien d'autre** ; les huit autres contrôles et leur prose
restent. Si le poste dit que la section entière « Checks that are not about the
stubs » est de moi, l'extraction emporte les 160 lignes ; si elle est partagée,
on s'en tient au paragraphe. **Je ne tranche pas seul : écrire dans un fichier
non commité est irréversible.** Le même doute ne se pose pas dans
`infra/README.md` : la marque `2026-10-06` y est unique et délimite le bloc.

**Pourquoi pas `git add -p` :** interactif, donc non reproductible ni
vérifiable ; et il ne sait pas séparer deux contenus dans un même hunk de 1552
lignes, ce qui est précisément le cas ici.

**Pourquoi pas committer le fichier entier :** la politique du poste est
« commit only what I verified ». Committer 1552 lignes non relues est exactement
ce qu'elle interdit.

### Vérification (critère d'acceptation)

* `git diff infra/README.md | grep -c "2026-10-06"` → **0**, idem sur
  `infra/selftest/README.md` : plus une seule de mes marques dans le diff.
* `git diff infra/README.md | grep -cE "^-"` → **0** et
  `git diff infra/selftest/README.md | grep -cE "^-"` → **0** : aucune ligne du
  travail en attente n'a été supprimée (je n'ai fait qu'enlever mes propres
  ajouts).
* **Comptage avant/après, seul critère non ambigu** : `git diff --numstat`. Avant
  retrait : `infra/README.md 1559/2`, `infra/selftest/README.md 166/3`. Après
  retrait, les **suppressions sont inchangées** et les ajouts diminuent
  *exactement* du nombre de lignes que j'ai relues et retirées (compté à la main,
  pas deviné). C'est la seule formulation qui vaut : affirmer « le diff restant
  sera le hunk `@@ -219,2 +219,7 @@` » serait faux, puisque les 1552 lignes du
  hunk géant ne sont pas toutes à moi.
* `grep -c "Never use the stub harness" infra/selftest/README.md` → **1** : le
  paragraphe d'avertissement survit, exactement une fois.
* `git diff corpus/m4_bench_v2.py` (non indexé) contient encore `@@ -241` et
  `@@ -262` ; `git diff --cached` ne contient que mes deux hunks.

### Risque

Faible mais non nul : écrire dans un fichier non commité est irréversible si je
me trompe. Mitigation : sauvegarde `/tmp` des octets avant, vérification d'octets
après, et **D2 tranchée avant de toucher `infra/selftest/README.md`**. Si une
seule vérification échoue, restauration depuis `/tmp`.

Second risque, celui qui a failli passer : le hunk contient un **reword**
(l'avertissement « Never use this… » réécrit). Un « nettoyage par hunk »
l'effacerait sans le vouloir — la vérification `grep -c … → 1` ci-dessus existe
précisément pour l'attraper.

---

## 2. Limite 2a — un champ non demandé vaut « 1 », donc « vérifié, un seul objet »

### Ce qui est vrai

`iot_audit/contracts.py` : `n_salient_objects: int = 1`. Le manifeste v6
(`corpus/runner6-v6-triage.py`) ne contient que `{view, category, iot}` — le
champ n'est **jamais** renseigné par le producteur réel. Conséquence mesurée
aujourd'hui : l'UI affiche pour chaque objet un cadrage conforme, alors que
**rien n'a été vérifié**, et `screen_frame` rend `None` (feu vert) dans ce cas.

C'est la même classe de défaut que `E_CLOCK_SKEW` invisible ou qu'une chaîne HMAC
non vérifiée : une absence rendue comme une conformité.

### Cause racine

J'ai choisi `1` pour rendre l'ajout non destructif envers les mesures v6 déjà
publiées. Le raisonnement était bon pour la compatibilité et **faux pour la
sincérité** : les deux propriétés sont distinctes et un défaut ne peut pas porter
les deux sens.

### Option retenue

`n_salient_objects: int | None = None`, avec trois états distincts :

| valeur | sens | `screen_frame` | affichage |
|---|---|---|---|
| `None` | non demandé au modèle | pas de verdict (pas un feu vert) | « cadrage non vérifié » |
| `0` ou `≥ 2` | cadrage inexploitable | `E_MULTI_OBJECT_OR_UNCLEAR` | rejet |
| `1` | un objet, vérifié | `None` | conforme |

Le journal gagne `framing: "unverified" | "rejected" | "ok"` dans l'événement de
triage, et l'UI affiche l'état réel. Les mesures v6 restent valides sans
ambiguïté : `None` dit explicitement « le prompt v6 ne posait pas la question ».

Il faut aussi **changer le test** qui pin le défaut à 1
(`tests/test_triage.py::test_n_salient_objects_defaults_to_one`) : il verrouillait
la mauvaise propriété (compatibilité) au lieu de la bonne (sincérité). Le test
devient « défaut non vérifié » + un test de compatibilité qui passe explicitement
`n_salient_objects=1`.

### Vérification

* `screen_frame` sur un objet sans champ → `None` **et** l'orchestrateur journalise
  `framing="unverified"`.
* Un run UI réel affiche « cadrage non vérifié » sur les 144 photos v6 actuelles.
* Les 344 tests passent, avec les deux tests ci-dessus renommés et leurs
  assertions inversées (aucune assertion supprimée : réécrites pour porter la
  nouvelle propriété).

### Risque

Aucun sur les mesures : `None` n'est pas `0`, et aucun `screen_frame` ne rejette
jamais sur `None`.

---

## 3. Limite 1 — le prompt v6 ne demande pas le nombre d'objets

### Ce qui est vrai

* `corpus/make_runner_v6.py` impose par `assert` que le schéma v6 soit exactement
  `{view, category, iot}` (`required == ["view","category","iot"]`), que les 144
  items soient **identiques à l'octet** à ceux de v4, et que la différence entre
  v4 et v6 soit exactement `{prompt, prompt_version, schema}`. C'est la discipline
  à suivre, pas à contourner.
* Le run v6 existe et est **local** :
  `evidence/2026-10-06/v6-triage-live/predictions-v6.json` — 144 enregistrements
  avec `pred`, `truth_*`, `stratum`, `sha256_ok`, `latency_s`, `finish_reason`.
  La comparaison avant/après est donc possible sans re-télécharger les images.
* Les images sont en cache sur la station (`~/iot-corpus-measure/images`, 144/144).
* Le coût d'une passe : latence v6 mesurée entre ~0,4 s et ~3 s par image, soit
  **2 à 7 minutes** sur un nœud pour les 144. Ce n'est pas un budget, c'est une
  pause.

### Cause racine

Le prompt v6 a été figé pour que la comparaison v4/v6 tienne à l'octet près.
Ajouter une question au schéma *est* un changement du schéma : la discipline
`make_runner_vN.py` dit qu'on en fait une version **v7**, on ne modifie pas v6.

### Options

| Option | Coût | Risque | Verdict |
|---|---|---|---|
| **(a) Sonde séparée** `salience-v1` : un prompt, une question, schéma `{n_objects}` | 144 appels en plus (~5 min) | nul pour v6 | **retenu en premier** |
| (b) v7 = v6 + 1 champ | 144 appels, remplace v6 | ajouter une question **peut changer les réponses** existantes ; il faut le *mesurer* | retenu ensuite, si (a) prouve l'utilité |
| (c) Détecteur d'objets (YOLO/…) | nouvelle dépendance, nouveau modèle | hors du cadre « un seul instrument » du projet | rejeté |

**Pourquoi (a) avant (b) :** la sonde ne peut pas dégrader un chiffre publié et
elle répond à la seule question qui compte d'abord — *le détecteur sert-il à
quelque chose sur ce corpus ?* Si la sonde ne trouve rien à signaler sur 144
photos, alors v7 n'a pas à être écrit. C'est l'ordre « mesurer, puis décider »
que le dépôt applique déjà.

### Découpage de (a)

1. `corpus/make_runner_v7_salience.py` : génère un runner à partir du **même**
   manifeste v6, avec un schéma `{"n_objects": {"type":"integer","minimum":0}}`,
   `required = ["n_objects"]`, `prompt_version = "salience-v1"`, et les mêmes
   `assert` de non-régression (items identiques à l'octet, `temperature/seed/
   max_tokens` inchangés, un seul jeu de clés modifié).
2. Exécution sur les 144 images déjà en cache, sur un nœud.
3. `evidence/2026-10-06/salience-probe/` : prédictions gelées + `analyse.py` +
   `LIRE-MOI.md`, comme `evidence/2026-10-06/v6-triage-live/`.
4. Un banc qui rend la sonde **falsifiable** : deux photos du corpus contiennent
   **plusieurs** objets (le même objet y est photographié avec d'autres) et sont
   nommées, donc vérifiables : `wemo__smart_plug`
   (« Wemo smart plugs and switches.jpg ») et `amazon__echo_dot`
   (« … with normal coffee mug as size comparison.jpg »). Critère : la sonde doit
   signaler ≥ 2 objets sur ces deux-là et rester à 1 sur les photos d'objet seul.

### Critère d'acceptation de la phase (a) — **exécutée le 2026-10-06**

* Sur les 144 : taux de `n_objects >= 2` **publié**, et les deux positifs connus
  ci-dessus détectés. → **satisfait** : 68/144 = 47,2 %, Wemo = 13, Echo Dot + tasse = 2.
* **Zéro** modification de `evidence/2026-10-06/v6-triage-live/predictions-v6.json`
  (vérifié par sha256 avant/après). → `sha256 9c8ef8cc…` avant et après.
* Coût GPU relevé dans le `LIRE-MOI.md`. → 144/144 en ~5 min via le tunnel, 0 échec,
  0 image non conforme, aucun téléchargement (cache local).

**Mais le critère « (a) détecte quelque chose » n'était pas le bon critère.** Le
taux ne dépend pas de la vue (vue d'ensemble 42,1 %, détail 49,1 %) : le modèle
compte des objets *quelconques* — composants de carte mère compris — et non des
appareils concurrents. Une porte qui rejette 47 % du corpus détruirait des mesures
valides. **Conclusion de la phase (a) : v7 n'est pas écrit**, le cadrage reste
`unverified`, et la question à poser (« combien *d'appareils de ce type* ») est
écrite mais pas encore formulée. Détail : docs/06 §22.8 (a).

### Puis (b), si et seulement si (a) détecte quelque chose

`make_runner_v7.py` = v6 + `n_objects`, avec un critère d'acceptation
**quantifié** sur la dégradation : catégorie et `iot` doivent rester à l'écart ≤ 2
points des valeurs v6 sur les mêmes 144 photos, et les intervalles de Wilson
doivent se recouvrir. Si v7 dégrade, on garde v6 pour les chiffres publiés et la
sonde séparée pour le cadrage — et on l'écrit.

---

## 4. Limite 3 — étiquette falsifiée : détectable, et mesurable sans GPU

### Ce qui est vrai

La limite déclarée était « demande un lexique de marques curé, sans lequel on
rétrograde des identifications correctes ». Enquête :

* **Le lexique existe déjà** : `corpus/cpe.sqlite` contient **1711 vendeurs
  matériels** distincts (index `ix_cpe_vendor`), dont **1600 jetons utilisables**
  après retrait des mots génériques. Aucune liste à écrire.
* **Les données de mesure existent déjà hors GPU** : **857 sorties réelles** du
  modèle avec `pred.visible_text`, `pred.brand`, `pred.identification_basis`,
  `truth_brand/truth_model`, `text_visible` et `stratum`, réparties sur **13
  fichiers** dans `evidence/*/.../predictions-v*.json`.
* Le projet a déjà mesuré la *marque annoncée présente dans le texte* (test
  `containment`, `corpus/calibrate_status.py` §114 ; docs/06 §1544 :
  « `visible_text` vide sous `label` : 0/78 → 0/80 »). La direction inverse —
  *le texte nomme une AUTRE marque* — n'est pas instrumentée.

### Étape 0 — geler la mesure avant de s'en servir

Le chiffre ci-dessous a été obtenu **ad hoc**, et aucun script du dépôt ne le
reproduit (`corpus/probe-divergence.py` est une autre sonde : équivalence
inter-nœuds). Un résultat qui fonde un détecteur doit être re-dérivable :
`corpus/probe-label-divergence.py` est écrit et committé **avant**
`label_divergence`, relit les 13 fichiers de `evidence/*/.../predictions-v*.json`
et réimprime les trois lignes du tableau. Si le script ne redonne pas 72/72/6, le
chiffre est faux et c'est le script qui a raison.

### Mesure faite pour trancher — **corrigée le 2026-10-06**

Fait d'abord ad hoc, puis re-dérivé par `corpus/probe-label-divergence.py` (sortie
gelée : `evidence/2026-10-06/label-divergence/probe-output.txt`). **L'unité de
mesure était fausse** : 1008 enregistrements = **144 photos mesurées 7 fois**. Un
taux compté sur les enregistrements compte la même photo jusqu'à six fois.

| Règle | Enregistrements (n=556) | Photos distinctes (n=94) |
|---|---|---|
| A. marque annoncée absente du texte imprimé | 88 (15,8 %) | 15 (**16,0 %**) |
| B. A + `identification_basis == "label"` | 88 | 15 |
| C. B + un **autre vendeur connu** dans le texte (lexique cru) | 6 | **1** |
| C′. idem, lexique livré (mots ordinaires refusés) | **0** | **0** |

**Trois enseignements, dont deux désagréables :**

1. La règle A est inutilisable (16 % de rétrogradations).
2. **`identification_basis` ne discrimine rien ici** : dès que le modèle nomme une
   marque sur ce corpus, il écrit `label` — y compris dans les 88 cas où le texte
   ne contient pas la marque. Le champ présenté comme *vérifiable* ne se vérifie
   pas par simple containment. **Documenté comme limite** dans docs/06 §22.8 (c).
3. **La règle C ne tenait pas.** Ses « 6 déclenchements » sont **une seule photo**
   (`zyxel__p_870ha_vtu_r_2`) vue 6 fois, et la correspondance est le mot anglais
   « **ALARM** » imprimé sur une façade de modem, rapproché du vendeur CPE `alarm`
   (Alarm.com). Ce n'était pas une divergence : c'était un faux positif fabriqué
   par le lexique. Avec `alarm` et `free` refusés, la règle C tombe à zéro — et
   c'est ce que le détecteur livré fait.

### Option retenue

Détecteur **étroit**, dans `iot_audit/modules/adversarial.py` (même module : c'est
la même question, « le texte contredit-il l'objet ? ») :

```
def label_divergence(claimed_brand: str, visible_text: str) -> str | None:
    """Renvoie le vendeur CONNU nommé par le texte et différent de la marque
    annoncée, ou None. Lexique = dictionnaire CPE local, jamais une liste écrite
    à la main ; exigence : au moins 4 caractères, mot entier, non générique."""
```

Câblage, dans l'orchestrateur : divergence → `identified_with_reserve` (jamais
« identifié »), motif et texte dans le journal, **aucune correction silencieuse**
(le texte n'est pas une instruction : on rapporte, on ne répare pas). Pas de
nouveau code d'erreur : la taxonomie est figée à 20 par AC12, et docs/07 §5
attend pour ce cas « divergence remontée ; R chute, statut avec réserve ».

Extension : le lexique est chargé une fois depuis `corpus/cpe.sqlite` s'il est
présent ; en son absence, le détecteur rend `None` (pas de détection, pas de
faux positif) et le journal le dit.

### Vérification

* **Bruit** : la règle C déclenche sur **≤ 6/556 (1,08 %)** des sorties réelles,
  et **chacun des cas est lu et jugé à la main** dans le `LIRE-MOI.md` de la
  campagne — un budget de faux positifs se décide, il ne s'espère pas.
* **Détection** : une paire injectée (objet annoncé « D-Link », texte imprimé
  « TP-Link ») déclenche ; un test unitaire avec les deux libellés exacts de
  docs/07 §5.
* **Non-nuisance** : sur un corpus d'étiquettes réelles (`tests/test_adversarial.py`,
  déjà en place) le détecteur ne déclenche pas.
* Le statut mesuré des runs live ne se dégrade pas : la spécificité reste à
  30/30 sur le banc non-IoT (`evidence/2026-10-06/specificity-protocol/`).

---

## 5. Limite 2b — aucun producteur de `Provenance`

### Ce qui est vrai

* `Provenance` est déclaré (`iot_audit/contracts.py` §436) et **jamais construit**
  dans le dépôt. La vérification et le refus existent (`preflight`, `seal`), le
  producteur non.
* Côté nœud, la provenance **est** mesurée : `infra/scripts/node_write_provenance.sh`
  écrit `~/vllm-env/ENV_STATUS.md` (§8.3) et sa philosophie est déjà la bonne :
  « Every number here is either measured in this run or read from a named log.
  Nothing is copied from an older report. Fields that are genuinely open are
  written as "NON FAIT" with the reason ». Mais c'est du **markdown**, donc pas
  lisible par une machine.
* Côté station, deux des trois empreintes sont **déjà dans les bases** :
  `corpus/nvd.sqlite` a une table `feed_versions (feed_name, sha256, ingested_at)`
  (les flux 2021…2026, ingérés le 2026-09-24), et `corpus/cpe.sqlite` a une table
  `dictionary_versions`.
* `docs/02-decisions.md` §154 : « une contrainte SQL empêche un run sans
  provenance », et §269 nomme la table `analysis_runs`. **Cette table n'existe
  dans aucun schéma du dépôt** (`iot_audit/vuln/schema.sql` : 4 tables, toutes
  côté CVE ; `iot_audit/corpus/schema.sql` : 7 tables de mesure). Le document
  promet une garantie qu'aucun code ne tient.
* `ETAT-DES-LIEUX-2026-09-15.md` §10.1 : `weights_sha256` ✅ mais **révision
  HuggingFace non épinglée** — `revision=` n'est pas passé au chargeur.

### Précédent à réutiliser, pas à copier

`evidence/2026-09-14/corpus/provenance.json` existe déjà : spécimen **écrit à la
main**, hors du contrat, mais il porte `prompt_sha256`, `schema_sha256`,
`sampling` (temperature/seed/max_tokens) et `model` — exactement ce que
`build_provenance` doit produire. Deux réserves : il n'a **pas** la forme du
contrat (`nodes_used`, `model_revision`, `weights_sha256`, empreintes des bases
manquent) et son champ `git_equivalent` affirme « arborescence non versionnée »,
ce qui est **faux depuis** (dépôt git initialisé) — il ne doit pas être recopié.
C'est néanmoins la preuve que la donnée est mesurable ; le travail est de la
normaliser, pas de l'inventer.

### Cause racine

La provenance est traitée comme un champ de contrat alors que c'est un
**artefact de mesure distribué** : il naît sur le nœud (version vLLM, torch,
poids), se complète sur la station (empreintes des bases, SHA du prompt) et n'est
assemblé qu'au scellement. Personne n'avait la charge de l'assembler.

### Décision à prendre — **D1**

Le point §10.1 n'est pas un détail : si `model_revision` ne peut pas être établie,
alors **le refus `E_PROVENANCE_INCOMPLETE` est correct** et il bloquera tout
scellement de run réel. Deux issues, et c'est un arbitrage qui appartient au
poste (et probablement au tuteur, car il touche §10.1 de l'état des lieux) :

* **D1-a — épingler la révision.** Passer `revision=<sha>` au chargeur vLLM
  (une ligne dans le service de nœud, + redémarrage du service, + ré-ingestion de
  `weights_sha256`). Coût : ~30 min et un redémarrage. État final : tous les
  champs observables, le scellement passe.
* **D1-b — déclarer la révision comme non établie et la laisser manquante.**
  Le scellement de production refuse, et **c'est le résultat honnête** : on
  publie un run non scellé + le motif, et la liste des champs ouverts devient un
  livrable (déjà amorcée : §10.1). Coût : 0. Conséquence : aucun run réel n'est
  scellé tant que D1-a n'est pas fait.

Recommandation : **D1-a**, parce qu'épingler une révision est un travail de
reproductibilité à faire de toute façon (ENF5), et que le refus a précisément
servi à rendre ce trou visible.

### Plan d'implémentation (identique dans les deux branches)

1. **Nœud → JSON.** `infra/scripts/node_write_provenance.sh` écrit en plus
   `~/vllm-env/provenance.json` (mêmes valeurs que `ENV_STATUS.md`, mêmes
   « NON FAIT » explicites). Rien d'inventé : le script mesure déjà tout.
2. **Récupération.** `infra/lib/lib_cluster.sh` a déjà `ssh_out` ; ajouter
   `node_provenance_json()` (lecture seule, un `cat`).
3. **Assemblage.** `iot_audit/pipeline/provenance.py` :
   `build_provenance(node_json, *, prompt_text, nvd_path, cpe_path,
   sampling_params, nodes_used, started_at, finished_at) -> Provenance`.
   * `nvd_snapshot_sha256` = sha256 de la liste triée `(feed_name, sha256)` de
     `feed_versions` — **définition écrite dans la docstring**, parce qu'un
     « sha256 du snapshot » sans définition n'est pas vérifiable.
   * `cpe_dict_version_id` = `dictionary_versions` de `cpe.sqlite`.
   * `prompt_sha256` = sha256 du texte de prompt réellement envoyé.
   * Chaque champ non observable reste **absent** : la fonction ne devine pas.
4. **Câblage.** `benchmarks/e2e_live_run.py`, le job de run de l'UI, et
   `sign_report(..., provenance=...)`.
5. **Contrainte SQL (docs/02 §154).** Créer `analysis_runs` dans un schéma de
   suivi (probablement `iot_audit/storage/schema.sql`) avec les colonnes de §269
   en `NOT NULL` et une clé étrangère vers la chaîne HMAC — ou **amender
   docs/02** et écrire que le refus est au scellement, pas en SQL. Les deux sont
   défendables ; laisser le document promettre une garantie absente ne l'est pas.

### Vérification

* `build_provenance` sur l'artefact réel d'un nœud → `missing_provenance_fields`
  rend `()` (D1-a) ou exactement `("model_revision",)` (D1-b) — **le résultat est
  le livrable**.
* Un rapport scellé contient le bloc provenance **sous** la signature, et le
  modifier invalide la vérification (test déjà écrit).
* Un run avec provenance incomplète est **refusé**, pas scellé avec des blancs
  (test déjà écrit).

---

## 6. Limite 5 — le cahier d'avancement gelé

Pas une limite à corriger : c'est une contrainte posée par le poste
(`cahiers/ETAT-AVANCEMENT-2026-10-02.*` ne doit plus être modifié). Rien à faire.
Ce qui est dû en revanche, c'est de ne pas y écrire en douce : tout ce plan vit
dans un fichier neuf, et les constats nouveaux vont dans des artefacts neufs
(`evidence/2026-10-06/…`), jamais dans le gelé. Vérification : mtime inchangé
(`2026-10-05 19:36`).

---

## 7. Ce que ce plan refuse de faire, et pourquoi

* **Inventer une révision de modèle** pour satisfaire `E_PROVENANCE_INCOMPLETE` :
  ce serait transformer une garantie de reproductibilité en décoration.
* **Modifier v6** pour y glisser la question du cadrage : casserait la
  comparaison v4/v6 à l'octet près qui fonde les chiffres publiés.
* **Amender le cahier gelé** pour y inscrire les nouvelles mesures.
* **Activer la règle A** du détecteur de divergence (16 % de bruit) sous prétexte
  qu'elle est plus sensible : rétrograder 88 sorties réelles (15 photos) pour
  attraper un cas fabriqué serait une régression déguisée en sévérité.
* **Publier « règle C : 6 détections, 1,08 % »** après avoir constaté que c'est une
  photo comptée six fois et un mot anglais : un chiffre qui décrit une intention
  plutôt qu'un résultat est plus coûteux qu'une absence de chiffre.
* **Déployer la porte de cadrage** alors qu'elle rejette 47 % du corpus : la
  mesurer a précisément servi à s'en abstenir.
* **Décider D1 à la place du poste** : épingler une révision touche l'infra des
  nœuds et §10.1 de l'état des lieux.
* **Décider D2 seule** : effacer 166 lignes non commitées d'un autre sur la foi
  de ma mémoire de qui a écrit quoi. La règle « est à moi ce qui décrit un
  artefact du 2026-10-06 » est proposée, pas imposée.
* **Faire reposer `label_divergence` sur un chiffre non re-dérivable** : les 6
  déclenchements sont un budget de faux positifs, et un budget non rejouable ne
  se vérifie pas (étape 0 de la limite 3).

## 8. Ordre, et ce qui peut l'invalider

| Phase | Contenu | Critère de sortie | Ce qui l'invaliderait |
|---|---|---|---|
| P0 | Limite 4 (hygiène) | `numstat` avant/après, `grep` de mes marques → 0, avertissement présent ×1 | **D2** non tranchée, ou une vérification qui échoue → restauration `/tmp` |
| P0 | Limite 2a (sincérité du cadrage) | UI affiche « non vérifié » ; 344 tests verts | un `screen_frame` qui rejette sur `None` |
| P1 | Limite 1 (a) sonde de cadrage | ≥ 2 détectés sur les 2 positifs nommés, 0 sur les objets seuls | la sonde ne détecte rien → **on s'arrête là et on l'écrit** |
| P1 | Limite 3 (divergence) | ≤ 6/556 déclenchements, les 6 jugés à la main | bruit > 2 % → règle retirée, limite maintenue |
| P2 | Limite 2b (provenance) | `missing_provenance_fields` vide (D1-a) ou `("model_revision",)` (D1-b) | D1 non tranchée par le poste |
| P2 | Limite 1 (b) v7 | écart ≤ 2 pts vs v6 sur les 144 | **a rendu un verdict négatif : v7 non écrit (2026-10-06)** |

---

## 9. Journal d'exécution (2026-10-06 → 2026-10-06)

| # | Ce qui a été fait | Sortie |
|---|---|---|
| 4 | Mes deux blocs README déplacés verbatim dans `infra/MAINTENANCE-2026-10-06-tunnel.md` ; les deux README rendus à leur état antérieur (`numstat` 1499/2 et 151/3, suppressions inchangées) ; mes seuls hunks des deux scripts corpus indexés par `git apply --cached` | commit `b15a175` |
| 2a | `n_salient_objects: int \| None = None`, `framing_state` (`unverified`/`ok`/`rejected`), journal `framing` + compteurs, `ObjectTriage.framing`, badge UI, docs/07 §5.1 | commit `0b6c3de` |
| 1 | Sonde `salience-v1` (144/144, v6 intact), analyse + `LIRE-MOI.md` | `evidence/2026-10-06/salience-probe/` — critère satisfait, **déploiement refusé par la mesure** |
| 3 | Sonde `probe-label-divergence.py` **avant** le détecteur, puis `label_divergence` + câblage + limite docs/06 §22.8 | `evidence/2026-10-06/label-divergence/` — **0 détection sur le corpus**, 1 collision expliquée |
| 2b | `provenance.json` côté nœud, `build_provenance` côté station, câblage banc + interface + scellement, `analysis_runs` (docs/02 §154), révision épinglée et vérifiée au démarrage du service | commit `591bd9b` |
| 2b | Moitié **nœud** : `node_write_provenance.sh` écrit `provenance.json`, `lib_cluster.sh` le lit (`node_provenance_json`) — seulement ma moitié : le travail en attente de ces deux fichiers est laissé non indexé, hunk par hunk, avec contrôle que ses lignes n'entrent pas | commit `c079209` |
| D1-a | Déploiement sur zabeth21 : `~/vllm-service.sh` remplacé (sauvegarde `.bak-20261006-avant-epingle`), `QWEN_MODEL_REVISION` ajouté au `cluster.env` du nœud ; vérifié **sur le nœud** : épingle lue == révision du disque (`85acc985…`), au moyen de la fonction extraite du script déployé | zabeth21 seulement, **aucun redémarrage** : le contrôle s'appliquera au prochain démarrage |

**Deux erreurs à moi, trouvées en vérifiant ce plan plutôt qu'en le relisant :**

* **Une chirurgie par hunks a produit un fichier incohérent.** `git apply --cached
  --unidiff-zero` ancre chaque insertion aux numéros de ligne de `HEAD` : quand les hunks
  voisins du poste *déplacent* du code, `WLIST=` s'est retrouvé **après** sa première
  utilisation, `rm -f "$WLIST"` a disparu, et la fonction `node_provenance_json` s'est
  retrouvée **en double**. `bash -n` ne voit rien de tout ça — il ne lit pas l'ordre des
  affectations. Méthode corrigée, et utilisée pour les deux fichiers : partir de l'arbre
  de travail (l'état cohérent) et **retirer** les hunks d'autrui, puis vérifier que le
  résultat est identique au fichier obtenu, occurrence par occurrence. Les commits fautifs
  ont été amendés : ils ne sont pas dans l'histoire (ils restent des objets non
  référencés jusqu'au prochain `gc`).
* **J'ai annoncé une estimation fausse au poste** (« une cinquantaine de fichiers portent
  des corrections de date non commitées »). Mesure : **zéro** ligne `2026-10-07` subsiste
  dans le diff — ces corrections étaient déjà commitées. Le vrai résidu est ailleurs et
  plus petit (dix fichiers de réordonnancement d'imports, plus le travail en attente).
  L'annexe porte la correction, écrite comme telle.

**Un chiffre de D1-a s'est révélé faux à l'exécution.** Le plan écrivait
« épingler la révision = passer `revision=<sha>` au chargeur vLLM ». Mesure du
2026-10-06, sur le modèle tel qu'il est servi : `QWEN_MODEL_DIR` est un **chemin
local**, et sur un chemin local `revision=` est **ignoré en silence**
(`AutoConfig.from_pretrained(<chemin>, revision="bogus-revision-0000")` répond OK).
Passer le drapeau aurait donc publié une épingle que rien n'applique — pire qu'une
absence d'épingle, puisqu'elle aurait aussi fait taire le doute. L'épingle est
devenue une **égalité vérifiée au démarrage** (`model_disk_revision` contre
`QWEN_MODEL_REVISION`, refus en code retour 6) : la même mesure que celle qui part
dans `provenance.json`, donc une épingle qui porte sur ce que le rapport publie.

**Trois chiffres de ce plan se sont révélés faux à l'exécution**, et le plan est
corrigé sur place plutôt que réécrit : les 72/72/6 de la limite 3 (→ 88/88/1 photo
par collision, 0 avec le lexique livré) ; le critère « (a) détecte quelque chose »
de la limite 1 (→ détecte 47 %, donc refuse la suite) ; et le critère
« le diff restant sera le hunk utilisateur » de la limite 4 (→ `numstat` avant/après,
seule formulation atteignable). La règle appliquée est celle du dépôt : **le chiffre
gelé n'a pas d'autorité sur la mesure rejouée**.
