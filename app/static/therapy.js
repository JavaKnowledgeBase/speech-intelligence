/**
 * TalkBuddy Therapy Session Runtime
 *
 * Manages the full child therapy session loop and caregiver dashboard.
 *
 * Voice pipeline (in priority order):
 *  STT: Deepgram WebSocket (via /runtime/voice/stream) → Web Speech API → manual fallback
 *  TTS: Backend /runtime/voice/tts/speak (OpenAI TTS) → Web Speech Synthesis → silent
 *
 * State machine:
 *  idle → starting → coaching → listening → processing → success | retry | escalated
 *  success  → coaching (next target)
 *  retry    → coaching (same target, retry prompt)
 *  escalated → help overlay → idle
 */

'use strict';

/* ─── Constants ──────────────────────────────────────────────────────────── */
const MASCOT_EMOJI = '🦊';

// Word → emoji icon mapping for the target card visual
const TARGET_ICONS = {
  ball: '⚾', house: '🏠', cat: '🐱', dog: '🐶', cup: '🥤',
  sun: '☀️', tree: '🌳', car: '🚗', bird: '🐦', fish: '🐟',
  hat: '🎩', bus: '🚌', boat: '⛵', shoe: '👟', hand: '✋',
  bath: '🛁', bed: '🛏️', door: '🚪', milk: '🥛', book: '📚',
  sock: '🧦', coat: '🧥', rain: '🌧️', snow: '❄️', moon: '🌙',
  star: '⭐', cake: '🎂', duck: '🦆', bear: '🐻', pig: '🐷',
  frog: '🐸', bee: '🐝', ant: '🐜', map: '🗺️', key: '🔑',
  bag: '👜', box: '📦', pen: '🖊️', cup: '🥤', egg: '🥚',
  arm: '💪', ear: '👂', eye: '👁️', lip: '👄', nose: '👃',
  apple: '🍎', banana: '🍌', orange: '🍊', grape: '🍇',
  water: '💧', juice: '🧃', bread: '🍞', rice: '🍚',
  chair: '🪑', table: '🪑', window: '🪟', phone: '📱',
  clock: '🕐', pencil: '✏️', spoon: '🥄', fork: '🍴',
};

function getTargetIcon(word) {
  return TARGET_ICONS[(word || '').toLowerCase()] || '💬';
}

/* ─── State ──────────────────────────────────────────────────────────────── */
const S = {
  IDLE:       'idle',
  STARTING:   'starting',
  COACHING:   'coaching',    // TTS speaking
  LISTENING:  'listening',   // mic active, waiting for child
  PROCESSING: 'processing',  // evaluating attempt
  SUCCESS:    'success',
  RETRY:      'retry',
  ESCALATED:  'escalated',
  COMPLETED:  'completed',
};

const state = {
  mode:         'child',       // 'child' | 'caregiver'
  sessionState: S.IDLE,
  sessionId:    null,
  childId:      null,
  childName:    null,
  rewardPoints: 0,
  children:     [],
  recognition:  null,
  wakeLock:     null,
  sttReady:     false,        // Web Speech API available
  ttsBackend:   false,        // OpenAI TTS backend available
  deepgramWs:       null,      // Deepgram WebSocket connection
  deepgramRecorder: null,      // MediaRecorder sending audio to bridge
  deepgramMicStream: null,     // MediaStream for Deepgram (separate from Web Speech)
  deepgramReady: false,
  recognitionActive: false,
  currentTarget: null,
  stars:         0,
  wizard: {
    firstName:     '',
    lastName:      '',
    caregiverName: '',
  },
};

/* ─── DOM refs ───────────────────────────────────────────────────────────── */
const el = {
  // Child mode
  childMode:          document.getElementById('child-mode'),
  setupScreen:        document.getElementById('setup-screen'),
  sessionScreen:      document.getElementById('session-screen'),
  childSelect:        document.getElementById('child-select'),
  beginSessionBtn:    document.getElementById('begin-session-btn'),
  switchCaregiverBtn: document.getElementById('switch-to-caregiver-btn'),

  // Session header
  sessionChildName:   document.getElementById('session-child-name'),
  starsDisplay:       document.getElementById('stars-display'),
  sttBadge:           document.getElementById('stt-badge'),
  ttsBadge:           document.getElementById('tts-badge'),
  caregiverModeBtn:   document.getElementById('caregiver-mode-btn'),
  endSessionBtn:      document.getElementById('end-session-btn'),

  // Practice arena
  mascot:             document.getElementById('mascot'),
  mascotBubble:       document.getElementById('mascot-bubble'),
  mascotBubbleText:   document.getElementById('mascot-bubble-text'),
  mascotStatus:       document.getElementById('mascot-status'),
  targetCard:         document.getElementById('target-card'),
  targetIcon:         document.getElementById('target-icon'),
  targetWord:         document.getElementById('target-word'),
  targetCue:          document.getElementById('target-cue'),
  micRing:            document.getElementById('mic-ring'),
  micLabel:           document.getElementById('mic-label'),
  interimDisplay:     document.getElementById('interim-display'),

  // Overlays
  celebrationOverlay: document.getElementById('celebration-overlay'),
  celebrationEmoji:   document.getElementById('celebration-emoji'),
  celebrationTitle:   document.getElementById('celebration-title'),
  celebrationSub:     document.getElementById('celebration-sub'),
  helpOverlay:        document.getElementById('help-overlay'),
  helpMessage:        document.getElementById('help-message'),
  dismissHelpBtn:     document.getElementById('dismiss-help-btn'),
  completedOverlay:   document.getElementById('completed-overlay'),
  completedSub:       document.getElementById('completed-sub'),
  startOverBtn:       document.getElementById('start-over-btn'),

  // Wizard
  wizardCard:        document.getElementById('wizard-card'),
  wizardMascot:      document.getElementById('wizard-mascot'),
  wizardStepChild:   document.getElementById('wz-step-child'),
  wizardStepCaregiver: document.getElementById('wz-step-caregiver'),
  wizardStepLaunch:  document.getElementById('wz-step-launch'),
  wizardPrompt:      document.getElementById('wizard-prompt'),
  wizardNameDisplay: document.getElementById('wizard-name-display'),
  wizardLetters:     document.getElementById('wizard-letters'),
  wizardInterim:     document.getElementById('wizard-interim'),
  wizardMicArea:     document.getElementById('wizard-mic-area'),
  wizardMicRing:     document.getElementById('wizard-mic-ring'),
  wizardMicLabel:    document.getElementById('wizard-mic-label'),
  wizardConfirm:     document.getElementById('wizard-confirm'),
  wizardYesBtn:      document.getElementById('wizard-yes-btn'),
  wizardNoBtn:       document.getElementById('wizard-no-btn'),
  wizardManual:      document.getElementById('wizard-manual'),
  wizardSkipBtn:     document.getElementById('wizard-skip-btn'),

  // Caregiver mode
  caregiverMode:            document.getElementById('caregiver-mode'),
  backToChildBtn:           document.getElementById('back-to-child-btn'),
  caregiverChildSelect:     document.getElementById('caregiver-child-select'),
  refreshCaregiverBtn:      document.getElementById('refresh-caregiver-btn'),
  sessionStatusPanelContent: document.getElementById('session-status-panel-content'),
  alertsPanelContent:       document.getElementById('alerts-panel-content'),
  alertCountBadge:          document.getElementById('alert-count-badge'),
  progressPanelContent:     document.getElementById('progress-panel-content'),
  clinicianPanelContent:    document.getElementById('clinician-panel-content'),
};

