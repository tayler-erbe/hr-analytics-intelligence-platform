# First-unit intake: org chart to workforce evidence

An org chart can establish the starting scope. Upload the original PDF, PowerPoint, image, or other chart file in this chat. Include its date and whether it covers a whole unit or only leadership if you know. A readable chart can be enough to identify the pilot unit without selecting it separately.

## What we will extract

For every visible node: original title, visible name when relevant to matching, unit, explicit reporting line, source page/node location, and any visible vacancy or acting/interim label. Preserve labels verbatim alongside any normalized role family. Mark unreadable text and ambiguous connectors for review; do not turn proximity on a page into a confirmed reporting line.

The chart's document date and our observation date are different fields. A snapshot does not establish when an appointment started. Chart node IDs are local source IDs, not HR position numbers. Until a real position identifier is obtained, leave position_id null and retain the node as source_record_id.

An org chart establishes visible structure and title evidence. Duties, FTE, employment status, complete staffing coverage, and historical changes require additional evidence. A missing node is not proof of a vacancy or termination.

## Import contract

Use one JSON object per line. Required for every observation:

| Field | Meaning |
|---|---|
| kind | org_chart, directory, appointment, job_description, or posting |
| source_system | Stable source label, e.g. unit_org_chart_2026_11 |
| source_record_id | Source-native record ID or chart page/node ID; never a name-derived identity |
| observed_on | Date we observed the evidence, YYYY-MM-DD |
| institution_id | Stable campus/institution identifier agreed for the pilot |

Optional: position_id, person_key, unit_id, title, class_code, reports_to_position_id, duties, effective_from, effective_to, fte, source_locator. IDs and class codes must be strings to preserve leading zeros. Unknown values are null or omitted. Dates are YYYY-MM-DD. FTE is a fraction from 0 to 1 for an individual appointment record; source percentages need explicit conversion.

Org-chart records require source_locator (e.g. page 2, node 7). Job-description records require duties. Additional fields are retained inside payload_json, including document_date, extraction_status, source_filename and source_notes. Use a source revision ID for corrections; an existing observation cannot silently change.

Illustrative input only; this is not a real university position:

```json
{"kind":"org_chart","source_system":"example_chart","source_record_id":"page1-node7","observed_on":"2026-11-02","institution_id":"EXAMPLE_ONLY","title":"Example Analyst","source_locator":"page 1, node 7","document_date":null,"position_id":null,"extraction_status":"needs_review"}
```

## Local workflow

```powershell
python scripts/workforce_store.py
python scripts/workforce_store.py --import-jsonl data/local/unit_observations.jsonl
```

The first command creates a local SQLite store and loads the acquired public occupation and class reference tables. The second imports your prepared observations and prints a coverage report. No network calls or Microsoft 365 authentication occur. The current reference release is O*NET 31.0; use a separate database for a future release until versioned reference migration is implemented.

Imports are atomic and repeatable. Identical observations are skipped; conflicting observations with the same source identity/date reject the whole batch. Reports retain unresolved position identities and multiple titles. Position-level evidence links use institution_id + position_id only; people are not merged by name and class codes are not treated as unique source records.

The database and all input exports belong in data/local, which is excluded from Git. The report shows aggregate evidence coverage. This is not a privacy access-control system: use an institution-approved storage location for actual directory/HR exports. Do not upload such exports into free cloud trials as part of this starter.

## Additional exports to obtain after chart review

For the selected unit, obtain an authorized roster with stable person and position identifiers, campus/unit identifiers, working title, formal class code, FTE, appointment status and effective dates. Obtain position-description text/version and its position linkage. For historical recruitment, obtain requisition ID, position ID if present, original title/text, organizational unit, dates and recorded outcome.

A Teams/Entra directory export can supplement names, directory titles and departments. It cannot by itself establish active employment, multiple appointments, actual duties or historical headcount. No Teams export or Graph access has been configured in this workspace.

## Next review deliverable

After receiving a chart, produce a source-linked inventory, a reporting-line review, visible role families, and a gap list for duties/classifications/position IDs. Only then propose reviewed SUCSS/O*NET mappings. Historical growth or decline needs comparable dated snapshots or appointment histories; the intake report deliberately does not label roles as increasing or decreasing.
