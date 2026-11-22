# API reference: hmap

84 endpoint(s), read from the app's OpenAPI document.

| Endpoint | Handler |
|---|---|
| GET /api/agents | `backend/src/hmap/api/routers/system.py::agents` |
| GET /api/agents/capabilities | `backend/src/hmap/api/routers/system.py::capabilities` |
| POST /api/auth/forgot | `backend/src/hmap/api/routers/auth.py::forgot` |
| POST /api/auth/login | `backend/src/hmap/api/routers/auth.py::login` |
| POST /api/auth/logout | `backend/src/hmap/api/routers/auth.py::logout` |
| POST /api/auth/logout-all | `backend/src/hmap/api/routers/auth.py::logout` |
| GET /api/auth/me | `backend/src/hmap/api/routers/auth.py::me` |
| PATCH /api/auth/me | `backend/src/hmap/api/routers/auth.py::update_me` |
| POST /api/auth/password | `backend/src/hmap/api/routers/auth.py::change_password` |
| POST /api/auth/register | `backend/src/hmap/api/routers/auth.py::register` |
| POST /api/auth/reset | `backend/src/hmap/api/routers/auth.py::reset` |
| POST /api/auth/ws-ticket | `backend/src/hmap/api/routers/auth.py::ws_ticket` |
| GET /api/coding/heads/{project_id} | `backend/src/hmap/agents/coding/router.py::get_head` |
| GET /api/coding/runs/{project_id} | `backend/src/hmap/agents/coding/router.py::list_runs` |
| GET /api/coding/runs/{project_id}/{task_id} | `backend/src/hmap/agents/refine/router.py::get_run` |
| GET /api/coding/runs/{project_id}/{task_id}/diff | `backend/src/hmap/agents/refine/router.py::get_diff` |
| GET /api/coding/runs/{project_id}/{task_id}/files | `backend/src/hmap/agents/coding/router.py::get_files` |
| POST /api/coding/runs/{project_id}/{task_id}/revise | `backend/src/hmap/agents/coding/router.py::request_changes` |
| GET /api/coding/runs/{project_id}/{task_id}/workspace.zip | `backend/src/hmap/agents/coding/router.py::download` |
| GET /api/dead-letters | `backend/src/hmap/api/routers/system.py::dead_letters` |
| GET /api/doc_intel/document-model/{project_id} | `backend/src/hmap/agents/doc_intel/router.py::get_document_model` |
| GET /api/doc_intel/pages/{project_id}/{artifact_id}/{page} | `backend/src/hmap/agents/doc_intel/router.py::page_image` |
| GET /api/doc_intel/requirements/{project_id} | `backend/src/hmap/agents/doc_intel/router.py::get_requirements` |
| PUT /api/doc_intel/requirements/{project_id} | `backend/src/hmap/agents/doc_intel/router.py::edit_requirements` |
| GET /api/docgen/bundles/{project_id} | `backend/src/hmap/agents/docgen/router.py::list_bundles` |
| GET /api/docgen/bundles/{project_id}/{task_id} | `backend/src/hmap/agents/docgen/router.py::get_bundle` |
| GET /api/docgen/bundles/{project_id}/{task_id}/architecture.svg | `backend/src/hmap/agents/docgen/router.py::architecture_svg` |
| GET /api/docgen/bundles/{project_id}/{task_id}/docstrings.diff | `backend/src/hmap/agents/docgen/router.py::docstrings` |
| GET /api/docgen/bundles/{project_id}/{task_id}/files/{name} | `backend/src/hmap/agents/docgen/router.py::get_file` |
| POST /api/docgen/bundles/{project_id}/{task_id}/regenerate | `backend/src/hmap/agents/docgen/router.py::regenerate` |
| GET /api/docgen/bundles/{project_id}/{task_id}/site.html | `backend/src/hmap/agents/docgen/router.py::site_html` |
| POST /api/docgen/check/{project_id} | `backend/src/hmap/agents/docgen/router.py::check` |
| GET /api/events | `backend/src/hmap/api/routers/system.py::events` |
| GET /api/health | `backend/src/hmap/api/routers/system.py::health` |
| GET /api/llm/usage | `backend/src/hmap/api/routers/system.py::llm_usage` |
| GET /api/ops/dlq | `backend/src/hmap/agents/ops/router.py::dlq` |
| GET /api/ops/explain/{task_id} | `backend/src/hmap/agents/ops/router.py::explain_task` |
| GET /api/ops/failures | `backend/src/hmap/agents/ops/router.py::failures` |
| GET /api/ops/overview | `backend/src/hmap/agents/ops/router.py::overview` |
| POST /api/ops/replay/{task_id} | `backend/src/hmap/agents/ops/router.py::replay` |
| GET /api/planning/capabilities | `backend/src/hmap/api/routers/system.py::capabilities` |
| GET /api/planning/plan/{project_id} | `backend/src/hmap/agents/planning/router.py::get_plan` |
| PUT /api/planning/plan/{project_id} | `backend/src/hmap/agents/planning/router.py::edit_plan` |
| POST /api/planning/plan/{project_id}/approve | `backend/src/hmap/agents/planning/router.py::decide` |
| POST /api/planning/plan/{project_id}/replan | `backend/src/hmap/agents/planning/router.py::start_replan` |
| GET /api/planning/plan/{project_id}/roadmap.md | `backend/src/hmap/agents/planning/router.py::roadmap_markdown` |
| GET /api/projects | `backend/src/hmap/api/routers/projects.py::list_projects` |
| POST /api/projects | `backend/src/hmap/api/routers/projects.py::create_project` |
| DELETE /api/projects/{project_id} | `backend/src/hmap/api/routers/projects.py::delete_project` |
| GET /api/projects/{project_id} | `backend/src/hmap/api/routers/projects.py::get_project` |
| PATCH /api/projects/{project_id} | `backend/src/hmap/api/routers/projects.py::update_project` |
| POST /api/projects/{project_id}/approval | `backend/src/hmap/api/routers/projects.py::decide_approval` |
| GET /api/projects/{project_id}/artifacts | `backend/src/hmap/api/routers/projects.py::list_artifacts` |
| GET /api/projects/{project_id}/artifacts/{artifact_id} | `backend/src/hmap/api/routers/projects.py::download_artifact` |
| POST /api/projects/{project_id}/documents | `backend/src/hmap/api/routers/projects.py::upload_document` |
| POST /api/projects/{project_id}/plan | `backend/src/hmap/api/routers/projects.py::submit_plan` |
| POST /api/projects/{project_id}/runs | `backend/src/hmap/api/routers/projects.py::start_run` |
| POST /api/projects/{project_id}/stop | `backend/src/hmap/api/routers/projects.py::stop_project` |
| GET /api/projects/{project_id}/tasks | `backend/src/hmap/api/routers/projects.py::list_tasks` |
| POST /api/projects/{project_id}/tasks | `backend/src/hmap/api/routers/projects.py::create_task` |
| GET /api/refine/policy | `backend/src/hmap/agents/refine/router.py::policy` |
| GET /api/refine/runs/{project_id} | `backend/src/hmap/agents/coding/router.py::list_runs` |
| POST /api/refine/runs/{project_id} | `backend/src/hmap/api/routers/projects.py::start_run` |
| GET /api/refine/runs/{project_id}/{run_id} | `backend/src/hmap/agents/refine/router.py::get_run` |
| GET /api/refine/runs/{project_id}/{run_id}/diff | `backend/src/hmap/agents/refine/router.py::get_diff` |
| GET /api/refine/runs/{project_id}/{run_id}/outputs/{index} | `backend/src/hmap/agents/refine/router.py::get_output` |
| GET /api/research/pages/{project_id}/{artifact_id} | `backend/src/hmap/agents/research/router.py::get_page` |
| GET /api/research/providers | `backend/src/hmap/agents/research/router.py::providers` |
| GET /api/research/runs/{project_id} | `backend/src/hmap/agents/coding/router.py::list_runs` |
| POST /api/research/runs/{project_id} | `backend/src/hmap/api/routers/projects.py::start_run` |
| GET /api/research/runs/{project_id}/{task_id} | `backend/src/hmap/agents/refine/router.py::get_run` |
| GET /api/tasks/{task_id} | `backend/src/hmap/api/routers/projects.py::get_task` |
| POST /api/tasks/{task_id}/cancel | `backend/src/hmap/api/routers/projects.py::cancel_task` |
| GET /api/testing/quarantine/{project_id} | `backend/src/hmap/agents/testing/router.py::get_quarantine` |
| POST /api/testing/quarantine/{project_id}/release | `backend/src/hmap/agents/testing/router.py::release_test` |
| GET /api/testing/runs/{project_id} | `backend/src/hmap/agents/coding/router.py::list_runs` |
| GET /api/testing/runs/{project_id}/{task_id} | `backend/src/hmap/agents/refine/router.py::get_run` |
| GET /api/testing/runs/{project_id}/{task_id}/log | `backend/src/hmap/agents/testing/router.py::get_log` |
| POST /api/testing/runs/{project_id}/{task_id}/rerun | `backend/src/hmap/agents/testing/router.py::rerun` |
| GET /api/verify/runs/{project_id} | `backend/src/hmap/agents/coding/router.py::list_runs` |
| GET /api/verify/runs/{project_id}/{task_id} | `backend/src/hmap/agents/refine/router.py::get_run` |
| POST /api/verify/runs/{project_id}/{task_id}/follow-up | `backend/src/hmap/agents/verify/router.py::follow_up` |
| GET /api/verify/security | `backend/src/hmap/agents/verify/router.py::security` |
| GET /api/verify/table | `backend/src/hmap/agents/verify/router.py::decision_table` |

