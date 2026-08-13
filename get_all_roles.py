"""Download released Blood on the Clocktower character metadata.

The official app data includes reminder labels and repeats a label when several
physical copies are required.  Keeping those repetitions is important for 3D
printing complete token sets.
"""

import json
from pathlib import Path

import requests


ROLES_URL = (
    "https://raw.githubusercontent.com/ThePandemoniumInstitute/"
    "botc-release/main/resources/data/roles.json"
)
CHARACTER_IMAGE_ROOT = "https://release.botc.app/resources/characters"

TEAM_COLORS = {
    "townsfolk": "blue",
    "outsider": "blue",
    "minion": "red",
    "demon": "red",
    "traveller": "purple",
    "fabled": "yellow",
    "loric": "green",
}


def character_image_url(role):
    """Return the official app's icon URL, including alignment when required."""
    suffix = ""
    if role["team"] in ("townsfolk", "outsider"):
        suffix = "_g"
    elif role["team"] in ("minion", "demon"):
        suffix = "_e"
    return f"{CHARACTER_IMAGE_ROOT}/{role['edition']}/{role['id']}{suffix}.webp"


def normalise_role(role):
    """Convert an official role record to the generator's compact schema."""
    team = role["team"]
    return {
        "id": role["id"],
        "edition": role.get("edition", "experimental"),
        "team": team,
        "image": character_image_url(role),
        "color": TEAM_COLORS.get(team, "unknown"),
        # Do not deduplicate: repeated labels mean repeated physical tokens.
        "reminders": list(role.get("reminders", [])),
    }


def fetch_roles(session=requests):
    response = session.get(ROLES_URL, timeout=30)
    response.raise_for_status()
    return {
        role["name"]: normalise_role(role)
        for role in response.json()
        if role.get("id") and role.get("name") and role.get("team")
    }


def main(output_path="roles.json"):
    roles = fetch_roles()
    output_path = Path(output_path)
    output_path.write_text(
        json.dumps(roles, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    reminder_count = sum(len(role["reminders"]) for role in roles.values())
    print(
        f"Wrote {len(roles)} characters and {reminder_count} reminder tokens "
        f"to {output_path}"
    )


if __name__ == "__main__":
    main()
