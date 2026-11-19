// Apply bar sizes from safely rendered data-* attributes, not Jinja inline CSS.
// No requests, state mutations, timers or third-party chart scripts.
(() => {
  'use strict';
  for (const bar of document.querySelectorAll('[data-cf-fill]')) {
    const value = Number(bar.getAttribute('data-cf-fill'));
    bar.style.width = `${Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0}%`;
  }
})();
