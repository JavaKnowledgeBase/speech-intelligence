"use strict";

let cachedVoices = [];
if ("speechSynthesis" in window) {
  cachedVoices = window.speechSynthesis.getVoices();
  if (cachedVoices.length === 0) {
    window.speechSynthesis.addEventListener("voiceschanged", () => {
      cachedVoices = window.speechSynthesis.getVoices();
    });
  }
}

const S = {
  IDLE: "idle",
  COACHING: "coaching",
  LISTENING: "listening",
  PROCESSING: "processing",
  SUCCESS: "success",
  RETRY: "retry",
  ESCALATED: "escalated",
  COMPLETED: "completed",
};

const COACHING_TO_LISTENING_GAP_MS = 90;
const PROMPT_ECHO_GUARD_MS = 160;
const NO_PROMPT_ECHO_GUARD_MS = 60;

const state = {
  sessionState: S.IDLE,
  sessionId: sessionStorage.getItem("tb_session_id"),
  childId: sessionStorage.getItem("tb_child_id"),
  childName: sessionStorage.getItem("tb_child_name") || "Friend",
  rewardPoints: 0,
  recognition: null,
  recognitionActive: false,
  listenToken: 0,
  listenReadyAt: 0,
  wakeLock: null,
  ttsBackend: false,
  deepgramWs: null,
  deepgramMicStream: null,
  deepgramAudioContext: null,
  deepgramSourceNode: null,
  deepgramProcessor: null,
  deepgramSink: null,
  deepgramReady: false,
  deepgramFinalPending: false,
  currentTarget: null,
};

const el = {
  childName: document.getElementById("session-child-name"),
  starsDisplay: document.getElementById("stars-display"),
  sttBadge: document.getElementById("stt-badge"),
  ttsBadge: document.getElementById("tts-badge"),
  endSessionBtn: document.getElementById("end-session-btn"),
  mascot: document.getElementById("mascot"),
  mascotBubble: document.getElementById("mascot-bubble"),
  mascotBubbleText: document.getElementById("mascot-bubble-text"),
  mascotStatus: document.getElementById("mascot-status"),
  targetCard: document.getElementById("target-card"),
  targetIcon: document.getElementById("target-icon"),
  targetWord: document.getElementById("target-word"),
  targetCue: document.getElementById("target-cue"),
  micRing: document.getElementById("mic-ring"),
  micLabel: document.getElementById("mic-label"),
  interimDisplay: document.getElementById("interim-display"),
  celebrationOverlay: document.getElementById("celebration-overlay"),
  celebrationEmoji: document.getElementById("celebration-emoji"),
  celebrationTitle: document.getElementById("celebration-title"),
  celebrationSub: document.getElementById("celebration-sub"),
  helpOverlay: document.getElementById("help-overlay"),
  helpMessage: document.getElementById("help-message"),
  dismissHelpBtn: document.getElementById("dismiss-help-btn"),
  completedOverlay: document.getElementById("completed-overlay"),
  completedSub: document.getElementById("completed-sub"),
  startOverBtn: document.getElementById("start-over-btn"),
};

const TARGET_ICONS = {
  ball: "B",
  house: "H",
  cat: "C",
  dog: "D",
  cup: "U",
  sun: "S",
  tree: "T",
  car: "R",
  bird: "I",
  fish: "F",
  hat: "A",
  bus: "U",
  boat: "O",
  shoe: "E",
  hand: "N",
  bath: "B",
  bed: "D",
  door: "D",
  milk: "M",
  book: "K",
  sock: "S",
  coat: "C",
  apple: "A",
  banana: "N",
  orange: "O",
  water: "W",
  bread: "R",
  chair: "C",
};

function getIcon(word) {
  return TARGET_ICONS[(word || "").toLowerCase()] || "?";
}

function setMascot(animation) {
  el.mascot.className = `mascot lips-mascot ${animation}`;
}

function showBubble(text) {
  el.mascotBubbleText.textContent = text;
  el.mascotBubble.hidden = false;
}

function hideBubble() {
  el.mascotBubble.hidden = true;
}

function setMic(mode, label) {
  el.micRing.className = `mic-ring ${mode}`;
  el.micLabel.textContent = label;
}

function updateStars(points) {
  const earned = Math.min(5, Math.floor(points / 10));
  el.starsDisplay.querySelectorAll(".star").forEach((star, index) => {
    star.textContent = index < earned ? "*" : ".";
    star.classList.toggle("earned", index < earned);
  });
  el.starsDisplay.setAttribute("aria-label", `${earned} of 5 stars earned`);
}

