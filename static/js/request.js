(() => {
  const searchLink = document.getElementById('request-search-link');
  const form = document.getElementById('request-form');
  let catalogWindow = null;

  if (searchLink) {
    searchLink.addEventListener('click', (event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const width = Math.min(1100, Math.max(640, window.screen.availWidth - 80));
      const height = Math.min(820, Math.max(560, window.screen.availHeight - 80));
      const opened = window.open(searchLink.href, 'biblioteca-up-inventio', `popup=yes,width=${width},height=${height}`);
      if (!opened) return; // The link still opens normally when popups are blocked.
      event.preventDefault();
      catalogWindow = opened;
      try { opened.opener = null; } catch { /* Cross-origin windows may refuse this. */ }
      opened.focus();
    });
  }

  if (form) {
    const viewerInput = document.getElementById('request-url-input');
    viewerInput?.addEventListener('input', () => {
      try {
        const viewer = new URL(viewerInput.value);
        if (viewer.protocol === 'https:' && viewer.pathname.toLowerCase().endsWith('/visorbook.aspx') && catalogWindow && !catalogWindow.closed) {
          catalogWindow.close();
          catalogWindow = null;
        }
      } catch { /* The address is still being entered. */ }
    });
    form.addEventListener('submit', () => {
      try { if (catalogWindow && !catalogWindow.closed) catalogWindow.close(); } catch { /* The request still proceeds. */ }
      const button = form.querySelector('button[type="submit"]');
      if (button) {
        button.disabled = true;
        button.textContent = 'Enviando solicitud…';
      }
    });
  }

  const wait = document.getElementById('request-wait');
  if (!wait) return;

  const statusText = document.getElementById('request-status-text');
  const progress = document.getElementById('request-progress');
  const progressLabel = document.getElementById('request-progress-label');
  const actions = document.getElementById('request-wait-actions');
  const loginAction = document.getElementById('request-wait-login');
  const quote = document.getElementById('request-quote');
  const loginUrl = new URL(wait.dataset.loginUrl, location.href);
  loginUrl.searchParams.set('next', location.pathname + location.search);
  loginAction.href = loginUrl.href;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const quotes = [
    '“Cada libro abre una nueva posibilidad.”',
    '“La siguiente idea puede estar en la próxima página.”',
    '“Leer también es descubrir nuevos caminos.”',
    '“Una buena lectura siempre encuentra su momento.”',
  ];
  let quoteIndex = 0;
  let quoteTimer;
  let pollTimer;
  let polling = false;
  let stopped = false;
  let failures = 0;

  function setMessage(message) {
    if (statusText.textContent !== message) statusText.textContent = message;
  }

  function stop(state, message, needsLogin = false) {
    stopped = true;
    wait.dataset.state = state;
    clearTimeout(pollTimer);
    clearInterval(quoteTimer);
    setMessage(message);
    actions.hidden = false;
    loginAction.hidden = !needsLogin;
  }

  function schedule() {
    if (!stopped) pollTimer = setTimeout(poll, document.hidden ? 8000 : 2500);
  }

  async function poll() {
    if (polling || stopped) return;
    polling = true;
    try {
      const response = await fetch(wait.dataset.statusUrl, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } });
      if (response.status === 403) {
        stop('error', 'Tu sesión de Biblioteca UP terminó. Inicia sesión de nuevo para consultar esta solicitud.', true);
        return;
      }
      if (response.status === 404) {
        stop('error', 'No encontramos esta solicitud. Puedes iniciar una nueva.');
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      failures = 0;
      const data = await response.json();
      const state = data.status;
      wait.dataset.state = state;
      const done = Number(data.pages_done);
      const total = Number(data.pages_total);
      if (Number.isFinite(done) && Number.isFinite(total) && total > 0) {
        progress.max = total;
        progress.value = Math.min(total, Math.max(0, done));
        progressLabel.textContent = `${Math.min(total, Math.max(0, done))} de ${total} páginas preparadas`;
      } else {
        progress.removeAttribute('value');
        progressLabel.textContent = state === 'queued' ? 'Esperando turno…' : 'Preparando el recurso…';
      }
      if (state === 'completed') {
        if (data.book_url) {
          try {
            const destination = new URL(data.book_url, location.href);
            if (destination.origin === location.origin) {
              setMessage('El libro ya está disponible. Abriendo la ficha…');
              location.assign(destination.href);
              return;
            }
          } catch { /* The response did not contain a usable book URL. */ }
        }
        stop('error', 'El libro se preparó, pero no pudimos abrir su ficha. Vuelve al catálogo.');
        return;
      }
      if (state === 'failed') {
        stop('failed', data.message || 'No se pudo preparar el libro. Puedes revisar el enlace e intentarlo de nuevo.');
        return;
      }
      setMessage(data.message || (state === 'processing'
        ? 'La VPS está preparando las páginas del libro.'
        : 'La solicitud está en espera. La descarga se procesará en segundo plano.'));
    } catch {
      failures += 1;
      if (failures >= 3) setMessage('No pudimos consultar el avance. Seguiremos intentándolo automáticamente.');
    } finally {
      polling = false;
      schedule();
    }
  }

  function rotateQuote() {
    quoteIndex = (quoteIndex + 1) % quotes.length;
    if (reduceMotion.matches) {
      quote.textContent = quotes[quoteIndex];
      return;
    }
    quote.classList.add('is-changing');
    setTimeout(() => {
      quote.textContent = quotes[quoteIndex];
      quote.classList.remove('is-changing');
    }, 180);
  }

  quoteTimer = setInterval(rotateQuote, 7000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !stopped && !polling) {
      clearTimeout(pollTimer);
      poll();
    }
  });
  window.addEventListener('pagehide', () => {
    stopped = true;
    clearTimeout(pollTimer);
    clearInterval(quoteTimer);
  });
  poll();
})();
