(() => {
  const root = document.documentElement;
  const key = 'biblioteca-up:intro-seen:v1';
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let firstVisit = false;

  try {
    if (localStorage.getItem(key) !== '1') {
      localStorage.setItem(key, '1');
      firstVisit = true;
    }
  } catch {
    // If storage is blocked, keep the website immediate instead of replaying on every reload.
  }

  if (!firstVisit || reducedMotion.matches) {
    document.addEventListener('DOMContentLoaded', () => {
      document.getElementById('visit-intro')?.remove();
    }, { once: true });
    return;
  }
  root.dataset.intro = 'pending';

  document.addEventListener('DOMContentLoaded', () => {
    let intro = document.getElementById('visit-intro');
    if (!intro) {
      intro = document.createElement('div');
      intro.id = 'visit-intro';
      intro.className = 'visit-intro';
      intro.setAttribute('aria-hidden', 'true');
      intro.innerHTML = '<div class="visit-intro__halo"></div><div class="visit-intro__lens"><span class="visit-intro__mark brand-mark" aria-hidden="true"><span></span><span></span><span></span></span><span class="visit-intro__name">Bibliotecario</span><span class="visit-intro__line"></span></div>';
      document.body.prepend(intro);
    }

    let revealTimer;
    let cleanupTimer;
    let revealing = false;

    function cleanup() {
      clearTimeout(revealTimer);
      clearTimeout(cleanupTimer);
      delete root.dataset.intro;
      intro.remove();
      document.removeEventListener('keydown', onKeydown);
      reducedMotion.removeEventListener('change', onMotionChange);
    }

    function reveal() {
      if (revealing) return;
      revealing = true;
      root.dataset.intro = 'reveal';
      cleanupTimer = setTimeout(cleanup, 520);
    }

    function onKeydown(event) {
      if (event.key === 'Escape') reveal();
    }

    function onMotionChange(event) {
      if (event.matches) cleanup();
    }

    intro.addEventListener('click', reveal, { once: true });
    document.addEventListener('keydown', onKeydown);
    reducedMotion.addEventListener('change', onMotionChange);
    requestAnimationFrame(() => intro.classList.add('is-active'));
    revealTimer = setTimeout(reveal, 1060);
  }, { once: true });
})();
