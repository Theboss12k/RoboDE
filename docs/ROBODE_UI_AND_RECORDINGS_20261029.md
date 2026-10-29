# RoboDE branding, LLM setup and recordings

The visible IDE name is RoboDE. The wordmark aligns beside the user-supplied robot emblem. All shared welcome screens display “Plan, control and command your robot.” Server and Business App document titles and login branding use RoboDE. Internal package identifiers and existing saved data paths retain compatibility.

Project IDs are visible and selectable beneath the project selector, with a clipboard button and a manual-copy fallback.

LLM configuration now offers form setup or Python function setup using Monaco, paste/import, a downloadable runnable sample, and saved-adapter invocation. Prompt fields were removed from global configuration, tests, and task inspectors. Private provider prefixes are preserved through UI edits, excluded from public provider metadata and snapshots, and supplied internally. Newly compiled source manifests omit legacy task prompt fields. Historical runs and revisions remain unchanged.

Trusted custom LLM functions execute in disposable subprocess workers, using selected connection settings and credentials, with bounded answers, generic errors and timeout/cancellation cleanup. This does not implement an OS sandbox.

Validation: 40 backend tests and 12 browser/Electron tests passed; both production builds passed. Existing Monaco chunk-size and test-environment Starlette/httpx advisories remain. Three narrated, captioned videos cover both IDE editions and the Business App. See [recordings and chapter index](../artifacts/walkthroughs/README.md).