## `/api/agents`

### GET /api/agents

Agents

- Handler: `backend/src/hmap/api/routers/system.py::agents`

### GET /api/agents/capabilities

Which plug-in serves each capability, and whether it is still a stub ("no silent stubs", Sprint 10).

- Handler: `backend/src/hmap/api/routers/system.py::capabilities`

## `/api/auth`

### POST /api/auth/forgot

Forgot

- Handler: `backend/src/hmap/api/routers/auth.py::forgot`
- Request body: `ForgotIn`

### POST /api/auth/login

Login

- Handler: `backend/src/hmap/api/routers/auth.py::login`
- Request body: `LoginIn`

### POST /api/auth/logout

Ends this session. Works without a valid session (clears cookies either way); with one, CSRF is checked.

- Handler: `backend/src/hmap/api/routers/auth.py::logout`

### POST /api/auth/logout-all

Logout All

- Handler: `backend/src/hmap/api/routers/auth.py::logout`

### GET /api/auth/me

Me

- Handler: `backend/src/hmap/api/routers/auth.py::me`

### PATCH /api/auth/me

Update Me

- Handler: `backend/src/hmap/api/routers/auth.py::update_me`
- Request body: `ProfileIn`

### POST /api/auth/password

Change Password

- Handler: `backend/src/hmap/api/routers/auth.py::change_password`
- Request body: `PasswordIn`