function transitionTo(nextState) {
  state.sessionState = nextState;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`${path} ${response.status}`);
  }
  return response.json();
}

async function postCheckpoint(kind, elapsedMs, detail = null) {
  if (!state.sessionId) return;
  api("/runtime/voice/checkpoints", {
    method: "POST",
    body: JSON.stringify({
      session_id: state.sessionId,
      checkpoint_kind: kind,
      elapsed_ms: Math.max(0, Math.round(elapsedMs)),
      detail,
    }),
  }).catch(() => {});
}

async function completeSessionApi() {
  if (!state.sessionId) return;
  api(`/sessions/${state.sessionId}/complete`, { method: "POST" }).catch(() => {});
}

async function requestWakeLock() {
  if (!("wakeLock" in navigator)) return;
  try {
    state.wakeLock = await navigator.wakeLock.request("screen");
  } catch {}
}

function releaseWakeLock() {
  if (!state.wakeLock) return;
  state.wakeLock.release().catch(() => {});
  state.wakeLock = null;
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && state.sessionId) {
    requestWakeLock();
  }
});

function speak(text) {
  return new Promise((resolve) => {
    if (!text || !text.trim()) {
      resolve();
      return;
    }
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
  if (!("speechSynthesis" in window)) {
    done();
    return;
  }
  const synth = window.speechSynthesis;
  synth.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 0.88;
  utterance.pitch = 1.05;
  utterance.volume = 1.0;
  const preferredVoice =
    cachedVoices.find((voice) => voice.lang.startsWith("en") && voice.localService) ||
    cachedVoices.find((voice) => voice.lang.startsWith("en"));
  if (preferredVoice) {
    utterance.voice = preferredVoice;
  }
  const words = text.trim().split(/\s+/).length;
  const estimatedMs = Math.round((words / 130) * 60000 / 0.88) + 800;
  const guard = setTimeout(() => done(), Math.max(estimatedMs, 2000));
  const finish = () => {
    clearTimeout(guard);
    done();
  };
  utterance.onend = finish;
  utterance.onerror = finish;
  try {
    synth.speak(utterance);
  } catch {
    clearTimeout(guard);
    done();
  }
}

function initBrowserSTT() {
  return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
}

const browserSpeechReady = initBrowserSTT();

function startBrowserListening() {
  if (!browserSpeechReady) return;
  const token = ++state.listenToken;
  const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
  state.recognition = new SpeechRecognitionCtor();
  state.recognition.lang = "en-US";
  state.recognition.continuous = false;
  state.recognition.interimResults = true;
  state.recognitionActive = true;

  state.recognition.onresult = (event) => {
    const results = Array.from(event.results);
    const transcript = results.map((result) => result[0].transcript).join("");
    el.interimDisplay.textContent = transcript;
    if (!results[results.length - 1].isFinal || state.sessionState !== S.LISTENING) return;
    if (Date.now() < state.listenReadyAt) {
      el.interimDisplay.textContent = "";
      return;
    }
    state.recognitionActive = false;
    handleTranscript(transcript, null, "stt_stream");
  };

  state.recognition.onerror = (event) => {
    if (token !== state.listenToken) return;
    state.recognitionActive = false;
    if ((event.error === "aborted" || event.error === "no-speech") && state.sessionState === S.LISTENING) {
      setTimeout(() => startListening(), 500);
    }
  };

  state.recognition.onend = () => {
    if (token !== state.listenToken) return;
    state.recognitionActive = false;
    if (state.sessionState === S.LISTENING) {
      setTimeout(() => startListening(), 300);
    }
  };

  try {
    state.recognition.start();
  } catch {}
}

function downsampleBuffer(channelData, inputSampleRate, targetSampleRate) {
  if (inputSampleRate === targetSampleRate) {
    return channelData;
  }
  const ratio = inputSampleRate / targetSampleRate;
  const length = Math.round(channelData.length / ratio);
  const result = new Float32Array(length);
  let offsetResult = 0;
  let offsetBuffer = 0;

  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0;
    let count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < channelData.length; i += 1) {
      accum += channelData[i];
      count += 1;
    }
    result[offsetResult] = count > 0 ? accum / count : 0;
    offsetResult += 1;
    offsetBuffer = nextOffsetBuffer;
  }

  return result;
}

