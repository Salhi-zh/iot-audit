"""Tests unitaires de la taxonomie d'erreurs (D14, AC12, docs/03 §5).

Critère d'acceptation AC12 : un test par message d'erreur (20 codes).
Chaque test vérifie pour le code d'erreur :
  1. Son existence exacte dans l'énumération ``ErrorCode`` ;
  2. Son déclencheur documenté ;
  3. Le comportement système associé ;
  4. Le message utilisateur (FR, ton professionnel, non rassurant si 0 CVE) ;
  5. La trace journal (champs obligatoires).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from iot_audit.contracts import ERROR_TAXONOMY, ErrorCode, ErrorDefinition


def test_taxonomy_size_is_exactly_twenty() -> None:
    """AC12 exige exactement 20 codes d'erreur."""
    assert len(ErrorCode) == 20
    assert len(ERROR_TAXONOMY) == 20
    for code in ErrorCode:
        assert code in ERROR_TAXONOMY


@pytest.mark.parametrize(
    "code",
    list(ErrorCode),
)
def test_error_code_definition_contract(code: ErrorCode) -> None:
    defn = ERROR_TAXONOMY[code]
    assert isinstance(defn, ErrorDefinition)
    assert defn.code == code
    assert isinstance(defn.trigger, str) and len(defn.trigger) > 0
    assert isinstance(defn.system_behavior, str) and len(defn.system_behavior) > 0
    assert isinstance(defn.user_message_template, str)
    assert isinstance(defn.journal_trace_fields, tuple) and len(defn.journal_trace_fields) > 0


# --------------------------------------------------------------------------- #
# Tests spécifiques pour chacun des 20 codes d'erreur (AC12)
# --------------------------------------------------------------------------- #


def test_ac12_e_model_unavailable() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_MODEL_UNAVAILABLE]
    assert defn.trigger == "aucun nœud vLLM ne répond"
    assert "bascule" in defn.system_behavior
    assert "Service d'identification indisponible" in defn.user_message_template
    assert "stage" in defn.journal_trace_fields
    assert "nodes_tried" in defn.journal_trace_fields


def test_ac12_e_vlm_timeout() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_VLM_TIMEOUT]
    assert "délai" in defn.trigger
    assert "retry ×2" in defn.system_behavior
    assert "Analyse trop longue" in defn.user_message_template
    assert "image_id" in defn.journal_trace_fields
    assert "duration" in defn.journal_trace_fields


def test_ac12_e_vlm_invalid_json() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_VLM_INVALID_JSON]
    assert "Guided Decoding" in defn.trigger
    assert "1 retry" in defn.system_behavior
    assert "Réponse du modèle inexploitable" in defn.user_message_template
    assert "raw_response_truncated" in defn.journal_trace_fields


def test_ac12_e_image_unreadable() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_IMAGE_UNREADABLE]
    assert "décodage" in defn.trigger or "format" in defn.trigger
    assert "rejet immédiat" in defn.system_behavior
    assert "Fichier illisible ou non supporté." in defn.user_message_template
    assert "sha256" in defn.journal_trace_fields
    assert "cause" in defn.journal_trace_fields


def test_ac12_e_multi_object_or_unclear() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_MULTI_OBJECT_OR_UNCLEAR]
    assert "≥ 2 objets" in defn.trigger or "cadrage" in defn.trigger
    assert "rejet" in defn.system_behavior
    assert "Plusieurs objets détectés" in defn.user_message_template
    assert "detection_output" in defn.journal_trace_fields


def test_ac12_e_adversarial_label_suspected() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_ADVERSARIAL_LABEL_SUSPECTED]
    assert "visible_text" in defn.trigger or "instruction" in defn.trigger
    assert "jamais exécuté" in defn.system_behavior
    assert "Texte suspect détecté" in defn.user_message_template
    assert "raw_text" in defn.journal_trace_fields
    assert "pattern" in defn.journal_trace_fields