### POST /api/auth/register

Register

- Handler: `backend/src/hmap/api/routers/auth.py::register`
- Request body: `RegisterIn`

### POST /api/auth/reset

Reset

- Handler: `backend/src/hmap/api/routers/auth.py::reset`
- Request body: `ResetIn`

### POST /api/auth/ws-ticket

A single-use, 60-second ticket for opening the live-event WebSocket (browsers cannot send our cookies to the API's WebSocket port through the Next.js proxy).

- Handler: `backend/src/hmap/api/routers/auth.py::ws_ticket`

## `/api/coding`

### GET /api/coding/heads/{project_id}

Get Head

- Handler: `backend/src/hmap/agents/coding/router.py::get_head`
- Parameters: project_id: string (path)

### GET /api/coding/runs/{project_id}

List Runs

- Handler: `backend/src/hmap/agents/coding/router.py::list_runs`
- Parameters: project_id: string (path)

### GET /api/coding/runs/{project_id}/{task_id}

Get Run

- Handler: `backend/src/hmap/agents/refine/router.py::get_run`
- Parameters: project_id: string (path), task_id: string (path)

### GET /api/coding/runs/{project_id}/{task_id}/diff

Get Diff

- Handler: `backend/src/hmap/agents/refine/router.py::get_diff`
- Parameters: project_id: string (path), task_id: string (path)

### GET /api/coding/runs/{project_id}/{task_id}/files

Get Files

- Handler: `backend/src/hmap/agents/coding/router.py::get_files`
- Parameters: project_id: string (path), task_id: string (path), path:  (query)

### POST /api/coding/runs/{project_id}/{task_id}/revise

A human asks for changes to a coding step's result: a ``code.revise`` task (bounded rounds).

- Handler: `backend/src/hmap/agents/coding/router.py::request_changes`
- Parameters: project_id: string (path), task_id: string (path)
- Request body: `ReviseIn`

### GET /api/coding/runs/{project_id}/{task_id}/workspace.zip

Download

- Handler: `backend/src/hmap/agents/coding/router.py::download`
- Parameters: project_id: string (path), task_id: string (path)

## `/api/dead-letters`

### GET /api/dead-letters

Messages that exhausted their retries, for the user's projects. Platform-level dead letters (no project) are listed without their body, which could contain anything.

- Handler: `backend/src/hmap/api/routers/system.py::dead_letters`

## `/api/doc_intel`

### GET /api/doc_intel/document-model/{project_id}

Get Document Model

- Handler: `backend/src/hmap/agents/doc_intel/router.py::get_document_model`
- Parameters: project_id: string (path)

### GET /api/doc_intel/pages/{project_id}/{artifact_id}/{page}

Page Image

- Handler: `backend/src/hmap/agents/doc_intel/router.py::page_image`
- Parameters: project_id: string (path), artifact_id: string (path), page: integer (path)

### GET /api/doc_intel/requirements/{project_id}

Get Requirements

- Handler: `backend/src/hmap/agents/doc_intel/router.py::get_requirements`
- Parameters: project_id: string (path), artifact_id:  (query), version:  (query)

### PUT /api/doc_intel/requirements/{project_id}

Edit Requirements

- Handler: `backend/src/hmap/agents/doc_intel/router.py::edit_requirements`
- Parameters: project_id: string (path)
- Request body: `RequirementsEdit`

## `/api/docgen`

### GET /api/docgen/bundles/{project_id}

List Bundles

- Handler: `backend/src/hmap/agents/docgen/router.py::list_bundles`
- Parameters: project_id: string (path)

### GET /api/docgen/bundles/{project_id}/{task_id}

Get Bundle

- Handler: `backend/src/hmap/agents/docgen/router.py::get_bundle`
- Parameters: project_id: string (path), task_id: string (path)

### GET /api/docgen/bundles/{project_id}/{task_id}/architecture.svg

Architecture Svg

- Handler: `backend/src/hmap/agents/docgen/router.py::architecture_svg`
- Parameters: project_id: string (path), task_id: string (path)

### GET /api/docgen/bundles/{project_id}/{task_id}/docstrings.diff

The suggested docstrings as a patch (``git apply``); the agent never applies it.

- Handler: `backend/src/hmap/agents/docgen/router.py::docstrings`
- Parameters: project_id: string (path), task_id: string (path)

### GET /api/docgen/bundles/{project_id}/{task_id}/files/{name}

Get File

- Handler: `backend/src/hmap/agents/docgen/router.py::get_file`
- Parameters: project_id: string (path), task_id: string (path), name: string (path)

### POST /api/docgen/bundles/{project_id}/{task_id}/regenerate

Regenerate

- Handler: `backend/src/hmap/agents/docgen/router.py::regenerate`
- Parameters: project_id: string (path), task_id: string (path)

### GET /api/docgen/bundles/{project_id}/{task_id}/site.html

Every document on one static page (docs-as-site); served as a download with a strict CSP.

- Handler: `backend/src/hmap/agents/docgen/router.py::site_html`
- Parameters: project_id: string (path), task_id: string (path)

### POST /api/docgen/check/{project_id}

Check

- Handler: `backend/src/hmap/agents/docgen/router.py::check`
- Parameters: project_id: string (path)
- Request body: `CheckIn`

## `/api/events`

### GET /api/events

Recent events the user may see (newest ``limit``), oldest first. ``project_id`` narrows to one project.

- Handler: `backend/src/hmap/api/routers/system.py::events`
- Parameters: project_id:  (query), after_seq: integer (query), limit: integer (query)

## `/api/health`

### GET /api/health

Public: lets the sign-in page show whether the server is up. Queue names/depths carry no user data.

- Handler: `backend/src/hmap/api/routers/system.py::health`

## `/api/llm`

### GET /api/llm/usage

Gateway mode and team key-pool counters per key fingerprint (no secrets; ``{}`` without keys or in fake mode).

- Handler: `backend/src/hmap/api/routers/system.py::llm_usage`

## `/api/ops`

### GET /api/ops/dlq

Dlq

- Handler: `backend/src/hmap/agents/ops/router.py::dlq`

### GET /api/ops/explain/{task_id}

Explain Task

- Handler: `backend/src/hmap/agents/ops/router.py::explain_task`
- Parameters: task_id: string (path)

### GET /api/ops/failures

Failures

- Handler: `backend/src/hmap/agents/ops/router.py::failures`
- Parameters: limit: integer (query)

### GET /api/ops/overview

Overview

- Handler: `backend/src/hmap/agents/ops/router.py::overview`

### POST /api/ops/replay/{task_id}

Replay a dead-lettered task as a NEW execution (never automatic, never blind: research §26).

- Handler: `backend/src/hmap/agents/ops/router.py::replay`
- Parameters: task_id: string (path)
- Request body: `ReplayIn`

## `/api/planning`

### GET /api/planning/capabilities

Capabilities

- Handler: `backend/src/hmap/api/routers/system.py::capabilities`

### GET /api/planning/plan/{project_id}

Get Plan

- Handler: `backend/src/hmap/agents/planning/router.py::get_plan`
- Parameters: project_id: string (path), version:  (query)

### PUT /api/planning/plan/{project_id}

Edit Plan

- Handler: `backend/src/hmap/agents/planning/router.py::edit_plan`
- Parameters: project_id: string (path)
- Request body: `PlanEdit`

### POST /api/planning/plan/{project_id}/approve

Decide

- Handler: `backend/src/hmap/agents/planning/router.py::decide`
- Parameters: project_id: string (path)
- Request body: `Decision`

### POST /api/planning/plan/{project_id}/replan

Start Replan

- Handler: `backend/src/hmap/agents/planning/router.py::start_replan`
- Parameters: project_id: string (path)
- Request body: `ReplanIn`

### GET /api/planning/plan/{project_id}/roadmap.md

Roadmap Markdown

- Handler: `backend/src/hmap/agents/planning/router.py::roadmap_markdown`
- Parameters: project_id: string (path)

## `/api/projects`

### GET /api/projects

The signed-in user's projects (never anyone else's). ``archived=true`` lists the archive instead.

