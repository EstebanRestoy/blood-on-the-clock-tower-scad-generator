"""Generate character and reminder token SCAD/STL files."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

import requests
from PIL import Image, ImageFont
from solid import cylinder, import_, linear_extrude, rotate, scad_render_to_file, scale
from solid import text as scad_text
from solid import translate, union


# Dimensional constants in mm. Character tokens are intentionally compatible
# with the original project's 45 mm design; reminders use the usual small size.
COIN_DIAMETER = 45
REMINDER_DIAMETER = 25
COIN_HEIGHT = 2
ROLE_EXTRUDE_DEPTH = 0.2
FONT = "Dumbledor 1 Fixed"
FONT_FILE = "assets/Dumbledor1_fixed.ttf"
TEXT_SIZE = 4
REMINDER_TEXT_SIZE = 3


def find_executable(name):
    """Find a dependency on PATH or in the project's local tool directory."""
    executable = shutil.which(name)
    if executable:
        return executable
    candidates = {
        "potrace": [Path(".tools/potrace/potrace.exe")],
        "openscad": [Path("C:/Program Files/OpenSCAD/openscad.exe")],
    }
    for candidate in candidates.get(name, []):
        if candidate.exists():
            return str(candidate.resolve())
    raise FileNotFoundError(
        f"Required executable '{name}' was not found. See README.md."
    )


