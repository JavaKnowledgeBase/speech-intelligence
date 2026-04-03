'use strict';

/* ── State ─────────────────────────────────────────────────────────────────── */
const S = { IDLE:'idle', COACHING:'coaching', LISTENING:'listening',
            PROCESSING:'processing', SUCCESS:'success', RETRY:'retry',
            ESCALATED:'escalated', COMPLETED:'completed' };

const state = {
  sessionState: S.IDLE,
  sessionId:    sessionStorage.getItem('tb_session_id'),
  childId:      sessionStorage.getItem('tb_child_id'),
  childName:    sessionStorage.getItem('tb_child_name') || 'Friend',
  rewardPoints: 0,
  recognition:  null,
  recognitionActive: false,
  wakeLock:     null,
  ttsBackend:   false,
  deepgramWs:       null,
  deepgramRecorder: null,
  deepgramMicStream: null,
  deepgramReady: false,
  currentTarget: null,
};

/* ── DOM refs ──────────────────────────────────────────────────────────────── */
const el = {
  childName:          document.getElementById('session-child-name'),
  starsDisplay:       document.getElementById('stars-display'),
  sttBadge:           document.getElementById('stt-badge'),
  ttsBadge:           document.getElementById('tts-badge'),
  endSessionBtn:      document.getElementById('end-session-btn'),
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
};

/* ── Helpers ───────────────────────────────────────────────────────────────── */
const TARGET_ICONS = {
  ball:'⚾',house:'🏠',cat:'🐱',dog:'🐶',cup:'🥤',sun:'☀️',tree:'🌳',car:'🚗',
  bird:'🐦',fish:'🐟',hat:'🎩',bus:'🚌',boat:'⛵',shoe:'👟',hand:'✋',
  bath:'🛁',bed:'🛏️',door:'🚪',milk:'🥛',book:'📚',sock:'🧦',coat:'🧥',
  apple:'🍎',banana:'🍌',orange:'🍊',water:'💧',bread:'🍞',chair:'🪑',
};
const getIcon = w => TARGET_ICONS[(w||'').toLowerCase()] || '💬';

function setMascot(anim) { el.mascot.className = `mascot lips-mascot ${anim}`; }
function showBubble(t) { el.mascotBubbleText.textContent = t; el.mascotBubble.hidden = false; }
function hideBubble() { el.mascotBubble.hidden = true; }
function setMic(mode, label) {
  el.micRing.className = `mic-ring ${mode}`;
  el.micLabel.textContent = label;
}
function updateStars(pts) {
  const earned = Math.min(5, Math.floor(pts / 10));
  el.starsDisplay.querySelectorAll('.star').forEach((s, i) => {
    s.textContent = i < earned ? '★' : '☆';
    s.classList.toggle('earned', i < earned);
  });
  el.starsDisplay.setAttribute('aria-label', `${earned} of 5 stars earned`);
}
function transitionTo(s) { state.sessionState = s; }

/* ── API ───────────────────────────────────────────────────────────────────── */
async function api(path, opts = {}) {
  const r = await fetch(path, { headers:{'Content-Type':'application/json'}, ...opts });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}
async function postCheckpoint(kind, ms, detail=null) {
  if (!state.sessionId) return;
  api('/runtime/voice/checkpoints', { method:'POST',
    body: JSON.stringify({ session_id:state.sessionId, checkpoint_kind:kind,
                           elapsed_ms:Math.max(0,Math.round(ms)), detail }) }).catch(()=>{});
}
async function completeSessionApi() {
  if (!state.sessionId) return;
  api(`/sessions/${state.sessionId}/complete`, { method:'POST' }).catch(()=>{});
}

/* ── Wake lock ─────────────────────────────────────────────────────────────── */
async function requestWakeLock() {
  if ('wakeLock' in navigator) {
    try { state.wakeLock = await navigator.wakeLock.request('screen'); } catch {}
  }
}
function releaseWakeLock() {
  if (state.wakeLock) { state.wakeLock.release().catch(()=>{}); state.wakeLock = null; }
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && state.sessionId) requestWakeLock();
});

