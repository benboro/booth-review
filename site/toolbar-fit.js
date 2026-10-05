/**
 * Sizes the desktop toolbar's grid cells to fit the visitor's own font (04.9 D-21).
 *
 * Above 640px the toolbar is a grid of equal cells, so its row count never
 * changes when a filter label does. The cell's minimum width was a fixed
 * 116px, tuned on one machine's font; a wider default font (DejaVu Sans on
 * many Linux desktops) truncated resting labels such as "Bowls/Playoffs ▾"
 * and "Clear all filters". This script measures the widest resting label in
 * the font the page actually renders in and writes it to `--toolbar-cell-min`
 * on `#toolbar`, which style.css uses as the grid's minimum cell width.
 *
 * Only the resting labels are measured: the labels the toolbar ships with in
 * index.html, captured once here before app.js renders any filter summary.
 * Active summaries ("Game: CFP National Championship") still truncate with an
 * ellipsis. The width is re-measured only when the font or zoom can change it
 * (fonts ready, a font load, a resize, crossing the phone breakpoint), never
 * on a filter change, so the row count stays fixed while filters toggle.
 *
 * A classic script loaded right after the toolbar markup, not a module:
 * modules run after the whole page (and the Plotly bundle) has loaded, by
 * which point the toolbar may already have painted at the wrong row count.
 * Running here, before anything below the toolbar is parsed, avoids a
 * visible jump.
 */
(() => {
  const toolbar = document.getElementById('toolbar');
  if (!toolbar) return;

  const mobileMedia = window.matchMedia('(max-width: 640px)');
  const buttons = [...toolbar.querySelectorAll(':scope > .filter-trigger, :scope > #clear-filters')];
  // The resting labels, read before app.js replaces any of them with a summary.
  const restingLabels = new Map(buttons.map((btn) => [btn, btn.textContent.trim()]));

  // Everything that sets a label's rendered width, copied from the real button.
  const COPIED = [
    'fontFamily',
    'fontSize',
    'fontWeight',
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

  /** The `::after` text (the trigger's " ▾"), or '' when there is none. */
  function afterText(btn) {
    const content = getComputedStyle(btn, '::after').content;
    const match = /^"(.*)"$/s.exec(content || '');
    return match ? match[1].replace(/\\(.)/g, '$1') : '';
  }

  /** The widest resting label's full button width, in CSS pixels. */
  function widestRestingLabel() {
    const box = document.createElement('div');
    box.className = 'toolbar-measure';
    box.setAttribute('aria-hidden', 'true');
    const probes = buttons.map((btn) => {
      const style = getComputedStyle(btn);
      const probe = document.createElement('span');
      for (const prop of COPIED) probe.style[prop] = style[prop];
      probe.style.borderLeftStyle = 'solid';
      probe.style.borderRightStyle = 'solid';
      probe.textContent = restingLabels.get(btn) + afterText(btn);
      box.append(probe);
      return probe;
    });
    document.body.append(box);
    let widest = 0;
    for (const probe of probes) widest = Math.max(widest, probe.getBoundingClientRect().width);
    box.remove();
    return widest;
  }

  let applied = null;

  /** Measures and writes `--toolbar-cell-min`; a no-op on phones, where the toolbar is not a grid. */
  function fit() {
    if (mobileMedia.matches) return;
    const widest = widestRestingLabel();
    if (!(widest > 0)) return;
    // Rounded up to a whole pixel, so a fractional text width never clips by a sliver.
    const px = `${Math.ceil(widest)}px`;
    if (px === applied) return;
    applied = px;
    toolbar.style.setProperty('--toolbar-cell-min', px);
  }

  fit();

  if (document.fonts) {
    document.fonts.ready.then(fit);
    document.fonts.addEventListener('loadingdone', fit);
  }
  mobileMedia.addEventListener('change', fit);
  // Zoom fires a resize; text widths can shift with it under font hinting.
  let resizeTimer = null;
  window.addEventListener(
    'resize',
    () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(fit, 150);
    },
    { passive: true },
  );
})();
