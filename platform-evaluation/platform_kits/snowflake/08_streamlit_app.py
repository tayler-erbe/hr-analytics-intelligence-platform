"""08 — Streamlit in Snowflake: public-data role explorer (kit v0.1, 2026-11-06).

PUBLIC DATA ONLY (O*NET 31.0, SUCSS class catalog, IPEDS, QCEW, QWI).
Mapping suggestions are unreviewed; similarity scores are not probabilities.

Deploy (worksheet, role HR_KIT_ADMIN), after uploading this file to the stage:
    snow stage copy 08_streamlit_app.py @HR_KIT.APPS.APP_STAGE/role_explorer/ --overwrite
    CREATE OR REPLACE STREAMLIT HR_KIT.APPS.ROLE_EXPLORER
      FROM '@HR_KIT.APPS.APP_STAGE/role_explorer'
      MAIN_FILE = '08_streamlit_app.py'
      QUERY_WAREHOUSE = HR_KIT_WH
      RUNTIME_NAME = 'SYSTEM$WAREHOUSE_RUNTIME'   -- explicit; 2026_06 BCR makes container runtime the default
      TITLE = 'HR public role explorer';
    GRANT USAGE ON STREAMLIT HR_KIT.APPS.ROLE_EXPLORER TO ROLE HR_KIT_ANALYST;
Note that a Streamlit in Snowflake app runs with the OWNER's rights. Viewers see what HR_KIT_ADMIN
can see, so the row and masking policies in 07 evaluate CURRENT_ROLE() as the owner. Record this
for the G1 rubric item, and never point this app at restricted data.
The "Analyst test" tab calls the Cortex Analyst REST API through _snowflake.send_snow_api_request.
That works in the warehouse runtime; verify the endpoint and response shape in your account.
"""
import json
import time

import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session

session = get_active_session()
session.query_tag = "hr_kit:08_streamlit"

SEARCH_SERVICE = "HR_KIT.AI_EVAL.ONET_ROLE_SEARCH"
SEMANTIC_VIEW = "HR_KIT.CURATED.HR_PUBLIC_SV"
AREAS = {"17019": "Champaign County", "17031": "Cook County", "17167": "Sangamon County", None: "Illinois (statewide)"}

st.set_page_config(page_title="HR public role explorer", layout="wide")
st.title("HR public role explorer")
st.caption("Public data only: O*NET 31.0 (CC BY 4.0, USDOL/ETA), Illinois SUCSS class catalog, IPEDS, "
           "BLS QCEW, Census QWI. Not university HR records. Mapping candidates are unreviewed.")


