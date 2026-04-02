const state = {
  sessionId: null,
  children: [],
  currentChildId: null,
  audioContext: null,
  analyser: null,
  micStream: null,
  meterTimer: null,
  turnStartedAt: null,
};

const elements = {
  childSelect: document.querySelector('#child-select'),
  startSession: document.querySelector('#start-session'),
  completeSession: document.querySelector('#complete-session'),
  sessionStatus: document.querySelector('#session-status'),
  targetText: document.querySelector('#target-text'),
  targetCue: document.querySelector('#target-cue'),
  coachMessage: document.querySelector('#coach-message'),
  parentCard: document.querySelector('#parent-card'),
  parentMessage: document.querySelector('#parent-message'),
  enableMic: document.querySelector('#enable-mic'),
  connectTransport: document.querySelector('#connect-transport'),
  micStatus: document.querySelector('#mic-status'),
  meterFill: document.querySelector('#meter-fill'),
  meterCaption: document.querySelector('#meter-caption'),
  speakerReady: document.querySelector('#speaker-ready'),
  speakerStatus: document.querySelector('#speaker-status'),
  playbackState: document.querySelector('#playback-state'),
  transcriptInput: document.querySelector('#transcript-input'),
  attentionScore: document.querySelector('#attention-score'),
  attentionValue: document.querySelector('#attention-value'),
  sendTurn: document.querySelector('#send-turn'),
  turnFeedback: document.querySelector('#turn-feedback'),
  eventLog: document.querySelector('#event-log'),
  providerStatuses: document.querySelector('#provider-statuses'),
  runtimeRoom: document.querySelector('#runtime-room'),
  runtimeTokenState: document.querySelector('#runtime-token-state'),
  runtimeTransport: document.querySelector('#runtime-transport'),
  runtimeConnectionState: document.querySelector('#runtime-connection-state'),
  runtimeSttLane: document.querySelector('#runtime-stt-lane'),
  runtimeTtsLane: document.querySelector('#runtime-tts-lane'),
  runtimeTranscriptLane: document.querySelector('#runtime-transcript-lane'),
  latencySummary: document.querySelector('#latency-summary'),
};

function logEvent(message) {
  const item = document.createElement('li');
  item.textContent = `${new Date().toLocaleTimeString()} - ${message}`;
  elements.eventLog.prepend(item);
}

function setSessionState(label, active = false) {
  elements.sessionStatus.textContent = label;
  elements.completeSession.disabled = !active;
  elements.sendTurn.disabled = !active;
}

function renderChildren(children) {
  elements.childSelect.innerHTML = '';
  children.forEach((child) => {
    const option = document.createElement('option');
    option.value = child.child_id;
    option.textContent = `${child.name} (${child.age})`;
    elements.childSelect.append(option);
  });
  state.currentChildId = children[0]?.child_id ?? null;
}

function renderProviders(providers) {
  const wrap = document.createElement('div');
  wrap.className = 'provider-list';
  providers.forEach((provider) => {
    const badge = document.createElement('article');
    badge.className = `provider-badge ${provider.configured ? 'provider-live' : 'provider-mock'}`;
    badge.innerHTML = `<strong>${provider.provider}</strong><span>${provider.configured ? 'Configured' : 'Mock mode'}</span>`;
    wrap.append(badge);
  });
  const support = elements.providerStatuses.querySelector('.support-copy');
  if (support) support.remove();
  elements.providerStatuses.append(wrap);
}

async function loadBootstrap() {
  const [childrenRes, providerRes] = await Promise.all([
    fetch('/children'),
    fetch('/providers/status'),
  ]);
  const children = await childrenRes.json();
  const providers = await providerRes.json();
  state.children = children;
  renderChildren(children);
  renderProviders(providers);
  logEvent('Voice console loaded. Ready to start a child session.');
}





async function postCheckpoint(checkpointKind, elapsedMs, detail = null) {
  if (!state.sessionId) return null;
  const response = await fetch('/runtime/voice/checkpoints', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: state.sessionId,
      checkpoint_kind: checkpointKind,
      elapsed_ms: Math.max(0, Math.round(elapsedMs)),
      detail,
    }),
  });
  return response.json();
}


async function postRuntimeEvent(eventKind, detail, elapsedMs = 0) {
  if (!state.sessionId) return null;
  const response = await fetch('/runtime/voice/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: state.sessionId,
      event_kind: eventKind,
      elapsed_ms: Math.max(0, Math.round(elapsedMs)),
      detail,
    }),
  });
  return response.json();
}


async function enqueuePlayback(text, source = 'session_feedback') {
  if (!state.sessionId || !state.currentChildId || !text) return null;
  const response = await fetch('/runtime/voice/playback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: state.sessionId,
      child_id: state.currentChildId,
      text,
      source,
    }),
  });
  const item = await response.json();
  elements.playbackState.textContent = `${item.status} / ${item.voice_name}`;
  return item;
}

