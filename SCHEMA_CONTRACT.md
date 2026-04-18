# Schema Contract

## Scope
- This contract defines the canonical sheet schemas emitted by the logger.
- Backward compatibility is preserved for the current transition period.
- Legacy coexistence remains in place:
  - `Scans` continues as the canonical scan sheet
  - `Sheet1` continues as a mirrored compatibility scan sheet

## Timestamp Convention
- Canonical format: `YYYY-MM-DD HH:MM:SS`
- Example: `2026-04-10 14:23:55`
- Applies to:
  - `Scans`
  - `Sheet1`
  - `Production`
  - `Downtime`

## Workcenter Rule
- Canonical field name: `Workcenter`
- Required on all emitted scan, production, and downtime rows
- Value source: currently selected logger workcenter
- Empty string is allowed only as a compatibility fallback if workcenter is unavailable

## Canonical Status And Event Values
- Scan `Status`
  - `Scanned`
  - `Reworked`
- `Is_Rework`
  - boolean-like value emitted by the logger and stored as sheet/excel cell content
  - expected semantics:
    - `False` for normal accepted scan
    - `True` for duplicate-approved rework logging
- Production `Event Type`
  - `PRODUCTION_START`
  - `PRODUCTION_END`
- Downtime
  - no separate event-type column is emitted in the current contract
  - downtime semantics are carried by:
    - `Timestamp`
    - `Duration (sec)`
    - `Reason`
    - `Description`
    - `Operator`
    - `Workcenter`

## Scans
### Canonical sheet
- Sheet: `Scans`
- Required columns
  - `Timestamp`
  - `Product Code`
  - `Barcode`
  - `Batch`
  - `Cycle time`
  - `Status`
  - `Description`
  - `Operator`
  - `Notes`
  - `Is_Rework`
  - `Workcenter`
- Data types / semantics
  - `Timestamp`: formatted datetime string
  - `Product Code`: string
  - `Barcode`: string
  - `Batch`: string
  - `Cycle time`: decimal seconds string
  - `Status`: `Scanned` or `Reworked`
  - `Description`: string
  - `Operator`: string
  - `Notes`: string
  - `Is_Rework`: boolean-like cell value
  - `Workcenter`: string
- Optional columns
  - none in the canonical definition

### Compatibility aliases
- `Product_Code` -> `Product Code`
- The logger still accepts legacy sheet headers that use `Product_Code`
- When writing scan rows, the logger emits canonical `Product Code` and also preserves alias compatibility through the row-mapping helper

### Sheet-specific notes
- `Sheet1` remains a compatibility mirror of `Scans`
- The logger writes the same canonical scan row shape to both sheets
- If an existing `Sheet1` header row is legacy-shaped, the logger’s append helper still aligns values by header name and alias support

## Production
### Canonical sheet
- Sheet: `Production`
- Required columns
  - `Timestamp`
  - `Event Type`
  - `Product Code`
  - `Duration (sec)`
  - `Production Count`
  - `Operator`
  - `Workcenter`
- Data types / semantics
  - `Timestamp`: formatted datetime string
  - `Event Type`: `PRODUCTION_START` or `PRODUCTION_END`
  - `Product Code`: string
  - `Duration (sec)`: decimal seconds string
  - `Production Count`: integer string
  - `Operator`: string
  - `Workcenter`: string
- Optional columns
  - none in the canonical definition

## Downtime
### Canonical sheet
- Sheet: `Downtime`
- Required columns
  - `Timestamp`
  - `Duration (sec)`
  - `Reason`
  - `Description`
  - `Operator`
  - `Workcenter`
- Data types / semantics
  - `Timestamp`: downtime start timestamp
  - `Duration (sec)`: decimal seconds string
  - `Reason`: selected or derived downtime reason
  - `Description`: operator-entered description or empty string
  - `Operator`: operator name or empty string
  - `Workcenter`: string
- Optional columns
  - none in the canonical definition

### Downtime reason notes
- Current logger-emitted reason values can include:
  - `Mechanical Failure`
  - `Material Shortage`
  - `Quality Issue`
  - `Changeover`
  - `Operator Break`
  - `Planned Maintenance`
  - `Auto Detected`
  - `Unknown`
- This list remains operationally open for now because legacy behavior and manual entry flows still exist

## Products
### Interoperability subset
- Sheet: `Products`
- The logger currently depends on these positions/semantics:
  - `Product Code`: column 0
  - `Description`: column 1
  - `Expected Cycle`: column 4
  - `Barcode Display`: column 8
- Internal compatibility names still present in logger code:
  - `Barc` -> display/label barcode field loaded from product sheet column 8
  - `PC` -> product code loaded from column 0
- This phase does not redesign the `Products` sheet; it only documents the subset required for interoperability

## Old To Canonical Mapping
- `Product_Code` -> `Product Code`
- `Barc` -> internal logger/UI alias for product-sheet barcode display field; not a canonical emitted sheet column
- `PC` -> internal logger/UI alias for product code; not a canonical emitted sheet column

## Transition Notes
- Canonical names are now defined in code and used by the logger’s row builders
- Legacy compatibility remains in place because:
  - `Sheet1` still exists and is still written
  - some existing sheets may still carry `Product_Code` headers
  - dashboard compatibility/inference logic has not been broadly refactored yet
- Canonical values intentionally remain aligned with current live outputs where possible:
  - `Scanned`
  - `Reworked`
  - `PRODUCTION_START`
  - `PRODUCTION_END`
- Remaining ambiguity intentionally deferred
  - downtime reason vocabulary is not yet fully closed
  - historical sheets may still have older column layouts
  - dashboard ingestion still contains compatibility logic that is not removed in this phase
