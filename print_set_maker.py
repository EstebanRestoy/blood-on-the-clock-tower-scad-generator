"""Build edition-specific print folders and multipart Bambu Studio projects."""

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import tempfile
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

import lib3mf
import trimesh

import solid_maker


EDITION_NAMES = {
    "tb": "Trouble_Brewing",
    "bmr": "Bad_Moon_Rising",
    "snv": "Sects_And_Violets",
}

# The retail Trouble Brewing set contains 25 character tokens for 22 unique
# roles. The three extras are spare Imps used when the Demon changes player.
CHARACTER_QUANTITIES = {
    "tb": {"Imp": 4},
}

IDENTITY_4X4 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
PLATE_SIZE_MM = 256


@dataclass(frozen=True)
class PrintToken:
    name: str
    stem: str
    family: str
    color: str
    team: str
    source_3mf: Path
    base_stl: Path
    overlay_stl: Path


def reminder_stems(role_name, data):
    """Yield reminder names exactly as ``solid_maker`` generates them."""
    role_safe = solid_maker.safe_filename(role_name)
    totals = Counter(data.get("reminders", []))
    seen = Counter()
    for label in data.get("reminders", []):
        seen[label] += 1
        suffix = f"_{seen[label]:02d}" if totals[label] > 1 else ""
        token_name = f"{role_safe}__{solid_maker.safe_filename(label)}{suffix}"
        yield label, f"{data['color']}_{token_name}"


def tokens_for_roles(roles):
    """Return character and reminder files for the supplied role records."""
    result = []
    for role_name, data in roles:
        role_safe = solid_maker.safe_filename(role_name)
        character_stem = f"{data['color']}_{role_safe}"
        result.append(
            PrintToken(
                name=role_name,
                stem=character_stem,
                family="characters",
                color=data["color"],
                team=data["team"],
                source_3mf=Path("3mf/characters") / f"{character_stem}.3mf",
                base_stl=Path("stls/character_base.stl"),
                overlay_stl=Path("stls/characters")
                / f"{character_stem}_overlay.stl",
            )
        )
        for label, reminder_stem in reminder_stems(role_name, data):
            result.append(
                PrintToken(
                    name=f"{role_name} — {label}",
                    stem=reminder_stem,
                    family="tokens",
                    color=data["color"],
                    team=data["team"],
                    source_3mf=Path("3mf/reminders") / f"{reminder_stem}.3mf",
                    base_stl=Path("stls/reminder_base.stl"),
                    overlay_stl=Path("stls/reminders")
                    / f"{reminder_stem}_overlay.stl",
                )
            )
    return result


def split_edition_roles(roles, edition):
    matching = [
        (name, data) for name, data in roles.items() if data.get("edition") == edition
    ]
    core = [(name, data) for name, data in matching if data.get("team") != "traveller"]
    travellers = [
        (name, data) for name, data in matching if data.get("team") == "traveller"
    ]
    if not core:
        raise ValueError(f"No core roles found for edition: {edition}")
    return core, travellers


def copy_token_files(tokens, destination):
    copied = []
    for token in tokens:
        target_dir = Path(destination) / token.family
        target_dir.mkdir(parents=True, exist_ok=True)
        if not token.source_3mf.exists():
            raise FileNotFoundError(f"Missing generated token: {token.source_3mf}")
        target = target_dir / token.source_3mf.name
        shutil.copy2(token.source_3mf, target)
        copied.append(target)
    return copied