- Handler: `backend/src/hmap/api/routers/projects.py::list_projects`
- Parameters: q:  (query), archived: boolean (query)

### POST /api/projects

Create Project

- Handler: `backend/src/hmap/api/routers/projects.py::create_project`
- Request body: `ProjectIn`

### DELETE /api/projects/{project_id}

Stops running work, erases the project's files and removes it from the workspace (irreversible).

- Handler: `backend/src/hmap/api/routers/projects.py::delete_project`
- Parameters: project_id: string (path)

### GET /api/projects/{project_id}

Get Project

- Handler: `backend/src/hmap/api/routers/projects.py::get_project`
- Parameters: project_id: string (path)

### PATCH /api/projects/{project_id}

Update Project

- Handler: `backend/src/hmap/api/routers/projects.py::update_project`
- Parameters: project_id: string (path)
- Request body: `ProjectPatch`

### POST /api/projects/{project_id}/approval

Human-in-the-loop gate: approve or reject the submitted plan.

- Handler: `backend/src/hmap/api/routers/projects.py::decide_approval`
- Parameters: project_id: string (path)
- Request body: `ApprovalIn`

### GET /api/projects/{project_id}/artifacts

Every stored file of the project, newest first, with the task (and run) that produced it; uploads carry the ``name`` they were uploaded as ("Part A/brief.pdf", or "request.txt" for a typed request).

