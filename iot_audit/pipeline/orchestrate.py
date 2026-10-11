"""Orchestrateur de bout en bout (docs/03 §2, docs/08 tâche 3.5, D16).

Chaîne complète, dans l'ordre prescrit par la directive du 2026-10-05 (D16) :

    pré-vol (espace disque)      → refus éventuel AVANT tout appel de modèle
    photo → triage visuel {view, category, « IoT ou non », n objets}
          → cadrage rejeté si « ≥ 2 objets ou aucun » (P1 : une photo = un objet)
          → (si IoT) identification {brand, model} — l'étiquette n'est lue que
            quand le premier filtre a dit que l'objet a un intérêt
          → le texte lu est une donnée, jamais une instruction
          → confiance (A, R) → résolution CPE → recherche CVE
          → journal chaîné HMAC → export scellé Ed25519

Règles de couplage respectées (docs/03 §3) :
* C2 — la confiance est calculée **ici** (`orchestration`) ; la couche rapport
  ne fait que formater. La **formule** (A, R, matrice) vit dans
  `modules.confidence` et n'est jamais recopiée : une seconde implémentation
  dérive de la première (mesuré : « TP-Link » et « tp link » n'étaient pas
  fusionnés, A tombait de 1,0 à 0,67 pour un même vendeur).
* C4 — aucun appel à ``datetime.now()`` : l'horloge est injectée.
* C5 — **seul l'orchestrateur écrit le journal** ; les modules rendent des
  données, jamais des écritures.
* D16 — le triage « IoT ou non, catégorie sans marque » précède toute lecture
  de marque ; un objet non connecté n'envoie **aucune** photo au lecteur
  d'étiquette (l'auditeur n'est alerté que si l'objet a un intérêt).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from iot_audit.contracts import (
    CPECandidate,
    CVEResult,
    CVESearcher,
    ErrorCode,
    Identification,
    ImageInput,
    Journal,
    JournalEvent,
    JournalWriteError,
    ObjectTriage,
    Status,
    TriageRunner,
    VLMRawOutput,
    VLMRunner,
)
from iot_audit.modules.adversarial import (
    detect_injection_patterns,
    excerpt,
    label_divergence,
)
from iot_audit.modules.confidence import evaluate_confidence
from iot_audit.modules.label_brand import recover_brand_from_text
from iot_audit.modules.resolve_cpe import decide_cpe_code, resolve
from iot_audit.modules.triage import consolidate_triage, framing_state, screen_frame
from iot_audit.pipeline.normalize import canon_vendor, normalize_display
from iot_audit.pipeline.preflight import PreflightCheck

__all__ = [
    "Orchestrator",
    "PoolProvider",
    "RunConfig",
    "RunOutcome",
]

Clock = Callable[[], datetime]

# Fournisseur du bassin de candidats CPE (FTS5 / dictionnaire hors ligne).
# Signature : (brand, model, category, k) -> candidats **non classés**.
PoolProvider = Callable[[str | None, str, object, int], Sequence[CPECandidate]]


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Paramètres figés d'un run (reproductibilité, ENF5)."""

    run_id: str
    triage_prompt_version: str = "v6"
    ident_prompt_version: str = "v3"
    cve_since: date | None = None
    k_candidates: int = 3


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """Résultat complet d'un run sur N photos du même objet."""

    run_id: str
    object_id: str
    triage: ObjectTriage
    identification: Identification | None
    cpe_candidates: tuple[CPECandidate, ...]
    cves: tuple[CVEResult, ...]
    error_codes: tuple[ErrorCode, ...]
    n_images_ok: int
    n_images_failed: int
    journal_head_hmac: str