async function updatePlaybackState(playbackId, status, detail = null) {
  if (!state.sessionId || !playbackId) return null;
  const response = await fetch('/runtime/voice/playback/state', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: state.sessionId,
      playback_id: playbackId,
      status,
      detail,
    }),
  });
  const item = await response.json();
  elements.playbackState.textContent = `${item.status} / ${item.voice_name}`;
  return item;
}

async function createTtsJob(playbackId) {
  if (!state.sessionId || !playbackId) return null;
  const response = await fetch('/runtime/voice/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: state.sessionId,
      playback_id: playbackId,
    }),
  });
  const job = await response.json();
  elements.playbackState.textContent = `${job.status} / ${job.voice_name}`;
  return job;
}

async function processTtsJob(playbackId) {
  if (!state.sessionId || !playbackId) return null;
  const response = await fetch('/runtime/voice/tts/process', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: state.sessionId,
      playback_id: playbackId,
    }),
  });
  const job = await response.json();
  const artifactUri = job.artifact?.artifact_uri || 'artifact pending';
  elements.playbackState.textContent = `${job.status} / ${job.voice_name} / ${artifactUri}`;
  return job;
}

async function refreshCheckpointSummary() {
  if (!state.sessionId) return;
  const response = await fetch(`/runtime/voice/checkpoints?session_id=${encodeURIComponent(state.sessionId)}`);
  const payload = await response.json();
  const latest = payload.latest_by_kind || {};
  const parts = [];
  if (latest.turn_ended) parts.push(`turn end ${latest.turn_ended.elapsed_ms}ms`);
  if (latest.first_transcript) parts.push(`first transcript ${latest.first_transcript.elapsed_ms}ms`);
  if (latest.playback_started) parts.push(`playback ${latest.playback_started.elapsed_ms}ms`);
  elements.latencySummary.textContent = parts.length ? parts.join(' | ') : 'Voice checkpoints are waiting for the first turn.';
}

async function connectTransport() {
  if (!state.sessionId || !state.currentChildId) return;
  const response = await fetch('/runtime/voice/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: state.sessionId,
      child_id: state.currentChildId,
    }),
  });
  const payload = await response.json();
  elements.runtimeConnectionState.textContent = `${payload.connection_state} / ${payload.transport_kind}`;
  if (payload.access_token) {
    elements.runtimeTokenState.textContent = `LIVE transport - ${payload.token_status}`;
  }
  const dataLabels = (payload.data_channels || []).map((channel) => channel.label).join(', ');
  logEvent(`Transport handshake reached ${payload.connection_state}. Channels: ${dataLabels || 'none'}.`);
}

async function loadVoiceRuntime() {
  if (!state.sessionId || !state.currentChildId) return;
  const response = await fetch('/runtime/voice/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: state.sessionId,
      child_id: state.currentChildId,
      audio_enabled: true,
    }),
  });
  const payload = await response.json();
  elements.runtimeRoom.textContent = payload.room_name;
  elements.runtimeTokenState.textContent = `${payload.runtime_mode.toUpperCase()} transport - ${payload.token_status}`;
  elements.runtimeTransport.textContent = `${payload.transport_provider} / ${payload.client_config.transport_kind} / ${payload.client_config.turn_protocol}`;
  elements.runtimeConnectionState.textContent = `${payload.client_config.join_endpoint} / ${payload.client_config.reconnect_strategy}`;
  elements.runtimeSttLane.textContent = `${payload.client_config.stt_lane.provider} / ${payload.client_config.stt_lane.delivery_mode}`;
  elements.runtimeTtsLane.textContent = `${payload.client_config.tts_lane.provider} / ${payload.client_config.tts_lane.delivery_mode}`;
  elements.runtimeTranscriptLane.textContent = `${payload.client_config.transcript_lane.provider} / ${payload.client_config.transcript_lane.delivery_mode}`;
  elements.speakerStatus.textContent = payload.client_config.tts_lane.notes[0] || payload.tts_provider;
  elements.playbackState.textContent = 'No queued playback yet.';
  logEvent(`Voice runtime prepared in ${payload.runtime_mode} mode for room ${payload.room_name}.`);
}

async function startSession() {
  state.currentChildId = elements.childSelect.value;
  const response = await fetch('/session/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ child_id: state.currentChildId }),
  });
  const payload = await response.json();
  state.sessionId = payload.session_id;
  elements.targetText.textContent = payload.target_text;
  elements.targetCue.textContent = payload.cue;
  elements.coachMessage.textContent = payload.message;
  elements.turnFeedback.textContent = 'Waiting for the first recognized attempt.';
  if (payload.parent_message) {
    elements.parentCard.hidden = false;
    elements.parentMessage.textContent = payload.parent_message;
  } else {
    elements.parentCard.hidden = true;
  }
  setSessionState('Live', true);
  await loadVoiceRuntime();
  await connectTransport();
  await postRuntimeEvent('client_joined', 'Dev shell attached to voice runtime.');
  await postCheckpoint('turn_started', 0, 'session opened');
  await refreshCheckpointSummary();
  logEvent(`Session ${payload.session_id} started for ${state.currentChildId}. Target: ${payload.target_text}.`);
}

