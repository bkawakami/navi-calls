// Página da assistente (executada dentro do bot da Recall via Output Media).
//
// Fluxo: token efêmero (backend) -> conexão direta com a OpenAI Realtime (WebRTC; fallback WebSocket)
// -> ouve a reunião em silêncio (create_response=false) -> ao detectar "Navi, ..." pede uma resposta
// -> silencia o próprio microfone enquanto fala -> volta ao silêncio.
//
// No bot: o "microfone" (getUserMedia) é o áudio mixado da reunião, sem a voz do próprio bot;
// tudo que a página toca é enviado à reunião como a voz da Navi (convertido para 16 kHz mono).
(function () {
  const CFG = window.NAVI;
  const OPENAI_CALLS_URL = 'https://api.openai.com/v1/realtime/calls';
  const OPENAI_WS_URL = 'wss://api.openai.com/v1/realtime';
  const PENDING_WAKE_MS = 6000;             // espera máxima pelo fim da pergunta após um "Navi," isolado
  const UNMUTE_TAIL_MS = 350;               // folga após o fim do áudio da Navi antes de voltar a escutar
  const RECONNECT_BEFORE_EXPIRY_MS = 120000; // reconecta 2 min antes do limite da sessão (60 min)
  const WEBRTC_CONNECT_TIMEOUT_MS = 12000;  // sem ICE conectado nesse tempo -> cai para WebSocket
  const PCM_RATE = 24000;                   // formato do Realtime via WebSocket (PCM16 mono 24 kHz)

  const el = { orb: document.getElementById('orb'), dot: document.getElementById('dot'), status: document.getElementById('status'), caption: document.getElementById('caption'), log: document.getElementById('log'), audio: document.getElementById('remote') };
  if (CFG.debug) document.body.classList.add('debug');

  const forced = (CFG.transport || 'auto').toLowerCase();
  const state = {
    transport: null, transportKind: null, preferWebSocket: forced === 'websocket' || forced === 'ws',
    micStream: null, micTrack: null, audioCtx: null,
    session: null, status: 'connecting',
    isResponding: false, isSpeaking: false, currentRequest: null, currentKind: null,
    pending: null, answerTimer: null, expiryTimer: null, reconnectAttempts: 0, reconnecting: false,
    responseTranscripts: {}, maxAnswerSeconds: 25,
  };

  // ======================= UI / log =======================
  function setStatus(status, text) {
    state.status = status;
    el.orb.className = 'orb ' + ({ connecting: 'offline', reconnecting: 'offline', error: 'offline' }[status] || status);
    el.dot.className = 'dot ' + status;
    el.status.textContent = text || { connecting: 'Conectando…', reconnecting: 'Reconectando…', listening: 'Ouvindo a reunião', thinking: 'Pensando…', speaking: 'Falando', error: 'Erro de conexão' }[status] || status;
  }
  function setCaption(text, muted) { el.caption.textContent = text; el.caption.className = 'caption' + (muted ? ' muted' : ''); }
  function log(...args) {
    const line = new Date().toISOString().slice(11, 19) + ' ' + args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' ');
    console.log('[navi]', line);
    if (CFG.debug) el.log.textContent = (line + '\n' + el.log.textContent).slice(0, 20000);
  }

  // ======================= backend =======================
  async function api(method, path, body) {
    const res = await fetch(CFG.apiBase + path, { method, headers: { 'Content-Type': 'application/json', 'X-Navi-Token': CFG.token }, body: body ? JSON.stringify(body) : undefined });
    if (!res.ok) { const t = await res.text(); throw new Error(`${method} ${path} -> ${res.status} ${t.slice(0, 200)}`); }
    return res.json();
  }
  function logEvent(type, payload) { api('POST', '/events', { type, payload: payload || {} }).catch(e => log('evento não enviado', e.message)); }

  // ======================= áudio local =======================
  function audioContext() {
    if (!state.audioCtx) state.audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: PCM_RATE });
    if (state.audioCtx.state === 'suspended') state.audioCtx.resume().catch(() => {});
    return state.audioCtx;
  }
  async function getMic() {
    if (state.micStream && state.micStream.active) return state.micStream;
    state.micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: false, channelCount: 1 } });
    state.micTrack = state.micStream.getAudioTracks()[0];
    log('microfone:', state.micTrack.label || '(sem label)', state.micTrack.getSettings());
    return state.micStream;
  }
  // Silenciar enquanto a Navi fala: evita que ela ouça (e transcreva) a própria voz.
  function setMicEnabled(enabled) { if (state.micTrack) state.micTrack.enabled = enabled; if (state.transport && state.transport.setMicEnabled) state.transport.setMicEnabled(enabled); }

  // ======================= transporte WebRTC =======================
  async function connectWebRTC(session, ms) {
    const pc = new RTCPeerConnection();
    const dc = pc.createDataChannel('oai-events');
    const t = { kind: 'webrtc', pc, dc, closed: false,
      send(evt) { if (dc.readyState === 'open') dc.send(JSON.stringify(evt)); else log('datachannel fechado; evento perdido', evt.type); },
      close() { t.closed = true; try { dc.onclose = null; dc.close(); } catch (e) {} try { pc.onconnectionstatechange = null; pc.close(); } catch (e) {} },
    };
    // Saída: o stream remoto vai para um AudioContext (resume() sem gesto funciona no bot) e o <audio> fica mudo,
    // porque o Chrome só "liga" o stream WebRTC quando ele está anexado a um elemento de mídia.
    pc.ontrack = (e) => {
      const ctx = audioContext();
      const src = ctx.createMediaStreamSource(e.streams[0]);
      src.connect(ctx.destination);
      t.remoteSource = src;
      el.audio.srcObject = e.streams[0]; el.audio.muted = true; el.audio.play().catch(() => {});
    };
    pc.addTrack(state.micTrack, ms);
    pc.onconnectionstatechange = () => {
      log('pc state', pc.connectionState);
      if (['failed', 'disconnected', 'closed'].includes(pc.connectionState) && !t.closed) onTransportLost('pc ' + pc.connectionState);
    };
    dc.onclose = () => { if (!t.closed) onTransportLost('datachannel fechado'); };
    dc.onmessage = (e) => { try { handleServerEvent(JSON.parse(e.data)); } catch (err) { log('evento inválido', err.message); } };

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const sdpResponse = await fetch(OPENAI_CALLS_URL, { method: 'POST', body: offer.sdp, headers: { Authorization: `Bearer ${session.client_secret}`, 'Content-Type': 'application/sdp' } });
    if (!sdpResponse.ok) throw new Error(`OpenAI /realtime/calls -> ${sdpResponse.status} ${(await sdpResponse.text()).slice(0, 300)}`);
    await pc.setRemoteDescription({ type: 'answer', sdp: await sdpResponse.text() });

    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('WebRTC não conectou em ' + WEBRTC_CONNECT_TIMEOUT_MS + 'ms (UDP bloqueado?)')), WEBRTC_CONNECT_TIMEOUT_MS);
      dc.onopen = () => { clearTimeout(timer); resolve(); };
      pc.addEventListener('connectionstatechange', () => { if (pc.connectionState === 'failed') { clearTimeout(timer); reject(new Error('ICE failed')); } });
    });
    return t;
  }

  // ======================= transporte WebSocket (fallback) =======================
  // Captura PCM16 24 kHz do microfone via AudioWorklet e toca a resposta (PCM16) com agendamento no AudioContext.
  const WORKLET_SRC = `
    class PcmCapture extends AudioWorkletProcessor {
      constructor() { super(); this.enabled = true; this.port.onmessage = (e) => { if (e.data && 'enabled' in e.data) this.enabled = e.data.enabled; }; }
      process(inputs) {
        const ch = inputs[0] && inputs[0][0]; if (!ch) return true;
        const out = new Int16Array(ch.length);
        if (this.enabled) for (let i = 0; i < ch.length; i++) { const s = Math.max(-1, Math.min(1, ch[i])); out[i] = s < 0 ? s * 0x8000 : s * 0x7fff; }
        this.port.postMessage(out.buffer, [out.buffer]);
        return true;
      }
    }
    registerProcessor('pcm-capture', PcmCapture);`;

  async function connectWebSocket(session, ms) {
    const ctx = audioContext();
    if (!ctx.__workletLoaded) { await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET_SRC], { type: 'application/javascript' }))); ctx.__workletLoaded = true; }
    const ws = new WebSocket(`${OPENAI_WS_URL}?model=${encodeURIComponent(session.model)}`, ['realtime', 'openai-insecure-api-key.' + session.client_secret]);
    const t = { kind: 'websocket', ws, closed: false, playhead: 0, scheduled: [], micEnabled: true,
      send(evt) { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(evt)); else log('websocket fechado; evento perdido', evt.type); },
      setMicEnabled(enabled) { t.micEnabled = enabled; if (t.capture) t.capture.port.postMessage({ enabled }); },
      close() { t.closed = true; try { ws.onclose = null; ws.close(); } catch (e) {} try { t.source && t.source.disconnect(); t.capture && t.capture.disconnect(); } catch (e) {} t.stopPlayback(); },
      playPcm16(b64) {
        const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
        const int16 = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
        const f32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 0x8000;
        const buf = ctx.createBuffer(1, f32.length, PCM_RATE); buf.getChannelData(0).set(f32);
        const src = ctx.createBufferSource(); src.buffer = buf; src.connect(ctx.destination);
        const startAt = Math.max(ctx.currentTime + 0.05, t.playhead);
        src.start(startAt); t.playhead = startAt + buf.duration; t.scheduled.push(src);
        src.onended = () => { t.scheduled = t.scheduled.filter(s => s !== src); if (!t.scheduled.length && t.drainResolve) { const r = t.drainResolve; t.drainResolve = null; r(); } };
        if (!t.playing) { t.playing = true; onAudioOutputStarted(); }
      },
      // Chamado após response.done: aguarda o fim da reprodução e sinaliza como output_audio_buffer.stopped.
      async finishPlayback() { if (t.scheduled.length) await new Promise(r => { t.drainResolve = r; }); t.playing = false; onAudioOutputStopped(); },
      stopPlayback() { t.scheduled.forEach(s => { try { s.stop(); } catch (e) {} }); t.scheduled = []; t.playhead = 0; if (t.playing) { t.playing = false; onAudioOutputStopped(); } },
    };
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('WebSocket não abriu em 10s')), 10000);
      ws.onopen = () => { clearTimeout(timer); resolve(); };
      ws.onerror = () => { clearTimeout(timer); reject(new Error('erro no WebSocket')); };
    });
    ws.onclose = (e) => { if (!t.closed) onTransportLost('websocket fechado ' + e.code); };
    ws.onmessage = (e) => { try { handleServerEvent(JSON.parse(e.data), t); } catch (err) { log('evento inválido', err.message); } };

    t.source = ctx.createMediaStreamSource(ms);
    t.capture = new AudioWorkletNode(ctx, 'pcm-capture');
    t.capture.port.onmessage = (e) => {
      if (ws.readyState !== WebSocket.OPEN) return;
      const bytes = new Uint8Array(e.data); let bin = '';
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      ws.send(JSON.stringify({ type: 'input_audio_buffer.append', audio: btoa(bin) }));
    };
    const silent = ctx.createGain(); silent.gain.value = 0; // mantém o worklet no grafo sem ecoar a reunião de volta à chamada
    t.source.connect(t.capture); t.capture.connect(silent); silent.connect(ctx.destination);
    return t;
  }

  // ======================= conexão / reconexão =======================
  async function connect(reconnect) {
    cleanupConnection();
    setStatus(reconnect ? 'reconnecting' : 'connecting');
    state.session = await api('POST', `/session?reconnect=${reconnect ? 1 : 0}`);
    state.maxAnswerSeconds = state.session.max_answer_seconds || 25;
    const ms = await getMic();
    audioContext();
    if (!state.preferWebSocket) {
      try { state.transport = await connectWebRTC(state.session, ms); }
      catch (err) {
        if (forced === 'webrtc') throw err;
        log('WebRTC falhou; tentando WebSocket:', err.message);
        logEvent('transport_fallback', { reason: err.message });
        state.preferWebSocket = true;
      }
    }
    if (!state.transport) state.transport = await connectWebSocket(state.session, ms);
    state.transportKind = state.transport.kind;
    onConnected(reconnect);
  }

  function onConnected(reconnect) {
    state.reconnectAttempts = 0; state.reconnecting = false;
    setMicEnabled(true);
    setStatus('listening');
    setCaption(reconnect ? 'Reconectada. Continuo ouvindo a reunião.' : 'Diga “Navi, …” para me chamar. Eu ouço em silêncio e respondo quando chamada.', true);
    log('conectada via', state.transportKind, 'modelo', state.session.model);
    logEvent('connected', { reconnect: !!reconnect, model: state.session.model, transport: state.transportKind });
  }

  function cleanupConnection() {
    clearTimeout(state.expiryTimer); clearTimeout(state.answerTimer);
    if (state.transport) { try { state.transport.close(); } catch (e) {} }
    state.transport = null; state.isResponding = false; state.isSpeaking = false; state.responseTranscripts = {};
  }

  function onTransportLost(reason) {
    if (state.reconnecting) return;
    scheduleReconnect(reason);
  }

  function scheduleReconnect(reason) {
    if (state.reconnecting) return;
    state.reconnecting = true;
    cleanupConnection();
    const delay = Math.min(30000, 1500 * Math.pow(2, state.reconnectAttempts++));
    setStatus('reconnecting', `Reconectando em ${Math.round(delay / 1000)}s…`);
    log('reconectar:', reason, 'em', delay, 'ms');
    logEvent('disconnected', { reason, attempt: state.reconnectAttempts });
    setTimeout(() => connect(true).catch(err => { log('falha ao reconectar', err.message); logEvent('error', { message: err.message }); state.reconnecting = false; scheduleReconnect('erro: ' + err.message); }), delay);
  }

  // Reconexão planejada (limite de 60 min da sessão): espera a Navi terminar de falar. O contexto é reinjetado pelo backend.
  function gracefulReconnect(reason) {
    if (state.isSpeaking || state.isResponding) { setTimeout(() => gracefulReconnect(reason), 2000); return; }
    log('reconexão planejada:', reason);
    logEvent('disconnected', { reason, planned: true });
    state.reconnecting = true;
    connect(true).catch(err => { log('falha na reconexão planejada', err.message); state.reconnecting = false; scheduleReconnect(err.message); });
  }

  function send(evt) { if (state.transport) state.transport.send(evt); }

  // ======================= eventos do servidor =======================
  function onAudioOutputStarted() {
    state.isSpeaking = true;
    setMicEnabled(false);
    setStatus('speaking');
    clearTimeout(state.answerTimer);
    state.answerTimer = setTimeout(() => { log('resposta longa; cortando'); send({ type: 'response.cancel' }); if (state.transportKind === 'webrtc') send({ type: 'output_audio_buffer.clear' }); else if (state.transport) state.transport.stopPlayback(); }, state.maxAnswerSeconds * 1000);
  }
  function onAudioOutputStopped() {
    clearTimeout(state.answerTimer);
    setTimeout(() => { state.isSpeaking = false; if (!state.isResponding) { setMicEnabled(true); setStatus('listening'); } }, UNMUTE_TAIL_MS);
  }

  function handleServerEvent(ev, transport) {
    switch (ev.type) {
      case 'session.created': {
        const exp = ev.session && ev.session.expires_at;
        if (exp) {
          const ms = exp * 1000 - Date.now() - RECONNECT_BEFORE_EXPIRY_MS;
          clearTimeout(state.expiryTimer);
          state.expiryTimer = setTimeout(() => gracefulReconnect('sessão perto do limite de 60 min'), Math.max(30000, ms));
          log('sessão criada; expira em', Math.round((exp * 1000 - Date.now()) / 60000), 'min');
        }
        break;
      }
      case 'input_audio_buffer.speech_started':
        if (!state.isSpeaking && !state.isResponding) setStatus('listening', 'Ouvindo…');
        break;
      case 'input_audio_buffer.speech_stopped':
        if (!state.isSpeaking && !state.isResponding) setStatus('listening');
        break;
      case 'conversation.item.input_audio_transcription.completed':
        onTranscript(ev.transcript || '', ev.item_id);
        break;
      case 'conversation.item.input_audio_transcription.failed':
        log('transcrição falhou', ev.error && ev.error.message);
        break;
      case 'response.created':
        state.isResponding = true;
        state.responseTranscripts[ev.response.id] = '';
        setStatus('thinking');
        break;
      case 'response.output_audio_transcript.delta':
        state.responseTranscripts[ev.response_id] = (state.responseTranscripts[ev.response_id] || '') + (ev.delta || '');
        setCaption(state.responseTranscripts[ev.response_id], false);
        break;
      case 'response.output_audio_transcript.done':
        state.responseTranscripts[ev.response_id] = ev.transcript || state.responseTranscripts[ev.response_id];
        setCaption(state.responseTranscripts[ev.response_id], false);
        log('falei:', state.responseTranscripts[ev.response_id]);
        break;
      case 'response.output_audio.delta':              // só no WebSocket
        if (transport && transport.playPcm16) transport.playPcm16(ev.delta);
        break;
      case 'response.function_call_arguments.done':
        handleFunctionCall(ev).catch(err => log('erro na função', err.message));
        break;
      case 'output_audio_buffer.started':             // só no WebRTC
        onAudioOutputStarted();
        break;
      case 'output_audio_buffer.stopped':
      case 'output_audio_buffer.cleared':
        onAudioOutputStopped();
        break;
      case 'response.done':
        onResponseDone(ev.response, transport);
        break;
      case 'error':
        log('erro do servidor', ev.error);
        logEvent('error', { message: ev.error && ev.error.message, code: ev.error && ev.error.code });
        if (ev.error && /session.*(expired|closed|ended)/i.test(ev.error.message || '')) scheduleReconnect('erro de sessão');
        break;
      default:
        break;
    }
  }

  function onResponseDone(response, transport) {
    state.isResponding = false;
    const transcript = (state.responseTranscripts[response.id] || '').trim();
    const hadFunctionCall = (response.output || []).some(i => i.type === 'function_call');
    if (transcript) api('POST', '/response', { transcript, request: state.currentRequest, response_id: response.id }).catch(e => log('resposta não registrada', e.message));
    if (response.status !== 'completed') log('resposta terminou com status', response.status, response.status_details);
    if (transport && transport.finishPlayback && transport.playing) transport.finishPlayback();
    else if (!state.isSpeaking) { setMicEnabled(true); setStatus('listening'); }
    if (!hadFunctionCall) { state.currentRequest = null; state.currentKind = null; }
    if (transcript) setTimeout(() => { if (state.status === 'listening') setCaption('Diga “Navi, …” para me chamar.', true); }, 12000);
  }

  // ======================= chamados =======================
  async function onTranscript(text, itemId) {
    text = (text || '').trim();
    if (!text) return;
    if (state.isSpeaking) {
      // Vazamento da própria voz (ou alguém falando por cima): não deixar no contexto como fala de participante.
      log('transcrição durante a fala da Navi ignorada:', text);
      send({ type: 'conversation.item.delete', item_id: itemId });
      return;
    }
    log('ouvi:', text);
    const pendingText = state.pending ? state.pending.text : null;
    let decision;
    try { decision = await api('POST', '/transcript', { text, item_id: itemId, pending_text: pendingText, force: false }); }
    catch (err) { log('backend indisponível para decidir; usando detecção local', err.message); decision = localDecision(text, pendingText); }
    clearPending();
    if (!decision.wake) return;
    if (decision.kind === 'pending') {
      state.pending = { text: decision.pending_text || text, timer: setTimeout(forcePending, PENDING_WAKE_MS) };
      setStatus('listening', 'Sim? Estou ouvindo…');
      return;
    }
    respond(decision);
  }

  async function forcePending() {
    const pending = state.pending; state.pending = null;
    if (!pending) return;
    try {
      const decision = await api('POST', '/transcript', { text: '', item_id: null, pending_text: pending.text, force: true });
      if (decision.wake) respond(decision);
    } catch (err) { respond({ kind: 'question', instructions: 'Alguém chamou seu nome mas não completou o pedido. Pergunte, em poucas palavras e em português, como pode ajudar.', request: pending.text }); }
  }
  function clearPending() { if (state.pending) { clearTimeout(state.pending.timer); state.pending = null; } }

  function localDecision(text, pendingText) {
    const combined = (pendingText ? pendingText + ' ' : '') + text;
    const words = (state.session && state.session.wake_words) || ['navi'];
    const norm = combined.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
    const hit = words.some(w => new RegExp('(^|[^\\w])' + w.normalize('NFD').replace(/[̀-ͯ]/g, '') + '([^\\w]|$)').test(norm));
    if (!hit) return { wake: false };
    return { wake: true, kind: 'question', request: combined, tools: [], instructions: `Você foi chamada pelo nome. O pedido foi: "${combined}". Responda em português do Brasil, de forma breve e objetiva, começando direto pela resposta, usando o que foi dito na reunião até agora.` };
  }

  function respond(decision) {
    if (state.isResponding) { log('já respondendo; chamado ignorado'); return; }
    state.currentRequest = decision.request || null; state.currentKind = decision.kind;
    setStatus('thinking');
    setCaption(decision.kind === 'note' ? `Anotando: ${decision.note}` : `Pergunta: ${decision.request || ''}`, true);
    const response = { instructions: decision.instructions, output_modalities: ['audio'], conversation: 'auto', metadata: { kind: decision.kind || 'question' } };
    if (Array.isArray(decision.tools)) response.tools = decision.tools; // [] desliga funções nesta resposta
    send({ type: 'response.create', response });
  }

  async function handleFunctionCall(ev) {
    if (ev.name !== 'save_note') return;
    let args = {}; try { args = JSON.parse(ev.arguments || '{}'); } catch (e) {}
    const text = (args.text || '').trim();
    let output = { ok: false };
    if (text) { try { await api('POST', '/notes', { text, call_id: ev.call_id }); output = { ok: true, saved: text }; log('nota salva via função:', text); } catch (err) { output = { ok: false, error: err.message }; } }
    send({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: ev.call_id, output: JSON.stringify(output) } });
    send({ type: 'response.create', response: { instructions: output.ok ? 'Confirme em uma frase curta, em português, que a nota foi salva, repetindo o essencial.' : 'Diga em uma frase, em português, que não conseguiu salvar a nota agora.', output_modalities: ['audio'] } });
  }

  // ======================= início =======================
  connect(false).catch(err => {
    log('falha ao conectar', err.message);
    setStatus('error', 'Falha ao conectar');
    setCaption(err.message.slice(0, 160), true);
    logEvent('error', { message: err.message });
    state.reconnecting = false;
    scheduleReconnect(err.message);
  });
})();
