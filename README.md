# Central Control Database Tools

Python utilities for generating and converting Mitsubishi Electric central controller configuration files (`.dat`) from Design Build project files (`.dsbx`).

---

## Background

### The .dat file format

Mitsubishi Electric central controllers (AE-C400A, AE-200, EW-C50, EW-50) are configured by loading a `.dat` file through the ISToolAEC / ISToolAE initial settings application. Despite the `.dat` extension, these files are **ZipCrypto-encrypted ZIP archives** (PKWARE traditional encryption, password `MELCO`). Each archive contains one or more XML entries named `1`, `1-1`, `1-2`, etc. (one per controller), plus optional `NetworkSetting.xml` and `IMG/` entries depending on controller type.

The XML inside is a `<Packet><DatabaseManager>` structure. The only sections these tools write or modify are:

- **`<SystemData>`** — controller-level settings. Only the `Name` attribute is derived from the project; all other attributes are preserved from a known-good template for the target controller.
- **`<ControlGroup>`** — the unit configuration. This is the section these tools generate entirely from project data:
  - `<MnetGroupList>` — one record per physical unit (indoor, remote controller, Lossnay, AIC)
  - `<ViewInfoList>` — icon code per group
  - `<MnetList>` — display name per group
  - `<AreaGroupList>` — maps groups to areas (outdoor unit systems)
  - `<AreaList>` — area names (one per outdoor unit system, plus "ERVs" for Lossnay)

All other sections (`<ScSystem>`, `<Web>`, `<Apportion>`, `<ModbusSystem>`, etc.) are taken verbatim from the controller template and never modified.

### The .dsbx file format

A `.dsbx` file is a Mitsubishi Electric Design Build project. It is an **unencrypted ZIP** containing a single XML entry named `xml`. The relevant schema within that XML:

```
DSB/Project/
  Measure_TemperatureUnit       "Fahrenheit" | "Celsius"
  Measure_WaterPressureUnit     "PoundPerSquareInch" | ...
  Groupof50/                    one per central controller (up to 50 groups)
    Name                        → SystemData/@Name in DAT
    System[]                    one per outdoor unit
      SystemName                → AreaName in DAT
      OutdoorUnit/
        MNetAddress             used to detect AIC units
        BCController/           present on R2 systems only
          IndoorUnit[]
        IndoorUnit[]            present on P systems (no BCController)
    IndoorUnitGroup[]           defines groups 1–50
      GroupNumber               → Group attribute in DAT records
      GroupType                 "IU" | "Lossnay"
      TableId                   key linking IDUs to their group
      LocalRemoteController/    optional; if it has <MNetAddress>, adds RC record
    Lossnay[]                   Lossnay/ERV units
      MNetAddress               → Address in LC MnetGroupRecord
      ReferenceTag              → GroupNameWeb
      LossnayGroupId            links to IndoorUnitGroup.TableId
    SystemRemoteController/
      ModelNumber               → SystemData/@Model
      IPAddress                 → SystemData/@IPAdrsLan
      MNetAddress               → SystemData/@MnetAdrs
```

### Controller families

There are two distinct XML schemas among the supported controllers:

| Controller | Template file | ZIP contents | ControlGroup extras |
|---|---|---|---|
| AE-C400A | `templates/AE-C400A.xml` | `1`, `NetworkSetting.xml`, `IMG/` | `ModbusList` |
| EW-C50 | `templates/EW-C50.xml` | `1`, `NetworkSetting.xml`, `IMG/` | `ModbusList` |
| AE-200 | `templates/AE-200.xml` | `1` | `FloorList`, `FloorGroupList` |
| EW-50 | `templates/EW-50.xml` | `1`, `IMG/` | `FloorList`, `FloorGroupList` |

AE-C400A and EW-C50 are structurally identical. AE-200 and EW-50 are structurally identical.

### Unit model classification in MnetGroupList

Each `<MnetGroupRecord>` has a `Model` attribute determined as follows:

| Condition | Model |
|---|---|
| Indoor unit whose M-Net address differs from its outdoor unit | `IC` |
| Indoor unit sharing the same M-Net address as its outdoor unit (P-series single-port) | `AIC` |
| `LocalRemoteController` element that has an `<MNetAddress>` child | `RC` |
| Lossnay/ERV unit | `LC` |
| Systems or units with missing / "N/A" M-Net address | **skipped entirely** |

### Icon assignment (ViewInfoList)

Icons are looked up from `dsbx_dat_mapping.json` by matching the first indoor unit's model number. Rules are evaluated in order; first match wins:

