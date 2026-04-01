# Speech Filters Handoff

Date: 2026-04-01
Repo completed: `C:\Users\rkafl\Documents\Projects\speech-filters`
GitHub: `https://github.com/JavaKnowledgeBase/speech-core`
Latest known fix commit: `ba75dfa` (`Fix seed runtime and API startup issues`)

## What was completed

### Output filter architecture

The output-filter service now has a more explicit architecture for child-facing and parent-facing responses.

Completed capabilities:
- explicit `output_kind` routing
- explicit architecture reporting (`rules_only` vs `hybrid_rules_model`)
- policy matrix per output kind
- environment-aware request context
- request-level limits and verbosity caps
- dedicated routes for caregiver alerts and environment guidance

Important files in `speech-filters`:
- `app/models.py`
- `app/policy_matrix.py`
- `app/pipeline.py`
- `app/providers.py`
- `app/main.py`
- `app/filters/`

### Vector-db and persistence foundation

Completed capabilities:
- Supabase-aware repository layer with in-memory fallback
- starter vector entities for target profiles, reference vectors, child attempts, output-filter profiles, and environment standards
- retrieval flow for modality match and blended target match
- attempt ingestion that stores top reference match and cosine similarity
- JSON and CSV importers for targets and reference vectors
- seed/import script and generated starter reference dataset

Important files in `speech-filters`:
- `app/vector_entities.py`
- `app/repositories.py`
- `app/vector_retrieval.py`
- `app/vector_retrieval_models.py`
- `app/importers.py`
- `scripts/seed_supabase.py`
- `scripts/generate_reference_seed.py`
- `seed_data/`
- `sql/supabase_schema.sql`

### Operational status

Completed and verified:
- Supabase schema applied successfully
- starter seed pushed successfully
- API now starts successfully with `uvicorn app.main:app --reload`
- dry-run seeding works offline
- test suite passed at `172 passed`

Recent bug fixes that matter for later integration:
- fixed malformed import corruption in `app/main.py`
- fixed `seed_supabase.py --dry-run` so it no longer tries to call Supabase during local planning
- fixed repository/data seed behavior so seed data can stay local until explicit upsert time

## What is still not finished

This repo is a strong scaffold, but not the full production speech system yet.

Still pending:
- real production embeddings instead of scaffold/generated vectors
- dense per-target multimodal reference collection beyond the starter seed set
- real environment image ingestion and analysis
- production-grade retrieval directly optimized inside Supabase/pgvector queries
- auth, RBAC, and tenant-safe access patterns
- full main-app wiring so the body app uses this filter/vector layer in real workflows

## What the main body app should do next

In `speech-intellegence`, the next work should not rebuild this logic from scratch. It should reorganize and wire the main app around what now exists.

Recommended body-app priorities:
1. treat `speech-filters` as the current source of truth for output filtering and starter vector persistence contracts
2. identify overlapping logic in the body app and remove or consolidate duplicates
3. create a clean integration layer for:
   - output filtering
   - target/reference retrieval
   - child-attempt ingestion
   - environment-standard checks
4. reorganize the body app into clearer modules around:
   - session orchestration
   - speaking workflow
   - environment checks
   - output filtering gateway
   - vector retrieval and attempt scoring
   - caregiver/clinician surfaces
5. keep the child experience optimized for tablet, TV, and desktop while reducing text-heavy paths

## Suggested reorganization map for `speech-intellegence`

Recommended top-level lanes for the body app:
- `app/orchestration/` for conductor flow and agent coordination
- `app/sessions/` for session lifecycle and speaking workflow
- `app/speech/` for target progression, attempts, and scoring orchestration
- `app/environment/` for room checks and environment standards
- `app/output_filtering/` for integration with the filter service/contracts
- `app/vectors/` for target/reference/attempt repository integration
- `app/ui/` or frontend shells for tablet, TV, desktop experiences

## Immediate next integration tasks for the body app

1. inspect the current `speech-intellegence` app structure and mark duplicate or obsolete logic
2. define where the body app should call the output-filter layer before any child or parent output
3. define where child attempts should be written and where retrieval should be queried
4. add integration contracts or client wrappers instead of scattering raw calls
5. preserve the speaking-first purpose while simplifying architecture where possible

## Important reminder for the next Codex pass

The next pass in `speech-intellegence` should assume:
- the filter service already exists and works
- the vector-db scaffold already exists and is seeded
- the immediate job is integration and reorganization, not re-inventing those pieces
