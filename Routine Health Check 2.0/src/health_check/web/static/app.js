(() => {
  // ---------------------------------------------------------------- DOM
  const $log = document.getElementById('log');
  const $state = document.getElementById('job-state');
  const $title = document.getElementById('job-title');
  const $elapsed = document.getElementById('job-elapsed');
  const $btnClear = document.getElementById('btn-clear');
  const $btnRail = document.getElementById('btn-rail-toggle');
  const $app = document.querySelector('.app');

  const $summaryLast = document.getElementById('summary-last');
  const $counts = document.getElementById('summary-counts');
  const $cUp = document.getElementById('count-up');
  const $cDeg = document.getElementById('count-degraded');
  const $cDown = document.getElementById('count-down');

  const $dashFrame = document.getElementById('dashboard-frame');
  const $jsonViewer = document.getElementById('json-viewer');
  const $jsonExpand = document.getElementById('json-expand-all');
  const $jsonCollapse = document.getElementById('json-collapse-all');
  const $historyList = document.getElementById('history-list');

  const allActionButtons = () => document.querySelectorAll('button[data-kind]');

  // ---------------------------------------------------------------- STATE
  let activeJobId = null;
  let activeES = null;
  let startedAt = null;
  let tickerId = null;
  let currentView = 'overview';
  let dashboardLoaded = false;

  // ===================================================================
  // VIEW ROUTER
  // ===================================================================
  function switchView(name) {
    if (currentView === name) return;
    currentView = name;
    document.querySelectorAll('.nav-item').forEach((n) => {
      n.classList.toggle('active', n.dataset.view === name);
    });
    document.querySelectorAll('.view').forEach((v) => {
      v.classList.toggle('active', v.dataset.view === name);
    });

    if (name === 'dashboard' && !dashboardLoaded) {
      $dashFrame.src = '/dashboard';
      dashboardLoaded = true;
    }
    if (name === 'dashboard') {
      // always re-source so a freshly-rebuilt dashboard appears
      $dashFrame.src = '/dashboard?t=' + Date.now();
    }
    if (name === 'report') {
      loadJsonReport();
    }
    if (name === 'history') {
      loadHistory();
    }
  }

  document.querySelectorAll('.nav-item').forEach((n) => {
    n.addEventListener('click', () => switchView(n.dataset.view));
  });

  // ===================================================================
  // BADGE / COUNT HELPERS
  // ===================================================================
  function badgeClass(verdict) {
    if (!verdict || verdict === 'UNKNOWN') return 'b-unknown';
    const v = verdict.toUpperCase();
    if (v.startsWith('UP') || v.startsWith('HEALTHY')) return 'b-ok';
    if (v.startsWith('DOWN') || v === 'FAILED' || v === 'ERROR') return 'b-bad';
    if (v.startsWith('DEGRADED') || v.startsWith('SLOW') || v.startsWith('KNOWN')) return 'b-warn';
    if (v.startsWith('AUTH')) return 'b-info';
    return 'b-unknown';
  }
  function setBadge(el, verdict) {
    if (!el) return;
    const next = verdict || '—';
    const nextCls = 'badge ' + badgeClass(verdict);
    const changed = el.textContent !== next || el.className !== nextCls + ' just-updated';
    el.textContent = next;
    el.className = nextCls;
    if (changed) {
      void el.offsetWidth;  // reflow → restart animation
      el.classList.add('just-updated');
    }
  }
  function setCount(el, value) {
    if (!el) return;
    if ((el.dataset.prev || '') !== value) {
      el.classList.remove('just-updated');
      void el.offsetWidth;
      el.classList.add('just-updated');
      el.dataset.prev = value;
    }
    el.textContent = value;
  }

  // ===================================================================
  // VERDICTS LOADER
  // ===================================================================
  function loadVerdicts() {
    fetch('/verdicts').then((r) => r.json()).then((v) => {
      if (!v.available) {
        $summaryLast.textContent = 'No sweep recorded yet';
        $counts.hidden = true;
        return;
      }
      const ended = v.ended_ist ? v.ended_ist.replace(/\+.*$/, '').replace('T', ' ') : '—';
      $summaryLast.textContent = `Last run: ${ended}`;
      // Authoritative leaf-check counts. Do NOT add liveness counts here —
      // that double-counts outages (a UMANG host showing DOWN in liveness
      // is the same outage as the umang script's DOWN leaf checks).
      const sum = v.summary || { up: 0, warn: 0, down: 0 };
      setCount($cUp,   `${sum.up} UP`);
      setCount($cDeg,  `${sum.warn} DEG`);
      setCount($cDown, `${sum.down} DOWN`);
      $counts.hidden = false;

      Object.entries(v.projects || {}).forEach(([name, verdict]) => {
        document.querySelectorAll(`[data-project-badge="${CSS.escape(name)}"]`)
          .forEach((el) => setBadge(el, verdict));
      });
      Object.entries(v.checks || {}).forEach(([name, verdict]) => {
        document.querySelectorAll(`[data-check-badge="${CSS.escape(name)}"]`)
          .forEach((el) => setBadge(el, verdict));
      });
    }).catch(() => {});
  }

  // ===================================================================
  // JSON REPORT VIEWER (recursive tree)
  // ===================================================================
  function loadJsonReport() {
    $jsonViewer.textContent = 'Loading…';
    fetch('/report').then((r) => {
      if (!r.ok) throw new Error('no report');
      return r.json();
    }).then((data) => {
      $jsonViewer.innerHTML = '';
      $jsonViewer.appendChild(renderJson(data, true));
    }).catch(() => {
      $jsonViewer.textContent = 'No master_report.json yet — run a sweep first.';
    });
  }

  function renderJson(value, expanded) {
    const wrap = document.createElement('div');
    wrap.className = 'json-node';
    if (value === null) {
      wrap.innerHTML = '<span class="json-null">null</span>';
      return wrap;
    }
    const t = typeof value;
    if (t === 'string') {
      const s = document.createElement('span');
      s.className = 'json-str';
      s.textContent = '"' + value + '"';
      wrap.appendChild(s);
      return wrap;
    }
    if (t === 'number' || t === 'boolean') {
      const s = document.createElement('span');
      s.className = t === 'number' ? 'json-num' : 'json-bool';
      s.textContent = String(value);
      wrap.appendChild(s);
      return wrap;
    }
    if (Array.isArray(value)) {
      return renderContainer(value, '[', ']', true, expanded);
    }
    if (t === 'object') {
      return renderContainer(value, '{', '}', false, expanded);
    }
    return wrap;
  }

  function renderContainer(value, open, close, isArray, expanded) {
    const wrap = document.createElement('div');
    wrap.className = 'json-node';

    const collap = document.createElement('span');
    collap.className = 'json-collap';
    collap.textContent = expanded ? '▾' : '▸';

    const punc = document.createElement('span');
    punc.className = 'json-punc';
    punc.textContent = open;

    const count = document.createElement('span');
    count.className = 'json-count';
    const len = isArray ? value.length : Object.keys(value).length;
    count.textContent = `${len} ${isArray ? 'item' : 'key'}${len === 1 ? '' : 's'}`;

    const closeSpan = document.createElement('span');
    closeSpan.className = 'json-punc';
    closeSpan.textContent = close;

    const children = document.createElement('div');
    children.className = 'json-children' + (expanded ? '' : ' collapsed');

    const entries = isArray ? value.map((v, i) => [i, v]) : Object.entries(value);
    entries.forEach(([k, v]) => {
      const row = document.createElement('div');
      row.className = 'json-node';
      const keySpan = document.createElement('span');
      keySpan.className = 'json-key';
      keySpan.textContent = isArray ? '' : `"${k}"`;
      const colon = document.createElement('span');
      colon.className = 'json-punc';
      colon.textContent = isArray ? '' : ': ';
      row.appendChild(keySpan);
      row.appendChild(colon);
      const child = renderJson(v, false);
      // inline simple values; box containers
      row.appendChild(child);
      children.appendChild(row);
    });

    collap.addEventListener('click', () => {
      const collapsed = children.classList.toggle('collapsed');
      collap.textContent = collapsed ? '▸' : '▾';
    });

    wrap.appendChild(collap);
    wrap.appendChild(punc);
    wrap.appendChild(count);
    wrap.appendChild(children);
    wrap.appendChild(closeSpan);
    return wrap;
  }

  $jsonExpand.addEventListener('click', () => {
    $jsonViewer.querySelectorAll('.json-children.collapsed').forEach((c) => c.classList.remove('collapsed'));
    $jsonViewer.querySelectorAll('.json-collap').forEach((c) => { if (c.textContent === '▸') c.textContent = '▾'; });
  });
  $jsonCollapse.addEventListener('click', () => {
    $jsonViewer.querySelectorAll('.json-children').forEach((c) => c.classList.add('collapsed'));
    $jsonViewer.querySelectorAll('.json-collap').forEach((c) => c.textContent = '▸');
  });

  // ===================================================================
  // HISTORY
  // ===================================================================
  function loadHistory() {
    $historyList.innerHTML = 'Loading…';
    fetch('/history').then((r) => r.json()).then((data) => {
      const jobs = data.jobs || [];
      if (!jobs.length) {
        $historyList.innerHTML = '<div class="history-empty">No jobs run yet in this session.</div>';
        return;
      }
      $historyList.innerHTML = '';
      jobs.forEach((j) => {
        const row = document.createElement('div');
        row.className = 'history-item';
        const dur = j.duration_s != null ? `${j.duration_s.toFixed(1)}s` :
                    (j.state === 'running' ? 'running…' : '—');
        const when = j.ended_at ? new Date(j.ended_at * 1000).toLocaleTimeString() :
                     j.started_at ? new Date(j.started_at * 1000).toLocaleTimeString() : '—';
        row.innerHTML =
          `<span class="history-state s-${j.state}">${j.state}</span>` +
          `<div><div class="history-title">${escapeHtml(j.title)}</div>` +
          `<div class="history-meta">${j.steps.length} step${j.steps.length === 1 ? '' : 's'}</div></div>` +
          `<span class="history-meta">${dur}</span>` +
          `<span class="history-meta">${when}</span>`;
        $historyList.appendChild(row);
      });
    }).catch(() => {
      $historyList.innerHTML = '<div class="history-empty">Failed to load history.</div>';
    });
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  // ===================================================================
  // LIVE LOG
  // ===================================================================
  function classifyLine(line) {
    if (/__JOB_END__/.test(line)) return 'muted';
    if (/^\[step\]/.test(line)) return 'step';
    if (/^===.*===$/.test(line)) return 'info';
    if (/\b(UP|HEALTHY|AUTHED|✅)\b/.test(line)) return 'ok';
    if (/\b(DOWN|FAILED|ERROR|Traceback|❌|exit=[1-9])\b/.test(line)) return 'bad';
    if (/\b(DEGRADED|SLOW|AUTH_EXPIRED|KNOWN-?ISSUE|🔑|⚠)\b/.test(line)) return 'warn';
    return '';
  }
  function appendLine(line) {
    if ($log.firstElementChild && $log.firstElementChild.classList.contains('log-empty')) {
      $log.innerHTML = '';
    }
    const div = document.createElement('div');
    const cls = classifyLine(line);
    div.className = 'log-line' + (cls ? ' ' + cls : '');
    div.textContent = line;
    const atBottom = ($log.scrollTop + $log.clientHeight) >= ($log.scrollHeight - 20);
    $log.appendChild(div);
    if (atBottom) $log.scrollTop = $log.scrollHeight;
  }
  function clearLog() {
    $log.innerHTML = '<div class="log-empty">Log cleared.</div>';
  }
  $btnClear.addEventListener('click', clearLog);

  // ===================================================================
  // STATE + ELAPSED + RAIL TOGGLE
  // ===================================================================
  function setState(state, title) {
    $state.className = 'state-pill s-' + state;
    $state.textContent = state;
    $title.textContent = title || (state === 'idle' ? 'No job running' : '');
  }
  function startTicker() {
    startedAt = Date.now();
    if (tickerId) clearInterval(tickerId);
    tickerId = setInterval(() => {
      const s = Math.floor((Date.now() - startedAt) / 1000);
      const m = Math.floor(s / 60);
      $elapsed.textContent = (m ? m + 'm ' : '') + (s % 60) + 's';
    }, 250);
  }
  function stopTicker() {
    if (tickerId) { clearInterval(tickerId); tickerId = null; }
  }
  function setBusy(busy) {
    allActionButtons().forEach((b) => { b.disabled = busy; });
  }

  $btnRail.addEventListener('click', () => {
    $app.classList.toggle('rail-collapsed');
  });

  // ===================================================================
  // TOAST
  // ===================================================================
  function toast(kind, title, sub) {
    const t = document.createElement('div');
    t.className = 'toast t-' + kind;
    t.innerHTML = `<div class="toast-title">${escapeHtml(title)}</div>` +
                  (sub ? `<div class="toast-sub">${escapeHtml(sub)}</div>` : '');
    document.body.appendChild(t);
    setTimeout(() => {
      t.classList.add('leaving');
      setTimeout(() => t.remove(), 380);
    }, 3800);
  }

  // ===================================================================
  // JOB SUBMIT + SSE
  // ===================================================================
  function startJob(payload) {
    if (activeJobId) return;
    setBusy(true);
    setState('running', 'Submitting…');
    startTicker();
    // auto-expand rail when starting a job
    $app.classList.remove('rail-collapsed');

    fetch('/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          appendLine('[ui] ' + data.error);
          setState('failed', '');
          stopTicker();
          setBusy(false);
          return;
        }
        activeJobId = data.job_id;
        setState('running', data.title);
        openStream(data.job_id);
      })
      .catch((e) => {
        appendLine('[ui] submit failed: ' + e);
        setState('failed', '');
        stopTicker();
        setBusy(false);
      });
  }

  function openStream(jobId) {
    if (activeES) activeES.close();
    activeES = new EventSource(`/events/${jobId}`);
    activeES.onmessage = (e) => { appendLine(e.data); };
    activeES.onerror = () => {
      activeES.close();
      activeES = null;
      fetch(`/status/${jobId}`).then((r) => r.json()).then((s) => {
        const finalState = s.state === 'done' ? 'done'
                          : s.state === 'failed' ? 'failed'
                          : 'idle';
        setState(finalState, s.title);
        stopTicker();
        setBusy(false);
        activeJobId = null;
        if (finalState === 'done') {
          toast('done', '✓ ' + (s.title || 'Job complete'),
                'Finished in ' + ($elapsed.textContent || '?'));
        } else if (finalState === 'failed') {
          toast('failed', '✗ ' + (s.title || 'Job failed'),
                'Check the log for the failing step');
        }
        loadVerdicts();
        // if user is on dashboard or report tab, refresh those too
        if (currentView === 'dashboard') $dashFrame.src = '/dashboard?t=' + Date.now();
        if (currentView === 'report')    loadJsonReport();
        if (currentView === 'history')   loadHistory();
      });
    };
  }

  // ===================================================================
  // WIRE BUTTONS
  // ===================================================================
  document.querySelectorAll('button[data-kind]').forEach((btn) => {
    btn.addEventListener('click', () => {
      startJob({
        kind: btn.dataset.kind,
        name: btn.dataset.name || null,
        mode: btn.dataset.mode || 'all',
      });
    });
  });

  // ===================================================================
  // INIT
  // ===================================================================
  // reload-safe: reconnect to running job
  fetch('/status').then((r) => r.json()).then((s) => {
    if (s.current) {
      activeJobId = s.current;
      const j = (s.jobs || []).find((x) => x.id === s.current);
      setState('running', j ? j.title : 'Job in progress');
      setBusy(true);
      startTicker();
      openStream(s.current);
    } else {
      setState('idle', '');
    }
  });

  loadVerdicts();
})();
