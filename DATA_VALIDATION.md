# Data Validation

## Canonical-First Ingest Rules
- `Scans` is the canonical scan source for dashboard ingestion.
- `Sheet1` is retained as a legacy-compatible fallback scan source.
- `Production`, `Downtime`, and `Products` are parsed against canonical field names first.
- Canonical field names come from [`schema_contract.py`](C:/Developments/Fluidra_Manufacturing%20Solution/schema_contract.py).
- Compatibility handling is only used after canonical resolution fails.

## Required Vs Optional Fields By Sheet

### Scans
- Required for dashboard use
  - `Timestamp`
  - `Product Code`
  - `Barcode`
  - `Cycle time`
  - `Status`
- Optional
  - `Batch`
  - `Description`
  - `Operator`
  - `Notes`
  - `Is_Rework`
  - `Workcenter`

### Production
- Required for dashboard use
  - `Timestamp`
  - `Event Type`
  - `Product Code`
  - `Duration (sec)`
  - `Production Count`
- Optional
  - `Operator`
  - `Workcenter`

### Downtime
- Required for dashboard use
  - `Timestamp`
  - `Duration (sec)`
  - `Reason`
- Optional
  - `Description`
  - `Operator`
  - `Workcenter`

### Products
- Required for dashboard use
  - `Product Code`
  - `Expected Cycle`
- Optional
  - `Description`
  - `Barcode Display`

## Legacy Compatibility Shims Retained
- `Sheet1` remains supported as a fallback scan source.
- Legacy scan column alias:
  - `Product_Code` -> `Product Code`
- Legacy-compatible production/product field names still tolerated where needed:
  - `Event` -> `Event Type`
  - `Duration` -> `Duration (sec)`
  - `Count` -> `Production Count`
  - `ProductCode` / `StockCode` / `Stock Code` -> `Product Code`
  - `IRuntime` / `Runtime` -> `Expected Cycle`
- Limited inferred fallback remains for malformed historical sheets when exact canonical or legacy aliases are unavailable.

## Validation Warnings And Errors Produced
- Validation warnings are emitted when:
  - only a legacy column alias matched
  - only inferred token-based parsing matched
  - rows contain malformed timestamp values
  - rows contain malformed duration or cycle values
  - rows contain non-canonical status or event values that are still preserved for compatibility
  - `Sheet1` is used as a compatibility fallback because `Scans` had no positive cycle values
- Validation errors are logged when:
  - a required canonical field could not be resolved at all
- Health behavior
  - true sheet read failures remain `ERROR`/degraded-read behavior
  - successful reads with validation problems are surfaced as refresh/read `WARNING`
  - valid empty/idle data remains distinct from failed reads

## Canonical-First Parsing Order
- For each critical field:
  1. exact canonical header
  2. explicit legacy alias list
  3. limited token-based inference
- This order now applies to:
  - timestamp
  - barcode
  - product code
  - cycle time
  - status
  - event type
  - duration
  - reason
  - workcenter

## Workcenter Handling
- Canonical field: `Workcenter`
- If missing on downtime rows, the existing backfill helper is still used.
- Global workcenter option updates remain in place, but ingestion now prefers explicit `_wc` values derived from canonical-first parsing.

## Tolerated Historical / Malformed Cases
- Historical sheets with `Product_Code`
- Historical `Sheet1` scan-only usage
- Production rows using `Event` / `Duration` / `Count`
- Product rows using stock-code/runtime naming
- Malformed row values are tolerated where enough structure remains to preserve dashboard behavior

## Deferred Limits
- Historical data is not migrated in this phase.
- Broad dashboard formula/chart logic is unchanged.
- Global workcenter state mutation is not fully redesigned in this phase.
