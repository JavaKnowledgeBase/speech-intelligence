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

const PROMPT_ECHO_GUARD_MS = 160;
const NO_PROMPT_ECHO_GUARD_MS = 60;
const DEEPGRAM_RECONNECT_MS = 1500;
const GEMINI_PROMOTION_DELAY_MS = 1800;

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
  deepgramPeerConnection: null,
  deepgramDataChannel: null,
  deepgramRemoteAudio: null,
  deepgramMicStream: null,
  deepgramAudioContext: null,
  deepgramSourceNode: null,
  deepgramProcessor: null,
  deepgramSink: null,
  deepgramReady: false,
  deepgramFinalPending: false,
  deepgramReconnectTimer: null,
  deepgramReconnectAttempts: 0,
  deepgramPromotionTimer: null,
  deepgramFinalizeTimer: null,
  deepgramLastTranscript: "",
  usingBrowserFallback: false,
  exitingSession: false,
  turnCaptureEnabled: false,
  ttsActive: false,
  currentTarget: null,
  embeddedHost: false,
  initialized: false,
  pendingSessionData: null,
};

const root = document.getElementById("session-screen") || document;
const pick = (id) => root.querySelector(`#${id}`);
const el = {
  childName: pick("session-child-name"),
  starsDisplay: pick("stars-display"),
  sttBadge: pick("stt-badge"),
  ttsBadge: pick("tts-badge"),
  endSessionBtn: pick("end-session-btn"),
  mascot: pick("mascot"),
  mascotBubble: pick("mascot-bubble"),
  mascotBubbleText: pick("mascot-bubble-text"),
  mascotStatus: pick("mascot-status"),
  targetCard: pick("target-card"),
  targetIcon: pick("target-icon"),
  targetWord: pick("target-word"),
  targetCue: pick("target-cue"),
  micRing: pick("mic-ring"),
  micLabel: pick("mic-label"),
  interimDisplay: pick("interim-display"),
  celebrationOverlay: pick("celebration-overlay"),
  celebrationEmoji: pick("celebration-emoji"),
  celebrationTitle: pick("celebration-title"),
  celebrationSub: pick("celebration-sub"),
  helpOverlay: pick("help-overlay"),
  helpMessage: pick("help-message"),
  dismissHelpBtn: pick("dismiss-help-btn"),
  completedOverlay: pick("completed-overlay"),
  completedSub: pick("completed-sub"),
  startOverBtn: pick("start-over-btn"),
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
    state.ttsActive = true;
    if (state.ttsBackend) {
      const audio = new Audio(`/runtime/voice/tts/speak?text=${encodeURIComponent(text)}`);
      const finish = () => {
        state.ttsActive = false;
        resolve();
      };
      audio.onended = finish;
      audio.onerror = () => {
        state.ttsActive = false;
        speakBrowser(text, resolve);
      };
      audio.play().catch(() => {
        state.ttsActive = false;
        speakBrowser(text, resolve);
      });
      return;
    }
    speakBrowser(text, resolve);
  });
}

function speakBrowser(text, done) {
  state.ttsActive = true;
  if (!("speechSynthesis" in window)) {
    state.ttsActive = false;
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
    state.ttsActive = false;
    done();
  };
  utterance.onend = finish;
  utterance.onerror = finish;
  try {
    synth.speak(utterance);
  } catch {
    clearTimeout(guard);
    state.ttsActive = false;
    done();
  }
}

function initBrowserSTT() {
  return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
}

const browserSpeechReady = initBrowserSTT();

function canAcceptTranscript() {
  return state.turnCaptureEnabled && !state.ttsActive && Date.now() >= state.listenReadyAt;
}

function openTurnCapture(messageWasSpoken) {
  state.turnCaptureEnabled = true;
  state.deepgramFinalPending = false;
  state.listenReadyAt = Date.now() + (messageWasSpoken ? PROMPT_ECHO_GUARD_MS : NO_PROMPT_ECHO_GUARD_MS);
  transitionTo(S.LISTENING);
  setMascot("listen");
  el.mascotStatus.textContent = "Mic live";
  setMic("listening", "Mic live");
  el.interimDisplay.textContent = "";
}

function closeTurnCapture() {
  state.turnCaptureEnabled = false;
  state.deepgramFinalPending = false;
}

function clearDeepgramReconnectTimer() {
  if (state.deepgramReconnectTimer) {
    clearTimeout(state.deepgramReconnectTimer);
    state.deepgramReconnectTimer = null;
  }
}

