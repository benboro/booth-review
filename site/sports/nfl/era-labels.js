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
