/**
 * Era band labels that stay inside the plot (999.5-19, D-15/D-16).
 *
 * A label anchors left at its band start; when its measured text would run
 * past the plot's right edge it anchors right at the plot edge instead, and
 * a label wider than the whole plot is cut with an ellipsis.
 */
let measureCtx = null;

function textWidth(text, size, family) {
  if (!measureCtx) measureCtx = document.createElement('canvas').getContext('2d');
  measureCtx.font = `${size}px ${family}`;
  return measureCtx.measureText(text).width;
}

/** Returns { text, x, xanchor, xshift } for one band label (text is plain, unescaped). */
export function placeEraLabel(text, x0, range, plotPx, size) {
  const family = getComputedStyle(document.body).fontFamily;
  const pad = 6;
  const max = Math.max(plotPx - pad * 2, 20);
  let label = text;
  if (textWidth(label, size, family) > max) {
    let end = label.length;
    while (end > 1 && textWidth(label.slice(0, end) + '…', size, family) > max) end -= 1;
    label = label.slice(0, end) + '…';
  }
  const w = textWidth(label, size, family);
  const x0px = ((x0 - range[0]) / (range[1] - range[0])) * plotPx;
  if (x0px + 4 + w <= plotPx - 2) return { text: label, x: x0, xanchor: 'left', xshift: 4 };
  return { text: label, x: range[1], xanchor: 'right', xshift: -4 };
}

/**
 * Places every band label, then drops any whose box would touch the previous
 * kept one (4px gap), going left to right. `bands` is [{ text, x0 }]; returns
 * one placement (or null when dropped) per band, in the same order.
 */
export function placeEraLabels(bands, range, plotPx, size) {
  const family = getComputedStyle(document.body).fontFamily;
  const placed = bands.map((b, i) => {
    const pos = placeEraLabel(b.text, b.x0, range, plotPx, size);
    const w = textWidth(pos.text, size, family);
    const left = pos.xanchor === 'left'
      ? ((b.x0 - range[0]) / (range[1] - range[0])) * plotPx + pos.xshift
      : plotPx + pos.xshift - w;
    return { i, pos, left, right: left + w };
  });
  placed.sort((a, b) => a.left - b.left);
  const out = new Array(bands.length).fill(null);
  let edge = -Infinity;
  for (const p of placed) {
    if (p.left < edge + 4) continue;
    out[p.i] = p.pos;
    edge = p.right;
  }
  return out;
}

/** One caption line under the plot naming every era (textContent only). */
export function setEraCaption(host, labels, show) {
  for (const old of host.querySelectorAll('.nfl-era-caption')) old.remove();
  if (!show || !labels.length) return;
  const p = document.createElement('p');
  p.className = 'nfl-era-caption';
  p.textContent = `Measurement eras: ${labels.join(' · ')}`;
  host.appendChild(p);
}