def safe_filename(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return value.strip("_") or "token"


def get_relative_widths_pillow(font_path, font_size, characters):
    """Return the rendered width of every character in ``characters``."""
    try:
        font = ImageFont.truetype(font_path, font_size)
    except OSError:
        print(f"Error: Font file not found at {font_path}")
        return {}

    return {char: font.getbbox(char)[2] for char in characters}


def felt_coin_model(diameter=COIN_DIAMETER):
    """Create the base below the 0.2 mm inlay/overlay layer."""
    return cylinder(d=diameter, h=COIN_HEIGHT - ROLE_EXTRUDE_DEPTH)


def curved_text_model(label, diameter, text_size):
    """Lay out a label along the lower edge of a token."""
    printed_label = label.upper()
    widths = get_relative_widths_pillow(
        FONT_FILE, max(1, round(text_size * 5)), printed_label
    )
    if not widths:
        raise RuntimeError(f"Unable to load token font: {FONT_FILE}")
    widths[" "] = max(widths.get(" ", 0), round(text_size * 3.5))

    steps = [
        (widths[left] + widths[right]) / 2
        for left, right in zip(printed_label, printed_label[1:], strict=False)
    ]
    # Long reminder labels are compressed around the arc instead of spilling
    # onto the upper half of the token.
    total_angle = sum(steps)
    angle_scale = min(1.0, 210 / total_angle) if total_angle else 1.0
    steps = [step * angle_scale for step in steps]

    angle = 270 - sum(steps) / 2
    radius = diameter / 2 - max(1.5, text_size / 2)
    parts = []
    for index, char in enumerate(printed_label):
        if index:
            angle += steps[index - 1]
        x = radius * math.cos(math.radians(angle))
        y = radius * math.sin(math.radians(angle))
        character = scad_text(
            char,
            font=FONT,
            size=text_size,
            halign="center",
            valign="bottom",
        )
        character_3d = linear_extrude(height=ROLE_EXTRUDE_DEPTH)(character)
        parts.append(
            translate((x, y, COIN_HEIGHT - ROLE_EXTRUDE_DEPTH))(
                rotate(a=angle + 90, v=[0, 0, 1])(character_3d)
            )
        )
    return union()(*parts)


def token_overlay_model(label, svg_filename, diameter, text_size, icon_scale=1.0):
    """Create the icon and text body used as the token's second colour."""
    # SCAD files live in nested output directories. An absolute POSIX-style
    # path keeps OpenSCAD imports valid on Windows as well as Unix.
    svg_path = Path(svg_filename).resolve().as_posix()
    svg_shape = import_(svg_path, convexity=10)
    centered_svg = scale((icon_scale, icon_scale, 1))(
        translate((-diameter / 2, -diameter / 2, 0))(svg_shape)
    )
    extruded_svg = linear_extrude(height=ROLE_EXTRUDE_DEPTH)(centered_svg)
    extruded_svg = translate((0, 0, COIN_HEIGHT - ROLE_EXTRUDE_DEPTH))(extruded_svg)
    return extruded_svg + curved_text_model(label, diameter, text_size)


def role_overlay_model(role_name, svg_filename):
    """Create a 45 mm character-token overlay."""
    return token_overlay_model(role_name, svg_filename, COIN_DIAMETER, TEXT_SIZE)


def reminder_overlay_model(reminder_label, svg_filename):
    """Create a 25 mm reminder-token overlay."""
    size = REMINDER_TEXT_SIZE
    if len(reminder_label) > 18:
        size = 2.1
    elif len(reminder_label) > 12:
        size = 2.5
    return token_overlay_model(
        reminder_label, svg_filename, REMINDER_DIAMETER, size, icon_scale=0.72
    )


def download_png(url, filename):
    """Download an image and normalize it to an RGBA PNG."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    image = Image.open(BytesIO(response.content)).convert("RGBA")
    image.save(filename, format="PNG")
    print(f"Downloaded {filename}")


def convert_png_to_greyscale_png(png_path, greyscale_png_path):
    """Composite transparency on white and save a grayscale image."""
    image = Image.open(png_path).convert("RGBA")
    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
    composite = Image.alpha_composite(background, image)
    composite.convert("L").save(greyscale_png_path)


def convert_to_svg_with_potrace(png_path, svg_path, diameter=COIN_DIAMETER):
    """Threshold an image with Pillow and vectorize it with Potrace."""
    pbm_path = str(Path(png_path).with_suffix(".pbm"))
    image = Image.open(png_path).convert("L")
    # Pillow writes a valid monochrome PBM, avoiding ImageMagick's conflicting
    # ``convert`` executable on Windows.
    image.point(lambda pixel: 0 if pixel < 128 else 255, mode="1").save(pbm_path)
    dimension = f"{diameter / 10:.2f}cm"
    subprocess.run(
        [
            find_executable("potrace"),
            pbm_path,
            "-o",
            str(svg_path),
            "--svg",
            "-W",
            dimension,
            "-H",
            dimension,
        ],
        check=True,
        capture_output=True,
    )


def export_coin_to_stl(model, scad_filename="coin.scad", stl_filename="coin.stl"):
    """Render an existing SCAD file to STL with OpenSCAD."""
    stl_path = Path(stl_filename)
    stl_path.unlink(missing_ok=True)
    result = subprocess.run(
        [find_executable("openscad"), "-o", str(stl_path), str(scad_filename)],
        capture_output=True,
    )
    stderr = result.stderr.decode(errors="replace")
    if result.returncode or "ERROR:" in stderr or not stl_path.exists():
        raise RuntimeError(stderr or "OpenSCAD failed to create the STL")


def render_model(model, scad_path, stl_path, force=False):
    """Render one model, or reuse an existing non-empty STL."""
    stl_path = Path(stl_path)
    if not force and stl_path.exists() and stl_path.stat().st_size > 0:
        return False
    scad_render_to_file(model, str(scad_path), file_header="$fn=100;")
    export_coin_to_stl(model, scad_path, stl_path)
    return True


def prepare_role_icon(role_name, data):
    role_safe = safe_filename(role_name)
    png_path = Path("pngs") / f"{role_safe}.png"
    gray_path = Path("grey_pngs") / f"{role_safe}.png"
    character_svg = Path("svgs") / f"{role_safe}_character.svg"
    reminder_svg = Path("svgs") / f"{role_safe}_reminder.svg"

    if not png_path.exists():
        download_png(data["image"], png_path)
    convert_png_to_greyscale_png(png_path, gray_path)
    if not character_svg.exists():
        convert_to_svg_with_potrace(gray_path, character_svg, COIN_DIAMETER)
    if data.get("reminders") and not reminder_svg.exists():
        convert_to_svg_with_potrace(gray_path, reminder_svg, REMINDER_DIAMETER)
    return character_svg, reminder_svg


def generate_character(role_name, data, svg_path):
    role_safe = safe_filename(role_name)
    overlay = role_overlay_model(role_name, svg_path)
    return int(
        render_model(
            overlay,
            Path("scads/characters") / f"{role_safe}_overlay.scad",
            Path("stls/characters") / f"{data['color']}_{role_safe}_overlay.stl",
        )
    )


def generate_reminders(role_name, data, svg_path):
    role_safe = safe_filename(role_name)
    totals = {}
    generated = 0
    for label in data.get("reminders", []):
        totals[label] = totals.get(label, 0) + 1

    seen = {}
    for label in data.get("reminders", []):
        seen[label] = seen.get(label, 0) + 1
        suffix = f"_{seen[label]:02d}" if totals[label] > 1 else ""
        token_name = f"{role_safe}__{safe_filename(label)}{suffix}"
        overlay = reminder_overlay_model(label, svg_path)
        generated += int(
            render_model(
                overlay,
                Path("scads/reminders") / f"{token_name}_overlay.scad",
                Path("stls/reminders") / f"{data['color']}_{token_name}_overlay.stl",
            )
        )
    return generated


def generate_role(role_name, data, target):
    """Generate all requested files for one role; safe to run in a worker."""
    character_svg, reminder_svg = prepare_role_icon(role_name, data)
    generated = 0
    if target in ("all", "characters"):
        generated += generate_character(role_name, data, character_svg)
    if target in ("all", "reminders") and data.get("reminders"):
        generated += generate_reminders(role_name, data, reminder_svg)
    return generated


def main(target="all", role_filter=None, jobs=1):
    roles = json.loads(Path("roles.json").read_text(encoding="utf-8"))
    for directory in (
        "pngs",
        "grey_pngs",
        "svgs",
        "scads/characters",
        "scads/reminders",
        "stls/characters",
        "stls/reminders",
    ):
        Path(directory).mkdir(parents=True, exist_ok=True)

    if target in ("all", "characters"):
        render_model(
            felt_coin_model(COIN_DIAMETER),
            Path("scads/character_base.scad"),
            Path("stls/character_base.stl"),
        )
    if target in ("all", "reminders"):
        render_model(
            felt_coin_model(REMINDER_DIAMETER),
            Path("scads/reminder_base.scad"),
            Path("stls/reminder_base.stl"),
        )

    selected_roles = [
        (role_name, data)
        for role_name, data in roles.items()
        if (not role_filter or role_name.casefold() == role_filter.casefold())
        and (target != "reminders" or data.get("reminders"))
    ]
    if role_filter and not selected_roles:
        raise ValueError(f"No matching role with requested output: {role_filter}")

    completed = 0
    generated = 0
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(generate_role, role_name, data, target): role_name
            for role_name, data in selected_roles
        }
        for future in as_completed(futures):
            role_name = futures[future]
            generated += future.result()
            completed += 1
            print(
                f"[{completed}/{len(selected_roles)}] {role_name} "
                f"({generated} new STL files)"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        choices=("all", "characters", "reminders"),
        default="all",
        help="Select which token family to generate (default: all).",
    )
    parser.add_argument(
        "--role",
        help="Generate only one role (case-insensitive), useful for test prints.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        metavar="N",
        help="Run N roles in parallel (recommended on most computers: 4).",
    )
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    main(args.target, args.role, args.jobs)