/* ── TTS ───────────────────────────────────────────────────────────────────── */
function speak(text) {
  return new Promise(resolve => {
    if (!text?.trim()) { resolve(); return; }
    if (state.ttsBackend) {
      const audio = new Audio(`/runtime/voice/tts/speak?text=${encodeURIComponent(text)}`);
      audio.onended = resolve;
      audio.onerror = () => speakBrowser(text, resolve);
      audio.play().catch(() => speakBrowser(text, resolve));
      return;
    }
    speakBrowser(text, resolve);
  });
}
function speakBrowser(text, done) {
  if (!('speechSynthesis' in window)) { done(); return; }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 0.88; u.pitch = 1.05; u.volume = 1.0;
  const v = window.speechSynthesis.getVoices();
  const pref = v.find(x => x.lang.startsWith('en') && x.localService) || v.find(x=>x.lang.startsWith('en'));
  if (pref) u.voice = pref;
  const guard = setTimeout(() => done(), Math.max(text.length * 80, 1500));
  const fin = () => { clearTimeout(guard); done(); };
  u.onend = fin; u.onerror = fin;
  window.speechSynthesis.speak(u);
}

/* ── STT ───────────────────────────────────────────────────────────────────── */
function initSTT() {
  if (window.SpeechRecognition || window.webkitSpeechRecognition) {
    el.sttBadge.textContent = 'STT: Browser';
    el.sttBadge.classList.remove('mock');
    return true;
  }
  return false;
}
const sttReady = initSTT();

function startListening() {
  if (!sttReady) return;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  state.recognition = new SR();
  state.recognition.lang = 'en-US';
  state.recognition.continuous = false;
  state.recognition.interimResults = true;
  state.recognitionActive = true;

  state.recognition.onresult = e => {
    const results = Array.from(e.results);
    const transcript = results.map(r => r[0].transcript).join('');
    el.interimDisplay.textContent = transcript;
    if (results[results.length-1].isFinal && state.sessionState === S.LISTENING) {
      state.recognitionActive = false;
      handleTranscript(transcript);
    }
  };
  state.recognition.onerror = e => {
    state.recognitionActive = false;
    if ((e.error === 'aborted' || e.error === 'no-speech') && state.sessionState === S.LISTENING)
      setTimeout(startListening, 500);
  };
  state.recognition.onend = () => {
    state.recognitionActive = false;
    if (state.sessionState === S.LISTENING) setTimeout(startListening, 300);
  };
  try { state.recognition.start(); } catch {}
}

function stopListening() {
  state.recognitionActive = false;
  if (state.recognition) { try { state.recognition.abort(); } catch {} state.recognition = null; }
  if (state.deepgramRecorder?.state === 'recording') {
    try { state.deepgramRecorder.pause(); } catch {}
  }
}

/* ── Session loop ──────────────────────────────────────────────────────────── */
async function coachAndListen(message) {
  transitionTo(S.COACHING);
  showBubble(message);
  setMascot('speak');
  setMic('idle', 'Getting ready…');
  await speak(message);
  hideBubble();
  if (state.sessionState !== S.COACHING) return;
  transitionTo(S.LISTENING);
  setMascot('listen');
  setMic('listening', 'Listening…');
  el.interimDisplay.textContent = '';
  startListening();
}

async function handleTranscript(transcript) {
  if (state.sessionState !== S.LISTENING) return;
  transitionTo(S.PROCESSING);
  stopListening();
  el.interimDisplay.textContent = transcript;
  setMascot('idle');
  setMic('processing', 'Thinking…');
  el.mascotStatus.textContent = 'Thinking…';
  await postCheckpoint('turn_ended', 0, 'speech detected');

  let result;
  try {
    result = await api('/runtime/voice/transcript', {
      method:'POST',
      body: JSON.stringify({
        session_id: state.sessionId,
        transcript,
        is_final: true,
        elapsed_ms: 0,
        attention_score: 0.8,
        source: 'web_speech_api',
      }),
    });
  } catch {
    transitionTo(S.LISTENING); setMic('listening','Listening…'); startListening(); return;
  }

  const ev = result.evaluation;
  if (!ev) { transitionTo(S.LISTENING); setMic('listening','Listening…'); startListening(); return; }

  if (ev.action === 'advance') {
    state.rewardPoints += 10; updateStars(state.rewardPoints);
    await handleSuccess(ev);
  } else if (ev.action === 'escalate') {
    await handleEscalation(ev);
  } else {
    await handleRetry(ev);
  }
}