def test_ac12_e_no_identification() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_NO_IDENTIFICATION]
    assert "aucun tuple" in defn.trigger
    assert "non identifié" in defn.system_behavior
    assert "Objet non identifié — vérification manuelle requise." in defn.user_message_template
    assert "distribution" in defn.journal_trace_fields


def test_ac12_e_low_confidence() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_LOW_CONFIDENCE]
    assert "A < seuil bas" in defn.trigger
    assert "EF5" in defn.system_behavior or "non identifié" in defn.system_behavior
    assert "Identification peu stable" in defn.user_message_template
    assert "agreement" in defn.journal_trace_fields
    assert "distribution" in defn.journal_trace_fields


def test_ac12_e_uncalibrated_consensus() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_UNCALIBRATED_CONSENSUS]
    assert "A élevé" in defn.trigger and "R faible" in defn.trigger
    assert "identifié avec réserve" in defn.system_behavior
    assert "Résultat cohérent mais non retrouvé dans le référentiel" in defn.user_message_template
    assert "agreement" in defn.journal_trace_fields
    assert "resolvability" in defn.journal_trace_fields


def test_ac12_e_no_cpe_match() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_NO_CPE_MATCH]
    assert "résolvabilité" in defn.trigger or "score" in defn.trigger
    assert "jamais de CPE inventé" in defn.system_behavior
    assert "absent du référentiel NIST" in defn.user_message_template
    assert "top3_scores" in defn.journal_trace_fields


def test_ac12_e_cpe_ambiguous() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_CPE_AMBIGUOUS]
    assert "marge" in defn.trigger or "top1−top2" in defn.trigger
    assert "force le HITL" in defn.system_behavior or "propose les 2" in defn.system_behavior
    assert "Deux référentiels correspondent" in defn.user_message_template
    assert "top2_scores" in defn.journal_trace_fields


def test_ac12_e_no_cve() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_NO_CVE]
    assert "0 CVE" in defn.trigger
    assert "non rassurant" in defn.system_behavior
    # Formule non négociable du CDC/CDS interdisant de conclure à l'innocuité
    msg = defn.format_message(date="2026-10-06")
    assert "Aucune CVE référencée pour ce produit au 2026-10-06." in msg
    assert "ne signifie pas qu'il est exempt de vulnérabilités" in msg
    assert "version firmware non déterminée" in msg
    assert "cpe" in defn.journal_trace_fields
    assert "snapshot" in defn.journal_trace_fields
    assert "n" in defn.journal_trace_fields


def test_ac12_e_nvd_unavailable() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_NVD_UNAVAILABLE]
    assert "snapshot absent" in defn.trigger or "illisible" in defn.trigger
    assert "mode dégradé" in defn.system_behavior
    assert "Base CVE locale indisponible" in defn.user_message_template
    assert "cache_status" in defn.journal_trace_fields


def test_ac12_e_nvd_cache_miss() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_NVD_CACHE_MISS]
    assert "hors snapshot" in defn.trigger
    assert "marque explicitement" in defn.system_behavior
    msg = defn.format_message(date="2026-10-06")
    assert "Recherche effectuée sur la base du 2026-10-06" in msg
    assert "snapshot_sha256" in defn.journal_trace_fields


def test_ac12_e_provenance_incomplete() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_PROVENANCE_INCOMPLETE]
    assert "provenance" in defn.trigger
    assert "écriture refusée" in defn.system_behavior
    assert "Analyse refusée : traçabilité incomplète." in defn.user_message_template
    assert "missing_field" in defn.journal_trace_fields


def test_ac12_e_hmac_chain_broken() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_HMAC_CHAIN_BROKEN]
    assert "chaîne" in defn.trigger
    assert "run invalide" in defn.system_behavior or "bloqué" in defn.system_behavior
    assert "Intégrité du journal compromise" in defn.user_message_template
    assert "break_index" in defn.journal_trace_fields
    assert "expected" in defn.journal_trace_fields
    assert "computed" in defn.journal_trace_fields


