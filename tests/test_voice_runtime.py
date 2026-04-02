from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


client = TestClient(app)


def _start_session() -> tuple[str, str]:
    child_id = "child-1"
    response = client.post('/session/start', json={'child_id': child_id})
    payload = response.json()
    return child_id, payload['session_id']


def test_voice_runtime_mock_contract():
    child_id, session_id = _start_session()
    response = client.post('/runtime/voice/session', json={'child_id': child_id, 'session_id': session_id})
    payload = response.json()
    assert response.status_code == 200
    assert payload['runtime_mode'] == 'mock'
    assert payload['room_name'].startswith('talkbuddy-child-1-')
    assert payload['speech_to_text_provider'] == 'Deepgram Flux'
    assert payload['transport_provider'] == 'Mock Voice Harness'
    assert payload['client_config']['transport_kind'] == 'local_mock'
    assert payload['client_config']['turn_protocol'] == 'manual_turn'
    assert payload['client_config']['stt_lane']['provider'] == 'Transcript fallback form'
    assert payload['client_config']['stt_lane']['delivery_mode'] == 'local_only'
    assert payload['client_config']['stt_lane']['path'] == '/runtime/voice/transcript'
    assert payload['client_config']['tts_lane']['provider'] == 'Speaker-ready placeholder'
    assert payload['client_config']['transcript_lane']['delivery_mode'] == 'https_poll'
    assert payload['client_config']['event_lane']['path'] == '/runtime/voice/events'


def test_voice_runtime_live_token_when_configured(monkeypatch):
    child_id, session_id = _start_session()
    monkeypatch.setattr(settings, 'use_live_provider_calls', True)
    monkeypatch.setattr(settings, 'livekit_url', 'wss://livekit.example.test')
    monkeypatch.setattr(settings, 'livekit_api_key', 'lk_api_key')
    monkeypatch.setattr(settings, 'livekit_api_secret', 'lk_secret')
    monkeypatch.setattr(settings, 'livekit_room_prefix', 'tb')
    monkeypatch.setattr(settings, 'livekit_token_ttl_seconds', 120)
    response = client.post('/runtime/voice/session', json={'child_id': child_id, 'session_id': session_id})
    payload = response.json()
    assert response.status_code == 200
    assert payload['runtime_mode'] == 'live'
    assert payload['token_status'] == 'ready'
    assert payload['access_token']
    assert payload['transport_url'] == 'wss://livekit.example.test'
    assert payload['room_name'].startswith('tb-child-1-')
    assert payload['transport_provider'] == 'LiveKit'
    assert payload['client_config']['transport_kind'] == 'livekit_webrtc'
    assert payload['client_config']['turn_protocol'] == 'server_vad_stream'
    assert payload['client_config']['stt_lane']['provider'] == 'Deepgram Flux'
    assert payload['client_config']['stt_lane']['delivery_mode'] == 'webrtc_data'
    assert payload['client_config']['tts_lane']['provider'] == 'Dedicated streaming TTS'
    assert payload['client_config']['transcript_lane']['path'] == '/runtime/voice/transcript'
    assert payload['client_config']['event_lane']['delivery_mode'] == 'https_stream'
    assert payload['client_config']['event_lane']['path'] == '/runtime/voice/events'



def test_voice_runtime_checkpoint_snapshot():
    child_id, session_id = _start_session()
    response = client.post('/runtime/voice/checkpoints', json={
        'session_id': session_id,
        'checkpoint_kind': 'turn_ended',
        'elapsed_ms': 210,
        'detail': 'child stopped speaking',
    })
    payload = response.json()
    assert response.status_code == 200
    assert payload['checkpoint_kind'] == 'turn_ended'

    response = client.post('/runtime/voice/checkpoints', json={
        'session_id': session_id,
        'checkpoint_kind': 'first_transcript',
        'elapsed_ms': 480,
    })
    assert response.status_code == 200

    snapshot = client.get('/runtime/voice/checkpoints', params={'session_id': session_id}).json()
    assert snapshot['session_id'] == session_id
    assert len(snapshot['checkpoints']) == 2
    assert snapshot['latest_by_kind']['turn_ended']['elapsed_ms'] == 210
    assert snapshot['latest_by_kind']['first_transcript']['elapsed_ms'] == 480


