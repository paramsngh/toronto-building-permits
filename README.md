# Toronto Building Permits Pipeline

An end to end data pipeline on City of Toronto building permit data, built with Azure Data Lake Storage, Azure Databricks and Power BI.

The analytical question: **how long does the City of Toronto take to issue a building permit, and is it getting faster or slower?** Approval speed is regularly cited in the debate about housing supply in Toronto, and this data can measure it directly.

---

## Headline finding

Median days from application to permit issued, for permits applied for between 2020 and 2024:

| Year | Permits issued | Median days | Average days |
|---|---|---|---|
| 2020 | 19,428 | 28 | 68.0 |
| 2021 | 22,182 | 30 | 89.3 |
| 2022 | 21,188 | **34** | 74.2 |
| 2023 | 18,321 | 29 | 66.5 |
| 2024 | 19,008 | 23 | 52.6 |

Approval times rose through 2022 and then improved, with 2024 the fastest year in the window.

The gap between median and average is itself informative: a small number of permits take years, which pulls the average up by 30 to 60 days. Median is used throughout for that reason.

**2025 and 2026 are deliberately excluded.** Permits from those years that are still undecided have no issue date, so only the fast ones have been resolved and any average for those years looks artificially good. The cutoff is derived from the current date rather than hardcoded, so it advances on its own.

---

## Architecture

```
City of Toronto Open Data (CSV)
            │
            ▼
   Azure Data Lake Storage Gen2          raw files, never modified
            │
            ▼
   Databricks  ·  bronze                 loaded as text, nothing cleaned
            │
            ▼
   Databricks  ·  silver                 typed, keyed, deduplicated, flagged
            │
            ▼
   Databricks  ·  gold                   star schema, renamed, documented
            │
     ┌──────┴──────┐
     ▼             ▼
  Power BI     Question answering API
```

Authentication from Databricks to storage uses a Unity Catalog storage credential backed by an Azure managed identity. No access keys exist anywhere in this repository.

---

## Data model

Gold is a star schema. A dimension was only created where it adds information the fact table does not already have, which is why structure type and work type remain plain columns rather than becoming tables of their own.

| Table | Rows | Contents |
|---|---|---|
| `fact_permits` | 152,937 | One row per permit revision, applied for 2020 onward |
| `dim_date` | 2,557 | One row per day, with year, quarter, month and weekday |
| `dim_status` | 30 | Each status mapped to a broader stage |
| `dim_permit_type` | 16 | Each type marked as a main or secondary permit |
| `dim_postal_area` | 98 | Each postal area mapped to a region |
| `approval_trend` | 5 | Median and average days to issue, by year |
| `dq_results` | grows | Quality metrics appended on every run |

Relationships are many to one from the fact table to each dimension. `dim_date` connects three times, to application, issued and completed dates, so the same calendar can answer "applied for in March" and "issued in March" as separate questions.

---

## Data quality findings

The source data needed substantial work. These were the findings that changed the result rather than just tidying it.

### Spark was silently corrupting 1% of rows

A numeric conversion failed on values like `" 1 shower"` and `" 1 2 compt. l.t."`, which is plumbing description text appearing in a numeric column. Investigation showed descriptions, use types and even cost figures sitting in the wrong columns for roughly 6,850 rows.

The cause: Spark's CSV reader defaults to a backslash as its escape character, while CSV files use a doubled quote. When a free text description contained a quote, the reader lost track of the field boundary and every column after it shifted one position.

Fixed by setting `escape` and `multiLine` on the read. The fix belongs in bronze, because once values have shifted there is no rule downstream that can restore them.

This surfaced only because Databricks casts strictly and raises on bad input rather than quietly returning null. A silent null would have hidden corrupted values in every column after the description.

### The obvious key was not unique

Permit number plus revision number appeared to be the natural key, but had **5,065 duplicates**: the City reuses the same number and revision across different permit types. Adding permit type as a third component reduced that to 24, which are resolved by keeping the most recently loaded row and reporting the count.

### Flagging by permit type would have deleted 60,732 real projects

Plumbing, drain and HVAC permits usually duplicate a main building permit on the same project, so one house can appear four times. The obvious approach is to exclude every permit of those types.