class Orchestrator:
    """Enchaîne les étapes et écrit **seul** le journal (C5).

    Dépendances injectées par protocole (docs/03 §2) : testable sans GPU ni
    réseau avec de faux runners.
    """

    def __init__(
        self,
        *,
        triage_runner: TriageRunner,
        vlm_runner: VLMRunner,
        pool_provider: PoolProvider,
        searcher: CVESearcher,
        journal: Journal,
        clock: Clock,
        preflight: PreflightCheck | None = None,
    ) -> None:
        self._triage = triage_runner
        self._vlm = vlm_runner
        self._pool = pool_provider
        self._searcher = searcher
        self._journal = journal
        self._clock = clock
        self._seq = 0
        # Pré-vol optionnel (`E_DISK_FULL`). ``None`` = pas de contrôle, ce qui
        # garde les bancs et les fakes existants valides : un contrôle de
        # disque implicite ferait échouer des runs qui n'ont jamais prétendu
        # écrire ailleurs qu'en mémoire.
        self._preflight = preflight
        # Horloge : l'orchestrateur ne lit l'heure qu'ici, pour détecter un
        # recul (`E_CLOCK_SKEW`). Aucun calcul de durée ne s'appuie dessus.
        self._last_ts: datetime | None = None
        self._clock_skew_delta: float | None = None

    def _next_seq(self) -> int:
        """Index de séquence : **global** si le journal le connaît, sinon local.

        La séquence est une propriété de la chaîne, pas d'un run : deux runs
        partagent la même table. Un journal capable de répondre ``next_seq()``
        (cas SQLite) rend la question impossible à se poser ; les fakes de test
        conservent un compteur local monotone.
        """
        getter = getattr(self._journal, "next_seq", None)
        if callable(getter):
            return int(getter())
        seq = self._seq
        self._seq += 1
        return seq

    # ------------------------------------------------------------------ #
    # Journal : la seule porte d'écriture du système (C5)
    # ------------------------------------------------------------------ #
    def _emit(self, run_id: str, stage: str, code: str, payload: dict) -> str:
        now = self._clock()
        if self._last_ts is not None:
            delta = (now - self._last_ts).total_seconds()
            if delta < 0:
                # E_CLOCK_SKEW : « horloge incohérente entre étapes » — avertit,
                # continue (docs/03 §5). Le seq fait foi : la chaîne reste
                # valide, donc le run n'est pas invalidé. Mais un horodatage
                # qui recule doit être signalé, sinon il se lit comme un
                # artefact de mesure au lieu d'un défaut d'horloge (mesuré :
                # sur un run distribué, les trois nœuds ne partagent pas de
                # source de temps).
                self._clock_skew_delta = (
                    delta if self._clock_skew_delta is None
                    else min(self._clock_skew_delta, delta)
                )
                payload = {**payload, "measured_delta_s": delta}
        self._last_ts = now

        ev = JournalEvent(
            run_id=run_id,
            seq=self._next_seq(),
            stage=stage,
            code=code,
            payload=payload,
            occurred_at=now,
        )
        try:
            return self._journal.append(ev)
        except (JournalWriteError, OSError) as exc:
            # E_JOURNAL_WRITE_FAILED : « on ne produit pas de résultat non
            # tracé ». Une implémentation SQLite traduit déjà ses erreurs de
            # driver ; ce second filet couvre les journaux qui remonteraient
            # une OSError brute. Dans les deux cas le run s'arrête ici.
            raise JournalWriteError(
                f"{ErrorCode.E_JOURNAL_WRITE_FAILED.value}: écriture refusée au stade "
                f"{stage!r} — le run s'arrête, un résultat non tracé n'est pas un "
                f"résultat : {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Pipeline
    # ------------------------------------------------------------------ #
    def run_object(
        self,
        config: RunConfig,
        object_id: str,
        images: Sequence[ImageInput],
    ) -> RunOutcome:
        errors: list[ErrorCode] = []

        # ---- 0. Pré-vol : refuser AVANT d'appeler un modèle ----------------
        # Un run refusé ici ne laisse rien à nettoyer ; un run parti sans
        # espace laisse une chaîne tronquée.
        if self._preflight is not None:
            refusal = self._preflight()
            if refusal is not None:
                head = self._emit(config.run_id, "preflight", refusal.value, {
                    "object_id": object_id,
                    "n_images": len(images),
                })
                return self._outcome(
                    config, object_id, consolidate_triage(object_id, []),
                    None, (), (), [refusal], 0, 0, head,
                )

        # ---- 1. Triage visuel (D16) : la porte d'entrée ----------------
        triage_outputs = []
        ok_images: list[ImageInput] = []
        failed = 0
        n_framing_unverified = 0
        n_framing_rejected = 0
        for img in images:
            try:
                triage_out = self._triage.triage(
                    img, prompt_version=config.triage_prompt_version
                )
            except TimeoutError:
                failed += 1
                errors.append(ErrorCode.E_VLM_TIMEOUT)
                continue
            except ValueError:
                failed += 1
                errors.append(ErrorCode.E_VLM_INVALID_JSON)
                continue
            except Exception:
                # aucun diagnostic plus fin : le nœud n'a pas répondu du tout
                failed += 1
                errors.append(ErrorCode.E_MODEL_UNAVAILABLE)
                continue

            # P1 « une photo = un objet ». Le cadrage est refusé AVANT que la
            # photo entre dans la consolidation : deux objets dans une image,
            # c'est un tuple attribué au hasard en aval, et cette erreur-là ne
            # se voit pas dans le rapport (il a l'air d'une réussite).
            refusal = screen_frame(triage_out)
            if refusal is not None:
                failed += 1
                errors.append(refusal)
                n_framing_rejected += 1
                continue
            if framing_state(triage_out) == "unverified":
                # Le prompt de triage n'a pas posé la question (schéma v6 :
                # {view, category, iot}). La photo est acceptée — un champ
                # absent n'est pas un refus — mais l'invariant P1 n'est pas
                # établi pour autant, et ce compteur est ce qui l'empêche de
                # devenir une conformité silencieuse au moment du rapport.
                n_framing_unverified += 1

            triage_outputs.append(triage_out)
            ok_images.append(img)

        if not triage_outputs:
            # la cause est déjà enregistrée image par image ; le seul cas où
            # aucune erreur n'existe est une liste d'images vide
            if not errors:
                errors.append(ErrorCode.E_IMAGE_UNREADABLE)
            head = self._emit(config.run_id, "triage", errors[-1].value, {"object_id": object_id})
            return self._outcome(
                config, object_id, consolidate_triage(object_id, []),
                None, (), (), errors, 0, failed, head,
            )
        triage = consolidate_triage(object_id, triage_outputs)
        # Le journal porte le cadrage **réellement vérifié**. « framing:
        # unverified » n'est pas un détail d'affichage : c'est l'état de toute
        # mesure produite par un prompt qui ne pose pas la question, et il est
        # écrit ici pour que personne n'ait à le supposer à la lecture du
        # rapport.
        self._emit(config.run_id, "triage", "OK", {
            "object_id": object_id,
            "n_images": len(images),
            "n_failed": failed,
            "framing": triage.framing,
            "framing_unverified": n_framing_unverified,
            "framing_rejected": n_framing_rejected,
        })

        # ---- 2. Objet non connecté : STOP (jamais de lecture de marque) --
        if not triage.is_iot:
            self._note_partial(errors, failed)
            head = self._emit(config.run_id, "triage", "NON_IOT", {
                "object_id": object_id,
                "category": triage.category.value,
                "agreement": triage.iot_agreement,
                "n_failed": failed,
                "errors": [e.value for e in errors],
            })
            return self._outcome(
                config, object_id, triage, None, (), (), errors,
                len(ok_images), failed, head,
            )

        # ---- 3. Identification (marque/modèle) — seulement si IoT --------
        raw_outputs: list[VLMRawOutput] = []
        for img in ok_images:
            try:
                raw_outputs.append(self._vlm.infer(img, prompt_version=config.ident_prompt_version))
            except TimeoutError:
                # taxonomie D14 : le délai et la sortie illisible ne sont pas
                # le même défaut, ils n'appellent pas le même correctif
                failed += 1
                errors.append(ErrorCode.E_VLM_TIMEOUT)
            except ValueError:
                failed += 1
                errors.append(ErrorCode.E_VLM_INVALID_JSON)
            except Exception:
                failed += 1
                errors.append(ErrorCode.E_VLM_TIMEOUT)

        if not raw_outputs:
            errors.append(ErrorCode.E_MODEL_UNAVAILABLE)
            head = self._emit(config.run_id, "identify", errors[-1].value, {"object_id": object_id})
            return self._outcome(
                config, object_id, triage, None, (), (), errors, 0, failed, head,
            )

        # ---- 3 bis. Le texte lu est une DONNÉE, jamais une instruction ----
        # docs/03 §5, docs/07 §5. Rien ici n'exécute ni ne réécrit visible_text :
        # on constate la tentative. Le Guided Decoding empêche la sortie de
        # quitter le schéma, il n'empêche pas le modèle de permuter une marque
        # *à l'intérieur* du schéma si un texte imprimé l'y invite.
        suspicious: list[dict[str, str]] = []
        for raw in raw_outputs:
            found = detect_injection_patterns(raw.visible_text)
            if found:
                suspicious.append({
                    "pattern": found[0],
                    "raw_text": excerpt(raw.visible_text),
                })
        if suspicious:
            errors.append(ErrorCode.E_ADVERSARIAL_LABEL_SUSPECTED)

        # ---- 4. Confiance (A, R) + résolution CPE (C2 : calcul ici) -----
        # L'identité rapportée est consolidée sur la MÊME canonisation que la
        # confiance ci-dessous (`modules.confidence`), jamais sur des chaînes
        # brutes. Défaut corrigé le 2026-10-06, mesuré : sur le même jeu
        # `[D-Link, TP-Link, tp link]`, l'ancien vote publiait `brand="D-Link"`
        # à côté de `agreement = 0,667` — un chiffre qui portait, lui, sur
        # « TP-Link ». Trois ordres d'entrée donnaient trois marques publiées
        # pour un seul consensus. La marque rapportée ne peut plus sortir de la
        # classe gagnante.
        brand = self._modal(raw_outputs, lambda r: r.brand, canon_vendor)
        model = self._modal(raw_outputs, lambda r: r.model, normalize_display)

        # Le modèle lit et n'ose pas conclure : quand il a transcrit du texte
        # sans restituer de marque, on reprend la marque **du texte qu'il a
        # lui-même lu**, avec le lexique curé du périmètre. Jamais d'invention,
        # jamais de contradiction d'une marque annoncée — la fonction n'est
        # appelée que sur un champ vide, et n'accepte qu'un vendeur présent en
        # mot entier dans la transcription (voir `modules.label_brand`, dont le
        # coût est mesuré : +9 et +21 images pour une seule marque fausse).
        brand_from_text: str | None = None
        if not brand:
            brand_from_text = recover_brand_from_text(r.visible_text for r in raw_outputs)
            brand = brand_from_text

        # ---- 3 ter. Divergence d'étiquette (docs/07 §5) ------------------
        # Le texte imprimé nomme un autre vendeur CONNU que la marque
        # revendiquée par le rapport. Mesuré le 2026-10-06 sur toutes les
        # sorties réelles gelées : la règle étroite ne déclenche sur aucune
        # photo (voir `modules.adversarial` — la prise de la version large
        # était le mot « ALARM » sur une façade de modem). Elle est donc câblée
        # pour le cas qu'elle existe pour attraper, et l'absence de mesure
        # positive est écrite plutôt que compensée par un seuil inventé.
        #
        # Aucun code d'erreur : la taxonomie est figée à 20 (AC12) et docs/07 §5
        # attend pour ce cas « divergence remontée ; statut avec réserve ».
        claimed = brand or ""
        divergences: list[dict[str, str]] = []
        for raw in raw_outputs:
            other = label_divergence(claimed, raw.visible_text)
            if other:
                divergences.append({
                    "claimed_brand": claimed,
                    "text_brand": other,
                    "raw_text": excerpt(raw.visible_text),
                })
        pool = list(self._pool(brand, model or "", triage.category, config.k_candidates))
        top3 = resolve(model or "", None, pool)
        cpe_status, cpe_code = decide_cpe_code(top3)
        if cpe_code is not None:
            errors.append(cpe_code)

        # Source UNIQUE de la confiance : `modules.confidence` (docs/05 §4).
        # Ne jamais recalculer A ici — une seconde formule, sans la
        # normalisation d'alias, séparait un même vendeur (« TP-Link » vs
        # « tp link ») et sous-estimait l'accord (A = 0,67 au lieu de 1,0).
        evaluation = evaluate_confidence(raw_outputs, top3)
        if evaluation.error_code is not None:
            errors.append(evaluation.error_code)

        # Un run marqué suspect ne s'affiche jamais « identifié » : le statut
        # descend d'un cran, il ne remonte pas (docs/03 §5). Même règle pour une
        # divergence d'étiquette : une marque contredite par le texte imprimé de
        # la photo n'est pas une identification.
        #
        # R n'est **pas** recalculé, alors que docs/07 §5 le mentionne : R est la
        # résolvabilité du tuple retenu dans le référentiel CPE (docs/05 §4), et
        # y injecter une défiance encoderait la confiance dans une métrique qui
        # mesure autre chose. La défiance est portée là où elle se lit : le
        # statut, et la trace de la divergence.
        status = evaluation.status
        if (suspicious or divergences) and status is Status.IDENTIFIED:
            status = Status.WITH_RESERVE

        identification = Identification(
            brand=brand,
            model=model,
            category=triage.category,
            status=status,
            n_images=len(raw_outputs),
            agreement=evaluation.agreement,
            resolvability=evaluation.resolvability,
            per_field_agreement=dict(evaluation.per_field_agreement),
            distribution=dict(evaluation.distribution),
            cpe_candidates=tuple(top3),
            cves=(),
        )
        self._emit(config.run_id, "identify", "OK", {
            "object_id": object_id,
            "status": status.value,
            "agreement": evaluation.agreement,
            "resolvability": evaluation.resolvability,
            "cpe_status": cpe_status,
            "adversarial": suspicious,
            "label_divergence": divergences,
            # Trace de la restitution : sans elle, une marque reprise du texte lu
            # serait indistinguable d'une marque annoncée par le modèle, et le
            # rapport ne pourrait pas dire d'où elle vient.
            "brand_from_text": brand_from_text,
        })

        # ---- 5. Recherche CVE -----------------------------------------
        cves: list[CVEResult] = []
        selected = top3[0] if top3 and cpe_status == "auto" else None
        if selected is not None:
            try:
                cves = list(self._searcher.search(selected, since=config.cve_since or date.min))
                if not cves:
                    errors.append(ErrorCode.E_NO_CVE)
                elif any(c.cache_status == "miss" for c in cves):
                    # docs/03 §5 : « marque explicitement ». La recherche est
                    # juste, c'est la base qui peut être en retard ; taire le
                    # retard ferait lire une lacune de données comme une
                    # absence de vulnérabilité.
                    errors.append(ErrorCode.E_NVD_CACHE_MISS)
            except Exception:
                errors.append(ErrorCode.E_NVD_UNAVAILABLE)
        self._emit(config.run_id, "cve", "OK", {
            "object_id": object_id,
            "n_cves": len(cves),
            "cpe": selected.cpe_name if selected else None,
        })

        self._note_partial(errors, failed)

        head = self._emit(config.run_id, "run", "DONE", {
            "object_id": object_id,
            "errors": [e.value for e in errors],
        })

        return self._outcome(
            config, object_id, triage, identification, tuple(top3), tuple(cves),
            errors, len(raw_outputs), failed, head,
        )

    # ------------------------------------------------------------------ #
    # Utilitaires
    # ------------------------------------------------------------------ #
    def _outcome(
        self,
        config: RunConfig,
        object_id: str,
        triage: ObjectTriage,
        identification: Identification | None,
        cpe_candidates: tuple[CPECandidate, ...],
        cves: tuple[CVEResult, ...],
        errors: list[ErrorCode],
        n_ok: int,
        n_failed: int,
        head: str,
    ) -> RunOutcome:
        # E_CLOCK_SKEW est ajouté ici, et non au fil de l'eau : l'horloge peut
        # reculer à n'importe quelle étape, y compris dans un chemin qui
        # s'arrête tôt (objet non connecté, aucune photo exploitable). Le point
        # de sortie unique garantit que tous les chemins le signalent.
        if self._clock_skew_delta is not None and ErrorCode.E_CLOCK_SKEW not in errors:
            errors.append(ErrorCode.E_CLOCK_SKEW)
        return RunOutcome(
            run_id=config.run_id,
            object_id=object_id,
            triage=triage,
            identification=identification,
            cpe_candidates=cpe_candidates,
            cves=cves,
            error_codes=tuple(errors),
            n_images_ok=n_ok,
            n_images_failed=n_failed,
            journal_head_hmac=head,
        )

    @staticmethod
    def _note_partial(errors: list[ErrorCode], failed: int) -> None:
        """« Run partiel » est un état du run, pas une propriété du chemin IoT.

        La même trace doit exister quand l'objet s'arrête au triage : sinon un
        objet non connecté mesuré sur des images partiellement perdues
        s'enregistrait comme un run complet (incohérence D14 corrigée).
        """
        if failed:
            errors.append(ErrorCode.E_PARTIAL_RUN)

    @staticmethod
    def _modal(
        raws: Sequence[VLMRawOutput],
        key: Callable[[VLMRawOutput], str],
        canon: Callable[[str], str] = lambda s: s,
    ) -> str | None:
        """Valeur consolidée d'un champ — **le vote porte sur la forme canonisée**.

        `canon` est celle de `modules.confidence.compute_agreements`
        (`canon_vendor` pour la marque, `normalize_display` pour le modèle), pour
        que les orthographes d'un même vendeur soient **une seule classe** et que
        la valeur rapportée ne puisse pas être une minorité. La forme rendue reste
        l'orthographe d'origine — `Identification.brand` sert à l'affichage, le
        jeton CPE est reconstruit plus loin.

        Départage des ex æquo, explicite et non laissé à l'ordre d'un `dict` :

        * entre classes, la **première rencontrée** — même règle que
          `corpus.metrics.modal`, et pour la même raison : elle est *observée* sur
          la table publiée, donc révisable par un humain et pas par accident ;
        * dans la classe gagnante, l'orthographe brute la plus fréquente, et à
          égalité la première rencontrée.

        `canon` vaut l'identité par défaut : un appelant sans canonisation
        obtient le comportement d'origine, et les gardes sur séquence vide
        restent vérifiables à l'identique.
        """
        classes: dict[str, Counter[str]] = {}
        for r in raws:
            raw = key(r).strip()
            if not raw:
                continue
            classes.setdefault(canon(raw), Counter())[raw] += 1
        best: str | None = None
        best_n = 0
        for name, spellings in classes.items():
            n = sum(spellings.values())
            if n > best_n:            # strict : la première classe l'emporte à égalité
                best, best_n = name, n
        if best is None:
            return None
        return classes[best].most_common(1)[0][0]
