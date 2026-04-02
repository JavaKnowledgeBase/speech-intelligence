# Working Process

## Core purpose

The purpose is to encourage the child to speak.

The goal is not mainly to familiarize the child with words or texts.

This means the system should optimize for:

- spoken output
- imitation attempts
- confidence to vocalize
- repeated speech production
- low-pressure speaking practice

It should not drift into becoming mostly:

- a vocabulary familiarization app
- a reading app
- a text-learning app
- a passive content player

## Core training idea

We try 20 words for 1 month.

The progression is:

1. Letters first
2. Numbers `0` to `9`
3. Words after that

## Device requirement

This app should run well on:

- tablet
- TV
- desktop

The child-facing experience should not be limited to a single device class.

It should be designed for:

- touch-first interaction on tablet
- large buttons and targets
- readable text from a distance on TV
- very clear visuals on bigger screens
- simple navigation without keyboard dependence for child use
- low-reading and low-friction child interaction
- responsive layouts that also support desktop use for caregivers, clinicians, and admin workflows

For TV use, the interface should still be usable when the child is a few feet away from the screen.

## Voice-first runtime requirement
This product should operate as a voice-first system.
Target assumption:
- more than 98% of child-session interaction should happen through voice input and voice output
That means frontend and runtime work should prioritize:
- dependable microphone capture
- low-latency speech playback
- barge-in while the system is speaking
- transcript capture for audit and clinician review
- fallback behavior when speech services are degraded
The preferred production voice stack is:
1. LiveKit for WebRTC transport
2. Deepgram Flux for streaming speech-to-text and turn detection
3. OpenAI Responses API for orchestration and tool use
4. dedicated streaming TTS for the default child-facing reply path
5. OpenAI Realtime API only as a selective fallback or special conversational mode
Important product rule:
- do not rely on browser speech APIs as the primary production path
- do not rely on a single speech-to-speech model as the only runtime path
- keep a text transcript even when the spoken path is primary
## Per-word data strategy

For each word, create a dictionary of:

- sound variants
- noise/background variants
- lip patterns
- emotions

Target collection size: `25` examples for each category per target.

These examples should be stored in a vector database so the system can compare a child's attempt to known reference patterns.

## Matching goal

The platform should detect which attempts are very near the required cosine similarity threshold, then learn which patterns the child can successfully imitate.

That means we are not only scoring correctness. We are also learning:

- which sound shape the child responds to best
- which lip pattern is easiest to imitate
- which emotional tone improves repetition
- which background conditions reduce or improve success

## Environment and attention requirement

The surrounding environment will also play a role in drawing or reducing attention.

We should ask the parent to take a `360 degree` picture of the place where the child will be learning.

Then the system should:

- inspect the environment
- learn which environment is most comfortable for the child
- make notes about what works
- keep those notes as standards
- check those standards every time a session starts

If anything in the environment is not relevant or may distract the child, the system should ask the parent to adjust it before or during the session.

## Mandatory empathy filter before any output or action

Before any system command, response, prompt, feedback, escalation, or action is executed, there must be a special filter layer.

This filter should shape everything the system outputs to both the child and the parent.

The filter should combine:

- empathy
- special sound choice
- expression style
- emotional appropriateness
- delivery tone for the child
- delivery tone for the parent

This may be:

- built as our own expert agent
- built as a hybrid expert plus rules system
- powered by a third-party API if needed

The important point is that every outward action should pass through this layer first.

## Output style requirements for the filter

We need that filter to make output:

- constructive
- user friendly
- calming
- peaceful
- lower-emotion and lower-arousal
- attention-guiding without being intense

This should apply to both child output and parent output.

The system should avoid becoming:

- irritating
- overly emotional
- noisy
- too talkative
- a chatter box

## Why this should be agentic

This is one reason the system needs to be agentic.

A single model is not enough. We need a dedicated pre-output filter agent that can:

- inspect the current context
- understand the child's state
- understand the caregiver's state
- choose the safest and most effective tone
- rewrite or reshape the outgoing response before delivery

## Agentic implication

The conductor agent should ask specialist experts:

- speech expert: how close is the attempt acoustically
- visual/lip expert: how close is the mouth shape pattern
- emotion expert: which affect pattern improves imitation
- learning expert: which reference cluster should we repeat next
- empathy/output-filter expert: how should this be expressed before it is shown or spoken
- environment expert: is the room setup aligned with the child's comfort and focus standards

## Near-term build interpretation

For MVP:

- start with 20 target items
- store reference embeddings per item
- compare incoming child attempts to reference clusters
- select the closest successful imitation pattern
- repeat and reinforce the most teachable pattern
- pass all child-facing and parent-facing output through the empathy/output-filter layer
- capture environment notes and compare them against the expected session standard
- make the child experience usable on tablet, TV, and desktop
- prioritize speaking attempts over text familiarity

## Long-term interpretation

The system should eventually build an individualized imitation map for each child.

That map can answer:

- which phoneme variants are easiest for the child
- which cues work best
- which sensory/emotional conditions help performance
- which next targets should be introduced
- which speaking style and expression style work best for that child and caregiver
- which environment setup leads to the best focus and comfort


