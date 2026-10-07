
(() => {
  const toggle = document.querySelector('.mobile-toggle');
  const nav = document.querySelector('.nav');
  if (toggle && nav) {
    toggle.addEventListener('click', () => {
      const open = nav.classList.toggle('mobile-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  document.querySelectorAll('.nav-dropdown > button').forEach(btn => {
    btn.addEventListener('click', () => {
      const wrap = btn.closest('.nav-dropdown');
      const open = wrap.classList.toggle('open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  });

  document.addEventListener('click', e => {
    document.querySelectorAll('.nav-dropdown.open').forEach(wrap => {
      if (!wrap.contains(e.target)) {
        wrap.classList.remove('open');
        const b = wrap.querySelector('button');
        if (b) b.setAttribute('aria-expanded','false');
      }
    });
  });

  document.querySelectorAll('[data-direct-url-form]').forEach(form => {
    form.addEventListener('submit', e => {
      e.preventDefault();
      const input = form.querySelector('input[type="url"]');
      let url = input.value.trim();
      if (!url) { input.focus(); return; }
      // Accept links pasted without the scheme, e.g. "youtube.com/watch?v=…".
      if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(url)) url = `https://${url}`;
      try {
        const u = new URL(url);
        location.href = 'download-video.html?url=' + encodeURIComponent(u.href);
      } catch {
        input.setCustomValidity('Enter a valid URL.');
        input.reportValidity();
        setTimeout(() => input.setCustomValidity(''), 1000);
      }
    });
  });
})();
