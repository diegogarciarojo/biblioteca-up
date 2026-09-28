(() => {
  const root = document.documentElement;
  const storageKey = 'biblioteca-up-theme';
  const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const themeColor = document.querySelector('meta[name="theme-color"]');
  const lightColor = themeColor?.dataset.lightColor || '#f4f1e9';
  let preference = readPreference();
  let transitionTimer;

  function readPreference() {
    try {
      const value = localStorage.getItem(storageKey);
      return value === 'dark' || value === 'light' ? value : null;
    } catch {
      return null;
    }
  }

  function applyTheme(theme, animate = false) {
    clearTimeout(transitionTimer);
    if (animate && !reducedMotion.matches) {
      root.dataset.themeTransition = 'true';
      transitionTimer = setTimeout(() => delete root.dataset.themeTransition, 240);
    } else {
      delete root.dataset.themeTransition;
    }
    root.dataset.theme = theme;
    if (themeColor) themeColor.content = theme === 'dark' ? '#142321' : lightColor;
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      const dark = theme === 'dark';
      button.setAttribute('aria-pressed', String(dark));
      button.title = dark ? 'Activar modo claro' : 'Activar modo nocturno';
      button.querySelector('[data-theme-label]').textContent = 'Modo nocturno';
      button.hidden = false;
    });
  }

  function resolvedTheme() {
    return preference || (systemTheme.matches ? 'dark' : 'light');
  }

  // Run before the stylesheets paint to avoid a flash of the wrong theme.
  applyTheme(resolvedTheme());
  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(resolvedTheme());
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      button.addEventListener('click', event => {
        preference = root.dataset.theme === 'dark' ? 'light' : 'dark';
        try { localStorage.setItem(storageKey, preference); } catch { /* The current page still works when storage is unavailable. */ }
        applyTheme(preference, event.detail > 0);
      });
    });
  }, { once: true });
  systemTheme.addEventListener('change', () => {
    if (!preference) applyTheme(resolvedTheme());
  });
  window.addEventListener('storage', event => {
    if (event.key === storageKey || event.key === null) {
      preference = readPreference();
      applyTheme(resolvedTheme());
    }
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) {
      preference = readPreference();
      applyTheme(resolvedTheme());
    }
  });
})();
