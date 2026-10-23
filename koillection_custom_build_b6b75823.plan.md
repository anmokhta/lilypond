---
name: Koillection Custom Build
overview: "Superseded 2026-10-22. Track B is sidecar-first (Compose); optional Koillection fork is phase B2 only — see goal-1-track-b.md."
todos:
  - id: goal-doc
    content: Rewrite goal-1-track-b.md as sidecar-first Compose + optional later fork
    status: completed
  - id: jwt-prereq
    content: JWT_PASSPHRASE in Portainer stack env
    status: completed
  - id: backup-fixture
    content: (B2 only) sanitised CI boot-test fixture
    status: cancelled
  - id: patch-datamodel
    content: (B2 only) position/displayGroup fork
    status: cancelled
  - id: patch-ordering-grouping
    content: (B2 only) ordering/grouping patch
    status: cancelled
  - id: patch-view-toggle
    content: (B2 only) list/grid toggle
    status: cancelled
  - id: patch-tests-staging
    content: (B2 only) patch tests + staging
    status: cancelled
  - id: ci-pipeline
    content: (B2 only) auto-update workflows
    status: cancelled
  - id: deploy-automation
    content: (B2 only) tertius deployer
    status: cancelled
isProject: false
---

# Superseded — see Goal 1 Track B

Canonical doc: [`goal-1-track-b.md`](goal-1-track-b.md)

- **B1 (default):** Compose sidecar beside stock Koillection — AI Organizer, AI Importer, optional Display-order helper.
- **B2 (optional later):** Custom Koillection image only if native groups / temporary list-grid toggle / first-class `position` are required.