/* ─── Mascot helpers ─────────────────────────────────────────────────────── */
function setMascotState(state) {
  el.mascot.className = `mascot ${state}`;
}

function showMascotBubble(text) {
  el.mascotBubbleText.textContent = text;
  el.mascotBubble.hidden = false;
}

function hideMascotBubble() {
  el.mascotBubble.hidden = true;
}

/* ─── Mic ring helpers ───────────────────────────────────────────────────── */
function setMicState(micState, label) {
  el.micRing.className = `mic-ring ${micState}`;
  el.micLabel.textContent = label;
}

/* ─── Star display ───────────────────────────────────────────────────────── */
function updateStars(points) {
  const earned = Math.min(5, Math.floor(points / 10));
  const stars = el.starsDisplay.querySelectorAll('.star');
  stars.forEach((s, i) => {
    const wasEarned = s.classList.contains('earned');
    const shouldBeEarned = i < earned;
    s.textContent = shouldBeEarned ? '★' : '☆';
    if (shouldBeEarned && !wasEarned) {
      s.classList.add('earned');
      // Remove class after animation to allow re-trigger
      setTimeout(() => s.classList.remove('earned'), 450);
    } else if (shouldBeEarned) {
      s.classList.add('earned');
    } else {
      s.classList.remove('earned');
    }
  });
  el.starsDisplay.setAttribute('aria-label', `${earned} of 5 stars earned`);
}

/* ─── API helpers ────────────────────────────────────────────────────────── */
async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`API ${path} returned ${res.status}: ${text}`);
  }
  return res.json();
}

async function loadChildren() {
  try {
    const children = await apiFetch('/children');
    state.children = children;
    return children;
  } catch {
    return [];
  }
}

async function startSessionApi(childId) {
  return apiFetch('/session/start', {
    method: 'POST',
    body: JSON.stringify({ child_id: childId }),
  });
}

async function sendTranscript(transcript, attentionScore = 0.8) {
  return apiFetch('/runtime/voice/transcript', {
    method: 'POST',
    body: JSON.stringify({
      session_id: state.sessionId,
      transcript,
      is_final: true,
      elapsed_ms: 0,
      attention_score: attentionScore,
      source: 'web_speech_api',
    }),
  });
}

async function postCheckpoint(kind, elapsedMs, detail = null) {
  if (!state.sessionId) return;
  return apiFetch('/runtime/voice/checkpoints', {
    method: 'POST',
    body: JSON.stringify({
      session_id: state.sessionId,
      checkpoint_kind: kind,
      elapsed_ms: Math.max(0, Math.round(elapsedMs)),
      detail,
    }),
  }).catch(() => null);
}

async function postRuntimeEvent(kind, detail) {
  if (!state.sessionId) return;
  return apiFetch('/runtime/voice/events', {
    method: 'POST',
    body: JSON.stringify({
      session_id: state.sessionId,
      event_kind: kind,
      elapsed_ms: 0,
      detail,
    }),
  }).catch(() => null);
}

async function completeSessionApi() {
  if (!state.sessionId) return;
  return apiFetch(`/sessions/${state.sessionId}/complete`, { method: 'POST' }).catch(() => null);
}

/* ─── Wake lock ──────────────────────────────────────────────────────────── */
async function requestWakeLock() {
  if ('wakeLock' in navigator) {
    try {
      state.wakeLock = await navigator.wakeLock.request('screen');
    } catch {
      // Wake lock not available in this context
    }
  }
}

function releaseWakeLock() {
  if (state.wakeLock) {
    state.wakeLock.release().catch(() => {});
    state.wakeLock = null;
  }
}

// Re-acquire on tab visibility (lock is released when page is backgrounded)
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && state.sessionId) {
    requestWakeLock();
  }
});

