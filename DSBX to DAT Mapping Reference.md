# DSBX → DAT Mapping Reference

This document describes how every field in the AE-C400 `.dat` XML is derived from the `.dsbx` design file. Edit `dsbx_dat_mapping.json` to correct lookup-table values. Edit this file to document corrections or open items.

Verified against: `Variety of Units/DSB to DAT Testing.dsbx` → `Variety of Units/Variety of units.dat` (and `Variety of units 2.dat` for multi-AIC case).

---

## Source File Structures

### DSBX (input)
ZIP archive containing one XML entry named `xml`. Relevant schema paths:

```
DSB/Project/
  Measure_TemperatureUnit     → "Fahrenheit" | "Celsius"
  Measure_WaterPressureUnit   → "PoundPerSquareInch" | "Kilopascal"

DSB/Project/Groupof50/
  Name                        → centralized system name (→ DAT SystemData/@Name)
  TableId                     → unique ID for this group of 50
  System[]/                   → one per outdoor unit
    SystemName                → area name in DAT
    TableId
    OutdoorUnit/
      MNetAddress             → ODU M-Net address (used for AIC detection)
      BCController/           → present on R2 systems only
        IndoorUnit[]/
          MNetAddress
          ModelNumber
          ReferenceTag
          AssociatedIndoorUnitGroup
          TableId
      IndoorUnit[]/           → present on P systems (no BCController)
        MNetAddress
        ModelNumber
        ReferenceTag
        AssociatedIndoorUnitGroup
        TableId
  IndoorUnitGroup[]/
    GroupNumber               → DAT Group attribute
    GroupType                 → "IU" | "Lossnay"
    TableId                   → matched by IndoorUnit.AssociatedIndoorUnitGroup
    LocalRemoteController/    → optional
      MNetAddress             → if present, creates RC record in DAT
  Lossnay[]/
    MNetAddress               → DAT Address for LC record
    ReferenceTag              → DAT GroupNameWeb
    LossnayGroupId            → matches IndoorUnitGroup.TableId
    IUGroupId                 → optional, links to an IU group (Lossnay 0 only)
  SystemRemoteController/
    ModelNumber               → DAT SystemData/@Model
    IPAddress                 → DAT SystemData/@IPAdrsLan
    MNetAddress               → DAT SystemData/@MnetAdrs (strip leading zeros)
```

### DAT (output)
ZipCrypto-encrypted ZIP (password `MELCO`) containing:
- `1` — main XML (built by this tool)
- `NetworkSetting.xml` — copied verbatim from the empty template
- `IMG/` — empty directory entry

---

## Mapping Tables

### 1. SystemData

| DAT Attribute | DSB Source Path | Transform |
|---|---|---|
| `Name` | `Groupof50/Name` | Direct |
| `Model` | `SystemRemoteController/ModelNumber` | Direct |
| `IPAdrsLan` | `SystemRemoteController/IPAddress` | Direct |
| `MnetAdrs` | `SystemRemoteController/MNetAddress` | Strip leading zeros ("000" → "0") |
| `TempUnit` | `Project/Measure_TemperatureUnit` | See `temp_unit_map` in JSON |
| `PressUnit` | `Project/Measure_WaterPressureUnit` | See `pressure_unit_map` in JSON |
| All others | — | Fixed defaults; see `system_data_defaults` in JSON |

### 2. MnetGroupList — Unit Model Classification

Each record: `<MnetGroupRecord Group="{n}" Address="{addr}" Model="{type}" SubModel="" />`

| Condition | Model |
|---|---|
| IDU where IDU.MNetAddress ≠ ODU.MNetAddress | `IC` |
| IDU where IDU.MNetAddress = ODU.MNetAddress (P-series single-port) | `AIC` |
| LocalRemoteController with MNetAddress child | `RC` |
| Lossnay unit | `LC` |