| Condition | Icon |
|---|---|
| Model number contains "LEV KIT" (case-insensitive) | 53 |
| Starts with `PKFY` or `PKA` | 10 |
| Starts with `PLFY` | 0 |
| Starts with `PCFY` | 6 |
| Starts with `PVFY` | 8 |
| Starts with `PFFY` | 11 |
| Starts with `PMFY` | 3 |
| Starts with `PEFY` | 4 |
| Lossnay units | 0 |
| Default | 0 |

---

## Scripts

### `dsbx_to_dat.py` — Convert a DSB project file to a controller DAT

```
python dsbx_to_dat.py input.dsbx [output.dat] [--controller AE-C400A] [--mapping dsbx_dat_mapping.json]
```

- Reads the DSB XML from the `.dsbx` ZIP
- Loads `templates/{controller}.xml` as the base document
- Sets `SystemData/@Name` from `Groupof50/Name`
- Builds a complete `<ControlGroup>` from DSB unit data
- Re-encrypts as a ZipCrypto `.dat` with the correct ZIP structure for the target controller
- If `output.dat` is omitted, auto-names the file `"{system name} {controller}.dat"` in the working directory

**`--controller`** options: `AE-C400A` (default), `AE-200`, `EW-C50`, `EW-50`

---

### `convert_dat.py` — Convert an existing DAT to a different controller type

```
python convert_dat.py input.dat --to AE-C400A [output_dir]
```

- Reads the `<ControlGroup>` data from the source DAT (units, icons, names, areas)
- Loads the target controller's template
- Copies `SystemData/@Name` and all five data lists into the target template
- Structural differences between controller families (ModbusList vs FloorList etc.) are handled automatically by the template
- Output is named `"{Name} {controller}.dat"` in `output_dir` (defaults to same folder as input)

---

### `split_dat.py` — Split a multi-controller DAT into individual DATs

```
python split_dat.py input.dat [output_dir]
```

An AE-200 database can contain multiple controllers in a single ZIP (entries `1`, `1-1`, `1-2`, `2`, etc.). This script extracts each XML entry into its own standalone `.dat` file named after the controller's `SystemData/@Name`. Useful for separating an AE-200 master + EW-50 expansion unit database into individual files for import.

---

### `generate_dat.py` — Generate a DAT from a CSV of group settings

```
python generate_dat.py groups.csv output.dat
```

A lower-level tool that builds an AE-C400A `.dat` directly from a CSV file with columns `group_number`, `mnet_address`, `group_name`. Predates the DSB-based workflow; useful when you want to manually specify group settings without a `.dsbx` file.

CSV format:
```
group_number,mnet_address,group_name
1,50,FCU-01
2,49,FCU-02
```

---

## Reference files

### `dsbx_dat_mapping.json`

Machine-readable configuration for `dsbx_to_dat.py`. Edit this file to correct icon mappings or add new model prefixes without touching any Python code. Contains:

- `icon_rules` — ordered list of match rules (startswith / contains) mapping model number patterns to icon codes
- `default_icon` — fallback icon (0) when no rule matches
- `temp_unit_map` — DSB temperature unit strings to DAT codes (e.g. "Fahrenheit" → "F")
- `pressure_unit_map` — DSB pressure unit strings to DAT codes
- `system_data_defaults` — all fixed `SystemData` attribute values (not used directly by the template-based scripts, kept for reference)

### `DSBX to DAT Mapping Reference.md`

Human-readable documentation of every DSB → DAT field mapping, including the full schema for both file formats, all classification rules, and a change log. Update this file whenever a mapping correction is discovered.

### `templates/`

Decrypted XML from the empty config `.dat` for each supported controller. These are the authoritative source of all static sections. To add support for a new controller type: decrypt its empty `.dat`, save the XML to `templates/{controller}.xml`, add an entry to the `EMPTY_CONFIGS` dict in `dsbx_to_dat.py` and `convert_dat.py`.

---

## Known restrictions

- Groups with more than one indoor unit are named after the unit with the lowest M-Net address (or first by XML document order — these coincide in all tested files)
- No support for databases with multiple central controllers in a single DSB project (one DSB → one DAT per run; multi-controller DSB files have not been tested)
- All generated `.dat` files use the IP address and M-Net address stored in the template for the target controller (defaults to `192.168.1.1`, M-Net address `0`)
- Icon assignment covers common model families; unrecognized models default to icon 0
- Lossnay interlock settings are not written
- Areas (blocks) are created per outdoor unit system; Lossnay ERVs get their own "ERVs" area

---

## Dependencies

```
pip install pyzipper
```

All other dependencies (`zipfile`, `xml.etree.ElementTree`, `zlib`, `struct`, `json`) are Python stdlib.
