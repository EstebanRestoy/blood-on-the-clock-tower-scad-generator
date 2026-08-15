import json
from zipfile import ZipFile
from xml.etree import ElementTree

import lib3mf
import trimesh

import print_set_maker


def test_split_edition_roles_keeps_travellers_optional():
    roles = {
        "Chef": {"edition": "tb", "team": "townsfolk"},
        "Imp": {"edition": "tb", "team": "demon"},
        "Thief": {"edition": "tb", "team": "traveller"},
        "Clockmaker": {"edition": "snv", "team": "townsfolk"},
    }

    core, travellers = print_set_maker.split_edition_roles(roles, "tb")

    assert [name for name, _ in core] == ["Chef", "Imp"]
    assert [name for name, _ in travellers] == ["Thief"]


def test_reminder_stems_preserve_duplicate_copies():
    reminders = list(
        print_set_maker.reminder_stems(
            "Shabaloth", {"color": "red", "reminders": ["Dead", "Dead"]}
        )
    )

    assert reminders == [
        ("Dead", "red_Shabaloth__Dead_01"),
        ("Dead", "red_Shabaloth__Dead_02"),
    ]


def test_trouble_brewing_project_contains_four_imps():
    token = print_set_maker.PrintToken(
        name="Imp",
        stem="red_Imp",
        family="characters",
        color="red",
        team="demon",
        source_3mf=None,
        base_stl=None,
        overlay_stl=None,
    )

    expanded = print_set_maker.expand_project_quantities([token], "tb")

    assert [entry.name for entry in expanded] == [
        "Imp",
        "Imp (copy 2)",
        "Imp (copy 3)",
        "Imp (copy 4)",
    ]


def test_bambu_project_contains_multiple_named_plates(tmp_path):
    base = trimesh.creation.cylinder(radius=12.5, height=2)
    base.apply_translation((0, 0, 1))
    overlay = trimesh.creation.box((4, 4, 0.2))
    overlay.apply_translation((0, 0, 1.9))
    base_path = tmp_path / "base.stl"
    overlay_path = tmp_path / "overlay.stl"
    base.export(base_path)
    overlay.export(overlay_path)
    source = tmp_path / "source.3mf"
    source.write_bytes(b"unused")
    tokens = [
        print_set_maker.PrintToken(
            name="Test character",
            stem="blue_Test",
            family="characters",
            color="blue",
            team="townsfolk",
            source_3mf=source,
            base_stl=base_path,
            overlay_stl=overlay_path,
        ),
        print_set_maker.PrintToken(
            name="Test reminder",
            stem="red_Test__Dead",
            family="tokens",
            color="red",
            team="demon",
            source_3mf=source,
            base_stl=base_path,
            overlay_stl=overlay_path,
        ),
    ]
    output = tmp_path / "project.3mf"

    plates = print_set_maker.create_bambu_project(tokens, output)

    assert [name for name, _ in plates] == ["Characters 1", "Tokens 1"]
    wrapper = lib3mf.get_wrapper()
    model = wrapper.CreateModel()
    model.QueryReader("3mf").ReadFromFile(str(output))
    assert model.GetUnit() == lib3mf.ModelUnit.MilliMeter
    assert model.GetMeshObjects().Count() == 4
    assert model.GetComponentsObjects().Count() == 2
    assert model.GetBuildItems().Count() == 2
    with ZipFile(output) as archive:
        core = ElementTree.fromstring(archive.read("3D/3dmodel.model"))
        config = ElementTree.fromstring(
            archive.read("Metadata/model_settings.config")
        )
        settings = json.loads(archive.read("Metadata/project_settings.config"))
    assert [
        node.get("value")
        for node in config.findall('./plate/metadata[@key="plater_name"]')
    ] == ["Characters 1", "Tokens 1"]
    namespace = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    x_positions = [
        float(item.get("transform").split()[9])
        for item in core.findall(".//m:build/m:item", namespace)
    ]
    assert x_positions == [30, 20 + print_set_maker.PLATE_SIZE_MM]
    assert settings["printer_settings_id"] == "Bambu Lab X2D 0.4 nozzle"
