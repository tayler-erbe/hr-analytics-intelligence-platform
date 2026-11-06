# Handoff: preserve, document, and back up server pipeline projects

Prepared November 2, 2026 for a separate project-management and repository chat.

## What I want to accomplish

I have several individual projects on a server that are mostly finalized. I want to preserve the work exactly as it exists, bring verified copies onto my laptop, organize each project into its own private GitHub repository under **terbe2022**, and then tidy and document the projects so they are understandable and maintainable.

I also want an ongoing second copy whenever I update a project, so a server failure or other accident does not wipe out my work. This is preservation and operational documentation first. Do not redesign the pipelines before establishing recoverable originals.

## Initial projects

These paths were supplied by me. Their absolute server locations have not yet been verified; do not assume a leading slash or a specific mount point.

| Project | Supplied server path | Proposed private repository name |
|---|---|---|
| Workforce planning | `datashare/Admin-pipeline/pipelines/workforce_planning` | `workforce-planning` |
| Proposals and awards | `datashare/Admin-pipeline/pipelines/proposals_and_awards` | `proposals-and-awards` |
| Job execution monitor | `datashare/Admin-pipeline/pipelines/job_execution_monitor` | `job-execution-monitor` |

Repository names are proposals, not existing repositories or final naming decisions. The requested owner is **terbe2022**, not the separate tayler-erbe account used elsewhere in the HR discussion.

The screenshot shows a JupyterLab-style file browser in `Admin-pipeline/pipelines`. Other visible folders are `archival_image_processing`, `archive`, `archivist_triage_tool`, and `Legislation_Pipeline`. These are potential later projects, not automatically included in the initial migration. Parent-level files include `cleanup.sh`, `rename_pipelines.sh`, and `wfp_20260812.zip`. Their contents, relevance, and integrity have not been inspected. Do not run cleanup/rename scripts or assume the ZIP is a complete current backup.

## Current state and boundaries

- The current local workspace is `C:\Users\terbe\Documents\ChatGPT\Databricks`.
- This chat built a separate synthetic HR analytics prototype. That code is not a copy of these server projects and must not be substituted for them.
- No server terminal, source code, repository history, database connection, or deployment configuration has been inspected for these three projects.
- No server archives have been created, downloaded, or verified in this work.
- No target repositories have been created or populated, and no synchronization or backup automation has been configured.
- My description that the projects are mostly finalized is project context, not a verified test or production-readiness result.
- This handoff is the requested deliverable. Do not treat it as a request to create a new chat, publish code, or start a recurring automation in the current chat.

## Preserve three distinct versions

1. **Original server snapshot:** a dated, unmodified preservation archive with an inventory and checksums, retained in an approved location. Include hidden files and existing Git metadata where present. Document exclusions or unreadable files; do not silently omit them.
2. **Repository baseline:** the complete approved code and required non-secret project assets, traceable to the original snapshot. Retain original source layout initially. Record exclusions and external dependencies explicitly.
3. **Maintained version:** subsequent documentation, cleanup, fixes, and tests committed separately so changes are easy to review and the original baseline remains recoverable.

“Exact working copy” means more than copying visible files. Inspect shared modules, parent configuration, symbolic links, environment files, notebook dependencies, database objects, scheduler settings, and paths outside each project. Copying a project folder may not make it independently runnable. Preserve existing Git history when available and appropriate; do not blindly replace the parent repository with three unrelated histories.

An exact private preservation copy and a GitHub code copy can legitimately differ. Credentials, restricted datasets, notebook outputs, logs, and confidential configuration may need to stay in approved restricted storage. Do not claim byte-for-byte GitHub equivalence when exclusions exist. A private personal GitHub repository is not automatically an approved destination for university material. Establish institutional authorization for the destination before transferring nonpublic work. Preserve originals before sanitizing a separate working copy; do not destroy the only recoverable source to make an upload safe.

## Work sequence for the receiving chat

### 1. Establish access and inventory

Confirm the server operating system, working directory, actual resolved project paths, available terminal/archive tools, and approved laptop/storage destination. Use read-only inspection first. Check file counts and sizes, hidden files, links, permissions, existing Git roots/remotes/branches, uncommitted changes, and ignored/untracked files. Avoid printing credentials or raw data into chat or logs.

Check whether these are subdirectories of one `Admin-pipeline` repository. Identify shared code and runtime configuration before choosing a standalone-repository layout. If the projects depend on active writers, arrange a consistent snapshot or document the capture window and recheck changed files. Do not stop production jobs without specific authorization.

### 2. Capture and verify originals

Create timestamped archives outside the folders being archived. ZIP is the user's preferred transfer form; if server metadata or links require a different preservation format, explain the tradeoff and retain an appropriate preservation copy as well.

For each snapshot, record project name, resolved source path, capture timestamp/timezone, archive format, file inventory, content checksums, archive checksum, exclusions, link handling, and capture consistency limitations. Do not dereference links into unrelated server paths without inspecting their targets.

