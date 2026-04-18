# Job Execution Foundation

## Operating Modes

When Teraoka is disabled, the logger keeps the existing operator workflow:

- Manual product selection remains the production context.
- Scans do not require job acceptance.
- Existing local-first scan durability, printing, downtime, and sync flows remain unchanged.

When Teraoka is enabled, the logger treats the current Teraoka job as a proposed production context:

- A proposed job is created from the Teraoka status payload.
- The operator is prompted to accept the job before scanning.
- Accepted jobs become the active production context for the logger.
- The accepted job product code is selected in the existing product selector, which updates the normal dependent product fields.

## Proposed vs Accepted Jobs

`proposed_job` is the latest job observed from Teraoka/ERP. It is not active and does not authorize scanning by itself.

`active_job` is the operator-accepted job context. Teraoka-enabled scanning is allowed only when the active job matches the current proposed job.

If the proposed Teraoka job changes, the logger requires a fresh operator acceptance before scanning against the new context.

## Modules Introduced

- `job_execution.models`
  - Defines `JobContext`, the small immutable job model used by the logger.
  - Carries future-facing fields such as target quantity, actual quantity, remaining quantity, percent complete, projected finish, and behind/ahead status.

- `job_execution.context`
  - Owns `JobContextManager`.
  - Tracks proposed and active job state.
  - Provides acceptance and active-job matching helpers.

- `job_execution.metrics`
  - Provides pure helper functions for quantity and completion calculations.
  - Keeps future job metric calculations away from UI and scan orchestration.

- `job_execution.teraoka_adapter`
  - Converts the existing Teraoka status shape into a `JobContext`.
  - Preserves the current Teraoka client/status contract.

- `ui.job_acceptance_dialog`
  - Builds the explicit operator acceptance dialog.
  - Accepts callbacks from the main app and does not own business rules.

## Assumptions and Limitations

- This phase does not add full MES compliance rules.
- This phase does not change dashboard schema outputs or add dashboard job views.
- Active job state is in-memory for this foundation phase.
- Product selection after acceptance uses the logger's existing product selection/update path.
- Teraoka remains optional; disabled mode is intentionally a no-op for job acceptance.

## Manual Verification Checklist

- Start the logger with Teraoka disabled and confirm startup behavior is unchanged.
- With Teraoka disabled, select a product manually and scan normally.
- Enable Teraoka with a connected job and confirm the job acceptance dialog appears.
- Confirm the dialog shows job ID, sequence, product code, target quantity, actual quantity, remaining quantity, percent complete, and workcenter.
- Accept the proposed job and confirm the logger product selection changes to the job product code.
- Confirm dependent product fields update as they do after normal product selection.
- Confirm scanning is blocked while a Teraoka job is proposed but not accepted.
- Confirm scanning works after accepting the proposed Teraoka job.
- Confirm local scan persistence, label printing, and Teraoka receipt enqueue still occur after an accepted scan.
- Confirm normal startup, health display, downtime handling, and sync behavior have no regressions.