@st.cache_data(ttl=600, show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    return session.sql(sql, params=list(params)).to_pandas()


def sql_literal(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "''")


tab_role, tab_search, tab_context, tab_analyst = st.tabs(
    ["Class → occupation", "Search O*NET", "Labor-market context", "Analyst test"])

# ---------------------------------------------------------------- Class → occupation
with tab_role:
    classes = q("SELECT source_record_id, class_code, class_title FROM HR_KIT.CURATED.V_SUCSS_CLASS ORDER BY class_title")
    classes.columns = [c.lower() for c in classes.columns]
    label = classes.apply(lambda r: f"{r.class_title} ({r.class_code}) · rec {r.source_record_id}", axis=1)
    pick = st.selectbox("SUCSS class (catalog record, not a vacancy or employee)", label.tolist())
    rec = classes.iloc[label.tolist().index(pick)]

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Lexical baseline candidates")
        lex = q("""SELECT c.candidate_rank, c.onetsoc_code, o.occupation_title, c.lexical_score
                   FROM HR_KIT.CURATED.V_SUCSS_ONET_CANDIDATE c
                   JOIN HR_KIT.CURATED.V_ONET_OCCUPATION o USING (onetsoc_code)
                   WHERE c.source_record_id = ? ORDER BY c.candidate_rank""", (int(rec.source_record_id),))
        st.dataframe(lex, hide_index=True, use_container_width=True)
    with c2:
        st.subheader("Embedding top-5 (from 02, if sampled)")
        try:
            emb = q("""SELECT e.embed_rank, e.onetsoc_code, o.occupation_title, ROUND(e.cosine_sim, 4) AS cosine_sim
                       FROM HR_KIT.AI_EVAL.R_EMBED_TOP5 e
                       JOIN HR_KIT.CURATED.V_ONET_OCCUPATION o USING (onetsoc_code)
                       WHERE e.source_record_id = ? ORDER BY e.embed_rank""", (int(rec.source_record_id),))
            st.dataframe(emb, hide_index=True, use_container_width=True) if len(emb) else st.info("Class not in the 02 sample.")
        except Exception as exc:  # table may not exist yet
            st.info(f"Run 02_ai_functions.sql first ({type(exc).__name__}).")

    codes = sorted(set(lex.iloc[:, 1].tolist()))
    if codes:
        occ = st.selectbox("Inspect an O*NET occupation", codes)
        d = q("SELECT occupation_title, occupation_description FROM HR_KIT.CURATED.V_ONET_OCCUPATION WHERE onetsoc_code = ?", (occ,))
        st.markdown(f"**{d.iloc[0, 0]}** — {d.iloc[0, 1]}")
        tasks = q("SELECT task_id, task_type, task_text FROM HR_KIT.CURATED.V_ONET_TASK WHERE onetsoc_code = ? ORDER BY task_id", (occ,))
        st.dataframe(tasks, hide_index=True, use_container_width=True)
        tech = q("""SELECT technology_example, hot_technology, in_demand FROM HR_KIT.CURATED.V_ONET_TECH_SKILL
                    WHERE onetsoc_code = ? ORDER BY technology_example LIMIT 50""", (occ,))
        with st.expander(f"Technology skills ({len(tech)})"):
            st.dataframe(tech, hide_index=True, use_container_width=True)
    st.warning("Title similarity is a starting point for human review. It is not a mapping decision, "
               "competency assessment, or AI-exposure score.")

# ---------------------------------------------------------------- Search
with tab_search:
    query = st.text_input("Describe duties or a role", "maintains databases and runs backups")
    only_occ = st.checkbox("Occupation profiles only (exclude task chunks)")
    if st.button("Search", type="primary") and query.strip():
        payload = {"query": query.strip(), "limit": 10,
                   "columns": ["doc_id", "doc_type", "onetsoc_code", "occupation_title", "search_text"]}
        if only_occ:
            payload["filter"] = {"@eq": {"doc_type": "occupation"}}
        t0 = time.time()
        raw = session.sql(
            f"SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW('{SEARCH_SERVICE}', '{sql_literal(json.dumps(payload))}')"
        ).collect()[0][0]
        st.caption(f"{time.time() - t0:.2f}s round trip")
        res = pd.DataFrame(json.loads(raw).get("results", []))
        st.dataframe(res, hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- Context
with tab_context:
    st.subheader("Census QWI — colleges & universities (NAICS 6113), stable turnover rate")
    qwi = q("""SELECT COALESCE(county_fips, 'IL') AS area, quarter_start, turnovrs, hira, sep, earns
               FROM HR_KIT.CURATED.V_QWI_HIGHER_ED
               WHERE county_fips IN ('17019','17031','17167') OR county_fips IS NULL ORDER BY quarter_start""")
    qwi.columns = [c.lower() for c in qwi.columns]
    if len(qwi):
        qwi["area"] = qwi["area"].map(lambda a: AREAS.get(a if a != "IL" else None, a))
        st.line_chart(qwi.pivot_table(index="quarter_start", columns="area", values="turnovrs"))
        st.caption("Quarterly rates; gaps are suppressed or missing cells, not zero.")
    st.subheader("BLS QCEW — NAICS 611310 average weekly wage")
    qc = q("""SELECT area_fips, own_code, quarter_start, avg_wkly_wage FROM HR_KIT.CURATED.V_QCEW
              WHERE industry_code = '611310' AND area_fips IN ('17000','17019','17031','17167')
              ORDER BY quarter_start""")
    qc.columns = [c.lower() for c in qc.columns]
    if len(qc):
        own = st.radio("Ownership", sorted(qc.own_code.astype(str).unique()), horizontal=True,
                       help="1 federal, 2 state, 3 local government, 5 private")
        sub = qc[qc.own_code.astype(str) == own]
        st.line_chart(sub.pivot_table(index="quarter_start", columns="area_fips", values="avg_wkly_wage"))

# ---------------------------------------------------------------- Analyst test harness
with tab_analyst:
    st.write("Sends one accuracy-test question to Cortex Analyst, logs the answer, and compares the "
             "result set with the expected SQL. A human still sets the verdict.")
    tests = q("SELECT test_id, question, expected_behavior FROM HR_KIT.AI_EVAL.ANALYST_TESTS ORDER BY test_id")
    tests.columns = [c.lower() for c in tests.columns]
    tid = st.selectbox("Test", tests.test_id.tolist())
    row = tests[tests.test_id == tid].iloc[0]
    st.markdown(f"**{row.question}**  \nExpected behavior: `{row.expected_behavior}`")
    run_no = st.number_input("Run number", 1, 10, 1)
    if st.button("Ask Cortex Analyst"):
        import _snowflake  # available inside Streamlit in Snowflake

        body = {"messages": [{"role": "user", "content": [{"type": "text", "text": row.question}]}],
                "semantic_view": SEMANTIC_VIEW}
        t0 = time.time()
        resp = _snowflake.send_snow_api_request("POST", "/api/v2/cortex/analyst/message", {}, {}, body, None, 60000)
        elapsed = time.time() - t0
        status = resp.get("status")
        content = json.loads(resp.get("content") or "{}")
        st.caption(f"HTTP {status} · {elapsed:.1f}s")
        texts, sql = [], None
        for item in content.get("message", {}).get("content", []):
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
            elif item.get("type") == "sql":
                sql = item.get("statement")
            elif item.get("type") == "suggestions":
                texts.append("Suggestions: " + "; ".join(item.get("suggestions", [])))
        st.write("\n\n".join(texts) or "(no text)")
        if sql:
            st.code(sql, language="sql")
            try:
                st.dataframe(session.sql(sql).to_pandas(), use_container_width=True)
            except Exception as exc:
                st.error(f"Generated SQL failed: {exc}")
        session.sql(
            """INSERT INTO HR_KIT.AI_EVAL.R_ANALYST_RUNS
               (test_id, run_no, surface, asked_at, elapsed_s, request_id, response_text, generated_sql)
               SELECT ?, ?, 'ANALYST_API', CURRENT_TIMESTAMP(), ?, ?, ?, ?""",
            params=[tid, int(run_no), elapsed, content.get("request_id"), "\n\n".join(texts), sql],
        ).collect()
        if sql and row.expected_behavior == "ANSWER":
            cmp = session.sql("CALL HR_KIT.AI_EVAL.COMPARE_ANALYST_RUN(?, ?, 'ANALYST_API')",
                              params=[tid, int(run_no)]).collect()[0][0]
            st.info(f"Result-set comparison: {cmp}")
        st.caption("Logged to HR_KIT.AI_EVAL.R_ANALYST_RUNS. Set behavior_observed and reviewer_verdict by hand.")