/* ─── TTS ────────────────────────────────────────────────────────────────── */

/**
 * Speak text. Returns a Promise that resolves when audio completes.
 * Priority: OpenAI TTS backend → Web Speech Synthesis → no-op.
 */
function speak(text) {
  return new Promise((resolve) => {
    if (!text || !text.trim()) { resolve(); return; }

    if (state.ttsBackend) {
      // Use backend OpenAI TTS streaming endpoint
      const audio = new Audio(`/runtime/voice/tts/speak?text=${encodeURIComponent(text)}`);
      audio.onended = resolve;
      audio.onerror = () => {
        // Fall back to Web Speech
        speakWebSpeech(text, resolve);
      };
      audio.play().catch(() => speakWebSpeech(text, resolve));
      return;
    }

    speakWebSpeech(text, resolve);
  });
}

function speakWebSpeech(text, onDone) {
  if (!('speechSynthesis' in window)) { onDone(); return; }
  window.speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(text);
  utt.rate   = 0.88;   // slightly slower — aids comprehension for children
  utt.pitch  = 1.05;
  utt.volume = 1.0;
  // Prefer a friendly en-US voice if available
  const voices = window.speechSynthesis.getVoices();
  const preferred = voices.find(v => v.lang.startsWith('en') && !v.localService === false)
    || voices.find(v => v.lang.startsWith('en'))
    || null;
  if (preferred) utt.voice = preferred;
  utt.onend = onDone;
  utt.onerror = () => onDone();
  window.speechSynthesis.speak(utt);
}

/* ─── STT — Web Speech API ───────────────────────────────────────────────── */
function initWebSpeechSTT() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { state.sttReady = false; return; }
  state.sttReady = true;
  el.sttBadge.textContent = 'STT: Browser';
  el.sttBadge.classList.remove('mock');
}

function startListeningWebSpeech() {
  if (!state.sttReady) return;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  state.recognition = new SR();
  state.recognition.continuous = false;
  state.recognition.interimResults = true;
  state.recognition.lang = 'en-US';
  state.recognitionActive = true;

  state.recognition.onresult = (event) => {
    const results = Array.from(event.results);
    const transcript = results.map(r => r[0].transcript).join('');
    const isFinal = results[results.length - 1].isFinal;

    el.interimDisplay.textContent = transcript;

    if (isFinal && state.sessionState === S.LISTENING) {
      state.recognitionActive = false;
      handleFinalTranscript(transcript);
    }
  };

  state.recognition.onerror = (event) => {
    state.recognitionActive = false;
    if (event.error === 'aborted' || event.error === 'no-speech') {
      // Restart if still in listening state
      if (state.sessionState === S.LISTENING) {
        setTimeout(startListeningWebSpeech, 500);
      }
    }
  };

  state.recognition.onend = () => {
    state.recognitionActive = false;
    // Restart automatically if still waiting for child speech
    if (state.sessionState === S.LISTENING) {
      setTimeout(startListeningWebSpeech, 300);
    }
  };

  try {
    state.recognition.start();
  } catch {
    // recognition already started — ignore
  }
}

function stopListening() {
  state.recognitionActive = false;
  if (state.recognition) {
    try { state.recognition.abort(); } catch { /* ignore */ }
    state.recognition = null;
  }
  // Pause Deepgram recorder (keep WS open; it resumes on next coachAndListen)
  if (state.deepgramRecorder && state.deepgramRecorder.state === 'recording') {
    try { state.deepgramRecorder.pause(); } catch { /* ignore */ }
  }
}

/* ─── STT — Deepgram WebSocket bridge ───────────────────────────────────── */

/**
 * Open the Deepgram streaming bridge and start sending mic audio.
 *
 * Audio path: getUserMedia → MediaRecorder (webm/opus, 250ms chunks)
 *             → WebSocket → FastAPI bridge → Deepgram → transcript frames → browser.
 *
 * Falls back to Web Speech API silently when the bridge closes with 4503
 * (Deepgram not configured) or on any other connection failure.
 */
async function tryInitDeepgramStream() {
  if (!state.sessionId || !state.childId) return;

  let micStream;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  } catch {
    return; // mic permission denied — Web Speech API will handle it
  }

  let ws;
  try {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(
      `${proto}://${location.host}/runtime/voice/stream` +
      `?session_id=${encodeURIComponent(state.sessionId)}` +
      `&child_id=${encodeURIComponent(state.childId)}`
    );

    await new Promise((resolve, reject) => {
      ws.onopen  = resolve;
      ws.onerror = () => reject(new Error('ws error'));
      ws.onclose = (ev) => reject(new Error(`ws closed: ${ev.code}`));
      setTimeout(() => reject(new Error('timeout')), 4000);
    });
  } catch {
    // Bridge rejected — stop mic tracks and fall through to Web Speech API
    micStream.getTracks().forEach(t => t.stop());
    return;
  }

  // Determine best MIME type (webm/opus preferred, fallback to whatever browser supports)
  const mimeTypes = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    '',
  ];
  const mimeType = mimeTypes.find(m => !m || MediaRecorder.isTypeSupported(m)) || '';

  const recorder = new MediaRecorder(micStream, mimeType ? { mimeType } : undefined);

  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
      ws.send(e.data);
    }
  };

  state.deepgramWs  = ws;
  state.deepgramRecorder = recorder;
  state.deepgramMicStream = micStream;
  state.deepgramReady = true;

  el.sttBadge.textContent = 'STT: Deepgram';
  el.sttBadge.classList.remove('mock');

  ws.onmessage = (event) => {
    try {
      const frame = JSON.parse(event.data);
      if (frame.transcript) {
        el.interimDisplay.textContent = frame.transcript;
        if ((frame.is_final || frame.speech_final) && state.sessionState === S.LISTENING) {
          handleFinalTranscript(frame.transcript);
        }
      }
    } catch { /* ignore malformed frames */ }
  };

  ws.onclose = () => {
    _cleanupDeepgram();
    // Fall back to Web Speech API for the rest of the session
    if (state.sessionState === S.LISTENING) {
      startListeningWebSpeech();
    }
  };

  // Start sending audio immediately — Deepgram buffers until VAD detects speech
  recorder.start(250); // 250ms chunks
}

