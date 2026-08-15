from io import BytesIO
import json
from unittest.mock import MagicMock, patch

from PIL import Image
import pytest
from solid import scad_render
import trimesh

import solid_maker


@pytest.fixture
def test_image_path(tmp_path):
    path = tmp_path / "test.png"
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(path)
    return path


def test_convert_png_to_greyscale_png(test_image_path, tmp_path):
    output = tmp_path / "gray.png"
    solid_maker.convert_png_to_greyscale_png(test_image_path, output)
    assert Image.open(output).mode == "L"


def test_felt_coin_model_supports_both_sizes():
    character = scad_render(solid_maker.felt_coin_model(45))
    reminder = scad_render(solid_maker.felt_coin_model(25))

    assert "d = 45" in character
    assert "h = 2" in character
    assert "d = 25" in reminder
    assert "h = 2" in reminder


def test_curved_text_spacing_adapts_generically_to_token_size(monkeypatch):
    monkeypatch.setattr(
        solid_maker,
        "get_relative_widths_pillow",
        lambda font, size, characters: {character: 1000 for character in characters},
    )

    label, character_steps = solid_maker.curved_text_layout("Dead", 45, 4)
    _, reminder_steps = solid_maker.curved_text_layout("Dead", 25, 3)
    reminder_label, reminder_case_steps = solid_maker.curved_text_layout(
        "Dead",
        25,
        3,
        solid_maker.REMINDER_FONT_FILE,
        uppercase=False,
        tracking_mm=0.54,
        max_angle=180,
    )
    _, long_steps = solid_maker.curved_text_layout("Final Night No Attack", 25, 2.1)

    assert label == "DEAD"
    assert reminder_label == "Dead"
    assert reminder_case_steps
    assert sum(reminder_steps) > sum(character_steps)
    assert sum(long_steps) == pytest.approx(210)


def test_character_tracking_matches_official_token_proportions(monkeypatch):
    monkeypatch.setattr(
        solid_maker,
        "get_relative_widths_pillow",
        lambda font, size, characters: {character: 600 for character in characters},
    )
    _, compact = solid_maker.curved_text_layout("Goblin", 45, 4, tracking_mm=0.4)
    _, official_style = solid_maker.curved_text_layout(
        "Goblin", 45, 4, tracking_mm=solid_maker.CHARACTER_TRACKING_MM
    )

    assert sum(official_style) > sum(compact)


def test_optical_centering_uses_visible_glyph_geometry(monkeypatch):
    key = solid_maker.glyph_outline_key(solid_maker.FONT, 4, 0.18, "A")
    monkeypatch.setitem(
        solid_maker.GLYPH_OUTLINES,
        key,
        solid_maker.np.array([[-1.0, 0.0], [2.0, 0.0]]),
    )

    correction = solid_maker.curved_text_optical_offset_x(
        "A", [], 45, 4, solid_maker.FONT, 0.18
    )

    assert correction == pytest.approx(-0.5)


def test_character_text_is_expanded_for_a_point_four_mm_nozzle(tmp_path):
    model = solid_maker.role_overlay_model("Goblin", tmp_path / "Goblin.svg")
    rendered = scad_render(model)

    assert "offset(r = 0.1800000000)" in rendered


def test_reminder_text_does_not_use_character_font_expansion(tmp_path):
    model = solid_maker.reminder_overlay_model("Dead", tmp_path / "Imp.svg")

    assert "offset(" not in scad_render(model)


@patch("solid_maker.requests.get")
def test_download_png_normalizes_webp(mock_get, tmp_path):
    content = BytesIO()
    Image.new("RGBA", (10, 10), "red").save(content, format="WEBP")
    response = MagicMock(content=content.getvalue())
    mock_get.return_value = response
    output = tmp_path / "download.png"

    solid_maker.download_png("https://example.test/icon.webp", output)

    response.raise_for_status.assert_called_once()
    assert Image.open(output).format == "PNG"


@patch("solid_maker.subprocess.run")
def test_convert_to_svg_uses_potrace_and_requested_size(
    mock_run, test_image_path, tmp_path
):
    output = tmp_path / "output.svg"
    solid_maker.convert_to_svg_with_potrace(test_image_path, output, 25)
    assert (tmp_path / "test.pbm").exists()
    command = mock_run.call_args.args[0]
    assert command[0].lower().endswith(("potrace", "potrace.exe"))
    assert command[-3:] == ["2.50cm", "-H", "2.50cm"]


