# Banc CVE — preuve de la porte G1

> Genere par `benchmarks/run_cve.py` le 2026-10-06T00:38:42+0200. Aucun chiffre saisi a la main.
> Base : `corpus/nvd.sqlite` (6c28e00f7285…, 161 Mo) · flux bruts : 4 fichiers, sha256 enregistres.

## 1. La source, re-derivee du brut (independamment de la base)

| flux | CVE lues | criteres h produits | attendus en base | `row_count` stocke | ecart | `cve_count` stocke |
|---|---|---|---|---|---|---|
| `nvdcve-2.0-2021.json.gz` | 23470 | 92968 | 90646 | 90646 | OK | 23470 |
| `nvdcve-2.0-2022.json.gz` | 27555 | 86988 | 85474 | 85474 | OK | 27555 |
| `nvdcve-2.0-2023.json.gz` | 31444 | 99578 | 98302 | 98302 | OK | 31444 |
| `nvdcve-2.0-2024.json.gz` | 39250 | 50245 | 50048 | 50048 | OK | 39250 |

Total criteres en base : **324470** · CVE : **121719** · `parts` presents : ['h'].

Sur les criteres `part='h'`, regles de semantique appliquees et comptees :

| regle | occurrences ecartees |
|---|---|
| `negate` (critere qui EXCLUT) | 0 |
| `vulnerable != 1` | 316311 |

## 2. Ce que le filtre `part='h'` laisse de cote

L'ingestion ne garde que les criteres CPE `part='h'` (materiel). Voici, pour **chaque vendeur du corpus du projet**, le nombre de CVE distinctes disponibles par partie dans les flux bruts (`a` = application, `o` = systeme) :

| vendeur (NVD) | `part=h` **gardees** | `part=a` | `part=o` | part conservee |
|---|---|---|---|---|
| `google` | **2** | 1680 | 3881 | 0.0 % |
| `apple` | **2** | 258 | 2058 | 0.1 % |
| `huawei` | **1** | 24 | 1118 | 0.1 % |
| `samsung` | **3** | 388 | 462 | 0.4 % |
| `d-link / dlink` | **0** | 18 | 800 | 0.0 % |
| `netgear` | **2** | 26 | 487 | 0.4 % |
| `tp-link` | **0** | 7 | 225 | 0.0 % |
| `zyxel` | **0** | 2 | 133 | 0.0 % |
| `amazon` | **0** | 59 | 16 | 0.0 % |
| `philips` | **0** | 16 | 7 | 0.0 % |
| `hikvision` | **0** | 7 | 12 | 0.0 % |
| `mikrotik` | **0** | 0 | 16 | 0.0 % |
| `belkin` | **0** | 0 | 4 | 0.0 % |

Total, tous vendeurs du corpus confondus : **10 CVE gardees sur 11714** (0.09 %). Autrement dit, le filtre ecarte **99.9 % des CVE** qui concernent les familles d'objets que le projet audite.

> **Ce que cela veut dire, sans detour.** Le banc est vert, et il est vert sur un sous-ensemble qui exclut l'essentiel. Un audit d'un routeur ou d'une camera de ce corpus produirait aujourd'hui une liste de CVE **vide ou quasi vide**, non parce que le produit n'a pas de vulnerabilite connue, mais parce que la decision d'ingestion `part='h'` l'a retiree. Ce n'est pas un bug du moteur (le moteur rend exactement ce que la base contient) : c'est une consequence de perimetre, qui n'etait pas mesuree avant ce banc. La trancher releve du contrat (D12 / §3.4), pas du code.

## 3. Idempotence — la base importee deux fois

Sur une base neuve jetable (20.5 s), trois passes :

| passe | `feed_versions` | `cves` | `cve_cpe_criteria` | doublons | flux sautes |
|---|---|---|---|---|---|
| 1 — flux d'origine | 4 | 121719 | 324470 | {'criteria': 0, 'cves': 0} | 0/4 |
| 2 — memes noms (provenance) | 4 | 121719 | 324470 | {'criteria': 0, 'cves': 0} | 4/4 |
| 3 — copies renommees (ecriture forcee) | 8 | 121719 | 324470 | {'criteria': 0, 'cves': 0} | 0/4 |