- Handler: `backend/src/hmap/api/routers/projects.py::list_artifacts`
- Parameters: project_id: string (path)

### GET /api/projects/{project_id}/artifacts/{artifact_id}

The file's bytes, SHA-256 verified. Owner only; never served as HTML (no script can run from a result).

- Handler: `backend/src/hmap/api/routers/projects.py::download_artifact`
- Parameters: project_id: string (path), artifact_id: string (path), version:  (query), download: boolean (query)

### POST /api/projects/{project_id}/documents

Store the uploads as immutable artifacts and start ONE run with all of them (the pipeline begins with extraction). Each document keeps its folder, so later steps can treat folders as parts of the work. Everything is checked before anything is stored: one unusable file rejects the whole upload and no

- Handler: `backend/src/hmap/api/routers/projects.py::upload_document`
- Parameters: project_id: string (path)

### POST /api/projects/{project_id}/plan

Submit a TaskGraph directly (normally the pipeline does this after plan.generate).

- Handler: `backend/src/hmap/api/routers/projects.py::submit_plan`
- Parameters: project_id: string (path), require_approval: boolean (query)
- Request body: `TaskGraph`

### POST /api/projects/{project_id}/runs

Run the project again with a (new) request; earlier runs stay in the history.

- Handler: `backend/src/hmap/api/routers/projects.py::start_run`
- Parameters: project_id: string (path)
- Request body: `RunIn`