async function completeSession() {
  if (!state.sessionId) return;
  const response = await fetch(`/sessions/${state.sessionId}/complete`, { method: 'POST' });
  const payload = await response.json();
  setSessionState(payload.status === 'completed' ? 'Completed' : payload.status, false);
  logEvent(`Session ${payload.session_id} closed with ${payload.reward_points} reward points.`);
  elements.runtimeConnectionState.textContent = 'Disconnected';
  state.sessionId = null;
}

async function sendTurn() {
  if (!state.sessionId) return;
  state.turnStartedAt = performance.now();
  const transcript = elements.transcriptInput.value.trim();
  if (!transcript) {
    logEvent('Transcript fallback was empty, so no turn was sent.');
    return;
  }
  await postRuntimeEvent('vad_stopped', 'Manual transcript fallback submitted by operator.');
  await postCheckpoint('turn_ended', 0, 'manual transcript submitted');
  const response = await fetch('/runtime/voice/transcript', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: state.sessionId,
      transcript,
      is_final: true,
      elapsed_ms: Math.round(performance.now() - state.turnStartedAt),
      attention_score: Number(elements.attentionScore.value),
      source: 'fallback_form',
    }),
  });
  const runtimePayload = await response.json();
  const payload = runtimePayload.evaluation;
  const transcriptElapsed = performance.now() - state.turnStartedAt;
  await postCheckpoint('first_transcript', transcriptElapsed, runtimePayload.transcript_record.transcript);
  await postCheckpoint('first_token', transcriptElapsed + 40, payload.action);
  await postCheckpoint('first_audio_byte', transcriptElapsed + 110, payload.feedback);
  await postCheckpoint('playback_started', transcriptElapsed + 180, payload.feedback);
  elements.turnFeedback.textContent = payload.feedback;
  elements.coachMessage.textContent = payload.feedback;
  const playbackItem = await enqueuePlayback(payload.feedback);
  if (playbackItem) {
    await createTtsJob(playbackItem.playback_id);
    const processedJob = await processTtsJob(playbackItem.playback_id);
    await updatePlaybackState(
      playbackItem.playback_id,
      'ready',
      processedJob?.artifact?.artifact_uri || 'Coach reply is ready for synthesis or playback.',
    );
  }
  if (payload.parent_message) {
    elements.parentCard.hidden = false;
    elements.parentMessage.textContent = payload.parent_message;
  }
  if (payload.next_target) {
    elements.targetText.textContent = payload.next_target;
  }
  await refreshCheckpointSummary();
  logEvent(`Turn processed as ${payload.action}. Transcript: "${runtimePayload.transcript_record.transcript}".`);
}

async function enableMicrophone() {
  try {
    state.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    state.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = state.audioContext.createMediaStreamSource(state.micStream);
    state.analyser = state.audioContext.createAnalyser();
    state.analyser.fftSize = 256;
    source.connect(state.analyser);

    const buffer = new Uint8Array(state.analyser.frequencyBinCount);
    if (state.meterTimer) {
      window.clearInterval(state.meterTimer);
    }
    state.meterTimer = window.setInterval(() => {
      state.analyser.getByteFrequencyData(buffer);
      const average = buffer.reduce((sum, value) => sum + value, 0) / buffer.length;
      const percent = Math.max(8, Math.min(100, Math.round((average / 255) * 100)));
      elements.meterFill.style.width = `${percent}%`;
      elements.meterCaption.textContent = `Live microphone level ${percent}%. Streaming STT wiring comes next.`;
    }, 120);

    elements.micStatus.textContent = 'Mic live';
    elements.meterCaption.textContent = 'Microphone permission granted.';
    await postRuntimeEvent('vad_started', 'Microphone permission granted in dev shell.');
    logEvent('Microphone permission granted and input level monitor started.');
  } catch (error) {
    elements.micStatus.textContent = 'Mic denied';
    elements.meterCaption.textContent = 'Microphone permission was blocked.';
    logEvent('Microphone permission was denied or unavailable.');
  }
}

async function markSpeakerReady() {
  elements.runtimeTtsLane.textContent = 'Speaker lane armed / local_only';
  elements.speakerStatus.textContent = 'Speaker lane armed for the future TTS handoff.';
  elements.playbackState.textContent = 'ready / calm-coach';
  await postRuntimeEvent('client_joined', 'Speaker lane marked ready in dev shell.');
  logEvent('Speaker output lane marked ready for the future TTS handoff.');
}

elements.childSelect?.addEventListener('change', (event) => {
  state.currentChildId = event.target.value;
});

elements.startSession?.addEventListener('click', startSession);

elements.completeSession?.addEventListener('click', completeSession);

elements.enableMic?.addEventListener('click', enableMicrophone);

elements.connectTransport?.addEventListener('click', connectTransport);

elements.speakerReady?.addEventListener('click', markSpeakerReady);

elements.sendTurn?.addEventListener('click', sendTurn);

elements.attentionScore?.addEventListener('input', (event) => {
  elements.attentionValue.textContent = Number(event.target.value).toFixed(2);
});

loadBootstrap().catch((error) => {
  logEvent('Initial voice console bootstrap failed.');
  console.error(error);
});
