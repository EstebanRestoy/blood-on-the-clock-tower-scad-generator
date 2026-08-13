from io import BytesIO
import json
from unittest.mock import MagicMock, patch

from PIL import Image
import pytest
from solid import scad_render

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
    assert "cylinder" in str(solid_maker.felt_coin_model(45))
    assert "d = 25" in scad_render(solid_maker.felt_coin_model(25))


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
        lambda model, scad, stl: rendered.append((str(scad), str(stl))),
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