- **donnees identiques** sur les trois passes (`cves`, `criteria`) : **oui** ;
- zero doublon sur les trois passes : **oui** ;
- `feed_versions` par passe : [4, 4, 8] — la passe 3 ajoute 4 lignes de provenance : c'est le but (flux rejoues sous un autre nom pour forcer le chemin d'ecriture). Seules les tables de donnees doivent etre invariantes.

> La passe 2 ne prouve que la **provenance** (le sha256 fait sauter le flux : c'est ce que la colonne « flux sautes » montre). Elle ne prouve rien du chemin d'ecriture. C'est la **passe 3** qui le fait : les memes flux rejoues sous un autre nom ne sont plus reconnus, donc `ON CONFLICT` doit absorber chaque ligne. Sans elle, « idempotent » resterait non prouve.

## 4. Les 60 cas

- **faux negatifs : 0** (cible : 0) · faux positifs : 0 (a documenter, pas a corriger) ;
- cas sans aucune divergence : 60/60 ;
- latence sur les 60 requetes distinctes : p50 0.235 ms · **p95 2.176 ms** · max 4.306 ms ;
- latence sur 600 executions (10 par requete) : p50 0.02 ms · **p95 0.429 ms** · p99 1.567 ms · max 4.306 ms ;
- cible contractuelle p95 < 50 ms : **PASS**.

| # | strate | vendor / product | attendus | rendus | FN | FP | premiere requete |
|---|---|---|---|---|---|---|---|
| 1 | `vendeurs_du_corpus` | `samsung/proxpress_sl-m4024_ss385a` | 1 | 1 | 0 | 0 | 1.814 ms |
| 2 | `vendeurs_du_corpus` | `samsung/ml-5012_ss146a` | 1 | 1 | 0 | 0 | 0.425 ms |
| 3 | `vendeurs_du_corpus` | `samsung/proxpress_sl-m4070_ss390c` | 1 | 1 | 0 | 0 | 0.015 ms |
| 4 | `vendeurs_du_corpus` | `samsung/scx-5737_ss183a` | 1 | 1 | 0 | 0 | 0.122 ms |
| 5 | `vendeurs_du_corpus` | `samsung/scx-4521_ss168a` | 1 | 1 | 0 | 0 | 0.174 ms |
| 6 | `vendeurs_du_corpus` | `samsung/proxpress_sl-m3375fd_ss369b` | 1 | 1 | 0 | 0 | 0.102 ms |
| 7 | `vendeurs_du_corpus` | `samsung/xpress_sl-m2620_ss323a` | 1 | 1 | 0 | 0 | 0.216 ms |
| 8 | `vendeurs_du_corpus` | `samsung/scx-5639_st676a` | 1 | 1 | 0 | 0 | 0.014 ms |
| 9 | `vendor_wildcard_owed` | `intel/xeon_gold_6146` | 12 | 12 | 0 | 0 | 2.81 ms |
| 10 | `vendor_wildcard_owed` | `intel/xeon_e3_1125c_v2` | 3 | 3 | 0 | 0 | 0.225 ms |
| 11 | `vendor_wildcard_owed` | `intel/core_i7-6560u` | 13 | 13 | 0 | 0 | 1.565 ms |
| 12 | `vendor_wildcard_owed` | `intel/core_i7-5960x` | 14 | 14 | 0 | 0 | 0.659 ms |
| 13 | `version_bounded` | `ysoft/safeq_server` | 1 | 1 | 0 | 0 | 0.637 ms |
| 14 | `version_bounded` | `siemens/simatic_process_historian` | 1 | 1 | 0 | 0 | 0.32 ms |
| 15 | `version_bounded` | `dell/inspiron_7590` | 1 | 1 | 0 | 0 | 0.423 ms |
| 16 | `version_bounded` | `intel/quickassist_technology_driver` | 2 | 2 | 0 | 0 | 0.635 ms |
| 17 | `version_bounded` | `dell/inspiron_3470` | 1 | 1 | 0 | 0 | 0.107 ms |
| 18 | `version_bounded` | `cisco/ic3000_industrial_compute_gateway` | 1 | 1 | 0 | 0 | 0.525 ms |
| 19 | `version_bounded` | `veritas/netbackup_appliance` | 19 | 19 | 0 | 0 | 3.595 ms |
| 20 | `version_bounded` | `apple/iphone` | 1 | 1 | 0 | 0 | 0.345 ms |
| 21 | `control_zero_cve` | `canon/lbp622cdw` | 0 | 0 | 0 | 0 | 0.015 ms |
| 22 | `control_zero_cve` | `hp/envy_inspire_7900e_242p6b` | 0 | 0 | 0 | 0 | 0.021 ms |
| 23 | `control_zero_cve` | `hp/381v5a` | 0 | 0 | 0 | 0 | 0.01 ms |
| 24 | `single_1_cve` | `lenovo/thinkagile_mx630_v3_firmware` | 1 | 1 | 0 | 0 | 0.532 ms |
| 25 | `single_1_cve` | `hp/laserjet_mfp_m439_7zb22a` | 1 | 1 | 0 | 0 | 0.123 ms |
| 26 | `single_1_cve` | `xiongmaitech/nbd7024h-p` | 1 | 1 | 0 | 0 | 0.505 ms |
| 27 | `single_1_cve` | `ftsafe/k13` | 1 | 1 | 0 | 0 | 0.415 ms |
| 28 | `single_1_cve` | `hp/laserjet_mfp_m438_8af44a` | 1 | 1 | 0 | 0 | 0.014 ms |
| 29 | `single_1_cve` | `canon/mf249dw` | 1 | 1 | 0 | 0 | 0.328 ms |
| 30 | `single_1_cve` | `xiongmaitech/nbd7804r-fw` | 1 | 1 | 0 | 0 | 0.014 ms |
| 31 | `single_1_cve` | `amd/epyc_7413` | 2 | 2 | 0 | 0 | 0.728 ms |
| 32 | `single_1_cve` | `xiongmaitech/nbd8008t-q` | 1 | 1 | 0 | 0 | 0.132 ms |
| 33 | `single_1_cve` | `intel/atom_x5-z8500` | 2 | 2 | 0 | 0 | 0.332 ms |
| 34 | `single_1_cve` | `samsung/xpress_sl-m2675_ss336a` | 1 | 1 | 0 | 0 | 0.017 ms |
| 35 | `single_1_cve` | `samsung/proxpress_sl-m4580_ss401a` | 1 | 1 | 0 | 0 | 0.106 ms |
| 36 | `few_2_5` | `nvidia/nvidia_t4` | 5 | 5 | 0 | 0 | 0.923 ms |
| 37 | `few_2_5` | `intel/core_i5-12600kf` | 3 | 3 | 0 | 0 | 0.233 ms |
| 38 | `few_2_5` | `intel/pentium_gold_4425y` | 3 | 3 | 0 | 0 | 0.22 ms |
| 39 | `few_2_5` | `intel/xeon_gold_6354` | 6 | 6 | 0 | 0 | 0.544 ms |
| 40 | `few_2_5` | `intel/xeon_gold_6338t` | 6 | 6 | 0 | 0 | 0.124 ms |
| 41 | `few_2_5` | `intel/xeon_e5-2418l_v3` | 3 | 3 | 0 | 0 | 0.218 ms |
| 42 | `few_2_5` | `intel/xeon_e3-1225_v5` | 4 | 4 | 0 | 0 | 0.342 ms |
| 43 | `few_2_5` | `intel/xeon_e3_1235l_v5` | 3 | 3 | 0 | 0 | 0.217 ms |
| 44 | `few_2_5` | `intel/core_i5-12500h` | 3 | 3 | 0 | 0 | 0.03 ms |
| 45 | `few_2_5` | `intel/core_i5-12450h` | 3 | 3 | 0 | 0 | 0.021 ms |
| 46 | `few_2_5` | `arm/cortex-a72` | 2 | 2 | 0 | 0 | 0.238 ms |
| 47 | `few_2_5` | `schneider-electric/plc_simulator_for_ecostruxure_process_expert` | 4 | 4 | 0 | 0 | 0.735 ms |
| 48 | `few_2_5` | `schneider-electric/modicon_m580_bmeh582040s` | 4 | 4 | 0 | 0 | 0.21 ms |
| 49 | `few_2_5` | `intel/xeon_gold_6122` | 3 | 3 | 0 | 0 | 0.22 ms |
| 50 | `many_6plus` | `netapp/h300s` | 24 | 24 | 0 | 0 | 4.306 ms |
| 51 | `many_6plus` | `netapp/h500s` | 24 | 24 | 0 | 0 | 0.114 ms |
| 52 | `many_6plus` | `netapp/h700s` | 24 | 24 | 0 | 0 | 0.116 ms |
| 53 | `many_6plus` | `netapp/h410s` | 24 | 24 | 0 | 0 | 0.104 ms |
| 54 | `many_6plus` | `intel/core_i7-10700k` | 19 | 19 | 0 | 0 | 2.011 ms |
| 55 | `many_6plus` | `intel/core_i7-11800h` | 19 | 19 | 0 | 0 | 1.405 ms |
| 56 | `many_6plus` | `intel/core_i5-1155g7` | 19 | 19 | 0 | 0 | 2.143 ms |
| 57 | `many_6plus` | `intel/core_i5-11320h` | 19 | 19 | 0 | 0 | 0.766 ms |
| 58 | `many_6plus` | `intel/core_i5-11260h` | 18 | 18 | 0 | 0 | 0.081 ms |
| 59 | `complement` | `nvidia/jetson_nano` | 8 | 8 | 0 | 0 | 0.642 ms |
| 60 | `complement` | `intel/core_i3-9350k` | 12 | 12 | 0 | 0 | 1.142 ms |

### Composition des strates (choix deterministe par hachage)

| strate | quota | retenus |
|---|---|---|
| `vendeurs_du_corpus` | 8 | 8 |
| `vendor_wildcard_owed` | 4 | 4 |
| `version_bounded` | 8 | 8 |
| `control_zero_cve` | 3 | 3 |
| `single_1_cve` | 20 | 12 |
| `few_2_5` | 15 | 14 |
| `many_6plus` | 10 | 9 |
| `complement` | 60 | 2 |

## Ce que ce banc prouve, et ce qu'il ne prouve pas

- **Prouve** : pour ces 60 couples `(vendor, product)`, la reponse de `search_cve` est identique a celle qu'on obtient en relisant les flux NVD bruts avec un code qui ne partage rien avec l'ingestion ni avec la recherche. Cela couvre **a la fois** l'extraction (colonnes `vendor`/`product`/`part`) **et** la restitution.
- **Ne prouve pas** que les regles de semantique (`part='h'`, `negate`, `vulnerable`, `Rejected`) sont les bonnes : elles sont reproduites des deux cotes parce que le contrat les fixe. C'est le point que la **verification a la main** doit valider, cas par cas.
- **Ne couvre pas** la logique de plages de versions sur une version connue : le chemin nominal du projet est `version=None` (une photo ne donne pas le firmware), et c'est ce chemin qui est mesure ici. Les plages sont couvertes par `tests/test_version.py` et `tests/test_search_cve.py`.
- **`negate` n'est jamais exerce par la donnee reelle** : 0 critere materiel `negate=1` dans les quatre flux. Sa branche de code n'est donc couverte que par `tests/test_search_cve.py`, pas par ce banc. Il ne faut pas lire « 0 faux negatif » comme une validation de ce chemin.
- **La base stockee est tres majoritairement inatteignable** : 316311 criteres materiels sur 329779 portent `vulnerable=0` (ils decrivent ce qu'une CVE **n'affecte pas** ou une plateforme requise). Ils entrent en base mais `search_cve` ne les rend jamais. Le volume de 324 470 lignes ne doit donc jamais etre cite comme « nombre de CVE exploitables ».
- **La strate `vendeurs_du_corpus` garantit le vendeur, pas la famille d'objet** : elle selectionne par nom de vendeur, donc un appareil `samsung` du corpus peut etre confronte a des CVE d'*imprimantes*. C'est suffisant pour prouver que la chaine fonctionne sur les vendeurs audites ; ce n'est pas une mesure par objet du corpus.
- **L'echantillon des 60 cas est choisi par ce script**, pas par le NVD ni par un tirage aleatoire : la composition des strates est publiee ci-dessus pour qu'on puisse la discuter. « 0 faux negatif » vaut pour **ces 60 cas**, et la section 1 montre que la base interrogee ne contient qu'une fraction du sujet.
