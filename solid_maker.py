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
import tempfile
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

import requests
import lib3mf
from PIL import Image, ImageFont
from solid import cylinder, import_, linear_extrude, rotate, scad_render_to_file, scale
from solid import text as scad_text
from solid import translate, union
import trimesh


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

BASE_COLOR = (20, 20, 20, 255)
OVERLAY_COLORS = {
    "blue": (50, 151, 244, 255),
    "red": (140, 14, 18, 255),
    "purple": (128, 0, 128, 255),
    "yellow": (212, 175, 55, 255),
    "green": (63, 150, 81, 255),
    "unknown": (80, 80, 80, 255),
}


def color_to_hex(color):
    return "#{:02X}{:02X}{:02X}".format(*color[:3])


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


def curved_text_layout(label, diameter, text_size):
    """Return the normalized label and generic angular spacing for its glyphs."""
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
    # The same glyph width needs a larger angle on a smaller token. Without
    # this radius compensation, reminder letters overlap one another.
    radius_compensation = COIN_DIAMETER / diameter
    steps = [step * radius_compensation for step in steps]
    total_angle = sum(steps)
    fit_scale = min(1.0, 210 / total_angle) if total_angle else 1.0
    steps = [step * fit_scale for step in steps]
    return printed_label, steps


def curved_text_model(label, diameter, text_size):
    """Lay out a label along the lower edge of a token."""
    printed_label, steps = curved_text_layout(label, diameter, text_size)

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