def test_ac12_e_journal_write_failed() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_JOURNAL_WRITE_FAILED]
    assert "journal" in defn.trigger
    assert "arrêt du run" in defn.system_behavior
    assert "Impossible d'enregistrer la trace. Analyse interrompue." in defn.user_message_template
    assert "error" in defn.journal_trace_fields


def test_ac12_e_disk_full() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_DISK_FULL]
    assert "espace insuffisant" in defn.trigger
    assert "refus avant run" in defn.system_behavior
    assert "Espace de stockage insuffisant." in defn.user_message_template
    assert "threshold" in defn.journal_trace_fields
    assert "available" in defn.journal_trace_fields


def test_ac12_e_clock_skew() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_CLOCK_SKEW]
    assert "horloge" in defn.trigger
    assert "avertit, continue" in defn.system_behavior
    assert defn.user_message_template == ""  # invisible pour l'utilisateur
    assert "measured_delta" in defn.journal_trace_fields


def test_ac12_e_partial_run() -> None:
    defn = ERROR_TAXONOMY[ErrorCode.E_PARTIAL_RUN]
    assert "nœud perdu" in defn.trigger
    assert "partiel" in defn.system_behavior
    assert "Analyse terminée avec un nœud en moins" in defn.user_message_template
    assert "nodes" in defn.journal_trace_fields
    assert "lost_images" in defn.journal_trace_fields


# --------------------------------------------------------------------------- #
# Registre de câblage — « déclaré » n'est pas « produit » (revue du 2026-10-06)
# --------------------------------------------------------------------------- #
# La taxonomie déclare 20 codes (AC12) et les tests ci-dessus vérifient leur
# **définition**. Aucun ne vérifiait qu'un code est **produit** quelque part —
# or un code déclaré et jamais émis n'est pas une protection, c'est une
# intention. Mesure du 2026-10-06 : **12 codes sur 20** étaient effectivement
# produits par le paquet, **8** ne l'étaient nulle part hors de ``contracts.py``.
#
# Le registre ci-dessous rend cet écart *vérifiable* au lieu de tacite :
#
#  * un code câblé cite son producteur, et le test exige que le nom du code
#    apparaisse dans ce fichier — retirer un producteur casse le test ;
#  * un code sans producteur fait tomber ``test_aucun_code_n_est_declare_sans_
#    producteur``. C'était le cas des huit codes ci-dessous jusqu'au
#    2026-10-06 ; ils sont désormais produits, et la liste vide est elle-même
#    l'assertion : elle interdit de réintroduire un code d'intention.
#
# Deux producteurs méritent d'être nommés parce qu'ils ne sont pas dans le
# chemin nominal : ``storage/journal.py`` produit ``E_JOURNAL_WRITE_FAILED`` en
# traduisant les erreurs de driver (le run s'arrête, l'exception *est* le code),
# et ``storage/seal.py`` produit ``E_HMAC_CHAIN_BROKEN`` en refusant de sceller
# un journal rompu — un refus qui n'existait pas avant cette date.
WIRING: dict[ErrorCode, tuple[str, ...]] = {
    # --- câblés, avec leur producteur ----------------------------------------
    ErrorCode.E_MODEL_UNAVAILABLE: ("iot_audit/pipeline/orchestrate.py",),
    ErrorCode.E_VLM_TIMEOUT: ("iot_audit/pipeline/orchestrate.py",),
    ErrorCode.E_VLM_INVALID_JSON: ("iot_audit/pipeline/orchestrate.py",),
    ErrorCode.E_IMAGE_UNREADABLE: ("iot_audit/pipeline/orchestrate.py",),
    ErrorCode.E_PARTIAL_RUN: ("iot_audit/pipeline/orchestrate.py",),
    ErrorCode.E_NO_CVE: ("iot_audit/pipeline/orchestrate.py",),
    ErrorCode.E_NVD_UNAVAILABLE: ("iot_audit/pipeline/orchestrate.py",
                                  "benchmarks/e2e_live_run.py"),
    ErrorCode.E_NO_CPE_MATCH: ("iot_audit/modules/resolve_cpe.py",),
    ErrorCode.E_CPE_AMBIGUOUS: ("iot_audit/modules/resolve_cpe.py",),
    ErrorCode.E_LOW_CONFIDENCE: ("iot_audit/modules/confidence.py",),
    ErrorCode.E_NO_IDENTIFICATION: ("iot_audit/modules/confidence.py",),
    ErrorCode.E_UNCALIBRATED_CONSENSUS: ("iot_audit/modules/confidence.py",),
    # --- câblés le 2026-10-06 (revue : les 8 codes d'intention restants) -------
    # P1 « une photo = un objet ». Producteur unique, et c'est le module de
    # triage : le cadrage y est jugé et c'est son verdict qui porte le code.
    # L'orchestrateur ne fait que transporter le code rendu jusqu'aux erreurs
    # du run — le nommer ici ferait croire à une seconde décision de cadrage.
    ErrorCode.E_MULTI_OBJECT_OR_UNCLEAR: ("iot_audit/modules/triage.py",),
    # Le texte lu est une donnée, jamais une instruction : les motifs vivent
    # dans leur propre module pour pouvoir être mesurés contre de vraies
    # étiquettes (faux positifs), et l'orchestrateur en tire un statut.
    ErrorCode.E_ADVERSARIAL_LABEL_SUSPECTED: ("iot_audit/modules/adversarial.py",
                                               "iot_audit/pipeline/orchestrate.py"),
    ErrorCode.E_NVD_CACHE_MISS: ("iot_audit/pipeline/orchestrate.py",),
    ErrorCode.E_PROVENANCE_INCOMPLETE: ("iot_audit/pipeline/preflight.py",
                                        "iot_audit/storage/seal.py"),
    ErrorCode.E_HMAC_CHAIN_BROKEN: ("iot_audit/storage/seal.py",),
    ErrorCode.E_JOURNAL_WRITE_FAILED: ("iot_audit/storage/journal.py",
                                       "iot_audit/pipeline/orchestrate.py"),
    ErrorCode.E_DISK_FULL: ("iot_audit/pipeline/preflight.py",
                            "iot_audit/pipeline/orchestrate.py"),
    ErrorCode.E_CLOCK_SKEW: ("iot_audit/pipeline/orchestrate.py",),
}