function encodePcm16(channelData, inputSampleRate) {
  const downsampled = downsampleBuffer(channelData, inputSampleRate, 16000);
  const pcm = new Int16Array(downsampled.length);
  for (let i = 0; i < downsampled.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, downsampled[i]));
    pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return pcm.buffer;
}

function cleanupDeepgramNodes() {
  if (state.deepgramProcessor) {
    try { state.deepgramProcessor.disconnect(); } catch {}
  }
  if (state.deepgramSourceNode) {
    try { state.deepgramSourceNode.disconnect(); } catch {}
  }
  if (state.deepgramSink) {
    try { state.deepgramSink.disconnect(); } catch {}
  }
  state.deepgramProcessor = null;
  state.deepgramSourceNode = null;
  state.deepgramSink = null;
}

async function closeDeepgram() {
  state.deepgramReady = false;
  state.deepgramFinalPending = false;
  cleanupDeepgramNodes();
  if (state.deepgramAudioContext) {
    try { await state.deepgramAudioContext.close(); } catch {}
  }
  state.deepgramAudioContext = null;
  if (state.deepgramMicStream) {
    state.deepgramMicStream.getTracks().forEach((track) => track.stop());
  }
  state.deepgramMicStream = null;
  if (state.deepgramWs) {
    try { state.deepgramWs.close(); } catch {}
  }
  state.deepgramWs = null;
}

async function suspendDeepgramCapture() {
  if (state.deepgramAudioContext?.state === "running") {
    try { await state.deepgramAudioContext.suspend(); } catch {}
  }
  state.deepgramFinalPending = false;
}

async function resumeDeepgramCapture() {
  if (state.deepgramAudioContext?.state === "suspended") {
    try { await state.deepgramAudioContext.resume(); } catch {}
  }
  state.deepgramFinalPending = false;
}

async function tryInitDeepgramStream() {
  if (!state.sessionId || !state.childId) return false;

  let micStream;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: false,
      },
      video: false,
    });
  } catch {
    return false;
  }

  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(
    `${proto}://${location.host}/runtime/voice/stream?session_id=${encodeURIComponent(state.sessionId)}&child_id=${encodeURIComponent(state.childId)}`
  );
  ws.binaryType = "arraybuffer";

  try {
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("timeout")), 4000);
      ws.onopen = () => {
        clearTimeout(timeout);
        resolve();
      };
      ws.onerror = () => {
        clearTimeout(timeout);
        reject(new Error("ws error"));
      };
      ws.onclose = (event) => {
        clearTimeout(timeout);
        reject(new Error(`ws closed: ${event.code}`));
      };
    });
  } catch {
    micStream.getTracks().forEach((track) => track.stop());
    return false;
  }

  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor) {
    micStream.getTracks().forEach((track) => track.stop());
    ws.close();
    return false;
  }

  const audioContext = new AudioContextCtor();
  const source = audioContext.createMediaStreamSource(micStream);
  const processor = audioContext.createScriptProcessor(2048, 1, 1);
  const sink = audioContext.createGain();
  sink.gain.value = 0;

  processor.onaudioprocess = (event) => {
    if (state.sessionState !== S.LISTENING) return;
    if (!state.deepgramWs || state.deepgramWs.readyState !== WebSocket.OPEN) return;
    const pcmFrame = encodePcm16(event.inputBuffer.getChannelData(0), event.inputBuffer.sampleRate);
    state.deepgramWs.send(pcmFrame);
  };

  source.connect(processor);
  processor.connect(sink);
  sink.connect(audioContext.destination);
  await audioContext.suspend().catch(() => {});

  state.deepgramWs = ws;
  state.deepgramMicStream = micStream;
  state.deepgramAudioContext = audioContext;
  state.deepgramSourceNode = source;
  state.deepgramProcessor = processor;
  state.deepgramSink = sink;
  state.deepgramReady = true;
  state.deepgramFinalPending = false;

  el.sttBadge.textContent = "STT: Deepgram";
  el.sttBadge.classList.remove("mock");

  ws.onmessage = (event) => {
    try {
      const frame = JSON.parse(event.data);
      if (!frame.transcript) return;
      el.interimDisplay.textContent = frame.transcript;
      if (!(frame.is_final || frame.speech_final)) return;
      if (state.sessionState !== S.LISTENING || state.deepgramFinalPending) return;
      if (Date.now() < state.listenReadyAt) {
        el.interimDisplay.textContent = "";
        return;
      }
      state.deepgramFinalPending = true;
      handleTranscript(frame.transcript, frame.confidence ?? null, "stt_stream");
    } catch {}
  };

  ws.onclose = () => {
    closeDeepgram().catch(() => {});
    if (state.sessionState === S.LISTENING && browserSpeechReady) {
      el.sttBadge.textContent = "STT: Browser";
      el.sttBadge.classList.remove("mock");
      startBrowserListening();
    }
  };

  return true;
}

