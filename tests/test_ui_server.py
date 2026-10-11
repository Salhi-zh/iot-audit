"""Tests de l'interface locale (``iot_audit/ui``).

L'interface n'est pas une API produit : elle écoute sur ``127.0.0.1`` et elle
n'a pas d'authentification. Ce qui doit donc être verrouillé ici n'est pas
l'accès, c'est le **périmètre** :

* les commandes lançables sont une liste fixe — un nom inconnu rend ``None``,
  jamais une commande composée à partir de la requête ;
* les fichiers servis sont une liste blanche de trois noms, donc la traversée
  d'arborescence n'est pas « évitée », elle est impossible ;
* une donnée absente (manifeste non versionné, aucun run) se dégrade en message
  lisible, jamais en exception : l'opérateur ne doit pas découvrir un écran
  blanc parce qu'un fichier de corpus manque.

Ce fichier ne lance aucun serveur et n'ouvre aucun port : ce sont les fonctions
pures qui sont éprouvées, plus un appel réseau volontairement fermé.
"""

from __future__ import annotations

import pytest

from iot_audit.ui import server

# --------------------------------------------------------------------------- #
# Périmètre des commandes : liste fixe
# --------------------------------------------------------------------------- #

def test_gate_names_are_a_closed_set() -> None:
    for name in ("tests", "lint", "types", "tunnel-scope", "live-e2e"):
        assert server.gate_argv(name), f"{name} devrait exister"


def test_unknown_gate_is_refused_without_being_executed() -> None:
    for name in ("", "rm", "../../bin/sh", "tests; rm -rf /", "pytest"):
        assert server.gate_argv(name) is None


def test_gate_commands_have_no_shell() -> None:
    """Aucun élément n'est une chaîne composite : tout est un argument distinct."""
    for name, argv in (
        (n, server.gate_argv(n)) for n in ("tests", "lint", "types", "tunnel-scope", "live-e2e")
    ):
        assert argv is not None
        for token in argv:
            assert ";" not in token and "|" not in token and "&&" not in token, (name, token)


def test_tests_gate_runs_the_project_test_suite() -> None:
    assert server.gate_argv("tests")[1:] == ["-m", "pytest", "-q"]


def test_tunnel_gate_uses_the_tunnel_script() -> None:
    argv = server.tunnel_argv("status")
    assert argv[0] == "bash"
    assert argv[1].endswith("infra/scripts/tunnel_vllm.sh")
    assert argv[2] == "status"


# --------------------------------------------------------------------------- #
# Fichiers servis : liste blanche
# --------------------------------------------------------------------------- #

def test_only_three_local_files_are_served() -> None:
    assert set(server.STATIC_WHITELIST) == {"/", "/app.js", "/style.css"}


def test_no_served_path_can_escape_the_static_directory() -> None:
    """La traversée est impossible par construction : table de correspondance."""
    for route, (name, _ctype) in server.STATIC_WHITELIST.items():
        assert "/" not in name and ".." not in name, route
        assert (server.STATIC_DIR / name).exists(), f"{route} -> fichier absent"


# --------------------------------------------------------------------------- #
# Dégradation : une donnée absente n'est pas une panne
# --------------------------------------------------------------------------- #

def test_corpus_summary_degrades_when_the_manifest_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Le manifeste runner v6 n'est pas versionné : son absence est normale."""
    monkeypatch.setattr(server, "RUNNER_MANIFEST", tmp_path / "absent.py")  # type: ignore[arg-type]
    out = server.corpus_summary()
    assert "error" in out
    assert out["objects"] == []
    assert out["n_images_cached"] == 0


def test_corpus_summary_does_not_raise_on_a_malformed_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    broken = tmp_path / "runner-broken.py"
    broken.write_text("MANIFEST = json.loads(r\"\"\"{not json}\"\"\")", encoding="utf-8")
    monkeypatch.setattr(server, "RUNNER_MANIFEST", broken)  # type: ignore[arg-type]
    out = server.corpus_summary()
    assert "error" in out


def test_corpus_summary_of_the_real_manifest_is_consistent() -> None:
    """Quand le manifeste est là, les comptes doivent se tenir entre eux."""
    out = server.corpus_summary()
    if "error" in out:
        pytest.skip("manifeste runner v6 absent de cette copie du dépôt")
    assert out["prompt_version"] == "v6"
    assert out["n_objects"] == len(out["objects"])
    assert out["n_images"] == sum(o["n_images"] for o in out["objects"])
    assert out["n_images_cached"] <= out["n_images"]
    assert all(o["n_cached"] <= o["n_images"] for o in out["objects"])
    assert {o["object_id"] for o in out["objects"]} and all(
        o["n_images"] > 0 for o in out["objects"]
    )


def test_last_run_is_absent_on_a_fresh_interface(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)  # type: ignore[arg-type]
    assert server.last_run_payload() == {"run": None}


def test_last_run_reports_a_readable_warning_on_a_corrupt_pointer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    runs = tmp_path / "ui-runs"
    runs.mkdir()
    (runs / "last-run.json").write_text("{}", encoding="utf-8")  # pas de run_id
    monkeypatch.setattr(server, "RUNS_DIR", runs)  # type: ignore[arg-type]
    out = server.last_run_payload()
    assert out["run"] is None and "warning" in out


# --------------------------------------------------------------------------- #
# Lecture de l'état du tunnel, et échec réseau propre
# --------------------------------------------------------------------------- #

def test_model_id_is_read_from_the_status_line() -> None:
    line = " OK  service reachable - model 'qwen2.5-vl-7b'"
    assert server._model_from_status(line) == "qwen2.5-vl-7b"


def test_model_id_is_absent_when_the_status_does_not_announce_one() -> None:
    assert server._model_from_status("listener : present") is None
    assert server._model_from_status("") is None


def test_unreachable_endpoint_is_a_verdict_not_an_exception() -> None:
    """Un port fermé doit produire « injoignable », pas une trace remontée à la page."""
    ok, detail = server.endpoint_answers("http://127.0.0.1:1/v1/chat/completions", timeout=1.0)
    assert ok is False
    assert detail


def test_state_exposes_the_contract_the_page_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """La page lit des clés précises : les renommer casserait un écran sans erreur."""
    monkeypatch.setattr(
        server, "tunnel_state",
        lambda: {"reachable": False, "exit_code": 1, "output": "", "model": None,
                 "command": "bash tunnel_vllm.sh status"},
    )
    state = server.Handler.state()
    assert set(state) >= {"repo", "python", "endpoint_default", "tunnel", "corpus",
                          "databases", "runs_dir", "served_at"}
    assert set(state["tunnel"]) == {"reachable", "exit_code", "output", "model", "command"}