function _cleanupDeepgram() {
  state.deepgramReady = false;
  state.deepgramWs = null;
  if (state.deepgramRecorder && state.deepgramRecorder.state !== 'inactive') {
    try { state.deepgramRecorder.stop(); } catch { /* ignore */ }
  }
  state.deepgramRecorder = null;
  if (state.deepgramMicStream) {
    state.deepgramMicStream.getTracks().forEach(t => t.stop());
    state.deepgramMicStream = null;
  }
  el.sttBadge.textContent = 'STT: Browser';
}

/* ─── Session state machine ──────────────────────────────────────────────── */

function transitionTo(newState) {
  state.sessionState = newState;
}

/**
 * Show coach message in mascot bubble, animate mascot, then speak via TTS.
 * After TTS finishes, transition to listening.
 */
async function coachAndListen(message, mascotAnim = 'speak') {
  transitionTo(S.COACHING);
  showMascotBubble(message);
  setMascotState(mascotAnim);
  setMicState('idle', 'Getting ready…');
  hideMascotBubble();
  showMascotBubble(message);

  await speak(message);

  hideMascotBubble();

  if (state.sessionState !== S.COACHING) return;  // interrupted
  transitionTo(S.LISTENING);
  setMascotState('listen');
  setMicState('listening', 'Listening…');
  el.micLabel.textContent = 'Listening…';
  el.interimDisplay.textContent = '';
  postRuntimeEvent('vad_started', 'Coach finished, listening for child attempt.');

  if (state.deepgramReady && state.deepgramRecorder) {
    // Resume sending audio to the Deepgram bridge
    if (state.deepgramRecorder.state === 'paused') {
      try { state.deepgramRecorder.resume(); } catch { /* ignore */ }
    } else if (state.deepgramRecorder.state === 'inactive') {
      try { state.deepgramRecorder.start(250); } catch { /* ignore */ }
    }
  } else if (state.sttReady) {
    startListeningWebSpeech();
  } else {
    // No STT available — display a notice
    setMicState('idle', 'Microphone not available');
  }
}

/**
 * Receive a final transcript from STT and evaluate it.
 */
async function handleFinalTranscript(transcript) {
  if (state.sessionState !== S.LISTENING) return;
  transitionTo(S.PROCESSING);
  stopListening();

  el.interimDisplay.textContent = transcript;
  setMascotState('idle');
  setMicState('processing', 'Thinking…');
  el.mascotStatus.textContent = 'Thinking…';

  await postCheckpoint('turn_ended', 0, 'speech detected');

  let result;
  try {
    result = await sendTranscript(transcript);
    await postCheckpoint('first_transcript', 0, transcript);
  } catch (err) {
    // Network error — retry listening
    transitionTo(S.LISTENING);
    setMicState('listening', 'Listening…');
    startListeningWebSpeech();
    return;
  }

  const evaluation = result.evaluation;
  if (!evaluation) {
    // Partial transcript ingested, not a final turn
    transitionTo(S.LISTENING);
    setMicState('listening', 'Listening…');
    startListeningWebSpeech();
    return;
  }

  state.rewardPoints = (state.rewardPoints || 0) + (evaluation.action === 'advance' ? 10 : 0);
  updateStars(state.rewardPoints);
  await postCheckpoint('first_audio_byte', 0, evaluation.feedback);

  if (evaluation.action === 'advance') {
    await handleSuccess(evaluation);
  } else if (evaluation.action === 'escalate') {
    await handleEscalation(evaluation);
  } else {
    await handleRetry(evaluation);
  }
}

async function handleSuccess(evaluation) {
  transitionTo(S.SUCCESS);

  // Animate target card
  el.targetCard.classList.add('state-success');
  setMascotState('cheer');

  // Show celebration overlay briefly
  el.celebrationEmoji.textContent = ['🌟', '🎉', '🏆', '⭐', '✨'][Math.floor(Math.random() * 5)];
  el.celebrationTitle.textContent = ['Great job!', 'Amazing!', 'You did it!', 'Brilliant!'][Math.floor(Math.random() * 4)];
  el.celebrationSub.textContent = evaluation.next_target ? `Next: ${evaluation.next_target}` : '';
  el.celebrationOverlay.hidden = false;

  await speak(evaluation.feedback);

  await new Promise(r => setTimeout(r, 1800));

  el.celebrationOverlay.hidden = true;
  el.targetCard.classList.remove('state-success');

  // Advance to next target
  if (evaluation.next_target) {
    updateTargetDisplay(evaluation.next_target, null);
    await coachAndListen(
      evaluation.feedback || `Now let's try ${evaluation.next_target}.`
    );
  } else {
    await handleSessionComplete();
  }
}

async function handleRetry(evaluation) {
  transitionTo(S.RETRY);
  el.targetCard.classList.add('state-retry');
  setMascotState('speak');
  setMicState('idle', '');

  await speak(evaluation.feedback);
  await new Promise(r => setTimeout(r, 400));

  el.targetCard.classList.remove('state-retry');
  await coachAndListen(evaluation.feedback || 'Let us try that one again.');
}

