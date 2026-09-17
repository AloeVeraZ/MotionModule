/* ==========================================================================
   MotionModule appearance, shared by the dashboard and the Driver Station.

   Nothing in this file talks to the robot. Every command, stop, and safety
   rule lives in the page's own script; this one only handles the theme
   switch, the bar's shadow once the page scrolls, the narrow-screen menu, and
   the press feedback on buttons.

   The inline boot script in each page's <head> has already set data-theme
   before first paint. Every browser API used here is optional, so a browser
   without one keeps a working page.
   ========================================================================== */
(() => {
  'use strict';

  const root = document.documentElement;
  const THEME_KEY = 'motionmodule-theme';
  const THEME_COLORS = { dark: '#080808', light: '#f3f1ec' };

  const read = key => {
    try { return localStorage.getItem(key); } catch (error) { return null; }
  };
  const write = (key, value) => {
    try { localStorage.setItem(key, value); } catch (error) { /* the choice holds for this page */ }
  };
  const media = query => (window.matchMedia ? window.matchMedia(query) : null);
  const lightScheme = media('(prefers-color-scheme: light)');
  const reducedMotion = media('(prefers-reduced-motion: reduce)');

  /* ---- theme: dark by default, light, or whatever the system asks for ---- */

  const themeButtons = [...document.querySelectorAll('[data-theme-choice]')];
  const themeChoice = () => {
    const saved = read(THEME_KEY);
    return saved === 'light' || saved === 'system' ? saved : 'dark';
  };

  function applyTheme(choice) {
    const resolved = choice === 'system'
      ? (lightScheme && lightScheme.matches ? 'light' : 'dark')
      : choice;
    root.setAttribute('data-theme', resolved);
    document.querySelectorAll('meta[name="theme-color"]').forEach(tag => {
      tag.setAttribute('content', THEME_COLORS[resolved]);
    });
    themeButtons.forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.themeChoice === choice));
    });
  }

  // A page without the switch (the Driver Station) keeps the theme it ships.
  if (themeButtons.length) {
    themeButtons.forEach(button => button.addEventListener('click', () => {
      write(THEME_KEY, button.dataset.themeChoice);
      applyTheme(button.dataset.themeChoice);
    }));
    applyTheme(themeChoice());
    if (lightScheme) {
      const follow = () => { if (themeChoice() === 'system') applyTheme('system'); };
      if (lightScheme.addEventListener) lightScheme.addEventListener('change', follow);
      else if (lightScheme.addListener) lightScheme.addListener(follow);
    }
  }

  /* ---- the bar lifts once the page scrolls beneath it --------------------- */

  const bar = document.querySelector('[data-bar]');
  if (bar) {
    let queued = false;
    const update = () => {
      queued = false;
      bar.classList.toggle('scrolled', (window.scrollY || 0) > 4);
    };
    addEventListener('scroll', () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(update);
    }, { passive: true });
    update();
  }

  /* ---- the narrow-screen menu --------------------------------------------- */

  const menuButton = document.querySelector('[data-nav-toggle]');
  if (bar && menuButton) {
    const setOpen = open => {
      if (open) bar.setAttribute('data-nav-open', '');
      else bar.removeAttribute('data-nav-open');
      menuButton.setAttribute('aria-expanded', String(open));
    };
    menuButton.addEventListener('click', () => setOpen(!bar.hasAttribute('data-nav-open')));
    document.addEventListener('keydown', event => { if (event.key === 'Escape') setOpen(false); });
    document.addEventListener('click', event => { if (!bar.contains(event.target)) setOpen(false); });
  }

  /* ---- a press blooms outward from where it landed ------------------------ */

  const PRESSABLE = '.button, .stop-button, .tabs button, .command, .stop-command, .mini-button, .mode-switch button, .camera-controls button';

  document.addEventListener('pointerdown', event => {
    if (event.button !== 0 || (reducedMotion && reducedMotion.matches)) return;
    const target = event.target && event.target.closest ? event.target.closest(PRESSABLE) : null;
    if (!target || target.disabled) return;
    const box = target.getBoundingClientRect();
    const ripple = document.createElement('span');
    ripple.className = 'press-ripple';
    ripple.setAttribute('aria-hidden', 'true');
    ripple.style.left = `${Math.round(event.clientX - box.left)}px`;
    ripple.style.top = `${Math.round(event.clientY - box.top)}px`;
    ripple.style.setProperty('--ripple-size', `${Math.round(Math.max(box.width, box.height) * 2.2)}px`);
    ripple.addEventListener('animationend', () => ripple.remove(), { once: true });
    target.append(ripple);
  }, { passive: true });
})();
