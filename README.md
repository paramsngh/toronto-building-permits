# Toronto Building Permits Pipeline

**[Live dashboard →](https://toronto-building-permits-1.onrender.com/)**

An end to end data pipeline on City of Toronto building permit data, built with Azure Data Lake Storage and Azure Databricks, with a live web dashboard and an AI layer that answers questions in plain English.

The analytical question: **how long does the City of Toronto take to issue a building permit, and is it getting faster or slower?** Approval speed is regularly cited in the debate about housing supply in Toronto, and this data can measure it directly.

---

## What this project solves

Toronto needs more housing, and every new home starts with a building permit. The City shares all its permit data online, but the raw files are messy. The same permit number is reused across different permit types, one project can show up as many as four times because plumbing, drain and HVAC permits are filed alongside the main permit, and costs are stored as text. If you just count the rows, you get far more permits than really exist.

This project cleans that data and answers three simple questions:

1. **How long does it take to get a permit?** By year and by area of the city.
2. **Where are new homes being built?** Counting homes, not just permits.
3. **What kind of work is happening?** Renovations, new buildings, trade work or demolitions.

You can explore the answers on the live dashboard, or type a question in plain English and get an answer back, with no SQL needed.

---

## Headline finding

Median days from application to permit issued, for permits applied for between 2020 and 2024:

| Year | Permits issued | Median days | Average days |
|---|---|---|---|
| 2020 | 19,428 | 28 | 68.0 |
| 2021 | 22,180 | 30 | 89.3 |
| 2022 | 21,184 | **34** | 74.2 |
| 2023 | 18,321 | 29 | 66.5 |
| 2024 | 19,007 | 23 | 52.6 |

Approval times rose through 2022 and then improved, with 2024 the fastest year in the window.

The gap between median and average is itself informative: a small number of permits take years, which pulls the average up by 30 to 60 days. Median is used throughout for that reason.

**2025 and 2026 are deliberately excluded.** Permits from those years that are still undecided have no issue date, so only the fast ones have been resolved and any average for those years looks artificially good. The cutoff is derived from the current date rather than hardcoded, so it advances on its own.

---

## Key findings

Numbers cover permits applied for from January 2020 to 14 September 2026. Approval times only use 2020 to 2024, for the reason above.

### Toronto at a glance

| Measure | Value |
|---|---|
| Permits since 2020 | 152,937 |
| Homes created | 143,601 |
| Construction value | $107.6B |
| Typical wait for a permit (2020 to 2024) | 28 days |
| Permits cancelled | 10.0% |
| Renovations / new buildings | 62% / 10% |

### Main findings

**1. Permits got slower, then faster.** The typical wait went from 28 days in 2020 up to 34 days in 2022, then dropped to 23 days in 2024, the fastest year so far.

**2. Counting permits gives the wrong picture.** Downtown has only 9% of the city's permits but 20% of its new homes (28,564).

**3. Downtown builds less often, but much bigger.** Only 2% of Downtown permits are for new buildings. But each one adds about 89 homes, compared to about 10 for the rest of the city. Downtown's housing comes from a few big condo towers.

**4. The 2022 slowdown hit the suburbs the most.** Downtown stayed around 30 days. Northwest Toronto jumped to 59 days, Etobicoke to 49 and Scarborough to 43. All areas got faster again by 2024.

**5. New homes go up and down much more than permits do.** The number of permits each year stayed about the same. But new homes dropped from 34,118 in 2021 to 14,813 in 2023, less than half.

### Surprising findings

**More permits does not mean more homes.** Scarborough and West Toronto have the most permits, but Downtown creates more homes than either. New buildings in Scarborough add about 6 homes each, so they are mostly houses, not towers.

**West and East Toronto are mostly renovating.** About three out of four permits there are renovations. Very few are new buildings.

**Permits with missing locations are often the big ones.** Permits without a usable postal code are only 6% of the total, but they make up 10% of new homes and 12% of construction value. That is why they are kept and shown as "Unknown area" instead of being removed.

**The fastest areas mostly do renovations.** East York, West and East Toronto have the shortest waits (21 days), and most of their permits are renovations, which are simpler to approve.

**Scarborough has the most cancelled permits.** 12.7% of its permits are cancelled, compared to about 8% in Midtown and Downtown.

### Why some numbers do not match

The headline finding table counts permits that were **issued**. The dashboard counts permits that were **applied for**. For example, 2020 has 19,428 issued permits but 21,481 applications.

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
     ┌──────┴───────────────┐
     ▼                      ▼
  Web dashboard        Ask the data API
  (Render)             (Groq + Databricks SQL)
                            │
                            ▼
                     Power BI (next)
```

Authentication from Databricks to storage uses a Unity Catalog storage credential backed by an Azure managed identity. No access keys exist anywhere in this repository.

---

## Ask the data: AI question answering

The dashboard includes a box where anyone can type a question in plain English, such as "How many permits were issued in Scarborough in 2025?"

1. **Groq writes the SQL.** An open source model running on Groq reads the question along with the gold table and column descriptions, and writes a Databricks SQL query.
2. **The query is checked.** The SQL is validated before it runs.
3. **Databricks runs it.** The query runs against the gold layer and the answer comes back with the exact SQL shown, so every answer can be verified.

The column descriptions stored in Unity Catalog are what the model reads in order to write correct SQL, which is why documenting every gold column matters.

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
| `ui_summary` | 96 | Region and year totals that power the web dashboard |
| `dq_results` | grows | Quality metrics appended on every run |

Relationships are many to one from the fact table to each dimension. `dim_date` connects three times, to application, issued and completed dates, so the same calendar can answer "applied for in March" and "issued in March" as separate questions.

---

## Data quality findings

The source data needed substantial work. These were the findings that changed the result rather than just tidying it.

### Summary

| Problem | What was done |
|---|---|
| About 6,850 rows had values shifted into the wrong columns | Fixed how the CSV is read in bronze |
| Permit number plus revision had 5,065 duplicates | Added permit type as a third key part |
| Plumbing, drain and HVAC permits often repeat a main permit | Excluded only when a main permit exists on the same project |
| 44,131 postal codes were just spaces | Converted to missing values |
| The same status existed with different capitalisation | Normalised, with a check that fails loudly |
| Costs were stored as text | Converted to numbers |
| 2025 and 2026 waits looked too fast, because slow permits are not finished yet | Left those years out of approval times |
| Postal codes do not match neighbourhoods | Grouped postal areas into ten regions, plus "Unknown area" |

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
- **About 9,000 permits have no usable postal code** and cannot be placed on a map. They appear as "Unknown area".
- **38 rows have impossible date sequences**, mostly permits recorded as issued before they were applied for, which are likely backdated entries. These are flagged and their durations set to null.
- **Region names are approximate.** The source contains no district names, so each postal area (the first three characters of the postal code) is mapped to one of ten regions. Postal areas do not line up exactly with neighbourhood or old borough boundaries.
- **No sale prices or property values.** That data is licensed and not publicly available. This is a construction and development dataset, not a housing market one.

---

## Design decisions

**Bronze preserves, silver cleans, gold shapes.** Bronze stores exactly what the City published, including values like `DO NOT UPDATE OR DELETE THIS INFO FIELD`, so the pipeline can be rebuilt from scratch without redownloading. All cleaning rules live in one notebook so the historical load and future incremental loads cannot diverge.

**Silver writes with a merge, not an append.** Comparing downloads taken a week apart showed that active permits change constantly: 940 new rows, 1,741 removed and 2,568 updated in seven days. Cleared permits also change, with 1,144 updated. Matching on the key means the job can be rerun after a failure without creating duplicates. Verified by running the notebook twice and confirming the row count does not move.

**Gold rebuilds rather than merges.** Gold is always silver filtered and renamed, so rebuilding from scratch is idempotent by construction.

**Exclusions are flags, not deletions.** Silver keeps every row and records what should be excluded. Filtering happens in gold, so a decision can be reversed without reloading anything, and the counts can be published rather than hidden.

**`dq_results` is appended on purpose.** Every other table is replaced on each run. A single quality measurement proves little; the same measurement over time is a monitor.

**Columns are documented in code.** Every gold column carries a description in Unity Catalog, applied by the notebook because overwriting a table clears them. These descriptions are also what the AI question answering layer reads in order to write correct SQL.

**Permit lifecycle is traceable.** Of the 1,741 permits that left the active file during the comparison week, 1,716 appeared in the cleared file. Permits can be followed from application through to completion.

**Built to run for close to $0.** Every choice, from serverless compute to keeping storage and processing lean, was made with cost in mind.

---

## Repository

```
bronze_layer_nb.ipynb    Load raw CSVs into Delta, no transformation
silver_layer_nb.ipynb    Clean, key, deduplicate, flag, merge
gold_layer_nb.ipynb      Filter, rename, document, build star schema
index.html               Live web dashboard
```

---

## Status

**Built**

- Azure Data Lake Storage with managed identity authentication
- Bronze, silver and gold layers in Databricks
- Idempotent merge, verified by repeated runs
- Quality checks written to a tracked table
- Star schema with documented columns
- Live web dashboard on Render
- AI question answering with Groq, with SQL validation, running against the gold layer

**Next steps**

- Power BI report: approval speed, what and where, data quality
- Live data from the City of Toronto's CKAN API, with a scheduled Databricks Workflow so the dashboard updates automatically

The data is currently a snapshot taken on 14 September 2026. The pipeline is written for incremental loading and the silver merge is already idempotent, so scheduling it requires no change to the transformation logic.

---

## Source

City of Toronto Open Data, Building Permits: Active Permits and Cleared Permits.

Raw inputs: 205,931 active and 436,794 cleared rows.