### POST /api/projects/{project_id}/stop

The human's Stop button: cancel all unfinished tasks and close the run (409 if it already finished).

- Handler: `backend/src/hmap/api/routers/projects.py::stop_project`
- Parameters: project_id: string (path)

### GET /api/projects/{project_id}/tasks

List Tasks

- Handler: `backend/src/hmap/api/routers/projects.py::list_tasks`
- Parameters: project_id: string (path), run:  (query)

### POST /api/projects/{project_id}/tasks

Create Task

- Handler: `backend/src/hmap/api/routers/projects.py::create_task`
- Parameters: project_id: string (path)
- Request body: `TaskIn`

## `/api/refine`

### GET /api/refine/policy

Policy

- Handler: `backend/src/hmap/agents/refine/router.py::policy`

### GET /api/refine/runs/{project_id}

List Runs

- Handler: `backend/src/hmap/agents/coding/router.py::list_runs`
- Parameters: project_id: string (path)

### POST /api/refine/runs/{project_id}

Check and improve one artifact of the project now (a ``refine.run`` task; its context artifacts — the document model for requirements, the requirements and report for a plan — are attached automatically).

- Handler: `backend/src/hmap/api/routers/projects.py::start_run`
- Parameters: project_id: string (path)
- Request body: `RefineIn`

### GET /api/refine/runs/{project_id}/{run_id}

Get Run

- Handler: `backend/src/hmap/agents/refine/router.py::get_run`
- Parameters: project_id: string (path), run_id: string (path)

### GET /api/refine/runs/{project_id}/{run_id}/diff

Get Diff

- Handler: `backend/src/hmap/agents/refine/router.py::get_diff`
- Parameters: project_id: string (path), run_id: string (path), a: integer (query), b: integer (query)

