"""
What the model is told about the data.

This file does more for answer quality than anything else in the backend.
If answers are wrong, the fix is almost always here rather than in the code.
"""

SCHEMA = """
permits.gold.fact_permits
  One row per permit revision, applied for 2020 onward.
  Already excludes plumbing, drain and HVAC permits that duplicate a main permit
  on the same project, and rows that are not building projects.

  permit_key              string   unique row id
  permit_number           string   City permit number, repeats across revisions
  revision_number         string   00 is the original application
  project_number          string   rows sharing it belong to the same project
  permit_type             string   New Houses, Small Residential Projects, Plumbing(PS) ...
  structure_type          string   SFD Detached, Apartment Building ...
  work_type               string   New Building, Interior Alterations, Demolition ...
  status                  string   Permit Issued, Inspection, Closed, Cancelled ...
  source                  string   'active' if in progress, 'cleared' if finished or cancelled
  application_date        date
  issued_date             date     null if refused, cancelled before issue, or still waiting
  completed_date          date     null if not finished
  application_year        int
  days_to_issue           int      null if never issued or dates were invalid
  days_to_complete        int
  estimated_cost_cad      double   declared by the applicant, not appraised, often null
  dwelling_units_created  double
  dwelling_units_lost     double
  postal_area             string   first three characters, for example M5V
  address                 string   street address only, contains no district name
  description             string   free text written by the applicant
  is_standalone_secondary boolean  trade permit with no main permit on the project
  is_cancelled            boolean
  is_issued               boolean
  has_bad_date            boolean

permits.gold.dim_postal_area
  postal_area  string
  region       string   Downtown Toronto, Midtown Toronto, East Toronto, East York,
                        West Toronto, York, North York, Scarborough, Etobicoke,
                        Northwest Toronto

permits.gold.dim_status
  status  string
  stage   string   Before issue, Issued in progress, Completed, Cancelled, Refused

permits.gold.dim_permit_type
  permit_type        string
  is_secondary_type  boolean

permits.gold.approval_trend
  application_year      int
  permits_issued        bigint
  median_days_to_issue  int
  avg_days_to_issue     double
  Only complete years. Use this for year over year approval time comparisons.
"""

RULES = """
Rules you must follow:

1. Return one SELECT statement and nothing else. No explanation, no markdown fences,
   no semicolon needed. Never write INSERT, UPDATE, DELETE, DROP or CREATE.

2. Region names do not exist in fact_permits. To filter or group by region, join
   dim_postal_area on postal_area.

3. The address column holds a street address only. It never contains a district or
   neighbourhood name, so never search it for words like Scarborough.

4. Exclude cancelled permits when counting homes created or summing construction value,
   because that work never happened. Use is_cancelled = false.

5. Never compare days_to_issue across years using fact_permits directly. Recent years
   are incomplete, since slow permits have not been decided yet, which makes them look
   artificially fast. Use approval_trend for any year over year comparison.

6. estimated_cost_cad is declared by the applicant and is null for most trade permits.
   It is fine to sum, but it understates real activity.

7. Prefer median over average for durations, using percentile_approx(col, 0.5).
   A small number of permits take years and drag averages up.

8. Always add a LIMIT, at most 200 rows.

9. If the question cannot be answered from these tables, return exactly:
   CANNOT_ANSWER
"""

EXAMPLES = """
Question: How many permits were applied for in Scarborough in 2025?
SQL:
SELECT count(*) AS permits
FROM permits.gold.fact_permits f
JOIN permits.gold.dim_postal_area d ON f.postal_area = d.postal_area
WHERE d.region = 'Scarborough' AND f.application_year = 2025
LIMIT 200

Question: Which region created the most homes since 2020?
SQL:
SELECT d.region, sum(f.dwelling_units_created) AS homes
FROM permits.gold.fact_permits f
JOIN permits.gold.dim_postal_area d ON f.postal_area = d.postal_area
WHERE f.is_cancelled = false
GROUP BY d.region
ORDER BY homes DESC
LIMIT 200

Question: Are permits faster now than in 2020?
SQL:
SELECT application_year, median_days_to_issue
FROM permits.gold.approval_trend
ORDER BY application_year
LIMIT 200

Question: What is the median approval time for new houses?
SQL:
SELECT percentile_approx(days_to_issue, 0.5) AS median_days
FROM permits.gold.fact_permits
WHERE permit_type = 'New Houses' AND days_to_issue IS NOT NULL
LIMIT 200

Question: What share of permits get cancelled?
SQL:
SELECT round(count_if(is_cancelled) / count(*) * 100, 1) AS cancelled_pct
FROM permits.gold.fact_permits
LIMIT 200

Question: Who is the mayor of Toronto?
SQL:
CANNOT_ANSWER
"""


def build_prompt(question: str) -> list[dict]:
    """Messages for the chat API: one system message, one user question."""
    system = (
        "You translate questions about Toronto building permit data into "
        "Databricks SQL.\n\n"
        f"Tables:\n{SCHEMA}\n{RULES}\n\nExamples:\n{EXAMPLES}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Question: {question}\nSQL:"},
    ]