def test_voice_runtime_transcript_partial_ingestion():
    child_id, session_id = _start_session()
    response = client.post('/runtime/voice/transcript', json={
        'session_id': session_id,
        'transcript': 'b',
        'is_final': False,
        'elapsed_ms': 120,
        'source': 'stt_stream',
        'confidence': 0.67,
    })
    payload = response.json()
    assert response.status_code == 200
    assert payload['accepted'] is True
    assert payload['transcript_record']['transcript'] == 'b'
    assert payload['transcript_record']['is_final'] is False
    assert payload['evaluation'] is None


def test_voice_runtime_transcript_final_ingestion_runs_session_loop():
    child_id, session_id = _start_session()
    response = client.post('/runtime/voice/transcript', json={
        'session_id': session_id,
        'transcript': 'ba',
        'is_final': True,
        'elapsed_ms': 340,
        'attention_score': 0.9,
        'source': 'fallback_form',
    })
    payload = response.json()
    assert response.status_code == 200
    assert payload['transcript_record']['is_final'] is True
    assert payload['transcript_record']['source'] == 'fallback_form'
    assert payload['evaluation'] is not None
    assert payload['evaluation']['recognized_text'] == 'ba'
    assert payload['evaluation']['action'] in {'advance', 'retry', 'escalate'}


def test_voice_runtime_event_recording():
    child_id, session_id = _start_session()
    response = client.post('/runtime/voice/events', json={
        'session_id': session_id,
        'event_kind': 'barge_in',
        'elapsed_ms': 520,
        'detail': 'Child interrupted the playback lane.',
    })
    payload = response.json()
    assert response.status_code == 200
    assert payload['event_kind'] == 'barge_in'
    assert payload['elapsed_ms'] == 520
    assert payload['detail'] == 'Child interrupted the playback lane.'


def test_voice_runtime_connect_mock_handshake():
    child_id, session_id = _start_session()
    response = client.post('/runtime/voice/connect', json={
        'child_id': child_id,
        'session_id': session_id,
    })
    payload = response.json()
    assert response.status_code == 200
    assert payload['connection_state'] == 'mock_connected'
    assert payload['transport_kind'] == 'local_mock'
    assert payload['join_url'] == 'mock://voice-harness'
    assert payload['data_channels'][0]['label'] == 'tb-local-events'


def test_voice_runtime_connect_live_ready_when_configured(monkeypatch):
    child_id, session_id = _start_session()
    monkeypatch.setattr(settings, 'use_live_provider_calls', True)
    monkeypatch.setattr(settings, 'livekit_url', 'wss://livekit.example.test')
    monkeypatch.setattr(settings, 'livekit_api_key', 'lk_api_key')
    monkeypatch.setattr(settings, 'livekit_api_secret', 'lk_secret')
    response = client.post('/runtime/voice/connect', json={
        'child_id': child_id,
        'session_id': session_id,
        'requested_transport': 'livekit_webrtc',
    })
    payload = response.json()
    assert response.status_code == 200
    assert payload['connection_state'] == 'ready_to_join'
    assert payload['transport_kind'] == 'livekit_webrtc'
    assert payload['join_url'] == 'wss://livekit.example.test'
    assert payload['token_status'] == 'ready'
    assert payload['access_token']
    assert {channel['label'] for channel in payload['data_channels']} == {'tb-transcript', 'tb-events', 'tb-tts'}


def test_deepgram_transcript_frame_partial_ingestion():
    child_id, session_id = _start_session()
    response = client.post('/runtime/voice/deepgram', json={
        'session_id': session_id,
        'child_id': child_id,
        'transcript': 'ba',
        'is_final': False,
        'speech_final': False,
        'confidence': 0.74,
        'start_ms': 100,
        'duration_ms': 160,
    })
    payload = response.json()
    assert response.status_code == 200
    assert payload['transcript_record']['transcript'] == 'ba'
    assert payload['transcript_record']['is_final'] is False
    assert payload['transcript_record']['elapsed_ms'] == 260
    assert payload['evaluation'] is None


def test_deepgram_transcript_frame_final_ingestion_runs_session_loop():
    child_id, session_id = _start_session()
    response = client.post('/runtime/voice/deepgram', json={
        'session_id': session_id,
        'child_id': child_id,
        'transcript': 'ba',
        'is_final': True,
        'speech_final': True,
        'confidence': 0.95,
        'start_ms': 50,
        'duration_ms': 320,
        'attention_score': 0.9,
    })
    payload = response.json()
    assert response.status_code == 200
    assert payload['transcript_record']['is_final'] is True
    assert payload['transcript_record']['source'] == 'stt_stream'
    assert payload['evaluation'] is not None
    assert payload['evaluation']['recognized_text'] == 'ba'


