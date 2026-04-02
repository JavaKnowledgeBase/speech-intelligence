create extension if not exists vector;

create table organizations (
  id uuid primary key default gen_random_uuid(),
  external_org_id text unique not null,
  name text not null,
  created_at timestamptz not null default now()
);

create table children (
  id uuid primary key default gen_random_uuid(),
  external_child_id text unique not null,
  organization_id uuid references organizations(id),
  caregiver_external_id text not null,
  clinician_external_id text not null,
  name text not null,
  age integer not null,
  engagement_baseline numeric(5,2) not null default 0.75,
  created_at timestamptz not null default now()
);

create table communication_profiles (
  id uuid primary key default gen_random_uuid(),
  external_profile_id text unique not null,
  audience text not null,
  owner_external_id text not null,
  preferred_tone text not null,
  preferred_pacing text not null,
  sensory_notes jsonb not null default '[]'::jsonb,
  banned_styles jsonb not null default '[]'::jsonb,
  preferred_phrases jsonb not null default '[]'::jsonb,
  calmness_level integer not null,
  verbosity_limit integer not null,
  encouragement_level integer not null,
  avoid_overstimulation boolean not null default true,
  avoid_exclamations boolean not null default true,
  avoid_chatter boolean not null default true,
  created_at timestamptz not null default now()
);

create table environment_profiles (
  id uuid primary key default gen_random_uuid(),
  child_id uuid references children(id) on delete cascade,
  external_environment_profile_id text unique not null,
  room_label text not null,
  baseline_room_embedding vector(4),
  baseline_visual_clutter_score numeric(5,2) not null,
  baseline_noise_score numeric(5,2) not null,
  baseline_lighting_score numeric(5,2) not null,
  baseline_distraction_notes jsonb not null default '[]'::jsonb,
  recommended_adjustments jsonb not null default '[]'::jsonb,
  preferred_objects jsonb not null default '[]'::jsonb,
  avoid_objects jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table curriculum_targets (
  id uuid primary key default gen_random_uuid(),
  external_target_id text unique not null,
  target_type text not null,
  display_text text not null,
  phoneme_group text not null,
  month_index integer not null,
  difficulty_level integer not null,
  created_at timestamptz not null default now()
);

create table reference_vectors (
  id uuid primary key default gen_random_uuid(),
  external_reference_id text unique not null,
  target_id uuid references curriculum_targets(id) on delete cascade,
  modality text not null,
  source_label text not null,
  quality_score numeric(5,2) not null,
  age_band text not null,
  notes text not null default '',
  embedding vector(4),
  created_at timestamptz not null default now()
);

create table child_attempt_vectors (
  id uuid primary key default gen_random_uuid(),
  external_attempt_id text unique not null,
  child_id uuid references children(id) on delete cascade,
  target_id uuid references curriculum_targets(id) on delete cascade,
  external_session_id text not null,
  audio_embedding vector(4),
  lip_embedding vector(4),
  emotion_embedding vector(4),
  noise_embedding vector(4),
  top_match_reference_external_id text,
  cosine_similarity numeric(6,3) not null default 0,
  success_flag boolean not null default false,
  created_at timestamptz not null default now()
);

create table goals (
  id uuid primary key default gen_random_uuid(),
  child_id uuid references children(id) on delete cascade,
  external_goal_id text unique not null,
  target_text text not null,
  cue text not null,
  difficulty integer not null,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table sessions (
  id uuid primary key default gen_random_uuid(),
  external_session_id text unique not null,
  child_id uuid references children(id) on delete cascade,
  current_goal_id uuid references goals(id),
  current_target text not null,
  status text not null,
  retries_used integer not null default 0,
  reward_points integer not null default 0,
  started_at timestamptz not null,
  completed_at timestamptz
);

create table session_events (
  id uuid primary key default gen_random_uuid(),
  session_id uuid references sessions(id) on delete cascade,
  kind text not null,
  detail text not null,
  created_at timestamptz not null default now()
);

create table alerts (
  id uuid primary key default gen_random_uuid(),
  external_alert_id text unique not null,
  session_id uuid references sessions(id) on delete cascade,
  child_id uuid references children(id) on delete cascade,
  caregiver_external_id text not null,
  reason text not null,
  message text not null,
  acknowledged boolean not null default false,
  created_at timestamptz not null default now()
);

create table clinician_reviews (
  id uuid primary key default gen_random_uuid(),
  external_review_id text unique not null,
  session_id uuid references sessions(id) on delete cascade,
  child_id uuid references children(id) on delete cascade,
  clinician_external_id text not null,
  priority text not null,
  status text not null default 'queued',
  summary text not null,
  created_at timestamptz not null default now()
);

create table progress_snapshots (
  id uuid primary key default gen_random_uuid(),
  child_id uuid references children(id) on delete cascade,
  target_text text not null,
  attempts integer not null default 0,
  successes integer not null default 0,
  mastery_score numeric(5,2) not null default 0,
  last_practiced_at timestamptz,
  unique(child_id, target_text)
);

-- Voice runtime audit tables
-- Required for full session auditability (medical record trail).

create table voice_transcripts (
  id uuid primary key default gen_random_uuid(),
  session_id uuid references sessions(id) on delete cascade,
  transcript text not null,
  is_final boolean not null default false,
  elapsed_ms integer not null default 0,
  attention_score numeric(5,2),
  confidence numeric(5,4),
  source text not null default 'unknown',
  created_at timestamptz not null default now()
);

create index voice_transcripts_session_idx on voice_transcripts(session_id, created_at);

create table voice_checkpoints (
  id uuid primary key default gen_random_uuid(),
  session_id uuid references sessions(id) on delete cascade,
  checkpoint_kind text not null,
  elapsed_ms integer not null default 0,
  detail text,
  created_at timestamptz not null default now()
);

create index voice_checkpoints_session_idx on voice_checkpoints(session_id, created_at);