def test_generate_reminders_preserves_duplicate_quantities(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for directory in ("scads/reminders", "stls/reminders"):
        (tmp_path / directory).mkdir(parents=True)
    rendered = []
    monkeypatch.setattr(solid_maker, "reminder_overlay_model", MagicMock())
    monkeypatch.setattr(
        solid_maker,
        "render_model",
        lambda model, scad, stl, **kwargs: not rendered.append((str(scad), str(stl))),
    )
    monkeypatch.setattr(
        solid_maker, "create_complete_token_files", lambda *args, **kwargs: 0
    )

    solid_maker.generate_reminders(
        "Shabaloth",
        {"color": "red", "reminders": ["Dead", "Dead", "Alive"]},
        "icon.svg",
    )

    names = [entry[1] for entry in rendered]
    assert any("Dead_01" in name for name in names)
    assert any("Dead_02" in name for name in names)
    assert any("Alive" in name for name in names)


def test_render_model_skips_existing_stl(tmp_path, monkeypatch):
    stl_path = tmp_path / "finished.stl"
    stl_path.write_bytes(b"completed")
    render = MagicMock()
    export = MagicMock()
    monkeypatch.setattr(solid_maker, "scad_render_to_file", render)
    monkeypatch.setattr(solid_maker, "export_coin_to_stl", export)

    created = solid_maker.render_model(MagicMock(), tmp_path / "token.scad", stl_path)

    assert created is False
    render.assert_not_called()
    export.assert_not_called()


@patch("solid_maker.subprocess.run")
def test_export_accepts_non_closed_intermediate_when_stl_exists(mock_run, tmp_path):
    stl_path = tmp_path / "usable.stl"

    def create_stl(*args, **kwargs):
        stl_path.write_bytes(b"solid token\nendsolid token\n")
        return MagicMock(
            returncode=0,
            stderr=b"ERROR: The given mesh is not closed! Unable to convert.\n",
        )

    mock_run.side_effect = create_stl
    solid_maker.export_coin_to_stl(MagicMock(), "token.scad", stl_path)
    assert stl_path.stat().st_size > 0


@patch("solid_maker.subprocess.run")
def test_export_rejects_other_openscad_errors(mock_run, tmp_path):
    stl_path = tmp_path / "incomplete.stl"

    def create_bad_stl(*args, **kwargs):
        stl_path.write_bytes(b"partial")
        return MagicMock(returncode=0, stderr=b"ERROR: Can't open file 'icon.svg'\n")

    mock_run.side_effect = create_bad_stl
    with pytest.raises(RuntimeError, match="Can't open file"):
        solid_maker.export_coin_to_stl(MagicMock(), "token.scad", stl_path)


def test_complete_outputs_include_base_and_declare_millimetres(tmp_path):
    base_path = tmp_path / "base.stl"
    overlay_path = tmp_path / "overlay.stl"
    complete_stl = tmp_path / "complete.stl"
    complete_3mf = tmp_path / "complete.3mf"
    base = trimesh.creation.cylinder(radius=12.5, height=2)
    base.apply_translation((0, 0, 1))
    overlay = trimesh.creation.box((8, 8, 0.2))
    overlay.apply_translation((0, 0, 1.9))
    base.export(base_path)
    overlay.export(overlay_path)

    generated = solid_maker.create_complete_token_files(
        base_path,
        overlay_path,
        complete_stl,
        complete_3mf,
        "Test token",
        "red",
    )

    completed_mesh = trimesh.load_mesh(complete_stl, process=True)
    assert generated == 2
    assert completed_mesh.extents == pytest.approx((25, 25, 2))
    wrapper = solid_maker.lib3mf.get_wrapper()
    model = wrapper.CreateModel()
    model.QueryReader("3mf").ReadFromFile(str(complete_3mf))
    assert model.GetUnit() == solid_maker.lib3mf.ModelUnit.MilliMeter
    assert model.GetMeshObjects().Count() == 2
    assert model.GetComponentsObjects().Count() == 1
    assert model.GetBuildItems().Count() == 1
    with solid_maker.ZipFile(complete_3mf) as archive:
        core_model = archive.read("3D/3dmodel.model").decode()
        model_settings = archive.read("Metadata/model_settings.config").decode()
        project_settings = json.loads(archive.read("Metadata/project_settings.config"))
    assert 'transform="1 0 0 0 -1 0 0 0 -1 0 0 1"' in core_model
    assert 'transform="1 0 0 0 1 0 0 0 1 0 0 0.9"' in core_model
    assert 'key="extruder" value="1"' in model_settings
    assert 'key="extruder" value="2"' in model_settings
    assert project_settings["filament_colour"] == ["#141414", "#8C0E12"]


def test_roles_json_reminder_arrays_are_not_deduplicated(tmp_path):
    data = {
        "Shabaloth": {
            "color": "red",
            "reminders": ["Dead", "Dead", "Alive"],
        }
    }
    path = tmp_path / "roles.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert json.loads(path.read_text())["Shabaloth"]["reminders"].count("Dead") == 2
