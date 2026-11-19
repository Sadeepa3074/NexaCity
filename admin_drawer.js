/* CivicFix — Reports drawer for Overview and Reports. No framework required. */
document.addEventListener('DOMContentLoaded', () => {
  'use strict';
  const root = document.getElementById('cf-report-drawer');
  if (!root) return;

  const panel = root.querySelector('.cf-drawer-panel');
  const content = document.getElementById('cf-drawer-content');
  const feedback = document.getElementById('cf-drawer-feedback');
  let activeUrl = null;
  let lastFocus = null;
  let map = null;
  let requestNumber = 0;
  let hasSuccessfulChanges = false;

  function notify(message, type = '') {
    feedback.textContent = message;
    feedback.className = 'cf-drawer-feedback' + (type ? ' is-' + type : '');
    feedback.hidden = !message;
  }

  function cleanupMap() {
    if (map) {
      map.remove();
      map = null;
    }
  }

  function initializeMap() {
    const element = content.querySelector('.cf-drawer-map[data-lat][data-lng]');
    if (!element) return;
    const lat = Number(element.dataset.lat);
    const lng = Number(element.dataset.lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) {
      element.textContent = 'Invalid location coordinates.';
      return;
    }
    if (typeof L === 'undefined') {
      element.textContent = 'Map library unavailable. Check your connection.';
      return;
    }
    cleanupMap();
    map = L.map(element, { scrollWheelZoom: false }).setView([lat, lng], 16);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    L.marker([lat, lng]).addTo(map).bindPopup('Citizen-reported issue location');
    window.setTimeout(() => { if (map) map.invalidateSize(); }, 320);
  }

  function makeDrawerUrl(reportUrl) {
    const url = new URL(reportUrl, window.location.href);
    if (url.origin !== window.location.origin || !/^\/admin\/reports\/\d+\/?$/.test(url.pathname)) {
      throw new Error('Not a CivicFix report detail link.');
    }
    url.searchParams.set('drawer', '1');
    return url.href;
  }

  async function loadDrawer(url, { resetScroll = false } = {}) {
    const seq = ++requestNumber;
    cleanupMap();
    content.innerHTML = '<div class="cf-drawer-loading" role="status">Loading report details…</div>';
    const response = await fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    if (seq !== requestNumber || !root.classList.contains('is-open')) return;
    if (response.redirected && new URL(response.url).pathname === '/admin/login') {
      window.location.assign(response.url);
      return;
    }
    if (!response.ok) throw new Error('Unable to open this report (HTTP ' + response.status + ').');
    const html = await response.text();
    if (seq !== requestNumber || !root.classList.contains('is-open')) return;
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const report = parsed.querySelector('.cf-drawer-inner');
    if (!report) throw new Error('The server did not return a report panel. Check the admin routes.');
    content.replaceChildren(report);
    if (resetScroll) content.querySelector('.cf-drawer-scroll').scrollTop = 0;
    initializeMap();
    panel.querySelector('.cf-drawer-close')?.focus();
  }

  async function openDrawer(href, trigger) {
    try {
      activeUrl = makeDrawerUrl(href);
    } catch (error) {
      window.location.assign(href);
      return;
    }
    lastFocus = trigger || document.activeElement;
    hasSuccessfulChanges = false;
    notify('');
    root.classList.add('is-open');
    root.setAttribute('aria-hidden', 'false');
    document.body.classList.add('cf-drawer-open');
    panel.focus();
    try {
      await loadDrawer(activeUrl, { resetScroll: true });
    } catch (error) {
      content.innerHTML = '<div class="cf-drawer-loading">Unable to load report. You can close this panel and try again.</div>';
      notify(error.message, 'error');
    }
  }

  function closeDrawer() {
    ++requestNumber;
    cleanupMap();
    root.classList.remove('is-open');
    root.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('cf-drawer-open');
    const shouldReload = hasSuccessfulChanges;
    const target = lastFocus;
    activeUrl = null;
    notify('');
    if (shouldReload) {
      // Update the underlying dashboard/report list metrics and status badges.
      window.location.reload();
    } else if (target && typeof target.focus === 'function') {
      target.focus();
    }
  }

  document.addEventListener('click', event => {
    const closeButton = event.target.closest('[data-cf-drawer-close]');
    if (closeButton && root.contains(closeButton)) {
      event.preventDefault();
      closeDrawer();
      return;
    }
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest('a[data-cf-drawer-link]');
    if (link) {
      event.preventDefault();
      openDrawer(link.href, link);
      return;
    }
    const row = event.target.closest('[data-cf-drawer-row]');
    if (!row || event.target.closest('a, button, input, select, textarea, label')) return;
    const rowLink = row.querySelector('a[data-cf-drawer-link]');
    if (rowLink) { event.preventDefault(); openDrawer(rowLink.href, rowLink); }
  });

  document.addEventListener('keydown', event => {
    if (!root.classList.contains('is-open')) return;
    if (event.key === 'Escape') { event.preventDefault(); closeDrawer(); return; }
    if (event.key !== 'Tab') return;
    const focusables = [...panel.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])')]
      .filter(el => el.getClientRects().length);
    if (!focusables.length) { event.preventDefault(); panel.focus(); return; }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });

  content.addEventListener('submit', async event => {
    const form = event.target.closest('form[data-cf-async-form]');
    if (!form || !activeUrl) return;
    event.preventDefault();
    if (!form.reportValidity()) return;
    const button = form.querySelector('button[type=submit]');
    if (button) button.disabled = true;
    notify('Saving changes…');
    try {
      // Reuse the existing Part 3 POST endpoints. They commit transactions,
      // flash status, and redirect to the standalone report page.
      const response = await fetch(form.action, {
        method: 'POST', body: new FormData(form), credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      if (response.redirected && new URL(response.url).pathname === '/admin/login') {
        window.location.assign(response.url);
        return;
      }
      if (!response.ok) throw new Error('Save failed (HTTP ' + response.status + ').');
      const html = await response.text();
      const resultPage = new DOMParser().parseFromString(html, 'text/html');
      const messages = [...resultPage.querySelectorAll('.admin-notice')];
      const resultMessage = messages.map(el => el.textContent.trim()).filter(Boolean).join(' ');
      const isError = messages.some(el => el.classList.contains('error'));
      const isSuccess = messages.some(el => el.classList.contains('success'));
      // If the previous server redirects and returns a login page, do not imply success.
      if (!resultPage.querySelector('.report-detail-heading')) {
        throw new Error('The response was not a report detail page. Check your session.');
      }
      if (isSuccess) hasSuccessfulChanges = true;
      await loadDrawer(activeUrl);
      notify(resultMessage || 'The request was processed. Review the current details.', isError ? 'error' : isSuccess ? 'success' : '');
    } catch (error) {
      notify(error.message || 'Unable to save changes.', 'error');
    } finally {
      if (button) button.disabled = false;
    }
  });
});
