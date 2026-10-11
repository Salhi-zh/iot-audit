"""Verrouille le **User-Agent** du corpus contre la politique Wikimedia.

Pourquoi ce fichier existe
--------------------------
Wikimedia refuse (`HTTP 429`) les clients dont le User-Agent ne permet pas de
les joindre. Ce n'est pas une préférence : c'est appliqué, et ça se mesure.

Relevé du 2026-10-06, sur la **même** URL de `upload.wikimedia.org`, demandée
trois fois de suite pour chaque en-tête :

=========================================================  ========
User-Agent                                                 résultat
=========================================================  ========
``iot-audit-corpus/0.1 (academic corpus for IoT device…``   429 429 429
``iot-audit-corpus/0.1 (academic IoT device corpus; …@…``   200 200 200
=========================================================  ========

Conséquence mesurée : un lot de 5 242 téléchargements d'images a échoué
**2 310 fois (44 %)** pour cette seule raison. Le défaut a d'abord été attribué
à un « étranglement de la passerelle du campus » — hypothèse plausible, fausse,
et coûteuse : elle a fait chercher des heures du côté du débit réseau alors que
le correctif tenait dans un en-tête.

Ce que ces tests protègent : l'en-tête par défaut porte bien un **moyen de
contact**, et la variable d'environnement `IOT_AUDIT_UA` reste prioritaire (pour
qu'un opérateur puisse mettre *son* adresse sans modifier le code).
"""

from __future__ import annotations

import importlib
import re

from iot_audit.corpus import commons


def test_le_user_agent_par_defaut_porte_un_contact() -> None:
    """Un contact joignable, c'est ce que Wikimedia exige pour ne pas plafonner."""
    ua = commons.USER_AGENT
    assert "@" in ua, f"UA sans adresse de contact (sera plafonné en 429) : {ua!r}"
    assert re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", ua), \
        f"UA dont le contact n'est pas une adresse exploitable : {ua!r}"


def test_le_user_agent_par_defaut_identifie_le_client() -> None:
    """Et il doit aussi dire *qui* parle : la forme `<produit>/<version> (…)`."""
    ua = commons.USER_AGENT
    assert re.match(r"^iot-audit[a-z-]*/[\d.]+ \(", ua), \
        f"UA sans identifiant produit/version en tête : {ua!r}"


def test_la_variable_d_environnement_prime(monkeypatch) -> None:
    """`IOT_AUDIT_UA` reste prioritaire — sinon un opérateur ne peut pas mettre son adresse."""
    monkeypatch.setenv("IOT_AUDIT_UA", "autre-client/9.9 (contact@exemple.org)")
    module = importlib.reload(commons)
    try:
        assert module.USER_AGENT == "autre-client/9.9 (contact@exemple.org)"
    finally:
        monkeypatch.undo()
        importlib.reload(commons)