function startListening() {
  state.deepgramFinalPending = false;
  if (state.deepgramReady) {
    resumeDeepgramCapture();
    return;
  }
  if (browserSpeechReady) {
    el.sttBadge.textContent = "STT: Browser";
    el.sttBadge.classList.remove("mock");
    startBrowserListening();
    return;
  }
  el.sttBadge.textContent = "STT: Unavailable";
}

function stopListening() {
  state.listenToken += 1;
  state.recognitionActive = false;
  if (state.recognition) {
    try { state.recognition.abort(); } catch {}
    state.recognition = null;
  }
  suspendDeepgramCapture();
}

async function coachAndListen(message) {
  transitionTo(S.COACHING);
  if (message) {
    showBubble(message);
    setMascot("speak");
    setMic("idle", "Almost ready...");
    await speak(message);
    hideBubble();
  }
  if (state.sessionState !== S.COACHING) return;
  setMic("idle", "Your turn...");
  await new Promise((resolve) => setTimeout(resolve, COACHING_TO_LISTENING_GAP_MS));
  if (state.sessionState !== S.COACHING) return;
  transitionTo(S.LISTENING);
  setMascot("listen");
  setMic("listening", "Listening...");
  el.interimDisplay.textContent = "";
  state.listenReadyAt = Date.now() + (message ? PROMPT_ECHO_GUARD_MS : NO_PROMPT_ECHO_GUARD_MS);
  startListening();
}

async function handleTranscript(transcript, confidence = null, source = "stt_stream") {
  if (state.sessionState !== S.LISTENING) return;
  transitionTo(S.PROCESSING);
  stopListening();
  el.interimDisplay.textContent = transcript;
  setMascot("idle");
  setMic("processing", "Thinking...");
  el.mascotStatus.textContent = "Thinking...";
  await postCheckpoint("turn_ended", 0, "speech detected");

  let result;
  try {
    result = await api("/runtime/voice/transcript", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.sessionId,
        transcript,
        is_final: true,
        elapsed_ms: 0,
        attention_score: 0.8,
        source,
        confidence,
      }),
    });
  } catch {
    transitionTo(S.LISTENING);
    setMic("listening", "Listening...");
    startListening();
    return;
  }

  const evaluation = result.evaluation;
  if (!evaluation) {
    transitionTo(S.LISTENING);
    setMic("listening", "Listening...");
    startListening();
    return;
  }

  if (evaluation.action === "advance") {
    state.rewardPoints += 10;
    updateStars(state.rewardPoints);
    await handleSuccess(evaluation);
    return;
  }
  if (evaluation.action === "escalate") {
    await handleEscalation(evaluation);
    return;
  }
  await handleRetry(evaluation);
}

async function handleSuccess(evaluation) {
  transitionTo(S.SUCCESS);
  el.targetCard.classList.add("state-success");
  setMascot("cheer");
  el.celebrationEmoji.textContent = ["*", "!", "+", "#", "^"][Math.floor(Math.random() * 5)];
  el.celebrationTitle.textContent = ["Great job!", "Amazing!", "You did it!", "Brilliant!"][Math.floor(Math.random() * 4)];
  el.celebrationSub.textContent = evaluation.next_target ? `Next: ${evaluation.next_target}` : "";
  el.celebrationOverlay.hidden = false;
  el.celebrationOverlay.style.display = "flex";
  await speak(evaluation.feedback);
  await new Promise((resolve) => setTimeout(resolve, 1400));
  el.celebrationOverlay.hidden = true;
  el.celebrationOverlay.style.display = "none";
  el.targetCard.classList.remove("state-success");
  if (evaluation.next_target) {
    updateTarget(evaluation.next_target, null);
    await coachAndListen(`Now let's try ${evaluation.next_target}. Can you say ${evaluation.next_target}?`);
    return;
  }
  await handleComplete();
}

async function handleRetry(evaluation) {
  transitionTo(S.RETRY);
  el.targetCard.classList.add("state-retry");
  setMascot("speak");
  setMic("idle", "");
  await speak(`${evaluation.feedback} Can you say ${state.currentTarget}?`);
  el.targetCard.classList.remove("state-retry");
  await coachAndListen(null);
}