ROOT = Path(__file__).resolve().parent.parent


def test_le_registre_de_cablage_couvre_exactement_les_vingts_codes() -> None:
    assert set(WIRING) == set(ErrorCode), (
        "le registre doit couvrir les 20 codes, ni plus ni moins"
    )


def test_chaque_code_declare_cable_est_reellement_produit() -> None:
    """Un code marqué câblé doit apparaître dans le fichier qui le produit."""
    for code, producteurs in WIRING.items():
        if not producteurs:
            continue
        for rel in producteurs:
            src = (ROOT / rel).read_text(encoding="utf-8")
            assert code.value in src, (
                f"{code.value} est déclaré produit par {rel}, "
                "mais le nom du code n'y apparaît pas"
            )


def test_aucun_code_n_est_declare_sans_producteur() -> None:
    """Aucun code de la taxonomie ne doit rester « déclaré mais pas produit ».

    Ce test remplace un scan du paquet qui cherchait les huit codes non câblés
    et échouait dès que l'un d'eux apparaissait quelque part. Le scan a fait son
    travail : il a signalé, un par un, chacun des huit branchements du
    2026-10-06. Il est retiré au profit de l'assertion directe — la propriété à
    tenir est « chaque code a un producteur », et un scan de tout le paquet
    coûte une lecture de fichiers pour la vérifier indirectement.
    """
    sans_producteur = sorted(
        c.value for c in ErrorCode if not WIRING.get(c)
    )
    assert not sans_producteur, (
        "ces codes sont déclarés sans producteur : " + ", ".join(sans_producteur)
        + " — les câbler, ou les retirer de la taxonomie (déclarer n'est pas protéger)"
    )