**Logic:**
1. For each `IndoorUnitGroup` (GroupType="IU"): collect all `IndoorUnit` elements where `AssociatedIndoorUnitGroup == IndoorUnitGroup.TableId`. These IDUs can appear anywhere under `Groupof50` (inside BCController or directly under OutdoorUnit).
2. For each IDU, look up its parent `System`'s `OutdoorUnit/MNetAddress` to determine IC vs AIC.
3. If the `IndoorUnitGroup` has a `LocalRemoteController` with a `<MNetAddress>` child, emit an additional RC record.
4. For each `IndoorUnitGroup` (GroupType="Lossnay"): find the `Lossnay` where `LossnayGroupId == TableId`.

**Ordering:** Records appear in `GroupNumber` order, then RC after the last IC/AIC for that group.

### 3. ViewInfoList — Icon Assignment

Each record: `<ViewInfoRecord Group="{n}" Icon="{icon}" />`

Icon is determined from the **ModelNumber of the first IDU** (first by XML document order in DSB) belonging to that group. Rules are evaluated in order (first match wins):

| Priority | Condition | Icon | Model Examples |
|---|---|---|---|
| 1 | ModelNumber contains "LEV KIT" (case-insensitive) | 53 | "6000 Btu/h LEV Kit" |
| 2 | Starts with `PKFY` | 10 | PKFY-P04NLMU-ER1 |
| 3 | Starts with `PKA` | 10 | PKA-A24KA8 |
| 4 | Starts with `PLFY` | 0 | PLFY-P05NFMU-ER1 |
| 5 | Starts with `PCFY` | 6 | PCFY-P15NKMU-ER2 |
| 6 | Starts with `PVFY` | 8 | PVFY-P08NAMU-E1 |
| 7 | Starts with `PFFY` | 11 | PFFY-P08NEMU-E |
| 8 | Starts with `PMFY` | 3 | PMFY-P06NBMU-ER6 |
| 9 | Starts with `PEFY` | 4 | PEFY-P06NMAU-E4 |
| — | Lossnay units | 0 | LGH-F300RVX2-E |
| — | Default (no match) | 0 | any other |

> **To add a new model:** Add an entry to `icon_rules` in `dsbx_dat_mapping.json`. No code change needed.

### 4. MnetList — Group Names

Each record: `<MnetRecord Group="{n}" GroupNameWeb="{name}" />`

| Group Type | GroupNameWeb Source |
|---|---|
| IU | `ReferenceTag` of the **first** `IndoorUnit` belonging to the group (by XML document order in DSB) |
| Lossnay | `ReferenceTag` of the `Lossnay` element whose `LossnayGroupId == IndoorUnitGroup.TableId` |

> **Open item:** For groups with multiple IDUs having different ReferenceTags (e.g., Group 5 had "Floor Mount1" and "Floor Mount2"), the first by document order is used. If this turns out to be wrong, the rule may instead be lowest MNetAddress — these happened to be the same in the reference file.

### 5. AreaGroupList / AreaList

Areas are derived from the `System` elements in DSB:

| DAT Element | Source |
|---|---|
| `AreaRecord Area="{n}" AreaName="{name}"` | Sequential area number per `System`; `AreaName = System/SystemName` |
| `AreaRecord Area="{erv_n}" AreaName="ERVs"` | Final area; created if any Lossnay groups exist |
| `AreaGroupRecord Area="{n}" Group="{g}" ModelID="MNET"` | Group `g` belongs to the System that contains its IDUs |

**Area assignment logic:**
- Walk each `System` → `OutdoorUnit` → `[BCController →]` `IndoorUnit` → `AssociatedIndoorUnitGroup` → `IndoorUnitGroup.GroupNumber`
- That GroupNumber belongs to this System's area
- Lossnay groups → ERVs area
- Groups not in any System and not Lossnay → "Other" area (fallback; should not occur in valid DSB)

`ModelID` is always `"MNET"` for all AreaGroupRecords.

### 6. ApportionRefSystemList

Always 40 `<ApportionRefSystemList ScNo="{1..40}" />` elements. Only ScNo="1" contains data:

