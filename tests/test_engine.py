from app.models import BuildInput
from app.services.engine import classify


def test_classify_power_armor_heavy_energy():
    assert classify(BuildInput()) == 'power_armor_heavy_energy'


def test_classify_bloodied_path():
    inp = BuildInput(primary_playstyle='Bloodied', primary_weapon_type='Rifle', preferred_weapons='Fixer')
    assert classify(inp) == 'bloodied_general'
