# Vector DB Design Note

## Proposed first curriculum

Initial 20 targets for the first month can be simple and imitation-friendly.

Example starter set:

- `a`
- `b`
- `m`
- `p`
- `t`
- `d`
- `k`
- `g`
- `s`
- `n`
- `0`
- `1`
- `2`
- `3`
- `4`
- `5`
- `6`
- `7`
- `8`
- `9`

This can later branch into clinically chosen words.

## Reference object model

For each target, store reference samples across four signal families:

- audio pattern embedding
- noise-context embedding
- lip/mouth-shape embedding
- emotion/prosody embedding

## Collection goal

Per target:

- `25` sound samples
- `25` noise-context samples
- `25` lip-pattern samples
- `25` emotion/prosody samples

This creates a dense reference neighborhood around each target instead of a single ideal example.

## Environment data need

We also need to treat the learning environment as part of the session quality model.

The parent should provide a `360 degree` picture of the learning space.

From that, the system should build an environment standard for the child.

That standard should track things like:

- visual clutter
- bright or distracting objects
- screen placement
- seating setup
- lighting comfort
- background movement risk
- environmental noise sources

At session start, the system should compare the current environment against the saved standard.

If something is likely to distract or discomfort the child, the system should ask the parent to adjust it.

## Special empathy/output filter data need

We also need a separate output-filter layer for everything the system says or does toward the child and parent.

That means the system should eventually store or infer patterns for:

- calming tone
- encouraging tone
- re-engagement tone
- parent guidance tone
- frustration-sensitive wording
- celebration wording that does not overstimulate
- low-arousal peaceful delivery
- non-chatty concise delivery

This can be built internally or supported by a third-party API, but it should act as a gate before final delivery.

## Filter behavior requirement

The filter should make the final output:

- constructive
- user friendly
- calming
- peaceful
- lower emotion
- less attention-grabbing in an irritating way

It should be applicable to both kid output and parent output.

It should prevent the system from sounding like an irritating chatter box.

## Suggested vector entities

### Target profile
- `target_id`
- `target_type`: `letter | number | word`
- `display_text`
- `phoneme_group`
- `difficulty_level`

### Reference vector
- `reference_id`
- `target_id`
- `modality`: `audio | noise | lip | emotion`
- `embedding`
- `source_label`
- `quality_score`
- `age_band`
- `notes`

### Child attempt vector
- `attempt_id`
- `child_id`
- `target_id`
- `session_id`
- `audio_embedding`
- `lip_embedding`
- `emotion_embedding`
- `noise_embedding`
- `top_match_reference_id`
- `cosine_similarity`
- `success_flag`

### Output filter profile
- `profile_id`
- `child_id`
- `caregiver_id`
- `preferred_tone_embedding`
- `safe_expression_embedding`
- `best_reengagement_style`
- `parent_guidance_style`
- `overstimulation_flags`
- `verbosity_limit`
- `calming_style_vector`

### Environment standard profile
- `environment_profile_id`
- `child_id`
- `baseline_room_embedding`
- `baseline_visual_clutter_score`
- `baseline_noise_score`
- `baseline_lighting_score`
- `baseline_distraction_notes`
- `recommended_adjustments`

## Matching loop

1. Child attempts target.
2. Generate embeddings for each modality.
3. Search nearest vectors by modality and blended score.
4. Identify which successful reference cluster is closest.
5. Check whether the current room still matches the child's saved environment standard.
6. Decide what the system should say or do next.
7. Pass that planned output through the empathy/output filter.
8. Deliver the filtered output to the child or parent.
9. Save success or failure to the child's imitation profile.

## Personalization goal

Over time the system should discover:

- best audio cue cluster for that child
- best lip-pattern cue cluster for that child
- best affective tone for that child
- best tolerated noise conditions for that child
- best response style for the child and parent
- best physical learning environment for the child

## Practical storage direction

Good production candidates:

- Supabase Postgres + `pgvector`
- Pinecone for separate high-scale retrieval if needed later

## Build implication

This means the therapy engine should not only ask "Was the child correct?"

It should ask:

- Which reference cluster was closest?
- Which cue family helped most?
- Should we repeat the same cluster or switch clusters?
- Is the child's best path visual, acoustic, emotional, or blended?
- Does the current environment still match the child's comfort standard?
- How should the final response be filtered before delivery to the child?
- How should the final response be filtered before delivery to the parent?
- Is the final response calm, concise, and non-irritating enough?