async function handleSuccess(ev) {
  transitionTo(S.SUCCESS);
  el.targetCard.classList.add('state-success');
  setMascot('cheer');
  el.celebrationEmoji.textContent = ['🌟','🎉','🏆','⭐','✨'][Math.floor(Math.random()*5)];
  el.celebrationTitle.textContent = ['Great job!','Amazing!','You did it!','Brilliant!'][Math.floor(Math.random()*4)];
  el.celebrationSub.textContent = ev.next_target ? `Next: ${ev.next_target}` : '';
  el.celebrationOverlay.hidden = false;
  await speak(ev.feedback);
  await new Promise(r => setTimeout(r, 1800));
  el.celebrationOverlay.hidden = true;
  el.targetCard.classList.remove('state-success');
  if (ev.next_target) {
    updateTarget(ev.next_target, null);
    await coachAndListen(ev.feedback || `Now let's try ${ev.next_target}.`);
  } else {
    await handleComplete();
  }
}

async function handleRetry(ev) {
  transitionTo(S.RETRY);
  el.targetCard.classList.add('state-retry');
  setMascot('speak');
  setMic('idle','');
  await speak(ev.feedback);
  await new Promise(r => setTimeout(r, 400));
  el.targetCard.classList.remove('state-retry');
  await coachAndListen(ev.feedback || 'Let us try that one again.');
}

async function handleEscalation(ev) {
  transitionTo(S.ESCALATED);
  stopListening();
  setMascot('idle');
  setMic('idle','');
  await speak(ev.feedback || 'A grown-up will help you now.');
  el.helpOverlay.hidden = false;
}

async function handleComplete() {
  transitionTo(S.COMPLETED);
  stopListening();
  releaseWakeLock();
  await completeSessionApi();
  el.completedSub.textContent = `${state.rewardPoints} reward points earned!`;
  await speak('Well done! Your session is complete.');
  el.completedOverlay.hidden = false;
}

function updateTarget(word, cue) {
  state.currentTarget = word;
  el.targetIcon.textContent = getIcon(word);
  el.targetWord.textContent = word;
  el.targetCue.textContent = cue || '';
}

/* ── Bootstrap ─────────────────────────────────────────────────────────────── */
async function init() {
  el.childName.textContent = state.childName;
  updateStars(0);
  setMic('idle','Starting…');
  setMascot('idle');

  await requestWakeLock();

  // Check backend TTS
  try {
    const r = await fetch('/runtime/voice/tts/speak?text=ping', { method:'HEAD' }).catch(()=>null);
    if (r && r.ok) { state.ttsBackend = true; el.ttsBadge.textContent = 'TTS: OpenAI'; el.ttsBadge.classList.remove('mock'); }
  } catch {}

  // Warm up speech voices
  if ('speechSynthesis' in window) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.addEventListener('voiceschanged', () => window.speechSynthesis.getVoices());
  }

  const sessionData = (() => {
    try { return JSON.parse(sessionStorage.getItem('tb_session_data') || 'null'); } catch { return null; }
  })();

  if (!state.sessionId || !state.childId) {
    // No session — redirect back to welcome
    el.mascotStatus.textContent = 'No session found. Returning to welcome…';
    await speak('Let me take you back to the start.');
    setTimeout(() => { window.location.href = '/'; }, 1500);
    return;
  }

  // Wire voice runtime scaffold
  await api('/runtime/voice/session', { method:'POST',
    body: JSON.stringify({ session_id:state.sessionId, child_id:state.childId, audio_enabled:true })
  }).catch(()=>{});

  if (sessionData) {
    updateTarget(sessionData.target_text, sessionData.cue);
    await postCheckpoint('turn_started', 0, 'session opened from welcome');
    await coachAndListen(sessionData.message || `Let's practice. Can you say ${sessionData.target_text}?`);
  } else {
    el.mascotStatus.textContent = 'Could not load session. Returning to welcome…';
    setTimeout(() => { window.location.href = '/'; }, 2000);
  }
}

/* ── Events ────────────────────────────────────────────────────────────────── */
el.endSessionBtn.addEventListener('click', async () => {
  stopListening(); releaseWakeLock();
  await completeSessionApi().catch(()=>{});
  sessionStorage.removeItem('tb_session_id');
  sessionStorage.removeItem('tb_child_id');
  sessionStorage.removeItem('tb_session_data');
  window.location.href = '/';
});

el.dismissHelpBtn.addEventListener('click', async () => {
  el.helpOverlay.hidden = true;
  stopListening(); releaseWakeLock();
  await completeSessionApi().catch(()=>{});
  window.location.href = '/';
});

el.startOverBtn.addEventListener('click', () => {
  el.completedOverlay.hidden = true;
  window.location.href = '/';
});

init().catch(() => {
  el.mascotStatus.textContent = 'Failed to load. Please refresh.';
});
