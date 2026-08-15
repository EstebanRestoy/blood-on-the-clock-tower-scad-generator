# Blood on the Clock Tower SCAD Generator

Generate complete and two-part models for Blood on the Clocktower character and
reminder tokens. Character tokens are 45 mm; reminder tokens are 25 mm. The
1.8 mm base and 0.2 mm top inlay have an assembled height of 2 mm.

Character names use the bundled Dumbledor 1 font. Reminder labels preserve
the official title casing and use bundled Barlow Condensed SemiBold, a freely
redistributable close substitute for the commercial condensed sans-serif used
on the physical reminders. Character-name tracking is increased to match the
wide letter spacing of the physical tokens. Dumbledor's very thin strokes are
also expanded before extrusion so a 0.4 mm FDM nozzle does not omit parts of
the letters. The generator measures the actual OpenSCAD glyph outlines once
and optically centres every curved label by its visible left/right margins.
OpenSCAD is automatically pointed at both fonts.

As in the working reference 3MF, the base remains a full 2 mm thick and the
coloured icon/text occupy the first 0.2 mm inside it. Each volume is centred
individually and placed with a 3MF component transform so Bambu Studio keeps the
two materials aligned. Generated files open with the decorated face against the
build plate for a clean first-layer finish.

## Instructions

1. Install the dependencies in the `requirements.txt` file:
   ```bash
   pip install -r requirements.txt
   ```

2. Install [OpenSCAD](https://openscad.org/) and
   [Potrace](https://potrace.sourceforge.net/), and ensure both commands are in
   your `PATH`.

3. Download the current released-role data from the official app resources:
   ```bash
   python get_all_roles.py
   ```

   `roles.json` retains repeated reminder labels because every repeated entry
   represents another physical token.

4. Generate both character and reminder tokens:
   ```bash
   python solid_maker.py
   ```

   You can generate only one token family while iterating:

   ```bash
   python solid_maker.py --target reminders
   python solid_maker.py --target characters
   ```

   Run several roles in parallel (four workers is a good starting point):

   ```bash
   python solid_maker.py --target reminders --jobs 4
   ```

   Existing non-empty STL files are skipped, so an interrupted run resumes
   without rebuilding completed tokens.

   Rebuild cached output after changing dimensions or text layout:

   ```bash
   python solid_maker.py --target reminders --jobs 4 --force
   ```

   For a quick test print of one character and its reminders:

   ```bash
   python solid_maker.py --role Washerwoman
   ```

## Output

- `stls/character_base.stl`: reusable 45 mm base
- `stls/reminder_base.stl`: reusable 25 mm base
- `stls/characters/`: one character overlay per released role
- `stls/reminders/`: one reminder overlay per required physical copy
- `stls/characters_complete/`: complete single-colour 45 mm character tokens
- `stls/reminders_complete/`: complete single-colour 25 mm reminder tokens
- `3mf/characters/`: assembled two-part character tokens with millimetre units
- `3mf/reminders/`: assembled two-part reminder tokens with millimetre units

For Bambu Studio or OrcaSlicer, import the 3MF file. It contains the base and
overlay grouped at the correct coordinates, declares millimetre units, and
includes Bambu-compatible extruder assignments: black base on filament 1 and
the team-coloured icon/text on filament 2. The complete STL is provided for
single-colour printing. Files ending in `_01`, `_02`, and so on intentionally
represent multiple copies of the same reminder.

The role metadata and icons come from the official Blood on the Clocktower
Online resources. Review the project's Community Created Content policy before
redistributing generated assets.

## Development

### Testing

This project uses pytest for testing. To run the tests:

```bash
pytest
```

### Code Formatting

This project uses ruff for code formatting and linting. To check your code:

```bash
ruff format .
```

### Continuous Integration

This project uses GitHub Actions for continuous integration. The CI pipeline:

1. Runs tests with pytest
2. Checks code formatting with ruff

The CI configuration is in `.github/workflows/ci.yml`.