### GET /api/refine/runs/{project_id}/{run_id}/outputs/{index}

Get Output

- Handler: `backend/src/hmap/agents/refine/router.py::get_output`
- Parameters: project_id: string (path), run_id: string (path), index: integer (path)

## `/api/research`

### GET /api/research/pages/{project_id}/{artifact_id}

Get Page

- Handler: `backend/src/hmap/agents/research/router.py::get_page`
- Parameters: project_id: string (path), artifact_id: string (path), task_id:  (query)

### GET /api/research/providers

Providers

- Handler: `backend/src/hmap/agents/research/router.py::providers`

### GET /api/research/runs/{project_id}

List Runs

- Handler: `backend/src/hmap/agents/coding/router.py::list_runs`
- Parameters: project_id: string (path)

### POST /api/research/runs/{project_id}

Research one or more questions now (an ad-hoc ``research.run`` task in this project).

- Handler: `backend/src/hmap/api/routers/projects.py::start_run`
- Parameters: project_id: string (path)
- Request body: `ResearchIn`

### GET /api/research/runs/{project_id}/{task_id}

Get Run

- Handler: `backend/src/hmap/agents/refine/router.py::get_run`
- Parameters: project_id: string (path), task_id: string (path)

## `/api/tasks`

### GET /api/tasks/{task_id}

Get Task

- Handler: `backend/src/hmap/api/routers/projects.py::get_task`
- Parameters: task_id: string (path)

### POST /api/tasks/{task_id}/cancel

Cancel Task

- Handler: `backend/src/hmap/api/routers/projects.py::cancel_task`
- Parameters: task_id: string (path)
- Request body: `CancelIn`

## `/api/testing`

### GET /api/testing/quarantine/{project_id}

Get Quarantine

- Handler: `backend/src/hmap/agents/testing/router.py::get_quarantine`
- Parameters: project_id: string (path)

### POST /api/testing/quarantine/{project_id}/release

Release Test

- Handler: `backend/src/hmap/agents/testing/router.py::release_test`
- Parameters: project_id: string (path)
- Request body: `ReleaseIn`

### GET /api/testing/runs/{project_id}

List Runs

- Handler: `backend/src/hmap/agents/coding/router.py::list_runs`
- Parameters: project_id: string (path)

### GET /api/testing/runs/{project_id}/{task_id}

Get Run

- Handler: `backend/src/hmap/agents/refine/router.py::get_run`
- Parameters: project_id: string (path), task_id: string (path)

### GET /api/testing/runs/{project_id}/{task_id}/log

Get Log

- Handler: `backend/src/hmap/agents/testing/router.py::get_log`
- Parameters: project_id: string (path), task_id: string (path)

### POST /api/testing/runs/{project_id}/{task_id}/rerun

Rerun

- Handler: `backend/src/hmap/agents/testing/router.py::rerun`
- Parameters: project_id: string (path), task_id: string (path)

## `/api/verify`

### GET /api/verify/runs/{project_id}

List Runs

- Handler: `backend/src/hmap/agents/coding/router.py::list_runs`
- Parameters: project_id: string (path)

### GET /api/verify/runs/{project_id}/{task_id}

Get Run

- Handler: `backend/src/hmap/agents/refine/router.py::get_run`
- Parameters: project_id: string (path), task_id: string (path)

### POST /api/verify/runs/{project_id}/{task_id}/follow-up

A human asks for more research: on the chosen claims (default: what the check flagged) + a re-check.

- Handler: `backend/src/hmap/agents/verify/router.py::follow_up`
- Parameters: project_id: string (path), task_id: string (path)
- Request body: `FollowUpIn`

### GET /api/verify/security

Platform-wide (like the agents page): what agents may send, and what was refused recently. No secrets: key ids and fingerprints only.

- Handler: `backend/src/hmap/agents/verify/router.py::security`

### GET /api/verify/table

Decision Table

- Handler: `backend/src/hmap/agents/verify/router.py::decision_table`