def token_overlay_model(
    label, svg_filename, diameter, text_size, icon_scale=1.0, icon_offset_y=0
):
    """Create the icon and text body used as the token's second colour."""
    # SCAD files live in nested output directories. An absolute POSIX-style
    # path keeps OpenSCAD imports valid on Windows as well as Unix.
    svg_path = Path(svg_filename).resolve().as_posix()
    svg_shape = import_(svg_path, convexity=10)
    centered_svg = translate((0, icon_offset_y, 0))(
        scale((icon_scale, icon_scale, 1))(
            translate((-diameter / 2, -diameter / 2, 0))(svg_shape)
        )
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
        reminder_label,
        svg_filename,
        REMINDER_DIAMETER,
        size,
        icon_scale=0.58,
        icon_offset_y=1.5,
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
    error_lines = [line for line in stderr.splitlines() if "ERROR:" in line]
    fatal_errors = [
        line for line in error_lines if "The given mesh is not closed!" not in line
    ]
    output_exists = stl_path.exists() and stl_path.stat().st_size > 0
    if result.returncode or fatal_errors or not output_exists:
        raise RuntimeError(stderr or "OpenSCAD failed to create the STL")
    if error_lines:
        print(
            f"Warning: OpenSCAD reported a non-closed intermediate mesh for "
            f"{stl_path.name}; the exported STL is present and usable."
        )


def render_model(model, scad_path, stl_path, force=False):
    """Render one model, or reuse an existing non-empty STL."""
    stl_path = Path(stl_path)
    if not force and stl_path.exists() and stl_path.stat().st_size > 0:
        return False
    scad_render_to_file(model, str(scad_path), file_header="$fn=100;")
    export_coin_to_stl(model, scad_path, stl_path)
    return True


def add_3mf_mesh(model, mesh, name, materials, material_index):
    """Add one trimesh body to a lib3mf model with an object-level material."""
    mesh_object = model.AddMeshObject()
    mesh_object.SetName(name)
    vertices = [lib3mf.Position(tuple(vertex)) for vertex in mesh.vertices]
    triangles = [
        lib3mf.Triangle(tuple(int(index) for index in face)) for face in mesh.faces
    ]
    mesh_object.SetGeometry(vertices, triangles)
    mesh_object.SetObjectLevelProperty(materials.GetResourceID(), material_index)
    return mesh_object


def add_xml_metadata(parent, key, value):
    ElementTree.SubElement(parent, "metadata", key=key, value=str(value))


def inject_bambu_metadata(
    path,
    token_name,
    base_object_id,
    overlay_object_id,
    assembly_object_id,
    base_faces,
    overlay_faces,
    overlay_color,
):
    """Add Bambu/Orca extruder assignments to an otherwise standard 3MF."""
    config = ElementTree.Element("config")
    object_node = ElementTree.SubElement(config, "object", id=str(assembly_object_id))
    add_xml_metadata(object_node, "name", token_name)
    add_xml_metadata(object_node, "extruder", "1")
    ElementTree.SubElement(
        object_node, "metadata", face_count=str(base_faces + overlay_faces)
    )

    identity = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
    for object_id, part_name, extruder, face_count in (
        (base_object_id, "Token base", 1, base_faces),
        (overlay_object_id, "Icon and text", 2, overlay_faces),
    ):
        part = ElementTree.SubElement(
            object_node, "part", id=str(object_id), subtype="normal_part"
        )
        add_xml_metadata(part, "name", part_name)
        add_xml_metadata(part, "matrix", identity)
        source_name = Path(path).name.replace(".tmp.3mf", ".3mf")
        add_xml_metadata(part, "source_file", source_name)
        add_xml_metadata(part, "source_object_id", "0")
        add_xml_metadata(part, "source_volume_id", "0")
        add_xml_metadata(part, "source_offset_x", "0")
        add_xml_metadata(part, "source_offset_y", "0")
        add_xml_metadata(part, "source_offset_z", "0")
        add_xml_metadata(part, "extruder", extruder)
        ElementTree.SubElement(
            part,
            "mesh_stat",
            face_count=str(face_count),
            edges_fixed="0",
            degenerate_facets="0",
            facets_removed="0",
            facets_reversed="0",
            backwards_edges="0",
        )

    plate = ElementTree.SubElement(config, "plate")
    add_xml_metadata(plate, "plater_id", "1")
    add_xml_metadata(plate, "plater_name", token_name)
    add_xml_metadata(plate, "locked", "false")
    add_xml_metadata(plate, "filament_map_mode", "Auto For Quality")
    add_xml_metadata(plate, "filament_maps", "1 2")
    add_xml_metadata(plate, "filament_volume_maps", "1 1")
    instance = ElementTree.SubElement(plate, "model_instance")
    add_xml_metadata(instance, "object_id", assembly_object_id)
    add_xml_metadata(instance, "instance_id", "0")
    add_xml_metadata(instance, "identify_id", "1")

    model_settings = ElementTree.tostring(
        config, encoding="utf-8", xml_declaration=True
    )
    filament_colors = [color_to_hex(BASE_COLOR), color_to_hex(overlay_color)]
    project_settings = json.dumps(
        {
            "name": "project_settings",
            "filament_colour": filament_colors,
            "filament_multi_colour": filament_colors,
            "filament_type": ["PLA", "PLA"],
            "filament_settings_id": ["Generic PLA", "Generic PLA"],
            "filament_ids": ["", ""],
            "filament_vendor": ["Generic", "Generic"],
            "filament_diameter": ["1.75", "1.75"],
            "filament_density": ["1.24", "1.24"],
            "filament_cost": ["20", "20"],
            "filament_flow_ratio": ["1", "1"],
            "filament_max_volumetric_speed": ["12", "12"],
            "filament_is_support": ["0", "0"],
            "filament_soluble": ["0", "0"],
            "filament_start_gcode": ["", ""],
            "filament_end_gcode": ["", ""],
            "filament_minimal_purge_on_wipe_tower": ["15", "15"],
            "filament_prime_volume": ["45", "45"],
            "filament_map": ["1", "2"],
            "flush_volumes_matrix": ["0", "120", "120", "0"],
            "flush_multiplier": "1",
            "single_extruder_multi_material": "1",
        },
        indent=2,
    ).encode("utf-8")

    path = Path(path)
    temporary = tempfile.NamedTemporaryFile(
        prefix=f"{path.stem}_", suffix=".3mf", dir=path.parent, delete=False
    )
    temporary_path = Path(temporary.name)
    temporary.close()
    metadata_names = {
        "Metadata/model_settings.config",
        "Metadata/project_settings.config",
    }
    try:
        with (
            ZipFile(path, "r") as source,
            ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as destination,
        ):
            for info in source.infolist():
                if info.filename not in metadata_names:
                    destination.writestr(info, source.read(info.filename))
            destination.writestr(
                "Metadata/model_settings.config", model_settings, ZIP_DEFLATED
            )
            destination.writestr(
                "Metadata/project_settings.config", project_settings, ZIP_DEFLATED
            )
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def create_complete_token_files(
    base_stl,
    overlay_stl,
    complete_stl,
    complete_3mf,
    token_name,
    color_name,
    force=False,
):
    """Create a fused STL and an assembled two-part, millimetre-aware 3MF."""
    complete_stl = Path(complete_stl)
    complete_3mf = Path(complete_3mf)
    outputs_missing = (
        [complete_stl, complete_3mf]
        if force
        else [
            path
            for path in (complete_stl, complete_3mf)
            if not path.exists() or path.stat().st_size == 0
        ]
    )
    if not outputs_missing:
        return 0

    base_mesh = trimesh.load_mesh(base_stl, process=True)
    overlay_mesh = trimesh.load_mesh(overlay_stl, process=True)
    generated = 0

    if complete_stl in outputs_missing:
        complete_stl.parent.mkdir(parents=True, exist_ok=True)
        combined = trimesh.util.concatenate((base_mesh, overlay_mesh))
        temporary_stl = complete_stl.with_suffix(".tmp.stl")
        combined.export(temporary_stl, file_type="stl")
        temporary_stl.replace(complete_stl)
        generated += 1

    if complete_3mf in outputs_missing:
        complete_3mf.parent.mkdir(parents=True, exist_ok=True)
        wrapper = lib3mf.get_wrapper()
        model = wrapper.CreateModel()
        model.SetUnit(lib3mf.ModelUnit.MilliMeter)
        materials = model.AddBaseMaterialGroup()
        base_material = materials.AddMaterial("Token base", lib3mf.Color(*BASE_COLOR))
        overlay_color = OVERLAY_COLORS.get(color_name, OVERLAY_COLORS["unknown"])
        overlay_material = materials.AddMaterial(
            f"{color_name.title()} overlay", lib3mf.Color(*overlay_color)
        )
        base_object = add_3mf_mesh(
            model, base_mesh, "Token base", materials, base_material
        )
        overlay_object = add_3mf_mesh(
            model, overlay_mesh, "Icon and text", materials, overlay_material
        )
        assembly = model.AddComponentsObject()
        assembly.SetName(token_name)
        identity = wrapper.GetIdentityTransform()
        assembly.AddComponent(base_object, identity)
        assembly.AddComponent(overlay_object, identity)
        model.AddBuildItem(assembly, identity)
        temporary_3mf = complete_3mf.with_suffix(".tmp.3mf")
        model.QueryWriter("3mf").WriteToFile(str(temporary_3mf))
        inject_bambu_metadata(
            temporary_3mf,
            token_name,
            base_object.GetResourceID(),
            overlay_object.GetResourceID(),
            assembly.GetResourceID(),
            len(base_mesh.faces),
            len(overlay_mesh.faces),
            overlay_color,
        )
        temporary_3mf.replace(complete_3mf)
        generated += 1

    return generated


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


def generate_character(role_name, data, svg_path, force=False):
    role_safe = safe_filename(role_name)
    overlay = role_overlay_model(role_name, svg_path)
    overlay_stl = Path("stls/characters") / f"{data['color']}_{role_safe}_overlay.stl"
    generated = int(
        render_model(
            overlay,
            Path("scads/characters") / f"{role_safe}_overlay.scad",
            overlay_stl,
            force=force,
        )
    )
    complete_name = f"{data['color']}_{role_safe}"
    generated += create_complete_token_files(
        Path("stls/character_base.stl"),
        overlay_stl,
        Path("stls/characters_complete") / f"{complete_name}.stl",
        Path("3mf/characters") / f"{complete_name}.3mf",
        role_name,
        data["color"],
        force=force,
    )
    return generated


def generate_reminders(role_name, data, svg_path, force=False):
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
        overlay_stl = (
            Path("stls/reminders") / f"{data['color']}_{token_name}_overlay.stl"
        )
        generated += int(
            render_model(
                overlay,
                Path("scads/reminders") / f"{token_name}_overlay.scad",
                overlay_stl,
                force=force,
            )
        )
        complete_name = f"{data['color']}_{token_name}"
        generated += create_complete_token_files(
            Path("stls/reminder_base.stl"),
            overlay_stl,
            Path("stls/reminders_complete") / f"{complete_name}.stl",
            Path("3mf/reminders") / f"{complete_name}.3mf",
            f"{role_name} — {label}",
            data["color"],
            force=force,
        )
    return generated


def generate_role(role_name, data, target, force=False):
    """Generate all requested files for one role; safe to run in a worker."""
    character_svg, reminder_svg = prepare_role_icon(role_name, data)
    generated = 0
    if target in ("all", "characters"):
        generated += generate_character(role_name, data, character_svg, force)
    if target in ("all", "reminders") and data.get("reminders"):
        generated += generate_reminders(role_name, data, reminder_svg, force)
    return generated


def main(target="all", role_filter=None, jobs=1, force=False):
    roles = json.loads(Path("roles.json").read_text(encoding="utf-8"))
    for directory in (
        "pngs",
        "grey_pngs",
        "svgs",
        "scads/characters",
        "scads/reminders",
        "stls/characters",
        "stls/reminders",
        "stls/characters_complete",
        "stls/reminders_complete",
        "3mf/characters",
        "3mf/reminders",
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
    failures = []
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(generate_role, role_name, data, target, force): role_name
            for role_name, data in selected_roles
        }
        for future in as_completed(futures):
            role_name = futures[future]
            try:
                generated += future.result()
            except Exception as error:  # Keep independent roles running.
                failures.append((role_name, error))
                print(f"FAILED {role_name}: {error}")
            completed += 1
            print(
                f"[{completed}/{len(selected_roles)}] {role_name} "
                f"({generated} new output files)"
            )
    if failures:
        names = ", ".join(role_name for role_name, _ in failures)
        raise RuntimeError(f"Generation failed for {len(failures)} role(s): {names}")


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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild outputs even when files already exist.",
    )
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    main(args.target, args.role, args.jobs, args.force)
