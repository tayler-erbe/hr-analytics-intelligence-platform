"""Role explorer: a Databricks App (Streamlit) over PUBLIC occupation and labor-market tables.

Shows, for one Illinois SUCSS class record: the unreviewed lexical O*NET candidates, the kit's semantic candidates and
ai_classify group (if 02/03 were run), and public context for a chosen O*NET occupation. It never shows person-level data.

Runs as the app's service principal by default. Grant it USE CATALOG / USE SCHEMA / SELECT on the kit schemas and
CAN USE on the SQL warehouse. On-behalf-of-user authorization is a separate option (verify availability in workspace).
"""
import os

import pandas as pd
import streamlit as st
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem

CAT = os.getenv("KIT_CATALOG", "workspace")
SCH = os.getenv("KIT_SCHEMA", "hr_public")
EVAL = os.getenv("KIT_EVAL_SCHEMA", "hr_eval_results")
WAREHOUSE = os.getenv("DATABRICKS_WAREHOUSE_ID")

st.set_page_config(page_title="Role explorer (public data)", layout="wide")
w = WorkspaceClient()


@st.cache_data(ttl=600, show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Parameterized statement execution; values are bound, never string-formatted into SQL."""
    resp = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE,
        statement=sql,
        parameters=[StatementParameterListItem(name=k, value=str(v)) for k, v in params],
        wait_timeout="30s",
    )
    if resp.status and resp.status.error:
        raise RuntimeError(resp.status.error.message)
    cols = [c.name for c in resp.manifest.schema.columns]
    rows = resp.result.data_array if resp.result and resp.result.data_array else []
    return pd.DataFrame(rows, columns=cols)


def show(df, err):
    if err:
        st.warning(err)
    else:
        st.dataframe(df, hide_index=True)


def safe(sql, params=()):
    try:
        return q(sql, params), None
    except Exception as e:  # show the failure instead of hiding it
        return pd.DataFrame(), str(e)[:300]


st.title("Role explorer: Illinois civil service classes and O*NET occupations")
st.caption(
    "Public data only (SUCSS catalog, O*NET 31.0 CC BY 4.0, Census QWI, BLS QCEW). Candidate mappings are UNREVIEWED "
    "suggestions; similarity scores are not probabilities. SUCSS catalog records are not employees or vacancies."
)
if not WAREHOUSE:
    st.error("DATABRICKS_WAREHOUSE_ID is not set. Add a SQL warehouse resource with key 'sql-warehouse'.")
    st.stop()

search = st.text_input("Search SUCSS class titles", value="Information Technology")
classes, err = safe(
    f"SELECT source_record_id, class_code, class_title FROM {CAT}.{SCH}.sucss_class "
    "WHERE lower(class_title) LIKE concat('%', lower(:s), '%') ORDER BY class_title LIMIT 200",
    (("s", search),),
)
if err:
    st.error(err)
    st.stop()
if classes.empty:
    st.info("No matching class titles.")
    st.stop()

label = classes.apply(lambda r: f"{r.class_title} (code {r.class_code}, record {r.source_record_id})", axis=1)
pick = st.selectbox("Class record", range(len(classes)), format_func=lambda i: label.iloc[i])
rec = classes.iloc[pick]

left, right = st.columns(2)
with left:
    st.subheader("Lexical candidates (baseline)")
    lex, err = safe(
        f"SELECT c.rank, c.onetsoc_code, o.title, c.score FROM {CAT}.{SCH}.sucss_onet_candidate c "
        f"JOIN {CAT}.{SCH}.onet_occupation o USING (onetsoc_code) WHERE c.source_record_id = :id ORDER BY c.rank LIMIT 5",
        (("id", rec.source_record_id),),
    )
    show(lex, err)
with right:
    st.subheader("Semantic candidates (kit run, latest)")
    sem, err = safe(
        f"SELECT sem_rank, onetsoc_code, title, round(cosine, 3) AS cosine, run_id FROM {CAT}.{EVAL}.semantic_candidates "
        f"WHERE source_record_id = :id AND run_id = (SELECT max(run_id) FROM {CAT}.{EVAL}.semantic_candidates) ORDER BY sem_rank",
        (("id", rec.source_record_id),),
    )
    if err or sem.empty:
        st.info("Not in the 02 embedding sample (cost-capped) or 02 not run.")
    else:
        st.dataframe(sem, hide_index=True)
    grp, _ = safe(
        f"SELECT pred_major_group, run_id FROM {CAT}.{EVAL}.ai_classify_results WHERE source_record_id = :id "
        "ORDER BY executed_at DESC LIMIT 1",
        (("id", rec.source_record_id),),
    )
    if not grp.empty:
        st.write(f"ai_classify SOC major group: **{grp.iloc[0].pred_major_group}** (run {grp.iloc[0].run_id}; unreviewed)")

codes = sorted(set(lex.get("onetsoc_code", pd.Series(dtype=str))) | set(sem.get("onetsoc_code", pd.Series(dtype=str))))
if not codes:
    st.stop()
code = st.selectbox("Inspect O*NET occupation", codes)

occ, _ = safe(f"SELECT title, description FROM {CAT}.{SCH}.onet_occupation WHERE onetsoc_code = :c", (("c", code),))
if not occ.empty:
    st.subheader(f"{code} · {occ.iloc[0].title}")
    st.write(occ.iloc[0].description)
c1, c2 = st.columns(2)
with c1:
    st.markdown("**Core tasks (O*NET)**")
    tasks, err = safe(
        f"SELECT task FROM {CAT}.{SCH}.onet_task_statement WHERE onetsoc_code = :c AND task_type = 'Core' LIMIT 12",
        (("c", code),),
    )
    show(tasks, err)
with c2:
    st.markdown("**Technology skills (hot technologies first)**")
    tech, err = safe(
        f"SELECT DISTINCT example, hot_technology FROM {CAT}.{SCH}.onet_technology_skill WHERE onetsoc_code = :c "
        "ORDER BY hot_technology DESC, example LIMIT 25",
        (("c", code),),
    )
    show(tech, err)

st.divider()
st.subheader("Labor-market context: Census QWI higher-education turnover (NAICS 6113)")
qwi, err = safe(
    f"SELECT make_date(CAST(year AS INT), (CAST(quarter AS INT) - 1) * 3 + 1, 1) AS quarter_start, "
    f"CAST(geography AS STRING) AS geography, CAST(turnovrs AS DOUBLE) AS turnover "
    f"FROM {CAT}.{SCH}.qwi_higher_ed WHERE CAST(sex AS STRING) = '0' AND agegrp = 'A00' ORDER BY quarter_start"
)
if err:
    st.warning(err)
elif not qwi.empty:
    qwi["turnover"] = pd.to_numeric(qwi["turnover"], errors="coerce")
    st.line_chart(qwi.pivot_table(index="quarter_start", columns="geography", values="turnover"))
    st.caption("Industry-level context, not occupation- or institution-specific. Turnover is a rate per QWI definitions.")