def grid_positions(count, columns, rows, x_start, y_start, x_step, y_step):
    capacity = columns * rows
    positions = []
    for index in range(count):
        within_plate = index % capacity
        positions.append(
            (
                index // capacity,
                x_start + (within_plate % columns) * x_step,
                y_start + (within_plate // columns) * y_step,
            )
        )
    return positions


def make_plate_layout(tokens):
    """Lay out tokens while reserving the plate's right side for purging."""
    characters = [token for token in tokens if token.family == "characters"]
    reminders = [token for token in tokens if token.family == "tokens"]
    plates = []

    character_positions = grid_positions(
        len(characters),
        columns=3,
        rows=5,
        x_start=30,
        y_start=27,
        x_step=55,
        y_step=50,
    )
    character_plate_count = max(
        (plate for plate, _, _ in character_positions), default=-1
    ) + 1
    for local_plate in range(character_plate_count):
        placements = [
            (token, x, y)
            for token, (plate, x, y) in zip(
                characters, character_positions, strict=True
            )
            if plate == local_plate
        ]
        plates.append((f"Characters {local_plate + 1}", placements))

    reminder_positions = grid_positions(
        len(reminders),
        columns=6,
        rows=6,
        x_start=20,
        y_start=20,
        x_step=30,
        y_step=30,
    )
    reminder_plate_count = max(
        (plate for plate, _, _ in reminder_positions), default=-1
    ) + 1
    for local_plate in range(reminder_plate_count):
        placements = [
            (token, x, y)
            for token, (plate, x, y) in zip(reminders, reminder_positions, strict=True)
            if plate == local_plate
        ]
        plates.append((f"Tokens {local_plate + 1}", placements))
    return plates


def expand_project_quantities(tokens, edition):
    """Add physical duplicate character tokens required by an edition."""
    quantities = CHARACTER_QUANTITIES.get(edition, {})
    expanded = []
    for token in tokens:
        expanded.append(token)
        if token.family != "characters":
            continue
        for copy_number in range(2, quantities.get(token.name, 1) + 1):
            expanded.append(
                PrintToken(
                    name=f"{token.name} (copy {copy_number})",
                    stem=token.stem,
                    family=token.family,
                    color=token.color,
                    team=token.team,
                    source_3mf=token.source_3mf,
                    base_stl=token.base_stl,
                    overlay_stl=token.overlay_stl,
                )
            )
    return expanded


def add_metadata(parent, key, value):
    ElementTree.SubElement(parent, "metadata", key=key, value=str(value))


def project_settings(colors):
    color_hex = [solid_maker.color_to_hex(color) for color in colors]
    count = len(colors)
    return {
        "name": "project_settings",
        "printer_model": "Bambu Lab X2D",
        "printer_variant": "0.4",
        "printer_settings_id": "Bambu Lab X2D 0.4 nozzle",
        "curr_bed_type": "Textured PEI Plate",
        "print_sequence": "by layer",
        "filament_colour": color_hex,
        "filament_multi_colour": color_hex,
        "filament_type": ["PLA"] * count,
        "filament_settings_id": ["Generic PLA"] * count,
        "filament_ids": [""] * count,
        "filament_vendor": ["Generic"] * count,
        "filament_diameter": ["1.75"] * count,
        "filament_density": ["1.24"] * count,
        "filament_cost": ["20"] * count,
        "filament_flow_ratio": ["1"] * count,
        "filament_max_volumetric_speed": ["12"] * count,
        "filament_is_support": ["0"] * count,
        "filament_soluble": ["0"] * count,
        "filament_start_gcode": [""] * count,
        "filament_end_gcode": [""] * count,
        "filament_minimal_purge_on_wipe_tower": ["15"] * count,
        "filament_prime_volume": ["45"] * count,
        "filament_map": [str(index) for index in range(1, count + 1)],
        "single_extruder_multi_material": "1",
    }


def inject_project_metadata(path, objects, plates, colors):
    config = ElementTree.Element("config")
    source_name = Path(path).name.replace(".tmp.3mf", ".3mf")
    for item in objects:
        object_node = ElementTree.SubElement(
            config, "object", id=str(item["assembly_id"])
        )
        add_metadata(object_node, "name", item["name"])
        add_metadata(object_node, "extruder", "1")
        ElementTree.SubElement(
            object_node,
            "metadata",
            face_count=str(item["base_faces"] + item["overlay_faces"]),
        )
        for object_id, name, extruder, face_count in (
            (item["base_id"], "Token base", 1, item["base_faces"]),
            (
                item["overlay_id"],
                "Icon and text",
                item["overlay_extruder"],
                item["overlay_faces"],
            ),
        ):
            part = ElementTree.SubElement(
                object_node, "part", id=str(object_id), subtype="normal_part"
            )
            add_metadata(part, "name", name)
            add_metadata(part, "matrix", IDENTITY_4X4)
            add_metadata(part, "source_file", source_name)
            add_metadata(part, "source_object_id", "0")
            add_metadata(part, "source_volume_id", "0")
            add_metadata(part, "source_offset_x", "0")
            add_metadata(part, "source_offset_y", "0")
            add_metadata(part, "source_offset_z", "0")
            add_metadata(part, "extruder", extruder)
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

    filament_map = " ".join(map(str, range(1, len(colors) + 1)))
    volume_map = " ".join(["1"] * len(colors))
    for plate_number, (plate_name, plate_objects) in enumerate(plates, start=1):
        plate = ElementTree.SubElement(config, "plate")
        add_metadata(plate, "plater_id", plate_number)
        add_metadata(plate, "plater_name", plate_name)
        add_metadata(plate, "locked", "false")
        add_metadata(plate, "filament_map_mode", "Auto For Quality")
        add_metadata(plate, "filament_maps", filament_map)
        add_metadata(plate, "filament_volume_maps", volume_map)
        for item in plate_objects:
            instance = ElementTree.SubElement(plate, "model_instance")
            add_metadata(instance, "object_id", item["assembly_id"])
            add_metadata(instance, "instance_id", "0")
            add_metadata(instance, "identify_id", item["identify_id"])

    model_settings = ElementTree.tostring(
        config, encoding="utf-8", xml_declaration=True
    )
    settings = json.dumps(project_settings(colors), indent=2).encode("utf-8")
    metadata_names = {
        "Metadata/model_settings.config",
        "Metadata/project_settings.config",
    }
    temporary = tempfile.NamedTemporaryFile(
        prefix=f"{Path(path).stem}_metadata_",
        suffix=".3mf",
        dir=Path(path).parent,
        delete=False,
    )
    temporary_path = Path(temporary.name)
    temporary.close()
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
                "Metadata/project_settings.config", settings, ZIP_DEFLATED
            )
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def create_bambu_project(tokens, output_path):
    plates = make_plate_layout(tokens)
    color_order = ["blue", "red", "purple", "yellow", "green"]
    used_colors = [
        color for color in color_order if any(token.color == color for token in tokens)
    ]
    colors = [solid_maker.BASE_COLOR] + [
        solid_maker.OVERLAY_COLORS[color] for color in used_colors
    ]
    color_extruders = {color: index + 2 for index, color in enumerate(used_colors)}

    wrapper = lib3mf.get_wrapper()
    model = wrapper.CreateModel()
    model.SetUnit(lib3mf.ModelUnit.MilliMeter)
    materials = model.AddBaseMaterialGroup()
    material_indices = [
        materials.AddMaterial("Token base", lib3mf.Color(*colors[0]))
    ]
    for color_name, color in zip(used_colors, colors[1:], strict=True):
        material_indices.append(
            materials.AddMaterial(
                f"{color_name.title()} overlay", lib3mf.Color(*color)
            )
        )

    records = []
    metadata_plates = []
    identify_id = 1
    for plate_index, (plate_name, placements) in enumerate(plates):
        plate_records = []
        for token, x, y in placements:
            base_mesh = trimesh.load_mesh(token.base_stl, process=True)
            overlay_mesh = trimesh.load_mesh(token.overlay_stl, process=True)
            base_center = base_mesh.bounds.mean(axis=0)
            overlay_center = overlay_mesh.bounds.mean(axis=0)
            base_mesh.apply_translation(-base_center)
            overlay_mesh.apply_translation(-overlay_center)
            overlay_material = used_colors.index(token.color) + 1
            base_object = solid_maker.add_3mf_mesh(
                model, base_mesh, "Token base", materials, material_indices[0]
            )
            overlay_object = solid_maker.add_3mf_mesh(
                model,
                overlay_mesh,
                "Icon and text",
                materials,
                material_indices[overlay_material],
            )
            assembly = model.AddComponentsObject()
            assembly.SetName(token.name)
            assembly.AddComponent(base_object, wrapper.GetIdentityTransform())
            assembly.AddComponent(
                overlay_object,
                solid_maker.translation_transform(
                    wrapper, overlay_center - base_center
                ),
            )
            transform = solid_maker.face_down_transform(
                wrapper, float(base_mesh.extents[2])
            )
            # Bambu Studio stores consecutive virtual plates side by side in
            # the core 3MF coordinate space. Metadata alone does not move an
            # object off plate 1, so add one full bed width per plate.
            transform.Fields[3][0] = float(x + plate_index * PLATE_SIZE_MM)
            transform.Fields[3][1] = float(y)
            model.AddBuildItem(assembly, transform)
            record = {
                "name": token.name,
                "base_id": base_object.GetResourceID(),
                "overlay_id": overlay_object.GetResourceID(),
                "assembly_id": assembly.GetResourceID(),
                "base_faces": len(base_mesh.faces),
                "overlay_faces": len(overlay_mesh.faces),
                "overlay_extruder": color_extruders[token.color],
                "identify_id": identify_id,
            }
            identify_id += 1
            records.append(record)
            plate_records.append(record)
        metadata_plates.append((plate_name, plate_records))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(".tmp.3mf")
    model.QueryWriter("3mf").WriteToFile(str(temporary_path))
    inject_project_metadata(temporary_path, records, metadata_plates, colors)
    temporary_path.replace(output_path)
    return plates