async function handleEscalation(evaluation) {
  transitionTo(S.ESCALATED);
  stopListening();
  setMascotState('idle');
  setMicState('idle', '');

  await speak(evaluation.feedback || 'A grown-up will help you now.');

  el.helpMessage.textContent = '';
  el.helpOverlay.hidden = false;
}

async function handleSessionComplete() {
  transitionTo(S.COMPLETED);
  stopListening();
  _cleanupDeepgram();
  releaseWakeLock();

  await completeSessionApi();
  el.completedSub.textContent = `${state.rewardPoints} reward points earned!`;
  el.completedOverlay.hidden = true;  // reveal below
  await speak('Well done! Your session is complete.');
  el.completedOverlay.hidden = false;
}

function updateTargetDisplay(word, cue) {
  state.currentTarget = word;
  el.targetIcon.textContent = getTargetIcon(word);
  el.targetWord.textContent = word;
  el.targetCue.textContent = cue || '';
}

/* ─── Welcome Wizard ─────────────────────────────────────────────────────── */

/**
 * One-shot speech recognition for a single wizard step.
 * Resolves with the transcript string (trimmed), or '' on silence/error.
 */
function wizardListen({ interimCb = null, timeout = 10000 } = {}) {
  return new Promise((resolve) => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { resolve(''); return; }

    const rec = new SR();
    rec.lang = 'en-US';
    rec.continuous = false;
    rec.interimResults = !!interimCb;

    let settled = false;
    const done = (val) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { rec.abort(); } catch { /* ignore */ }
      resolve((val || '').trim());
    };

    const timer = setTimeout(() => done(''), timeout);

    rec.onresult = (evt) => {
      const results = Array.from(evt.results);
      const text = results.map(r => r[0].transcript).join(' ');
      if (interimCb) interimCb(text);
      if (results[results.length - 1].isFinal) done(text);
    };
    rec.onerror = () => done('');
    rec.onend   = () => done('');

    try { rec.start(); } catch { done(''); }
  });
}

function wSetMic(mode) {           // 'listening' | 'idle' | 'hidden'
  if (mode === 'hidden') {
    el.wizardMicArea.hidden = true;
  } else {
    el.wizardMicArea.hidden = false;
    el.wizardMicRing.className = `mic-ring ${mode}`;
    el.wizardMicLabel.textContent = mode === 'listening' ? 'Listening…' : 'Got it!';
  }
}

function wShowLetters(text) {
  el.wizardLetters.textContent = text.toUpperCase();
  el.wizardNameDisplay.hidden = false;
}

function wHideLetters() {
  el.wizardNameDisplay.hidden = true;
  el.wizardInterim.textContent = '';
}

function wSetStep(step) {          // 'child' | 'caregiver' | 'launch'
  [el.wizardStepChild, el.wizardStepCaregiver, el.wizardStepLaunch].forEach(s => s.classList.remove('active'));
  if (step === 'child')     el.wizardStepChild.classList.add('active');
  if (step === 'caregiver') el.wizardStepCaregiver.classList.add('active');
  if (step === 'launch')    el.wizardStepLaunch.classList.add('active');
}

/** Yes/No tap — resolves true (yes) or false (no). */
function wAskConfirm() {
  return new Promise((resolve) => {
    el.wizardConfirm.hidden = false;
    const finish = (val) => {
      el.wizardConfirm.hidden = true;
      el.wizardYesBtn.removeEventListener('click', onYes);
      el.wizardNoBtn.removeEventListener('click', onNo);
      resolve(val);
    };
    const onYes = () => finish(true);
    const onNo  = () => finish(false);
    el.wizardYesBtn.addEventListener('click', onYes);
    el.wizardNoBtn.addEventListener('click', onNo);
  });
}

/**
 * Convert a spelled-out response ("L I A M", "el eye ay em") into letters.
 */
function parseSpelling(heard) {
  const map = {
    'ay':'A','bee':'B','see':'C','dee':'D','ee':'E','ef':'F','eff':'F',
    'gee':'G','aitch':'H','eye':'I','jay':'J','kay':'K','el':'L','ell':'L',
    'em':'M','en':'N','oh':'O','pee':'P','cue':'Q','are':'R','ar':'R',
    'ess':'S','tee':'T','you':'U','vee':'V','double you':'W','ex':'X',
    'why':'Y','zee':'Z','zed':'Z',
  };
  const tokens = heard.toLowerCase().split(/[\s\-,\.]+/).filter(Boolean);
  const letters = tokens.map(t =>
    t.length === 1 && /[a-z]/.test(t) ? t.toUpperCase() : (map[t] || '')
  );
  const result = letters.join('');
  return result || heard.replace(/\s+/g, '').toUpperCase();
}