Checking the data showed that **60,732 of them have no main permit at all**. They are genuine standalone jobs such as a furnace replacement or a drain repair.

The pipeline therefore flags by relationship rather than by type: a secondary permit is only excluded when a main permit exists on the same project number. That removes 270,998 true duplicates while keeping the standalone work.

Partial and conditional permits were found to duplicate projects 97 to 99 percent of the time and were added to the same rule. A further 698 rows turned out not to be permits at all, including contact lists and deferred fee records, and are excluded separately.

### A postal code made of spaces

44,131 rows carried a postal code of three literal space characters. It passes a length check and looks like a real value in a table, but would have rendered as a blank region on a map. Trimming converts these to null so they are honestly missing.

### A status that differs only by capitalisation

The data contains both `Application On Hold` and `Application on Hold`. Spark treats these as two values; Power BI matches text case insensitively and would reject the resulting duplicate key when building a relationship. Status is normalised, and every dimension build now checks for case collisions and fails loudly rather than letting the problem surface later in Power BI.

### Known data limitations

- **Construction values are self reported** by the applicant and not appraised. Roughly 84% of permits carry a usable figure, so any dollar total understates activity. The coverage percentage is tracked in `dq_results`.
- **About 9,000 permits have no postal code** and cannot be placed on a map.
- **38 rows have impossible date sequences**, mostly permits recorded as issued before they were applied for, which are likely backdated entries. These are flagged and their durations set to null.
- **Region names are approximate.** The source contains no district names, so regions are derived from the first two characters of the postal code. Scarborough, North York and Etobicoke map cleanly; other regions cross old borough boundaries and are named broadly.
- **No sale prices or property values.** That data is licensed and not publicly available. This is a construction and development dataset, not a housing market one.

---

## Design decisions

**Bronze preserves, silver cleans, gold shapes.** Bronze stores exactly what the City published, including values like `DO NOT UPDATE OR DELETE THIS INFO FIELD`, so the pipeline can be rebuilt from scratch without redownloading. All cleaning rules live in one notebook so the historical load and future incremental loads cannot diverge.

**Silver writes with a merge, not an append.** Comparing downloads taken a week apart showed that active permits change constantly: 940 new rows, 1,741 removed and 2,568 updated in seven days. Cleared permits also change, with 1,144 updated. Matching on the key means the job can be rerun after a failure without creating duplicates. Verified by running the notebook twice and confirming the row count does not move.

**Gold rebuilds rather than merges.** Gold is always silver filtered and renamed, so rebuilding from scratch is idempotent by construction.

**Exclusions are flags, not deletions.** Silver keeps every row and records what should be excluded. Filtering happens in gold, so a decision can be reversed without reloading anything, and the counts can be published rather than hidden.

**`dq_results` is appended on purpose.** Every other table is replaced on each run. A single quality measurement proves little; the same measurement over time is a monitor.

**Columns are documented in code.** Every gold column carries a description in Unity Catalog, applied by the notebook because overwriting a table clears them. These descriptions are also what the question answering layer will read in order to write correct SQL.

**Permit lifecycle is traceable.** Of the 1,741 permits that left the active file during the comparison week, 1,716 appeared in the cleared file. Permits can be followed from application through to completion.

---

## Repository

```
bronze_layer_nb.ipynb    Load raw CSVs into Delta, no transformation
silver_layer_nb.ipynb    Clean, key, deduplicate, flag, merge
gold_layer_nb.ipynb      Filter, rename, document, build star schema
```

---

## Status

**Built**

- Azure Data Lake Storage with managed identity authentication
- Bronze, silver and gold layers in Databricks
- Idempotent merge, verified by repeated runs
- Quality checks written to a tracked table
- Star schema with documented columns

**In progress**

- Daily ingestion job against the City's CKAN API
- Databricks Workflow to orchestrate the four notebooks on a schedule
- Power BI report: approval speed, what and where, data quality
- Natural language question answering over the gold layer, with SQL validation and query logging

The data is currently a snapshot taken on 14 September 2026. The pipeline is written for incremental loading and the silver merge is already idempotent, so scheduling it requires no change to the transformation logic.

---

## Source

City of Toronto Open Data, Building Permits: Active Permits and Cleared Permits.

Raw inputs: 205,931 active and 436,794 cleared rows.
