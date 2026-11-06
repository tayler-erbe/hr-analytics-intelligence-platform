# 08 · Role explorer app (Databricks Apps, Streamlit)

**Free Edition:** up to 3 apps per account. An app stops automatically 24 hours after it is started, updated or redeployed, and you can restart it. Verify current limits.

1. Run 01 (required) and 02/03 (optional; the app shows "not in sample" without them).
2. **Compute → Apps → Create app → Custom** (UI labels may differ). Name: `hr-role-explorer`.
3. Add the resource **SQL warehouse** with key `sql-warehouse` and permission *Can use*.
4. Deploy from this folder: sync it to the workspace (Git folder or `databricks sync`), then deploy with the source path set to the folder (CLI: `databricks apps deploy hr-role-explorer --source-code-path /Workspace/.../08_app`; verify flags).
5. Grant the app's service principal `USE CATALOG`, `USE SCHEMA` and `SELECT` on `hr_public` and `hr_eval_results`. Give it **no** grant on `hr_gov_synthetic`.
6. Evidence: deployment time, the app URL screenshot, cold-start latency, and the result of a negative test. Temporarily point a query at `hr_gov_synthetic.appointments_governed`; it should be denied for the service principal. Also record pinned package versions and the app's audit events.

Limitation to record: by default the app reads data as its service principal, not as the viewer. Per-viewer row and column policies need on-behalf-of-user authorization, which is a verify-in-workspace item.
