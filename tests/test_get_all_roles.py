from unittest.mock import MagicMock

import get_all_roles


def test_normalise_role_keeps_duplicate_reminders():
    role = {
        "id": "shabaloth",
        "name": "Shabaloth",
        "edition": "bmr",
        "team": "demon",
        "reminders": ["Dead", "Dead", "Alive"],
    }
    result = get_all_roles.normalise_role(role)
    assert result["color"] == "red"
    assert result["reminders"] == ["Dead", "Dead", "Alive"]
    assert result["image"].endswith("/bmr/shabaloth_e.webp")


def test_fetch_roles_uses_official_data():
    response = MagicMock()
    response.json.return_value = [
        {
            "id": "washerwoman",
            "name": "Washerwoman",
            "edition": "tb",
            "team": "townsfolk",
            "reminders": ["Townsfolk", "Wrong"],
        }
    ]
    session = MagicMock()
    session.get.return_value = response

    result = get_all_roles.fetch_roles(session)

    response.raise_for_status.assert_called_once()
    assert result["Washerwoman"]["reminders"] == ["Townsfolk", "Wrong"]
    assert result["Washerwoman"]["image"].endswith("/tb/washerwoman_g.webp")