def test_voice_playback_queue_enqueue_and_snapshot():
    child_id, session_id = _start_session()
    response = client.post('/runtime/voice/playback', json={
        'session_id': session_id,
        'child_id': child_id,
        'text': 'Nice work. We can move to the next sound now.',
    })
    payload = response.json()
    assert response.status_code == 200
    assert payload['status'] == 'pending'
    assert payload['voice_name'] == 'calm-coach'

    snapshot = client.get('/runtime/voice/playback', params={'session_id': session_id}).json()
    assert snapshot['session_id'] == session_id
    assert len(snapshot['items']) == 1
    assert snapshot['active_item']['status'] == 'pending'


def test_voice_playback_state_update_moves_item_forward():
    child_id, session_id = _start_session()
    item = client.post('/runtime/voice/playback', json={
        'session_id': session_id,
        'child_id': child_id,
        'text': 'Quiet try. Let us go again.',
    }).json()

    response = client.post('/runtime/voice/playback/state', json={
        'session_id': session_id,
        'playback_id': item['playback_id'],
        'status': 'playing',
        'detail': 'Dev shell marked playback as active.',
    })
    payload = response.json()
    assert response.status_code == 200
    assert payload['status'] == 'playing'
    assert payload['detail'] == 'Dev shell marked playback as active.'

    snapshot = client.get('/runtime/voice/playback', params={'session_id': session_id}).json()
    assert snapshot['active_item']['playback_id'] == item['playback_id']
    assert snapshot['active_item']['status'] == 'playing'


def test_voice_tts_job_created_from_playback_item():
    child_id, session_id = _start_session()
    playback = client.post('/runtime/voice/playback', json={
        'session_id': session_id,
        'child_id': child_id,
        'text': 'Nice work. We can move to the next sound now.',
    }).json()

    response = client.post('/runtime/voice/tts', json={
        'session_id': session_id,
        'playback_id': playback['playback_id'],
    })
    payload = response.json()
    assert response.status_code == 200
    assert payload['playback_id'] == playback['playback_id']
    assert payload['status'] == 'queued'
    assert payload['delivery_mode'] == 'streaming_tts'
    assert payload['voice_name'] == 'calm-coach'

    queue = client.get('/runtime/voice/playback', params={'session_id': session_id}).json()
    assert queue['items'][0]['status'] == 'synthesizing'


def test_voice_tts_job_process_creates_artifact_and_readies_playback():
    child_id, session_id = _start_session()
    playback = client.post('/runtime/voice/playback', json={
        'session_id': session_id,
        'child_id': child_id,
        'text': 'Nice work. We can move to the next sound now.',
    }).json()
    client.post('/runtime/voice/tts', json={
        'session_id': session_id,
        'playback_id': playback['playback_id'],
    })

    response = client.post('/runtime/voice/tts/process', json={
        'session_id': session_id,
        'playback_id': playback['playback_id'],
    })
    payload = response.json()
    assert response.status_code == 200
    assert payload['status'] == 'ready'
    assert payload['artifact']['artifact_uri'].startswith('mock://tts/')
    assert payload['artifact']['duration_ms'] > 0

    queue = client.get('/runtime/voice/playback', params={'session_id': session_id}).json()
    assert queue['items'][0]['status'] == 'ready'
    assert queue['items'][0]['detail'].startswith('mock://tts/')


def test_voice_tts_queue_snapshot_returns_latest_ready_job():
    child_id, session_id = _start_session()
    playback = client.post('/runtime/voice/playback', json={
        'session_id': session_id,
        'child_id': child_id,
        'text': 'Nice work. We can move to the next sound now.',
    }).json()
    client.post('/runtime/voice/tts', json={
        'session_id': session_id,
        'playback_id': playback['playback_id'],
    })
    client.post('/runtime/voice/tts/process', json={
        'session_id': session_id,
        'playback_id': playback['playback_id'],
    })

    snapshot = client.get('/runtime/voice/tts', params={'session_id': session_id}).json()
    assert snapshot['session_id'] == session_id
    assert len(snapshot['jobs']) == 1
    assert snapshot['latest_ready_job']['status'] == 'ready'
    assert snapshot['latest_ready_job']['artifact']['artifact_uri'].startswith('mock://tts/')
