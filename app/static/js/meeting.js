// Painel da reunião: polling do feed ao vivo, ações e renderização da ata.
function meetingPage(meetingId, hasMinutesInitial) {
  return {
    meetingId,
    meeting: { status: 'created', status_label: 'Carregando…', status_history: [] },
    segments: [], notes: [], events: [], counts: {},
    minutes: null, hasMinutes: hasMinutesInitial,
    showOpenai: false, busy: false, flash: '', lastSeq: 0, timer: null,

    async init() {
      await this.poll();
      if (this.hasMinutes) await this.loadMinutes();
      this.timer = setInterval(() => this.poll(), 2000);
    },

    async poll() {
      try {
        const res = await fetch(`/api/meetings/${this.meetingId}/live?after_seq=${this.lastSeq}`);
        if (!res.ok) return;
        const data = await res.json();
        this.meeting = data.meeting;
        this.notes = data.notes; this.events = data.events; this.counts = data.counts;
        if (data.segments.length) {
          const known = new Set(this.segments.map(s => s.id));
          for (const s of data.segments) if (!known.has(s.id)) this.segments.push(s);
          this.lastSeq = Math.max(this.lastSeq, ...data.segments.map(s => s.seq || 0));
          this.$nextTick(() => { const el = this.$refs.scroll; if (el) el.scrollTop = el.scrollHeight; });
        }
        if (data.has_minutes && !this.minutes) await this.loadMinutes();
      } catch (e) { /* mantém o último estado */ }
    },

    async loadMinutes() {
      const res = await fetch(`/api/meetings/${this.meetingId}/minutes`);
      if (res.ok) { this.minutes = (await res.json()).minutes; this.hasMinutes = true; }
    },

    visibleSegments() {
      const hasRecall = (this.counts.recall || 0) > 0;
      return this.segments.filter(s => s.source === 'navi' || s.source === 'recall' || (s.source === 'openai' && (this.showOpenai || !hasRecall)));
    },
    interactions() { return this.events.filter(e => e.type === 'wake_detected' || e.type === 'navi_response').slice(-20).reverse(); },
    connectionEvents() { return this.events.filter(e => e.type.startsWith('realtime_') || e.type === 'bot_error').slice(-8).reverse(); },

    isEnded() { return ['call_ended', 'done', 'fatal', 'media_expired'].includes(this.meeting.status); },
    isLive() { return ['in_call_recording', 'in_call_not_recording', 'recording_permission_allowed'].includes(this.meeting.status); },
    statusClass() {
      const s = this.meeting.status;
      if (this.isLive()) return 'bg-emerald-900/60 text-emerald-200';
      if (s === 'in_waiting_room') return 'bg-amber-900/60 text-amber-200';
      if (s === 'fatal' || s === 'recording_permission_denied') return 'bg-rose-900/60 text-rose-200';
      if (s === 'joining_call') return 'bg-sky-900/60 text-sky-200';
      return 'bg-slate-800 text-slate-200';
    },

    async refresh() {
      const res = await fetch(`/api/meetings/${this.meetingId}/refresh`, { method: 'POST' });
      const data = await res.json();
      this.flash = res.ok ? `Status atualizado: ${data.meeting.status_label}` : (data.detail || 'Falha ao atualizar');
      setTimeout(() => this.flash = '', 4000);
      await this.poll();
    },

    async leave() {
      if (!confirm('Encerrar a participação da Navi e gerar a ata agora?')) return;
      this.busy = true;
      const res = await fetch(`/api/meetings/${this.meetingId}/leave`, { method: 'POST' });
      const data = await res.json();
      this.flash = res.ok ? 'Navi saindo da reunião. Gerando a ata…' : (data.detail || 'Falha ao encerrar');
      this.busy = false;
      await this.poll();
      this.waitForMinutes();
    },

    async generate(force) {
      this.busy = true; this.flash = 'Gerando a ata com o modelo de texto…';
      const res = await fetch(`/api/meetings/${this.meetingId}/minutes?force=${force ? 1 : 0}`, { method: 'POST' });
      const data = await res.json();
      if (res.ok) { this.minutes = data.minutes; this.hasMinutes = true; this.flash = 'Ata gerada.'; document.getElementById('ata').scrollIntoView({ behavior: 'smooth' }); }
      else this.flash = data.detail || 'Falha ao gerar a ata';
      this.busy = false;
      setTimeout(() => this.flash = '', 5000);
    },

    waitForMinutes() {
      let tries = 0;
      const t = setInterval(async () => {
        tries++;
        await this.loadMinutes();
        if (this.minutes || tries > 60) { clearInterval(t); if (this.minutes) { this.flash = 'Ata gerada.'; setTimeout(() => this.flash = '', 4000); } }
      }, 3000);
    },

    fmt(sec) {
      if (sec === null || sec === undefined) return '--:--';
      const s = Math.max(0, Math.floor(sec)); const m = Math.floor(s / 60); const h = Math.floor(m / 60);
      const mm = String(m % 60).padStart(2, '0'), ss = String(s % 60).padStart(2, '0');
      return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
    },
    time(iso, withDate) {
      if (!iso) return '';
      const d = new Date(iso);
      return withDate ? d.toLocaleString('pt-BR') : d.toLocaleTimeString('pt-BR');
    },
  }
}
