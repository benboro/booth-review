/**
 * Sizes the desktop filter bars' equal-cell grids to fit the visitor's own font
 * (04.9 D-21, 13-10 C3).
 *
 * Above 480px a filter bar is a grid of equal cells whose row count depends on
 * the viewport width only, never on a control's value. For each registered bar
 * this script measures the widest resting label in the font the page actually
 * renders in, works out how many such cells fit in one row (k), and writes
 *   --toolbar-cell-min  the widest cell, in px
 *   --toolbar-cols      ceil(N / rows) with rows = ceil(N / k)  (balanced rows)
 * on the bar; style.css turns those into the grid.
 *
 * Only filter controls are measured (`:scope > .filter-trigger`): the labels
 * the bar ships with, captured when the bar is registered, before app.js
 * replaces any of them with a value. Long values truncate with an ellipsis. The
 * measurement is redone only when the font or the bar's width can change it
 * (fonts ready, a font load, a resize, crossing the phone breakpoint, the bar
 * becoming visible), never on a filter change, so the row count stays fixed
 * while filters toggle (T-13-23).
 *
 * The CFB `#toolbar` is no longer fitted (it is the fixed-width ledger); the NFL bar, built by JS, calls
 * `window.boothToolbarFit.register(bar)`.
 *
 * A classic script loaded right after the toolbar markup, not a module:
 * modules run after the whole page (and the Plotly bundle) has loaded, by
 * which point the toolbar may already have painted at the wrong row count.
 * Running here, before anything below the toolbar is parsed, avoids a
 * visible jump.
 */
(() => {
  // Mirrors PHONE_QUERY in modules/breakpoints.js; a classic script cannot import it.
  const mobileMedia = window.matchMedia('(max-width: 480px)');
  // Mirrors the grid gap and the control's caret (6px) plus its gap in style.css.
  const GAP_PX = 8;
  const CARET_PX = 14;

  // Everything that sets a label's rendered width, copied from the real button.
  const COPIED = [
    'fontFamily',
    'fontSize',
    'fontStyle',
    'fontStretch',
    'fontVariant',
    'fontKerning',
    'fontFeatureSettings',
    'fontVariationSettings',
    'fontOpticalSizing',
    'letterSpacing',
    'wordSpacing',
    'textTransform',
    'textRendering',
    'paddingLeft',
    'paddingRight',
    'borderLeftWidth',
    'borderRightWidth',
  ];

  /** bar -> { labels: Map(button -> resting label), applied: string|null } */
  const bars = new Map();

  function controlsOf(bar) {
    return [...bar.querySelectorAll(':scope > .filter-trigger')];
  }

  function restingLabelOf(btn) {
    const label = btn.querySelector('.filter-label');
    return (label ? label.textContent : btn.textContent).trim();
  }

  /** The widest resting label's full control width, in CSS pixels. */
  function widestRestingLabel(entry) {
    const box = document.createElement('div');
    box.className = 'toolbar-measure';
    box.setAttribute('aria-hidden', 'true');
    const probes = [...entry.labels].map(([btn, text]) => {
      const style = getComputedStyle(btn);
      const probe = document.createElement('span');
      for (const prop of COPIED) probe.style[prop] = style[prop];
      // Measured at the changed weight, the widest the label ever renders.
      probe.style.fontWeight = '600';
      probe.style.borderLeftStyle = 'solid';
      probe.style.borderRightStyle = 'solid';
      probe.textContent = text;
      box.append(probe);
      return probe;
    });
    document.body.append(box);
    let widest = 0;
    for (const probe of probes) widest = Math.max(widest, probe.getBoundingClientRect().width);
    box.remove();
    return widest + CARET_PX;
  }

  /** Measures one bar and writes its two custom properties; a no-op on phones and while hidden. */
  function fitBar(bar, entry) {
    if (mobileMedia.matches) return;
    const cs = getComputedStyle(bar);
    const width = bar.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    if (!(width > 0)) return;
    const widest = widestRestingLabel(entry);
    if (!(widest > 0)) return;
    // Rounded up to a whole pixel, so a fractional text width never clips by a sliver.
    const cell = Math.ceil(widest);
    const n = entry.labels.size;
    const perRow = Math.max(1, Math.floor((width + GAP_PX) / (cell + GAP_PX)));
    const rows = Math.max(1, Math.ceil(n / perRow));
    const cols = Math.max(1, Math.ceil(n / rows));
    const key = `${cell}/${cols}/${Math.round(width)}`;
    if (key === entry.applied) return;
    entry.applied = key;
    bar.style.setProperty('--toolbar-cell-min', `${cell}px`);
    bar.style.setProperty('--toolbar-cols', String(cols));
  }

  function fitAll() {
    for (const [bar, entry] of bars) fitBar(bar, entry);
  }

  /** Starts fitting `bar`'s `:scope > .filter-trigger` controls. Idempotent. */
  function register(bar) {
    if (!bar || bars.has(bar)) return;
    const entry = { labels: new Map(controlsOf(bar).map((btn) => [btn, restingLabelOf(btn)])), applied: null };
    bars.set(bar, entry);
    fitBar(bar, entry);
    // style.css keeps the controls invisible until now (a slow load can paint before this runs).
    bar.dataset.fitted = '';
    // A bar hidden by the sport switch has no width; it fits when it is shown again.
    // This fires on a size change only, never on a filter change.
    if (window.ResizeObserver) new ResizeObserver(() => fitBar(bar, entry)).observe(bar);
  }

  window.boothToolbarFit = { register };

  if (document.fonts) {
    const refit = () => {
      for (const entry of bars.values()) entry.applied = null;
      fitAll();
    };
    document.fonts.ready.then(refit);
    document.fonts.addEventListener('loadingdone', refit);
  }
  mobileMedia.addEventListener('change', fitAll);
  // Zoom fires a resize; text widths can shift with it under font hinting.
  let resizeTimer = null;
  window.addEventListener(
    'resize',
    () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(fitAll, 150);
    },
    { passive: true },
  );
})();