def build_print_set(edition, output_root=Path("print_sets")):
    roles = json.loads(Path("roles.json").read_text(encoding="utf-8"))
    core_roles, traveller_roles = split_edition_roles(roles, edition)
    scenario_name = EDITION_NAMES.get(edition, solid_maker.safe_filename(edition))
    scenario_root = Path(output_root) / scenario_name
    core_tokens = tokens_for_roles(core_roles)
    traveller_tokens = tokens_for_roles(traveller_roles)
    copied_core = copy_token_files(core_tokens, scenario_root)
    copied_travellers = copy_token_files(
        traveller_tokens, scenario_root / "optional_travellers"
    )
    project_path = scenario_root / f"{scenario_name}_Bambu_Project.3mf"
    project_tokens = expand_project_quantities(core_tokens, edition)
    plates = create_bambu_project(project_tokens, project_path)
    manifest = {
        "edition": edition,
        "scenario": scenario_name,
        "core": {
            "characters": sum(t.family == "characters" for t in core_tokens),
            "tokens": sum(t.family == "tokens" for t in core_tokens),
        },
        "physical_project": {
            "characters": sum(
                t.family == "characters" for t in project_tokens
            ),
            "tokens": sum(t.family == "tokens" for t in project_tokens),
        },
        "optional_travellers": {
            "characters": sum(t.family == "characters" for t in traveller_tokens),
            "tokens": sum(t.family == "tokens" for t in traveller_tokens),
        },
        "plates": [
            {"name": name, "objects": len(placements)}
            for name, placements in plates
        ],
        "project": project_path.name,
        "files": [str(path.relative_to(scenario_root)) for path in copied_core],
        "optional_files": [
            str(path.relative_to(scenario_root)) for path in copied_travellers
        ],
    }
    (scenario_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return scenario_root, manifest


def main():
    parser = argparse.ArgumentParser(
        description="Group one BOTC edition and create a Bambu multi-plate project."
    )
    parser.add_argument("--edition", required=True, help="Edition code, e.g. tb")
    parser.add_argument("--output-root", default="print_sets")
    args = parser.parse_args()
    root, manifest = build_print_set(args.edition, Path(args.output_root))
    print(f"Created {root}")
    for plate in manifest["plates"]:
        print(f"- {plate['name']}: {plate['objects']} objects")


if __name__ == "__main__":
    main()
