// CertiKeep front-end behaviour. Plain JavaScript, no build step. Every block is optional:
// with scripts off the forms still submit and the pages still work (the review page then needs a manual reload).
(() => {
  'use strict';
  const $ = (sel, root = document) => root.querySelector(sel);

  // ---------------------------------------------------------------- light / dark
  const toggle = $('#theme-toggle');
  if (toggle) {
    toggle.addEventListener('click', () => {
      const root = document.documentElement;
      const dark = root.dataset.theme ? root.dataset.theme === 'dark'
                                      : matchMedia('(prefers-color-scheme: dark)').matches;
      root.dataset.theme = dark ? 'light' : 'dark';
      try { localStorage.setItem('ck-theme', root.dataset.theme); } catch (e) { /* private window */ }
    });
  }

  // ---------------------------------------------------------------- messages, confirmations
  document.addEventListener('click', (ev) => {
    const x = ev.target.closest('.flash-x');
    if (x) x.closest('.flash').remove();
  });
  document.addEventListener('submit', (ev) => {
    const form = ev.target;
    if (form.dataset.confirm && !confirm(form.dataset.confirm)) { ev.preventDefault(); return; }
    // Show that a click was received on forms that say so.
    if (form.dataset.busy) setBusy($('button', form), form.dataset.busy);
  });

  function setBusy(button, text) {
    if (!button) return;
    button.dataset.label = button.innerHTML;
    button.classList.add('is-busy');
    button.innerHTML = '<i class="spinner"></i><span></span>';
    button.lastChild.textContent = text;
    // Disable after the browser has collected the form, or the submit would be cancelled.
    setTimeout(() => { button.disabled = true; }, 0);
  }
  // Coming back with the Back button restores the page as it was left: undo the "busy" state.
  addEventListener('pageshow', (ev) => {
    if (!ev.persisted) return;
    document.querySelectorAll('button.is-busy').forEach((b) => {
      b.innerHTML = b.dataset.label; b.disabled = false; b.classList.remove('is-busy');
    });
  });

  // ---------------------------------------------------------------- upload
  const upform = $('#upform');
  if (upform) {
    const zone = $('#dropzone'), input = $('#file'), error = $('#file-error');
    const MAX = 15 * 1024 * 1024, OK = /\.(jpe?g|png|webp|pdf)$/i;
    let thumbUrl = null;

    const size = (n) => n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1024 / 1024).toFixed(1) + ' MB';
    const problem = (file) => !OK.test(file.name) ? 'Only JPG, PNG, WEBP or PDF files.'
                            : file.size > MAX ? 'File is larger than 15 MB.' : '';

    function show() {
      const file = input.files[0];
      const msg = file ? problem(file) : '';
      error.textContent = msg; error.hidden = !msg;
      if (thumbUrl) { URL.revokeObjectURL(thumbUrl); thumbUrl = null; }
      const picked = Boolean(file) && !msg;
      zone.classList.toggle('has-file', picked);
      $('.dz-empty', zone).hidden = picked;
      $('.dz-file', zone).hidden = !picked;
      if (msg) input.value = '';
      if (!picked) return;
      $('.dz-name', zone).textContent = file.name;
      $('.dz-size', zone).textContent = size(file.size) + (file.type === 'application/pdf' ? ' · PDF' : '');
      const thumb = $('.dz-thumb', zone);
      const isImage = file.type.startsWith('image/');
      thumb.classList.toggle('has-img', isImage);
      thumb.style.backgroundImage = isImage ? `url("${thumbUrl = URL.createObjectURL(file)}")` : '';
    }
    input.addEventListener('change', show);
    ['dragenter', 'dragover'].forEach((t) => zone.addEventListener(t, () => zone.classList.add('is-over')));
    ['dragleave', 'drop'].forEach((t) => zone.addEventListener(t, () => zone.classList.remove('is-over')));
    show();   // a file may already be chosen after Back

    upform.addEventListener('submit', (ev) => {
      if (ev.defaultPrevented) return;
      setBusy($('#upbtn'), 'Uploading…');
    });
  }

  // ---------------------------------------------------------------- review: wait for the AI without blocking the page
  const progress = $('#ai-progress');
  if (progress) {
    const form = $('#review-form'), time = $('#ai-time'), hint = $('#ai-hint');
    const started = Date.now() - Number(progress.dataset.elapsed || 0) * 1000;
    let dirty = progress.dataset.dirty === '1';   // the person has typed values we must not throw away
    let failures = 0, finished = false;

    form.addEventListener('input', (ev) => {
      dirty = true;
      if (ev.target.classList) ev.target.classList.add('touched');
    });

    const clock = setInterval(() => {
      const s = Math.round((Date.now() - started) / 1000);
      time.textContent = s + ' s';
      if (s >= 25 && !hint.dataset.slow) {
        hint.dataset.slow = '1';
        hint.textContent = 'Taking longer than usual: Gemini may be busy. You can already fill in the fields by hand. '
                         + 'The read stops by itself if no answer comes.';
      }
    }, 1000);

    function done() {
      finished = true;
      clearInterval(clock);
      if (!dirty) { location.replace(location.pathname); return; }   // show the suggestion
      progress.classList.add('is-done');
      $('.ai-progress-top b', progress).textContent = 'AI finished';
      time.hidden = true; hint.hidden = true; $('#ai-done').hidden = false;
      form.classList.remove('awaiting-ai');
    }

    async function poll() {
      if (finished) return;
      try {
        const res = await fetch(progress.dataset.statusUrl, { headers: { Accept: 'application/json' }, cache: 'no-store' });
        if (!res.ok) throw new Error(res.status);
        const state = await res.json();
        failures = 0;
        if (!state.pending) { done(); return; }
      } catch (e) {
        if (++failures === 4) {
          hint.dataset.slow = '1';
          hint.textContent = 'Cannot reach CertiKeep. Check that the app is still running; this page keeps trying.';
        }
      }
      setTimeout(poll, 1500);
    }
    setTimeout(poll, 800);
  }

  // ---------------------------------------------------------------- documents: filter rows as you type
  const filter = $('#doc-filter');
  if (filter) {
    const rows = [...document.querySelectorAll('#doc-table tbody tr')];
    filter.addEventListener('input', () => {
      const q = filter.value.trim().toLowerCase();
      let shown = 0;
      rows.forEach((r) => { r.hidden = Boolean(q) && !r.textContent.toLowerCase().includes(q); if (!r.hidden) shown++; });
      $('#doc-none').hidden = shown > 0;
    });
  }
})();