Transfer via an approved route. Compare archive checksums on server and laptop, then test extraction into a separate directory. Compare extracted file contents against the manifest, including hidden files and case-sensitive filename collisions. Confirm required code files are present before declaring the backup valid. Keep the server originals untouched.

### 3. Establish private GitHub baselines

Use my **terbe2022** identity and verify the authenticated GitHub account and target owner before creating repositories. Inspect existing repositories first to avoid duplicates, overwrites, or unrelated history changes. Authentication could happen on the server or laptop; choose the approved location and avoid placing tokens in code, command history, archives, or documentation.

After destination authorization and code/content review, create one private repository per initial project, unless inspection shows shared dependencies require a documented alternative. Verify private visibility. Preserve appropriate history or document the history-splitting approach. Tag the preserved code baseline and make documentation/cleanup changes in later commits. Never force-push over existing work as a routine setup step.

Validate each remote with a fresh clone and the available safe checks. Record which files intentionally remain outside Git and how an authorized operator restores them. “Uploaded successfully” is not evidence that a project runs.

### 4. Document before changing behavior

Produce a README and supporting documentation for each project covering:

- Purpose, business owner, current status, entry points, and repository layout.
- Data sources, tables/views, SQL, joins, transformations, outputs, and destinations.
- Runtime and dependency versions; environment/configuration templates without secret values.
- Scheduling, orchestration, upstream/downstream dependencies, and deployment procedure.
- How to run safely, required access, side effects, validation, and expected results.
- Logging, monitoring, failure handling, restart behavior, troubleshooting, and rollback.
- Backup, restore, and the normal update workflow.
- Known limitations, unfinished work, and tests actually executed.

For workforce planning, trace exactly how data is pulled in. Inventory referenced datasets and database objects before writing platform-specific SQL. Determine the database engine first. Prefer metadata and definitions for the initial exploration; employee-level extracts are not needed to map the pipeline.

### 5. Tidy deliberately

Work on a copy or branch. Separate formatting/documentation changes from functional fixes. Identify dead code and obsolete outputs with evidence before removing anything. Maintain a change log connecting changes to tests. Do not execute production pipelines just to check whether they work: inspect their writes, messages, schedules, and downstream effects first. Use synthetic fixtures, dry-run modes, or isolated destinations where possible.

## Ongoing backup and update requirements

Define the authoritative working location for each project; do not leave server and laptop copies competing as equally current sources. A useful default workflow is:

1. Make a deliberate change in the designated working checkout.
2. Inspect the diff and run appropriate checks.
3. Commit with a meaningful message and push to the private remote.
4. Update an independent, versioned backup in approved storage and record success/failure.
5. Deploy or synchronize to the server through a documented, reviewed process.

This workflow is a proposal, not configured automation. Determine whether the user needs backup on every saved file or on every committed update; Git only captures committed content. Include a recovery path for uncommitted work if required. Backups must not automatically upload secrets or employee data to a personal account.

Keep historical recovery points rather than only a mirror that repeats deletions. Decide retention, encryption/access, frequency, failure notifications, and restore-test cadence. Keep at least one recovery copy independent of the live server. Test restoring code, approved configuration, and required assets into a clean location. Document recovery limitations where external systems or credentials are unavailable.

No automation should silently deploy code, delete prior archives, change public/private visibility, or overwrite divergent work. Obtain the necessary schedule/destination details before implementing recurring backup jobs.

## Completion checklist

- [ ] Actual project paths, Git roots, and shared dependencies verified.
- [ ] Three original snapshots preserved with manifests and checksums.
- [ ] Laptop transfers and independent extraction verified.
- [ ] Approved GitHub destination and terbe2022 identity verified.
- [ ] Private repositories/baselines established without losing existing work.
- [ ] Exclusions, restricted files, external dependencies, and restoration steps documented.
- [ ] Data lineage and operational documentation written for each project.
- [ ] Safe checks completed, with results and untested areas reported accurately.
- [ ] Normal update, backup, failure reporting, and recovery process implemented and tested.
- [ ] Final inventory lists archive locations, repository URLs, baseline commits/tags, documentation, and remaining issues without exposing secret values.

## Opening prompt for the new chat

> Help me preserve and organize three mostly finalized server pipeline projects: workforce_planning, proposals_and_awards, and job_execution_monitor under datashare/Admin-pipeline/pipelines. Read this handoff first. Start by verifying the server paths, Git structure, and shared dependencies without changing the originals. I want verified original archives on my laptop, approved private repositories under terbe2022, complete data-lineage and operational documentation, and a reliable secondary backup whenever I update the work. Preserve the exact baseline before cleanup, distinguish restricted preservation copies from GitHub-safe code, and report what is actually verified. The current synthetic HR analytics workspace is separate from these server projects.
