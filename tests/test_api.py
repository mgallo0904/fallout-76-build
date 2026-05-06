import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_archetypes_endpoint_lists_2026_meta():
    response = client.get("/api/archetypes")
    assert response.status_code == 200
    ids = {a["id"] for a in response.json()}
    assert ids >= {
        "power_armor_heavy_energy",
        "bullet_storm_heavy",
        "onslaught_commando",
        "rifleman",
        "shotgunner",
        "gunslinger",
        "melee",
        "playable_ghoul",
        "bow_stealth",
        "cremator_pyro",
        "pepper_shaker_stealth",
        "ghoul_commando",
        "ghoul_melee",
    }


def test_archetype_preview_endpoint():
    response = client.get("/api/archetypes/bow_stealth")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "bow_stealth"
    assert payload["name"] == "Bow Stealth Sniper"
    assert sum(payload["special_allocation"].values()) <= 56
    assert any(p["card_id"] == "rifleman" for p in payload["perk_picks"])


def test_archetype_preview_404():
    response = client.get("/api/archetypes/does_not_exist")
    assert response.status_code == 404


def test_legendary_perk_detail_endpoint():
    response = client.get("/api/legendary-perks/taking_one_for_the_team")
    assert response.status_code == 200
    assert response.json()["name"] == "Taking One for the Team"


def test_brain_research_returns_enabled_true_or_503():
    response = client.post("/api/brain/research", json={"query": "fallout 76 april 2026 patch", "max_results": 3})
    assert response.status_code in {200, 503}
    if response.status_code == 200:
        body = response.json()
        assert body["enabled"] is True
        assert body["search_results"] == []


def test_perks_endpoint_filters_deprecated_by_default():
    active = client.get("/api/perks").json()
    full = client.get("/api/perks?include_deprecated=true").json()
    assert all(p["status"] == "verified" for p in active)
    assert len(full) > len(active)


def test_legendary_perks_endpoint():
    payload = client.get("/api/legendary-perks").json()
    assert any(p["id"] == "taking_one_for_the_team" for p in payload)
    assert {p["id"] for p in payload if "ghoul_only" in p["tags"]} == {"action_diet", "feral_rage"}
    assert all(p["id"] != "glowing_one" for p in payload)


def test_perks_endpoint_includes_regular_glowing_one():
    payload = client.get("/api/perks").json()
    glowing_one = next(p for p in payload if p["id"] == "glowing_one")
    assert glowing_one["special"] == "Charisma"
    assert "ghoul_only" in glowing_one["tags"]


def test_generate_and_get_build_default_is_pa_heavy_energy():
    response = client.post("/api/build/generate", json={})
    assert response.status_code == 200
    build = response.json()
    assert build["build_name"] == "Power Armor Heavy Energy Gunner"
    fetched = client.get(f"/api/build/{build['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == build["id"]


def test_generate_build_without_brain_env_uses_deterministic_engine(monkeypatch):
    monkeypatch.delenv("USE_OLLAMA_BRAIN", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    response = client.post("/api/build/generate", json={})
    assert response.status_code == 200
    build = response.json()
    assert build["logic_engine"] == "deterministic"
    assert build["brain_confirmed"] is False


def test_generate_build_with_api_key_uses_brain(monkeypatch):
    monkeypatch.delenv("USE_OLLAMA_BRAIN", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    response = client.post("/api/build/generate", json={})
    assert response.status_code == 200
    build = response.json()
    assert build["logic_engine"].startswith("ollama:")
    assert build["brain_confirmed"] is True


def test_compare_endpoint_accepts_build_ids_object():
    a = client.post("/api/build/generate", json={"primary_playstyle": "Commando", "primary_weapon_type": "Auto rifle", "armor_type": "Regular armor", "combat_style": "VATS"}).json()
    b = client.post("/api/build/generate", json={"primary_playstyle": "Power Armor Heavy", "primary_weapon_type": "Heavy energy"}).json()
    response = client.post("/api/build/compare", json={"build_ids": [a["id"], b["id"]]})
    assert response.status_code == 200
    payload = response.json()
    assert set(payload["build_ids"]) == {a["id"], b["id"]}


def test_validate_endpoint_returns_list():
    build = client.post("/api/build/generate", json={}).json()
    response = client.post("/api/build/validate", json=build)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_admin_export_then_import_round_trip():
    exported = client.get("/api/admin/export/sources").json()
    assert isinstance(exported, list)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(exported, fh)
        tmp_path = Path(fh.name)
    with tmp_path.open("rb") as binary:
        response = client.post(
            "/api/admin/import/sources",
            files={"file": ("sources.json", binary, "application/json")},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] == len(exported)


def test_admin_import_rejects_invalid_payload_type():
    response = client.post(
        "/api/admin/import/sources",
        files={"file": ("sources.json", b'{"bad": true}', "application/json")},
    )
    assert response.status_code == 400
    assert "Payload must be a JSON list" in response.text


def test_brain_status_hides_api_key(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "secret-value")
    monkeypatch.setenv("USE_OLLAMA_BRAIN", "1")
    response = client.get("/api/brain/status")
    assert response.status_code == 200
    body = response.json()
    assert body["has_api_key"] is True
    assert "secret-value" not in response.text


def test_perks_pagination():
    full = client.get("/api/perks").json()
    page = client.get("/api/perks?limit=5").json()
    assert len(page) == 5
    assert page == full[:5]
    page2 = client.get("/api/perks?limit=5&offset=5").json()
    assert page2 == full[5:10]


def test_legendary_perks_pagination():
    full = client.get("/api/legendary-perks").json()
    page = client.get("/api/legendary-perks?limit=3").json()
    assert len(page) == min(3, len(full))
    assert page == full[:3]


def test_generate_build_brain_error_returns_503(monkeypatch):
    from app.services import brain as brain_module
    from app import main as main_module

    def boom(_user_input):
        raise main_module.BrainError("simulated brain outage")

    monkeypatch.setattr(main_module, "generate_and_refine_build", boom)
    response = client.post("/api/build/generate", json={})
    assert response.status_code == 503
    assert "simulated brain outage" in response.text


def test_admin_import_partial_success_returns_207():
    valid = client.get("/api/admin/export/sources").json()[:1]
    payload = valid + [{"id": "broken", "not": "valid"}]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(payload, fh)
        tmp_path = Path(fh.name)
    with tmp_path.open("rb") as binary:
        response = client.post(
            "/api/admin/import/sources",
            files={"file": ("sources.json", binary, "application/json")},
        )
    assert response.status_code == 207
    body = response.json()
    assert body["imported"] == 1
    assert body["errors"]


def test_brain_search_without_brain_returns_empty_or_503():
    response = client.post("/api/brain/search", json={"query": "fallout 76 patch", "max_results": 3})
    assert response.status_code in {200, 503}
    if response.status_code == 200:
        assert response.json() == []
