# Codex TODO

## Best pause point for brain work

A good pause point for the deeper "brain part" work is after these two items are done:

1. Supabase-backed repository layer replaces most in-memory storage.
2. First frontend shell exists for tablet, TV, and desktop.

That will be the moment when the system shape is stable enough that deeper reasoning work can focus on improving the intelligence, instead of chasing moving infrastructure.

## What the brain pass should learn from current work

The next deeper reasoning pass should study what is already built in this repo:

- agent roles and orchestration flow
- output filter logic
- communication profiles
- environment standards and room checks
- curriculum and vector scaffolding
- workflow queue behavior
- current session API behavior

## Brain-pass review task

When we pause for brain work, the review should explicitly figure out:

- what should be added
- what should be deleted
- what should be simplified
- what should be split into separate agents
- what should stay heuristic for now
- what should become model-driven next

## Current additions likely needed

- real persistence via Supabase
- real embedding generation and vector retrieval
- child-attempt ingestion pipeline
- environment image ingestion and scene analysis
- frontend shells for child, parent, clinician
- auth and RBAC
- durable workflow integration
- analytics and outcome tracking

## Current deletions or reductions likely needed

- reduce placeholder heuristics once real services are wired
- remove duplicated logic between old engine code and new orchestrator paths
- trim any API surface that does not support speaking-first outcomes
- avoid text-heavy child UX paths

## Decision standard

Every future addition should be tested against this question:

Does it help the child speak more confidently and more often?

If not, it may belong in a lower-priority lane or should be removed.

## Immediate working focus until that pause

- keep building infrastructure and integration shape
- keep committing checkpoints to GitHub
- keep aligning with speaking-first purpose
- keep protecting tablet, TV, and desktop support

## 2026-04-01 Integration checkpoint from `speech-filters`

Completed in sibling repo `speech-filters` and should now be treated as available work:
- output filter architecture with explicit output kinds and policy matrix
- environment-aware filtering and request limits
- Supabase-backed repository scaffold with seed/import flow
- starter target/reference/attempt/environment entities
- retrieval endpoints for modality and blended target match
- attempt ingestion flow
- applied Supabase schema and successful starter seed

Immediate next focus in `speech-intellegence`:
- reorganize the body app around these completed pieces
- avoid duplicating filter/vector logic already built in `speech-filters`
- add a clean integration layer for output filtering, retrieval, and attempt ingestion
- identify deletions, consolidations, and module boundaries before deeper brain work

See `notes/speech-filters-handoff-2026-04-01.md` for the full handoff.

