# NextGen pipeline architecture drafts

User-facing terminology: [Anime Intake](ANIME_INTAKE.md) records the agreed
**Intake** section name and its purpose. It supersedes trial/preview labels for
that area without renaming internal code, configuration keys or these files.

These are reviewable design documents, **not implemented pipelines**. They
supersede informal routing assumptions when discussing the planned worker;
open decisions in each file must be resolved before implementing that behavior.

1. [Intake to the trial folder](INTAKE_TO_TRIAL.md): process ownership graph,
   identity/release/acquisition/verification/staging graph, worker handoff contract,
   configurable trial destination and unresolved policy/storage requirements.
2. [Keep to the permanent library](KEEP_TO_LIBRARY.md): explicit user/API decision,
   Sonarr copy/import proof, permanent destination, cleanup/integration branches
   and the decisions needed before those components are written.

The worker advances the pipeline through trusted registered routes. Handlers
return typed outcomes; feature adapters own domain rules. Worker completion,
successor creation and audit commit together after lease validation. Handlers do
not separately mark a job DONE and then enqueue its successor. No workflow
parent/child engine or work_items/to-do table is introduced.

Current queue/diagnostic/configuration/migration libraries are foundations only.
These drafts add no job handlers, worker loop, SQL, settings fields, management
API, deployment, imports, torrent operations or filesystem media changes. No
CI/tests/application code/SQL have been executed for this documentation change.


Implementation progress: PRs #103–#107 are merged. The async worker and trial/Keep
settings are foundations. The first opt-in handler adapter is documented in
[Job handlers](../jobs/README.md); its live identity/provider library remains
unimplemented. Neither the trial nor Keep pipeline is operational yet.