async function handleEscalation(evaluation) {
  transitionTo(S.ESCALATED);
  stopListening();
  setMascot("idle");
  setMic("idle", "");
  await speak(evaluation.feedback || "A grown-up will help you now.");
  el.helpOverlay.hidden = false;
  el.helpOverlay.style.display = "flex";
}

async function handleComplete() {
  transitionTo(S.COMPLETED);
  stopListening();
  releaseWakeLock();
  await completeSessionApi();
  el.completedSub.textContent = `${state.rewardPoints} reward points earned!`;
  await speak("Well done! Your session is complete.");
  el.completedOverlay.hidden = false;
  el.completedOverlay.style.display = "flex";
}

function updateTarget(word, cue) {
  state.currentTarget = word;
  el.targetIcon.textContent = getIcon(word);
  el.targetWord.textContent = word;
  el.targetCue.textContent = cue || "";
}

async function init() {
  el.childName.textContent = state.childName;
  updateStars(0);
  setMic("idle", "Starting...");
  setMascot("idle");
  el.sttBadge.textContent = browserSpeechReady ? "STT: Browser Backup" : "STT: Connecting";

  await requestWakeLock();

  try {
    const response = await fetch("/runtime/voice/tts/speak?text=ping", { method: "HEAD" }).catch(() => null);
    if (response && response.ok) {
      state.ttsBackend = true;
      el.ttsBadge.textContent = "TTS: OpenAI";
      el.ttsBadge.classList.remove("mock");
    }
  } catch {}

  if ("speechSynthesis" in window) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.addEventListener("voiceschanged", () => {
      window.speechSynthesis.getVoices();
    });
  }

  const sessionData = (() => {
    try {
      return JSON.parse(sessionStorage.getItem("tb_session_data") || "null");
    } catch {
      return null;
    }
  })();

  if (!state.sessionId || !state.childId) {
    el.mascotStatus.textContent = "No session found. Returning to welcome...";
    await speak("Let me take you back to the start.");
    setTimeout(() => { window.location.href = "/"; }, 1500);
    return;
  }

  const runtimeOk = await api("/runtime/voice/session", {
    method: "POST",
    body: JSON.stringify({
      session_id: state.sessionId,
      child_id: state.childId,
      audio_enabled: true,
    }),
  }).then(() => true).catch(() => false);

  if (!runtimeOk) {
    sessionStorage.removeItem("tb_session_id");
    sessionStorage.removeItem("tb_child_id");
    sessionStorage.removeItem("tb_session_data");
    el.mascotStatus.textContent = "Session expired. Returning to welcome...";
    await speak("Let me take you back to the start.");
    setTimeout(() => { window.location.href = "/"; }, 1500);
    return;
  }

  const deepgramReady = await tryInitDeepgramStream();
  if (!deepgramReady && browserSpeechReady) {
    el.sttBadge.textContent = "STT: Browser";
    el.sttBadge.classList.remove("mock");
  }

  if (sessionData) {
    updateTarget(sessionData.target_text, sessionData.cue);
    await postCheckpoint("turn_started", 0, "session opened from welcome");
    await coachAndListen(`Hi ${state.childName}! Can you say ${sessionData.target_text}?`);
    return;
  }

  el.mascotStatus.textContent = "Could not load session. Returning to welcome...";
  setTimeout(() => { window.location.href = "/"; }, 2000);
}

async function exitSession() {
  stopListening();
  releaseWakeLock();
  await closeDeepgram().catch(() => {});
  await completeSessionApi().catch(() => {});
  sessionStorage.removeItem("tb_session_id");
  sessionStorage.removeItem("tb_child_id");
  sessionStorage.removeItem("tb_session_data");
  window.location.href = "/";
}

el.endSessionBtn.addEventListener("click", () => {
  exitSession();
});

el.dismissHelpBtn.addEventListener("click", () => {
  el.helpOverlay.hidden = true;
  exitSession();
});

el.startOverBtn.addEventListener("click", async () => {
  el.completedOverlay.hidden = true;
  await closeDeepgram().catch(() => {});
  sessionStorage.removeItem("tb_session_id");
  sessionStorage.removeItem("tb_child_id");
  sessionStorage.removeItem("tb_session_data");
  window.location.href = "/";
});

window.addEventListener("beforeunload", () => {
  stopListening();
  closeDeepgram().catch(() => {});
});

init().catch(() => {
  el.mascotStatus.textContent = "Failed to load. Please refresh.";
});