function clearDeepgramPromotionTimer() {
  if (state.deepgramPromotionTimer) {
    clearTimeout(state.deepgramPromotionTimer);
    state.deepgramPromotionTimer = null;
  }
}

function canRecoverDeepgram() {
  return !state.exitingSession && ![S.COMPLETED, S.ESCALATED].includes(state.sessionState);
}

function activateBrowserFallback(reason = "Mic live") {
  clearDeepgramPromotionTimer();
  state.usingBrowserFallback = true;
  if (state.sessionState !== S.PROCESSING && state.sessionState !== S.COMPLETED && state.sessionState !== S.ESCALATED) {
    el.mascotStatus.textContent = reason;
  }
  el.sttBadge.textContent = "STT: Browser Mic";
  el.sttBadge.classList.remove("mock");
  if (browserSpeechReady && !state.recognitionActive) {
    startBrowserListening();
  }
}

async function scheduleDeepgramReconnect() {
  if (state.deepgramReady || state.deepgramReconnectTimer || !canRecoverDeepgram()) return;
  state.deepgramReconnectTimer = setTimeout(async () => {
    state.deepgramReconnectTimer = null;
    if (!canRecoverDeepgram() || state.deepgramReady) return;
    const restored = await tryInitDeepgramStream();
    if (restored) {
      state.usingBrowserFallback = false;
      if (state.sessionState !== S.PROCESSING) {
        el.mascotStatus.textContent = "Mic live";
      }
      ensureSessionMicLive();
      return;
    }
    state.deepgramReconnectAttempts += 1;
    scheduleDeepgramReconnect();
  }, DEEPGRAM_RECONNECT_MS);
}

