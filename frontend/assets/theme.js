// Apply the saved palette before the stylesheet paints; this small bootstrap is
// intentionally synchronous. The application itself continues to use ES modules.
(() => {
  const key = 'lalaland.appearance';
  const normalize = value => ['dark', 'light', 'system'].includes(value) ? value : 'dark';
  const system = window.matchMedia?.('(prefers-color-scheme: light)');
  let preference = 'dark';
  try { preference = normalize(window.localStorage.getItem(key)); }
  catch { /* Appearance still works when browser storage is unavailable. */ }

  function apply() {
    document.documentElement.dataset.theme = preference === 'system'
      ? (system?.matches ? 'light' : 'dark') : preference;
    const control = document.getElementById('theme-select');
    if (control) control.value = preference;
  }

  function initializeControl() {
    const control = document.getElementById('theme-select');
    if (!control) return;
    control.value = preference;
    control.addEventListener('change', () => {
      preference = normalize(control.value);
      apply();
      try { window.localStorage.setItem(key, preference); }
      catch { /* Keep the current selection for this page. */ }
    });
  }

  apply();
  system?.addEventListener?.('change', () => {
    if (preference === 'system') apply();
  });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) {
      preference = normalize(event.newValue);
      apply();
    }
  });
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeControl, {once: true});
  } else {
    initializeControl();
  }
})();