/** Capitalise first letter of each word. */
function toTitleCase(s) {
  return s.replace(/\w\S*/g, w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
}

/**
 * Full ask-spell-confirm loop for one name part (first or last).
 * Returns the confirmed spelled name (uppercase letters string).
 */
async function wCollectName(askMsg, nameLabel) {
  while (true) {
    // ── Ask for name by voice ──────────────────────────────────────────────
    el.wizardPrompt.textContent = askMsg;
    wHideLetters();
    wSetMic('hidden');
    await speak(askMsg);

    wSetMic('listening');
    el.wizardInterim.textContent = '';
    const heardName = await wizardListen({
      interimCb: t => { el.wizardInterim.textContent = t; },
      timeout: 9000,
    });
    wSetMic('idle');
    const displayName = toTitleCase(heardName || nameLabel);

    // ── Ask to spell ───────────────────────────────────────────────────────
    const spellMsg = `Can you please spell ${nameLabel === 'first name' ? 'the first name' : 'the last name'}?`;
    el.wizardPrompt.textContent = spellMsg;
    wHideLetters();
    await speak(spellMsg);

    wSetMic('listening');
    el.wizardInterim.textContent = '';
    const heardSpelling = await wizardListen({
      interimCb: t => { el.wizardInterim.textContent = t; },
      timeout: 12000,
    });
    wSetMic('idle');

    const spelled = parseSpelling(heardSpelling || displayName);

    // ── Display letters and confirm ────────────────────────────────────────
    wShowLetters(spelled.split('').join('  '));
    const letterRead = spelled.split('').join(', ');
    const confirmMsg = `Please correct me if I'm wrong. Is the ${nameLabel} ${letterRead}?`;
    el.wizardPrompt.textContent = `Is this right?`;
    await speak(confirmMsg);

    const yes = await wAskConfirm();
    if (yes) return spelled;

    // ── Listen for correction ──────────────────────────────────────────────
    const correctMsg = 'Okay. Please say the correct spelling.';
    el.wizardPrompt.textContent = correctMsg;
    wHideLetters();
    await speak(correctMsg);

    wSetMic('listening');
    el.wizardInterim.textContent = '';
    const correction = await wizardListen({
      interimCb: t => { el.wizardInterim.textContent = t; },
      timeout: 12000,
    });
    wSetMic('idle');

    if (correction) {
      const corrected = parseSpelling(correction);
      wShowLetters(corrected.split('').join('  '));
      const reconfirm = `Is the ${nameLabel} now ${corrected.split('').join(', ')}?`;
      el.wizardPrompt.textContent = 'Is this right now?';
      await speak(reconfirm);
      const ok = await wAskConfirm();
      if (ok) return corrected;
    }
    // Loop again if still wrong
  }
}

/** Collect a plain spoken name — no spelling step (used for caregiver). */
async function wCollectSimpleName(msg) {
  el.wizardPrompt.textContent = msg;
  wHideLetters();
  wSetMic('hidden');
  await speak(msg);
  wSetMic('listening');
  el.wizardInterim.textContent = '';
  const heard = await wizardListen({
    interimCb: t => { el.wizardInterim.textContent = t; },
    timeout: 9000,
  });
  wSetMic('idle');
  return (heard || '').trim();
}

/** Find the best matching child from backend data. */
function matchChild(firstName, lastName) {
  if (!state.children.length) return null;
  const fn = firstName.toLowerCase();
  const ln = lastName.toLowerCase();
  return (
    state.children.find(c => {
      const parts = c.name.toLowerCase().split(/\s+/);
      return parts[0] === fn && (!ln || parts[1] === ln);
    }) ||
    state.children.find(c => c.name.toLowerCase().startsWith(fn)) ||
    state.children[0]
  );
}

async function runWizard() {
  // Reveal skip button after 2 s so parents can see the wizard first
  setTimeout(() => { el.wizardSkipBtn.style.opacity = '1'; }, 2000);

  wSetStep('child');
  wHideLetters();
  wSetMic('hidden');
  el.wizardConfirm.hidden = true;
  el.wizardMascot.className = 'mascot idle';

  // Step 1 — Welcome
  const welcome = 'Welcome to TalkBuddy!';
  el.wizardPrompt.textContent = welcome;
  await speak(welcome);

  // Step 2–4 — Child first name (with spelling + confirm)
  const firstName = await wCollectName("Please say the child's first name.", 'first name');

  // Step 5–9 repeated for last name
  const lastName = await wCollectName("Now please say the child's last name.", 'last name');

  // Caregiver name (simple, no spelling)
  wSetStep('caregiver');
  const caregiverName = await wCollectSimpleName('And your name? Please say the caregiver or parent name.');

  state.wizard.firstName     = firstName;
  state.wizard.lastName      = lastName;
  state.wizard.caregiverName = caregiverName;

  // Launch
  wSetStep('launch');
  const launchMsg = "Great! Let's start playing!";
  el.wizardPrompt.textContent = launchMsg;
  wHideLetters();
  wSetMic('hidden');
  await speak(launchMsg);

  // Match child and kick off session
  const matched = matchChild(firstName, lastName);
  if (matched) {
    el.childSelect.value = matched.child_id;
  } else if (state.children.length) {
    el.childSelect.value = state.children[0].child_id;
  }
  await startSession();
}

/* ─── Start session ──────────────────────────────────────────────────────── */
async function startSession() {
  const childId = el.childSelect.value;
  if (!childId) return;

  state.childId = childId;
  state.childName = el.childSelect.options[el.childSelect.selectedIndex].text;
  state.rewardPoints = 0;
  state.sessionId = null;

  transitionTo(S.STARTING);

  // Switch to session screen
  el.setupScreen.hidden = true;
  el.sessionScreen.hidden = false;
  el.sessionChildName.textContent = state.childName;
  updateStars(0);
  setMicState('idle', 'Starting…');
  setMascotState('idle');
  el.mascotStatus.textContent = 'Starting your session…';
  el.interimDisplay.textContent = '';

  await requestWakeLock();

  let session;
  try {
    session = await startSessionApi(childId);
  } catch (err) {
    el.mascotStatus.textContent = 'Could not connect — check your network.';
    transitionTo(S.IDLE);
    return;
  }

  state.sessionId = session.session_id;

  // Wire voice runtime (creates LiveKit session scaffold, records transport)
  await apiFetch('/runtime/voice/session', {
    method: 'POST',
    body: JSON.stringify({ session_id: state.sessionId, child_id: childId, audio_enabled: true }),
  }).catch(() => null);

  await apiFetch('/runtime/voice/connect', {
    method: 'POST',
    body: JSON.stringify({ session_id: state.sessionId, child_id: childId }),
  }).catch(() => null);

  // Try to open Deepgram streaming bridge
  await tryInitDeepgramStream();

  // Boot microphone permission (needed even for Web Speech API)
  try {
    await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    // Permission denied — STT may not work; session continues
  }

  updateTargetDisplay(session.target_text, session.cue);

  await postCheckpoint('turn_started', 0, 'session opened');
  await postRuntimeEvent('client_joined', 'Therapy session started from therapy UI.');

  await coachAndListen(session.message || `Let's practice. Can you say ${session.target_text}?`);
}

/* ─── Caregiver dashboard ────────────────────────────────────────────────── */
function switchMode(mode) {
  state.mode = mode;
  el.childMode.hidden     = mode !== 'child';
  el.caregiverMode.hidden = mode !== 'caregiver';

  if (mode === 'caregiver') {
    populateCaregiverChildSelect();
    const activeChildId = state.childId || (state.children[0] || {}).child_id;
    if (activeChildId) {
      el.caregiverChildSelect.value = activeChildId;
      loadCaregiverDashboard(activeChildId);
    }
  }
}

function populateCaregiverChildSelect() {
  el.caregiverChildSelect.innerHTML = state.children
    .map(c => `<option value="${c.child_id}">${escHtml(c.name)} (${c.age})</option>`)
    .join('');
}

async function loadCaregiverDashboard(childId) {
  if (!childId) return;

  // Run all fetches in parallel
  const [alertsData, reportData] = await Promise.all([
    apiFetch(`/caregiver/alerts?caregiver_id=${encodeURIComponent(childId)}`).catch(() => []),
    apiFetch(`/reports/child/${encodeURIComponent(childId)}`).catch(() => null),
  ]);

  renderAlertsPanel(alertsData);
  renderProgressPanel(reportData);
  renderSessionStatusPanel(reportData);

  // Clinician queue if a clinician is associated
  if (reportData && reportData.child && reportData.child.clinician_id) {
    const reviews = await apiFetch(`/clinician/queue?clinician_id=${encodeURIComponent(reportData.child.clinician_id)}`).catch(() => []);
    renderClinicianPanel(reviews);
  }
}

function renderAlertsPanel(alerts) {
  if (!alerts || alerts.length === 0) {
    el.alertsPanelContent.innerHTML = '<p class="care-empty">No alerts. All good!</p>';
    el.alertCountBadge.textContent = '0';
    el.alertCountBadge.classList.add('zero');
    return;
  }

  el.alertCountBadge.textContent = alerts.length;
  el.alertCountBadge.classList.remove('zero');

  el.alertsPanelContent.innerHTML = alerts.map(a => `
    <div class="alert-item" data-alert-id="${escHtml(a.alert_id)}">
      <span class="alert-reason">${escHtml(a.reason.replace(/_/g, ' '))}</span>
      <p class="alert-message">${escHtml(a.message)}</p>
      <span class="alert-meta">${new Date(a.created_at).toLocaleString()}</span>
      <button class="ack-btn" data-alert-id="${escHtml(a.alert_id)}">Acknowledge</button>
    </div>
  `).join('');

  el.alertsPanelContent.querySelectorAll('.ack-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const alertId = btn.dataset.alertId;
      await apiFetch(`/caregiver/alerts/${alertId}/acknowledge`, { method: 'POST' }).catch(() => null);
      btn.closest('.alert-item').remove();
      const remaining = el.alertsPanelContent.querySelectorAll('.alert-item').length;
      if (remaining === 0) {
        el.alertsPanelContent.innerHTML = '<p class="care-empty">No alerts. All good!</p>';
        el.alertCountBadge.textContent = '0';
        el.alertCountBadge.classList.add('zero');
      } else {
        el.alertCountBadge.textContent = remaining;
      }
    });
  });
}