function handleDeepgramDisconnect(reason = "Mic disconnected. Using backup") {
  Promise.resolve().then(() => closeDeepgram().catch(() => {}));
  activateBrowserFallback(reason);
  void scheduleDeepgramReconnect();
}

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
    if (!canAcceptTranscript()) {
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

function extractRealtimeTranscript(event) {
  const direct = event?.serverContent?.inputTranscription?.text || event?.inputTranscription?.text || event?.transcript;
  if (typeof direct === "string" && direct.trim()) {
    return direct.trim();
  }
  const content = event?.serverContent?.modelTurn?.parts || event?.item?.content;
  if (Array.isArray(content)) {
    for (const part of content) {
      const candidate = part?.transcript || part?.text || part?.value;
      if (typeof candidate === "string" && candidate.trim()) {
        return candidate.trim();
      }
    }
  }
  return "";
}

function clearDeepgramFinalizeTimer() {
  if (state.deepgramFinalizeTimer) {
    clearTimeout(state.deepgramFinalizeTimer);
    state.deepgramFinalizeTimer = null;
  }
}

function scheduleDeepgramTranscriptCommit(transcript, immediate = false) {
  state.deepgramLastTranscript = transcript;
  clearDeepgramFinalizeTimer();
  const delay = immediate ? 0 : 320;
  state.deepgramFinalizeTimer = setTimeout(() => {
    state.deepgramFinalizeTimer = null;
    const finalTranscript = (state.deepgramLastTranscript || "").trim();
    if (!finalTranscript) return;
    if (state.sessionState !== S.LISTENING || state.deepgramFinalPending || !canAcceptTranscript()) {
      return;
    }
    state.deepgramFinalPending = true;
    void handleTranscript(finalTranscript, null, "gemini_live");
  }, delay);
}

function cleanupDeepgramNodes() {
  clearDeepgramPromotionTimer();
  clearDeepgramFinalizeTimer();
  state.deepgramLastTranscript = "";
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
  clearDeepgramReconnectTimer();
  cleanupDeepgramNodes();
  if (state.deepgramAudioContext) {
    try { await state.deepgramAudioContext.close(); } catch {}
  }
  state.deepgramAudioContext = null;
  if (state.deepgramMicStream) {
    const mgr = window.TalkBuddyMicManager;
    if (mgr && state.deepgramMicStream === mgr.stream) {
      mgr.release();
    } else {
      state.deepgramMicStream.getTracks().forEach((track) => track.stop());
    }
  }
  state.deepgramMicStream = null;
  if (state.deepgramDataChannel) {
    try { state.deepgramDataChannel.close(); } catch {}
  }
  state.deepgramDataChannel = null;
  if (state.deepgramPeerConnection) {
    try { state.deepgramPeerConnection.close(); } catch {}
  }
  state.deepgramPeerConnection = null;
  if (state.deepgramRemoteAudio) {
    try { state.deepgramRemoteAudio.pause(); } catch {}
    state.deepgramRemoteAudio.srcObject = null;
  }
  state.deepgramRemoteAudio = null;
  if (state.deepgramWs) {
    try { state.deepgramWs.close(); } catch {}
  }
  state.deepgramWs = null;
}

async function tryInitDeepgramStream() {
  if (!state.sessionId || !state.childId) return false;

  let micStream;
  try {
    const hostMic = window.TalkBuddyMicManager;
    micStream = await (hostMic?.acquire?.() || navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: false,
      },
      video: false,
    }));
  } catch {
    return false;
  }

  let ws;
  let audioContext;
  let sourceNode;
  let processorNode;
  let sinkNode;

  try {
    const params = new URLSearchParams({
      session_id: state.sessionId,
      child_id: state.childId,
    });
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${window.location.host}/runtime/voice/gemini/live?${params.toString()}`);
    ws.binaryType = "arraybuffer";

    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Gemini Live connect timeout")), 10000);
      ws.onopen = () => {
        clearTimeout(timer);
        resolve();
      };
      ws.onerror = () => {
        clearTimeout(timer);
        reject(new Error("Gemini Live socket error"));
      };
      ws.onclose = () => {
        clearTimeout(timer);
        reject(new Error("Gemini Live socket closed"));
      };
    });

    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    sourceNode = audioContext.createMediaStreamSource(micStream);
    processorNode = audioContext.createScriptProcessor(4096, 1, 1);
    sinkNode = audioContext.createGain();
    sinkNode.gain.value = 0;

    processorNode.onaudioprocess = (event) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const input = event.inputBuffer.getChannelData(0);
      const pcmBuffer = encodePcm16(input, audioContext.sampleRate);
      try {
        ws.send(pcmBuffer);
      } catch {}
    };

    sourceNode.connect(processorNode);
    processorNode.connect(sinkNode);
    sinkNode.connect(audioContext.destination);

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.error) {
          handleDeepgramDisconnect("Live mic disconnected. Using backup");
          return;
        }
        const transcript = extractRealtimeTranscript(payload);
        if (transcript && canAcceptTranscript()) {
          el.interimDisplay.textContent = transcript;
          scheduleDeepgramTranscriptCommit(transcript, Boolean(payload.serverContent?.turnComplete));
        }
        if (payload.serverContent?.interrupted) {
          clearDeepgramFinalizeTimer();
        }
      } catch {}
    };

    ws.onclose = () => {
      handleDeepgramDisconnect("Live mic disconnected. Using backup");
    };
    ws.onerror = () => {
      handleDeepgramDisconnect("Live mic disconnected. Using backup");
    };
  } catch {
    const mgr = window.TalkBuddyMicManager;
    if (mgr && micStream === mgr.stream) {
      mgr.release();
    } else {
      micStream.getTracks().forEach((track) => track.stop());
    }
    try { if (processorNode) processorNode.disconnect(); } catch {}
    try { if (sourceNode) sourceNode.disconnect(); } catch {}
    try { if (sinkNode) sinkNode.disconnect(); } catch {}
    try { if (audioContext) audioContext.close(); } catch {}
    try { if (ws) ws.close(); } catch {}
    return false;
  }

  clearDeepgramReconnectTimer();
  clearDeepgramPromotionTimer();
  state.deepgramReconnectAttempts = 0;
  state.deepgramWs = ws;
  state.deepgramDataChannel = null;
  state.deepgramPeerConnection = null;
  state.deepgramRemoteAudio = null;
  state.deepgramMicStream = micStream;
  state.deepgramAudioContext = audioContext;
  state.deepgramSourceNode = sourceNode;
  state.deepgramProcessor = processorNode;
  state.deepgramSink = sinkNode;
  state.deepgramReady = true;
  state.deepgramFinalPending = false;
  state.deepgramLastTranscript = "";
  state.usingBrowserFallback = true;
  el.sttBadge.textContent = "STT: Browser Mic";
  el.sttBadge.classList.remove("mock");
  state.deepgramPromotionTimer = setTimeout(() => {
    state.deepgramPromotionTimer = null;
    if (!state.deepgramReady || state.exitingSession) return;
    state.usingBrowserFallback = false;
    if (state.sessionState !== S.PROCESSING && state.sessionState !== S.ESCALATED && state.sessionState !== S.COMPLETED) {
      el.mascotStatus.textContent = "Mic live";
    }
    el.sttBadge.textContent = "STT: Gemini Live";
    el.sttBadge.classList.remove("mock");
  }, GEMINI_PROMOTION_DELAY_MS);
  return true;
}

function ensureSessionMicLive() {
  if (state.deepgramReady) {
    if (state.sessionState !== S.PROCESSING && state.sessionState !== S.ESCALATED && state.sessionState !== S.COMPLETED) {
      el.mascotStatus.textContent = "Mic live";
    }
    el.sttBadge.textContent = "STT: Gemini Live";
    el.sttBadge.classList.remove("mock");
    setMic(state.sessionState === S.LISTENING ? "listening" : "idle", "Mic live");
    return;
  }
  if (browserSpeechReady) {
    activateBrowserFallback("Mic live");
    setMic(state.sessionState === S.LISTENING ? "listening" : "idle", "Mic live");
    return;
  }
  el.sttBadge.textContent = "STT: Unavailable";
  el.mascotStatus.textContent = "Mic unavailable";
}

function startListening() {
  ensureSessionMicLive();
}

function stopListening() {
  closeTurnCapture();
  state.listenToken += 1;
  state.recognitionActive = false;
  if (state.recognition) {
    try { state.recognition.abort(); } catch {}
    state.recognition = null;
  }
}

async function coachAndListen(message) {
  transitionTo(S.COACHING);
  closeTurnCapture();
  el.mascotStatus.textContent = message ? "Coach is speaking..." : "Mic live";
  setMic("idle", "Mic live");
  if (message) {
    showBubble(message);
    setMascot("speak");
    await speak(message);
    hideBubble();
  }
  if (state.sessionState !== S.COACHING) return;
  openTurnCapture(Boolean(message));
}

async function handleTranscript(transcript, confidence = null, source = "stt_stream") {
  if (state.sessionState !== S.LISTENING) return;
  transitionTo(S.PROCESSING);
  closeTurnCapture();
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
    openTurnCapture(false);
    ensureSessionMicLive();
    return;
  }

  const evaluation = result.evaluation;
  if (!evaluation) {
    openTurnCapture(false);
    ensureSessionMicLive();
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
  closeTurnCapture();
  setMascot("idle");
  setMic("idle", "");
  await speak(evaluation.feedback || "A grown-up will help you now.");
  el.helpOverlay.hidden = false;
  el.helpOverlay.style.display = "flex";
}

async function handleComplete() {
  transitionTo(S.COMPLETED);
  closeTurnCapture();
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

function returnToWelcome() {
  if (state.embeddedHost) {
    const childMode = document.getElementById("child-mode");
    if (childMode) childMode.hidden = true;
    const page = document.querySelector(".page");
    if (page) page.hidden = false;
    window.history.pushState({ view: "welcome" }, "", "/");
    return;
  }
  window.location.href = "/";
}

async function beginSessionTurn(sessionData) {
  if (!sessionData) return;
  state.pendingSessionData = null;
  updateTarget(sessionData.target_text, sessionData.cue);
  await postCheckpoint("turn_started", 0, "session opened from welcome");
  await coachAndListen(`Hi ${state.childName}! Can you say ${sessionData.target_text}?`);
}

async function init(options = {}) {
  if (state.initialized) return;
  state.initialized = true;
  state.embeddedHost = Boolean(options.embeddedHost);
  el.childName.textContent = state.childName;
  updateStars(0);
  el.mascotStatus.textContent = "Mic live";
  setMic("idle", "Mic live");
  setMascot("idle");
  el.sttBadge.textContent = browserSpeechReady ? "STT: Browser Mic" : "STT: Connecting";

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
  const realtimeReadiness = (() => {
    try {
      return JSON.parse(sessionStorage.getItem("tb_realtime_readiness") || "null");
    } catch {
      return null;
    }
  })();

  if (!state.sessionId || !state.childId) {
    el.mascotStatus.textContent = "No session found. Returning to welcome...";
    await speak("Let me take you back to the start.");
    setTimeout(() => { returnToWelcome(); }, 1500);
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
    sessionStorage.removeItem("tb_realtime_readiness");
    el.mascotStatus.textContent = "Session expired. Returning to welcome...";
    await speak("Let me take you back to the start.");
    setTimeout(() => { returnToWelcome(); }, 1500);
    return;
  }

  const allowGeminiLive = realtimeReadiness?.ready && realtimeReadiness?.mode === "gemini_live";

  if (options.preloadOnly) {
    // During preload: connect Gemini Live in background but keep audio suspended
    // so the main thread is free during the welcome→session transition.
    // Browser STT is intentionally NOT started here — it starts when the session
    // panel is revealed (startEmbeddedSession without preloadOnly).
    if (allowGeminiLive) {
      Promise.resolve().then(async () => {
        const deepgramReady = await tryInitDeepgramStream();
        if (deepgramReady && state.deepgramAudioContext) {
          // Suspend audio processing until the session panel is visible
          state.deepgramAudioContext.suspend().catch(() => {});
        }
      });
    }
    if (sessionData) {
      state.pendingSessionData = sessionData;
      updateTarget(sessionData.target_text, sessionData.cue);
    }
    return;
  }

  // Non-preload path: activate mic immediately
  if (allowGeminiLive) {
    Promise.resolve().then(async () => {
      const deepgramReady = await tryInitDeepgramStream();
      if (!deepgramReady) {
        void scheduleDeepgramReconnect();
        return;
      }
      ensureSessionMicLive();
    });
  }

  activateBrowserFallback("Mic live");
  ensureSessionMicLive();

  if (sessionData) {
    await beginSessionTurn(sessionData);
    return;
  }

  el.mascotStatus.textContent = "Could not load session. Returning to welcome...";
  setTimeout(() => { returnToWelcome(); }, 2000);
}

async function exitSession() {
  if (state.embeddedHost) {
    state.exitingSession = true;
    closeTurnCapture();
    stopListening();
    releaseWakeLock();
    await closeDeepgram().catch(() => {});
    await completeSessionApi().catch(() => {});
    sessionStorage.removeItem("tb_session_id");
    sessionStorage.removeItem("tb_child_id");
    sessionStorage.removeItem("tb_session_data");
    sessionStorage.removeItem("tb_realtime_readiness");
    state.initialized = false;
    state.embeddedHost = false;
    const childMode = document.getElementById("child-mode");
    if (childMode) childMode.hidden = true;
    const page = document.querySelector(".page");
    if (page) page.hidden = false;
    window.history.pushState({ view: "welcome" }, "", "/");
    return;
  }
  state.exitingSession = true;
  closeTurnCapture();
  stopListening();
  releaseWakeLock();
  await closeDeepgram().catch(() => {});
  await completeSessionApi().catch(() => {});
  sessionStorage.removeItem("tb_session_id");
  sessionStorage.removeItem("tb_child_id");
  sessionStorage.removeItem("tb_session_data");
  sessionStorage.removeItem("tb_realtime_readiness");
  returnToWelcome();
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
  sessionStorage.removeItem("tb_realtime_readiness");
  state.initialized = false;
  if (state.embeddedHost) {
    state.embeddedHost = false;
    const childMode = document.getElementById("child-mode");
    if (childMode) childMode.hidden = true;
    const page = document.querySelector(".page");
    if (page) page.hidden = false;
    window.history.pushState({ view: "welcome" }, "", "/");
    return;
  }
  returnToWelcome();
});

window.addEventListener("beforeunload", () => {
  state.exitingSession = true;
  stopListening();
  closeDeepgram().catch(() => {});
});

window.TalkBuddySessionApp = {
  async startEmbeddedSession(options = {}) {
    state.sessionId = sessionStorage.getItem("tb_session_id");
    state.childId = sessionStorage.getItem("tb_child_id");
    state.childName = sessionStorage.getItem("tb_child_name") || state.childName;
    state.exitingSession = false;
    if (!state.initialized) {
      await init({ embeddedHost: true, preloadOnly: Boolean(options.preloadOnly) });
      return;
    }
    if (!options.preloadOnly && state.pendingSessionData) {
      // Resume AudioContext if it was suspended during preload
      if (state.deepgramAudioContext?.state === "suspended") {
        state.deepgramAudioContext.resume().catch(() => {});
      }
      // Start browser STT fallback now that the session panel is visible
      activateBrowserFallback("Mic live");
      ensureSessionMicLive();
      await beginSessionTurn(state.pendingSessionData);
    }
  },
};

if (document.body && !document.getElementById("child-mode")?.hasAttribute("hidden")) {
  init().catch(() => {
    el.mascotStatus.textContent = "Failed to load. Please refresh.";
  });
}




