# Interface locale (navigateur)

Remplacer les commandes par des clics, sans ajouter de dépendance : trois
fichiers servis par la bibliothèque standard, aucune bibliothèque de présentation.

## Lancer

```bash
./.venv-core/bin/python -m iot_audit.ui.server --port 8788 --open
```

Le port 8765 est déjà pris sur le poste de travail de référence — le serveur le
dit en une phrase et propose le port suivant plutôt que de laisser remonter une
trace de `socketserver`. Si le port est occupé par une autre instance, `--port`
en change.

## Ce que l'interface fait

| Onglet | Remplace |
|---|---|
| **Infra** | `infra/scripts/tunnel_vllm.sh status\|start\|stop\|restart` |
| **Corpus** | lecture du manifeste v6 et des photos réellement en cache local |
| **Run live** | `benchmarks/live_vlm_orchestrator.py`, sur les objets choisis |
| **Résultats** | le tableau texte d'un run : A, R, distribution, quadrant, CPE, CVE |
| **Journal** | `SELECT * FROM hmac_chain` + l'état de la chaîne |
| **Contrôles** | `pytest`, `ruff`, `mypy`, `selftest/check-tunnel-scope.sh`, banc live |

Rien n'est recalculé dans l'interface : `agreement`, `resolvability`,
`per_field_agreement` et `distribution` sont ceux que l'orchestrateur a produits.
Une seconde formule de confiance dans la couche d'affichage serait le défaut que
la contrainte C2 interdit (`docs/03-architecture.md` §3).

## Deux règles de conception tenues par la page

1. `docs/05-matching-and-confidence.md` §4 : « l'UI affiche (A, R) **et** la
   distribution. Le score unique n'existe que pour trier une liste. » Aucun objet
   n'est résumé par un pourcentage unique, et le score `confidence_self` du modèle
   n'apparaît nulle part (il est conservé pour analyse, jamais affiché).
2. `docs/02-decisions.md` : « L'UI affiche le quadrant, pas un pourcentage
   unique. » Les seuils du quadrant sont ceux de la matrice de décision
   (`A ≥ 0,70` / `0,40 ≤ A < 0,70` / `A < 0,40`, `R ≥ 0,90` / `0,60 ≤ R < 0,90` /
   `R < 0,60`) — recopiés, pas réinventés. La cellule « A élevé / R faible » est
   mise en évidence : c'est la signature d'un consensus halluciné.

Un objet **sans** identification n'est pas placé dans le quadrant : une absence
de coordonnée n'est pas la coordonnée (0, 0), et l'y mettre inventerait une
mesure.

## Provenance d'un run (docs/02 §154)

Un run de l'onglet **Run live** assemble sa provenance avant de sceller son
rapport : quatre champs viennent du nœud (`model_revision`, `weights_sha256`,
`vllm_version`, `torch_version`, lus dans `~/vllm-env/provenance.json` par
`iot_audit/pipeline/provenance.py`), les autres sont mesurés ici (empreinte du
snapshot NVD, version du dictionnaire CPE, empreinte du prompt réellement envoyé,
paramètres d'échantillonnage, nœud).

```
IOT_AUDIT_NODE_PROVENANCE   # « ssh:<hôte> » (défaut : ssh:zabeth21) ou un chemin local
```

Si la provenance n'est pas complète — nœud injoignable, base absente — le run
n'est **pas** présenté comme reproductible : le journal du job nomme chaque champ
manquant, et le payload **signé** du rapport porte
`provenance_status: "incomplete"` avec la liste des manquants. Un rapport scellé
« sans provenance » le dit donc lui-même, en clair, et cette mention ne peut plus
être retirée sans invalider la signature.

## Portée et sécurité

* Écoute sur `127.0.0.1` uniquement, sans authentification : c'est un outil de
  poste, pas un service.
* Les commandes lançables sont une **liste fixe** écrite dans `server.py`. Aucun
  identifiant de commande ne vient de la requête HTTP, et il n'y a aucun shell.
* Les identifiants d'objets reçus sont validés contre le manifeste avant usage.
* Un en-tête `Host` non local est refusé (défense contre le rebinding DNS, qui
  rendrait `127.0.0.1` joignable depuis une page hostile du même navigateur).
* Les artefacts de run vont dans `logs/ui-runs/<run_id>/` : `logs/` est déjà
  ignoré par git, et le résultat du dernier run y est conservé pour survivre à un
  rechargement de page.
