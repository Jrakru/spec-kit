---
description: Generate a Portfolio/Product PRD (PPRD) Markdown document using the PPRD template.
scripts:
  sh: scripts/bash/check-prerequisites.sh --json --paths-only
  ps: scripts/powershell/check-prerequisites.ps1 -Json -PathsOnly
---

The user input to you can be provided directly by the agent or as a command argument - you MUST consider it before proceeding with the prompt (if not empty).

User input:

{ARGS}

Goal: Create a new Portfolio/Product PRD (PPRD) file by resolving the repository’s declarative layout and (optionally) drafting full content when `MODE=author`. Prefer a single file named per `files.pprd` (e.g., `specs/pprd.md`) unless the repository explicitly opts into a multi-PPRD convention.

Execution steps:

1. Run `{SCRIPT}` from the repository root ONCE and parse its JSON for `REPO_ROOT`. All subsequent paths are absolute.
2. Determine the canonical specs root: run `scripts/bash/spec-root.sh` (or PowerShell variant) and capture its absolute output as `SPEC_ROOT`.
3. Resolve the PPRD layout: run `scripts/bash/resolve-template.sh --json pprd` (or PowerShell) and parse `TEMPLATE_PATH`, then load the template.
4. Read `.specs/.specify/templates/layout.yaml` (e.g., run `scripts/bash/read-layout.sh` and parse `LAYOUT_FILES_PPRD`) to locate `files.pprd`; default to `pprd.md` when unset.
5. Parse the user input to extract fields using the `$ARGUMENTS` contract:
   - Required: `PPRD_ID` (e.g., `001`, `2025Q1-01`) and `TITLE` (short, human readable).
   - Optional: `VIS`, `STR`, `ROAD`, `MODE`, `BRIEF`, plus section hints (`NSM`, `INPUT_METRICS`, `GUARDRAILS`, `PERSONAS`, `CAPABILITIES`, `CONSTRAINTS`, `NON_GOALS`, `RISKS`, `RELEASE`, `MEASUREMENT`).
   - Accept key/value, quoted pairs, or `ID: Title` forms.
   - If `PPRD_ID` or `TITLE` cannot be inferred, STOP and ask the user for succinct values before continuing.
6. Compute `PPRD_PATH`:
   - Single-file convention: `PPRD_PATH = SPEC_ROOT + '/' + files.pprd`.
   - Multi-file convention (only if the user explicitly requests): slugify `<PPRD_ID>-<TITLE>` and place under `SPEC_ROOT/pprd/`.
   - If the destination exists and is non-empty, append a short header noting the attempted generation and exit without overwriting content.
7. Populate required boilerplate in all modes:
   - Replace the heading `# PPRD-[ID]: [Portfolio / Product PRD Title]` with `# PPRD-<PPRD_ID>: <TITLE>`.
   - Replace the links line with: `**Links:** Vision (<VIS or N/A>), Strategy (<STR or N/A>), Roadmap entry (<ROAD or N/A>)`.

8. If `MODE` is omitted (default scaffold mode):
   - Write the untouched remainder of the template so humans can complete it later.
   - Output a summary with `PPRD_ID`, `TITLE`, `PPRD_PATH`, and `"mode":"scaffold"`.

9. If `MODE=author`, follow the AI Authoring Guide to draft every section with substantive content:
   1. Gather repository signal (best-effort):
      - Read `product/Roadmap.csv`, `product/ExperimentLedger.csv`, and `telemetry/events-template.yml` when present.
      - Skim `ssot-templates-solo-founder/docs/` strategy/vision docs and `.specs/.specify/templates/pprd-template.md` for structure.
   2. Use the BRIEF and section hints to ground content; only emit `TODO:` markers when critical information cannot be inferred responsibly. Each TODO must be specific.
   3. Draft sections 1–8 per guide:
      - Context & Vision: 2–3 sentences + 3–5 strategic pillars tied to north-star metrics.
      - Outcomes & Targets: NSM with baseline/target, 3–5 input metrics with definitions/targets, and 2–3 guardrails with thresholds.
      - Personas & JTBD: 1–2 personas, each with JTBD, pains, motivations.
      - Capability Map: 3–7 level-1 capabilities, optionally level-2 examples.
      - Constraints & Non-Goals: reliability, privacy/compliance, accessibility, platform limits, plus 3–5 explicit non-goals.
      - Risks & Unknowns: top 5 risks with mitigations/spikes.
      - Release Strategy: phasing, flags, canary/rollback, environments/migrations.
      - Measurement Plan: key events/properties (align with telemetry templates), dashboards/IDs, alert thresholds.
   4. Ensure metrics include numbers (label “proposed” if inferred) and no raw placeholders like `[x]` remain.
   5. Respect idempotency: if the destination already contains content, prepend a short note about the skipped authoring attempt instead of overwriting.
   6. After writing, emit a JSON-style status summary with per-section coverage (e.g., drafted vs TODOs).

10. For both modes, create directories as needed and write atomically. Always use absolute paths.
11. Final output: short report with `PPRD_ID`, `TITLE`, `PPRD_PATH`, selected mode, and section status (for author mode).

Notes:
- PPRDs are portfolio/product-level assets; do NOT modify feature spec files or Git branches.
- When required sources are missing, proceed with reasonable defaults and clearly mark assumptions.
- Preserve existing Clarifications or metadata if re-running in author mode against a pre-existing file.

Context for PPRD creation: {ARGS}
