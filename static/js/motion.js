(() => {
  const root = document.documentElement;
  const art = document.querySelector('.hero-art');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  const setInput = (input) => {
    if (root.dataset.motionInput !== input) root.dataset.motionInput = input;
  };

  document.addEventListener('pointerdown', () => setInput('pointer'), { passive: true });
  document.addEventListener('pointermove', (event) => {
    if (event.pointerType === 'mouse') setInput('pointer');
  }, { passive: true });
  document.addEventListener('keydown', () => {
    setInput('keyboard');
    art?.classList.remove('motion-art-settle');
  }, true);

  if (!art || reduceMotion.matches) return;

  // The visual composition remains visible if storage or animation is unavailable.
  try {
    const key = 'biblioteca-up:book-settled';
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, '1');
  } catch {
    return;
  }

  art.classList.add('motion-art-settle');
  art.addEventListener('animationend', (event) => {
    if (event.animationName === 'book-settle') art.classList.remove('motion-art-settle');
  }, { once: true });
  reduceMotion.addEventListener('change', (event) => {
    if (event.matches) art.classList.remove('motion-art-settle');
  });
})();