```xml
<ApportionRefSystemList ScNo="1">
  <!-- one record per AIC unit -->
  <ApportionRefSystemRecord OcAddress="{ODU.MNetAddress}" Address="{IDU.MNetAddress}" Model="AIC" />
</ApportionRefSystemList>
```

For AIC units, ODU.MNetAddress == IDU.MNetAddress, so both attributes are the same value.

> **Open item:** ScNo is always 1 in all observed DATs. Unknown if multi-controller projects use ScNo 2+.

### 7. Boilerplate (always identical)

These sections are copied verbatim regardless of DSB contents:

**ScSystem:**
```xml
<ScSystem>
  <ScSystemDataList>
    <ScSystemDataRecord ScNo="1" HostName="" TotalMaster="ON" Apportion="OFF" />
  </ScSystemDataList>
</ScSystem>
```

**Web ControlScList (both MasterType="WEB" and "TOUCHPANEL"):**
```xml
<ControlScRecord ScNo="1" ConnectionIP="" />
```

**WebDisplayDataList (both MasterType="WEB" and "TOUCHPANEL") — fixed 9 records:**
```xml
<WebDisplayDataRecord Model="IC"  SubModel=""   FloorInfo1="ROOM_TEMP"    FloorInfo2="SET_TEMP"   RoomTemp="SHOW_ALWAYS" RoomHumidity="SHOW_ALWAYS" />
<WebDisplayDataRecord Model="LC"  SubModel=""   FloorInfo1="VENT_MODE"    FloorInfo2="CO2_AVERAGE" RoomTemp="SHOW_ALWAYS" RoomHumidity="SHOW_ALWAYS" />
<WebDisplayDataRecord Model="IC"  SubModel="HH" FloorInfo1="ROOM_TEMP"    FloorInfo2="SET_TEMP"   RoomTemp="SHOW_ALWAYS" RoomHumidity="SHOW_ALWAYS" />
<WebDisplayDataRecord Model="BU"  SubModel=""   FloorInfo1="WATER_TEMP"   FloorInfo2="SET_TEMP"   RoomTemp="SHOW_ALWAYS" RoomHumidity="SHOW_ALWAYS" />
<WebDisplayDataRecord Model="OC"  SubModel=""   FloorInfo1="OUTDOOR_TEMP" FloorInfo2=""           RoomTemp="SHOW_ALWAYS" RoomHumidity="SHOW_ALWAYS" />
<WebDisplayDataRecord Model="CEh" SubModel=""   FloorInfo1="SET_TEMP"     FloorInfo2="HEAD_TEMP"  RoomTemp="SHOW_ALWAYS" RoomHumidity="SHOW_ALWAYS" />
<WebDisplayDataRecord Model="CEW" SubModel=""   FloorInfo1="SET_TEMP"     FloorInfo2="HEAD_TEMP"  RoomTemp="SHOW_ALWAYS" RoomHumidity="SHOW_ALWAYS" />
<WebDisplayDataRecord Model="CHE" SubModel=""   FloorInfo1="SET_TEMP"     FloorInfo2="HEAD_TEMP"  RoomTemp="SHOW_ALWAYS" RoomHumidity="SHOW_ALWAYS" />
<WebDisplayDataRecord Model="CHM" SubModel=""   FloorInfo1="SET_TEMP"     FloorInfo2="HEAD_TEMP"  RoomTemp="SHOW_ALWAYS" RoomHumidity="SHOW_ALWAYS" />
```

**Always-empty lists:** `McList`, `DdcInfoList`, `InterlockList`, `OcNameList`, `McNameList`, `ModbusList`, `InterlockIndexList`, `ChangeoverList`, `EnergyManagement/UnitSourceList`, `EneBlockAreaList`, `EneBlockList`, all `WebF*` lists.

**ModbusSystem:** `BaudRate="19200" StopBit="1" ParityBit="EVEN"`

---

## Change Log

| Date | Change |
|---|---|
| 2026-04-17 | Initial version. Verified against Variety of Units test files. |