function renderProgressPanel(report) {
  if (!report || !report.progress || report.progress.length === 0) {
    el.progressPanelContent.innerHTML = '<p class="care-empty">No practice data yet.</p>';
    return;
  }

  const items = [...report.progress]
    .sort((a, b) => b.mastery_score - a.mastery_score)
    .slice(0, 10);

  el.progressPanelContent.innerHTML = items.map(p => {
    const pct = Math.round(p.mastery_score * 100);
    return `
      <div class="progress-item">
        <span class="progress-word">${escHtml(p.target_text)}</span>
        <span class="progress-pct">${pct}%</span>
        <div class="progress-bar-track">
          <div class="progress-bar-fill" style="width:${pct}%"></div>
        </div>
      </div>
    `;
  }).join('');
}

function renderSessionStatusPanel(report) {
  if (!report || !report.recent_sessions || report.recent_sessions.length === 0) {
    el.sessionStatusPanelContent.innerHTML = '<p class="care-empty">No recent sessions.</p>';
    return;
  }

  const latest = report.recent_sessions[0];
  const started = new Date(latest.started_at).toLocaleString();
  const statusLabel = { active: 'Active', completed: 'Completed', escalated: '⚠ Escalated' }[latest.status] || latest.status;

  el.sessionStatusPanelContent.innerHTML = `
    <div>
      <div class="stat-row"><span>Status</span><span class="stat-value">${statusLabel}</span></div>
      <div class="stat-row"><span>Target</span><span class="stat-value">${escHtml(latest.current_target)}</span></div>
      <div class="stat-row"><span>Points</span><span class="stat-value">⭐ ${latest.reward_points}</span></div>
      <div class="stat-row"><span>Started</span><span class="stat-value" style="font-size:var(--sz-base)">${started}</span></div>
    </div>
  `;
}

