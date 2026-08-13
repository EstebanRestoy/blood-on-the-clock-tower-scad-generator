# Blood on the Clock Tower SCAD Generator

Generate two-part SCAD/STL models for Blood on the Clocktower character and
reminder tokens. Character tokens are 45 mm; reminder tokens are 25 mm. The
1.8 mm base and 0.2 mm top inlay are separate bodies so they can be assigned
different colours in a slicer; their assembled height is 2 mm.

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

   For a quick test print of one character and its reminders:

   ```bash
   python solid_maker.py --role Washerwoman
   ```

## Output

- `stls/character_base.stl`: reusable 45 mm base
- `stls/reminder_base.stl`: reusable 25 mm base
- `stls/characters/`: one character overlay per released role
- `stls/reminders/`: one reminder overlay per required physical copy

Import a base and its matching overlay together at the same coordinates as a
multi-part object in your slicer. Duplicate the shared base for each overlay.
Files ending in `_01`, `_02`, and so on intentionally represent multiple copies
of the same reminder.

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