function renderClinicianPanel(reviews) {
  if (!reviews || reviews.length === 0) {
    el.clinicianPanelContent.innerHTML = '<p class="care-empty">No pending clinician reviews.</p>';
    return;
  }

  el.clinicianPanelContent.innerHTML = reviews.map(r => `
    <div class="review-item">
      <span class="review-priority ${escHtml(r.priority)}">${escHtml(r.priority.toUpperCase())} PRIORITY</span>
      <p class="review-summary">${escHtml(r.summary)}</p>
    </div>
  `).join('');
}

/* ─── Provider detection ─────────────────────────────────────────────────── */
async function detectProviders() {
  // Check if backend TTS (OpenAI) is available
  try {
    const res = await fetch('/runtime/voice/tts/speak?text=ping', { method: 'HEAD' }).catch(() => null);
    if (res && res.ok) {
      state.ttsBackend = true;
      el.ttsBadge.textContent = 'TTS: OpenAI';
      el.ttsBadge.classList.remove('mock');
    } else {
      el.ttsBadge.textContent = 'TTS: Browser';
    }
  } catch {
    el.ttsBadge.textContent = 'TTS: Browser';
  }
}

/* ─── Utility ────────────────────────────────────────────────────────────── */
function escHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ─── Bootstrap ──────────────────────────────────────────────────────────── */
async function init() {
  // Detect speech capabilities
  initWebSpeechSTT();

  // Load children for both selects
  const children = await loadChildren();

  if (children.length === 0) {
    el.childSelect.innerHTML = '<option value="">No children configured</option>';
    return;
  }

  el.childSelect.innerHTML = children
    .map(c => `<option value="${c.child_id}">${escHtml(c.name)} (${c.age})</option>`)
    .join('');

  el.beginSessionBtn.disabled = false;

  // Detect providers asynchronously (don't block UI)
  detectProviders();

  // Kick off the voice welcome wizard automatically
  runWizard().catch(() => {
    // Wizard failed (e.g. no mic) — show manual fallback
    showWizardManualFallback();
  });

  // Warm up speech synthesis voices list
  if ('speechSynthesis' in window) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.addEventListener('voiceschanged', () => {
      window.speechSynthesis.getVoices();
    });
  }
}

/* ─── Event listeners ────────────────────────────────────────────────────── */

function showWizardManualFallback() {
  // Stop any running speech
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  el.wizardCard.querySelector('.wizard-steps').hidden   = true;
  el.wizardMicArea.hidden   = true;
  el.wizardConfirm.hidden   = true;
  el.wizardNameDisplay.hidden = true;
  el.wizardInterim.textContent = '';
  el.wizardPrompt.textContent = "Who's practicing today?";
  el.wizardManual.hidden = false;
  el.wizardSkipBtn.style.display = 'none';
}

el.wizardSkipBtn.addEventListener('click', showWizardManualFallback);

el.beginSessionBtn.addEventListener('click', () => startSession());

el.switchCaregiverBtn.addEventListener('click', () => switchMode('caregiver'));
el.caregiverModeBtn.addEventListener('click', () => switchMode('caregiver'));
el.backToChildBtn.addEventListener('click', () => switchMode('child'));

el.endSessionBtn.addEventListener('click', async () => {
  stopListening();
  await completeSessionApi().catch(() => null);
  releaseWakeLock();
  // Return to setup
  el.sessionScreen.hidden = true;
  el.setupScreen.hidden = false;
  state.sessionId = null;
  transitionTo(S.IDLE);
});

el.dismissHelpBtn.addEventListener('click', async () => {
  el.helpOverlay.hidden = true;
  // Return to setup screen
  stopListening();
  await completeSessionApi().catch(() => null);
  releaseWakeLock();
  el.sessionScreen.hidden = true;
  el.setupScreen.hidden = false;
  state.sessionId = null;
  transitionTo(S.IDLE);
});

el.startOverBtn.addEventListener('click', () => {
  el.completedOverlay.hidden = true;
  el.sessionScreen.hidden = true;
  el.setupScreen.hidden = false;
  state.sessionId = null;
  transitionTo(S.IDLE);
});

el.refreshCaregiverBtn.addEventListener('click', () => {
  const childId = el.caregiverChildSelect.value;
  if (childId) loadCaregiverDashboard(childId);
});

el.caregiverChildSelect.addEventListener('change', (e) => {
  if (e.target.value) loadCaregiverDashboard(e.target.value);
});

el.childSelect.addEventListener('change', () => {
  el.beginSessionBtn.disabled = !el.childSelect.value;
});

// Allow tapping anywhere in the practice arena to toggle caregiver access
// (triple-tap within 2 seconds) — useful on TVs where buttons are hard to reach
let tripleTapCount = 0;
let tripleTapTimer = null;
document.addEventListener('click', () => {
  if (state.mode !== 'child' || state.sessionState === S.IDLE) return;
  tripleTapCount++;
  if (tripleTapTimer) clearTimeout(tripleTapTimer);
  tripleTapTimer = setTimeout(() => { tripleTapCount = 0; }, 1200);
  if (tripleTapCount >= 3) {
    tripleTapCount = 0;
    switchMode('caregiver');
  }
});

// Handle keyboard / TV remote navigation
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && state.mode === 'caregiver') {
    switchMode('child');
  }
});

/* ─── Run ────────────────────────────────────────────────────────────────── */
init().catch(() => {
  el.mascotStatus.textContent = 'Failed to load. Please refresh the page.';
});
