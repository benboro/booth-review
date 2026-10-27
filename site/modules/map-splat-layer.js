/**
 * Splat raster layer for one Plotly map element (Phase 11 D-06, factored out of
 * map-panel.js so a second map can own its own layer).
 *
 * Each layer holds its own render token, live image URL and queue of layout changes.
 * paintSplat shares module-level typed buffers, so callers must not run two maps'
 * paints at once; only one map is mounted at a time.
 */

/**
 * @param {HTMLElement} gd the Plotly graph div
 * @param {{imageSpec: (url: string) => object, landFill: (theme: string) => string,
 *   onFail?: (err: unknown) => void}} opts
 */
export function createSplatLayer(gd, { imageSpec, landFill, onFail }) {
  let token = 0;
  let currentImageUrl = null;
  let currentSpec = null;
  let count = 0;
  /** Tail of the queued raster layout changes (see serialLayout). */
  let layoutChain = Promise.resolve();

  /**
   * Runs one raster layout change after every earlier one has settled, so a slow older
   * relayout can never land on top of a newer render's layout. Failures do not break the chain.
   */
  function serialLayout(task) {
    const run = layoutChain.then(task, task);
    layoutChain = run.catch(() => {});
    return run;
  }

  /** Drops the live raster (if any) from the layout and revokes its blob URL. */
  async function clear() {
    token += 1;
    // Decided when the turn comes: an in-flight paint has registered its image by then.
    await serialLayout(async () => {
      if (!currentImageUrl) return;
      const url = currentImageUrl;
      currentImageUrl = null;
      currentSpec = null;
      try {
        await window.Plotly.relayout(gd, { images: [] });
      } finally {
        URL.revokeObjectURL(url);
      }
    });
  }

  /** Falls back to the plain land fill after a failed raster. */
  function failed(err, theme, mine) {
    onFail?.(err);
    currentSpec = null;
    const url = currentImageUrl;
    currentImageUrl = null;
    // Queued behind every other layout change; a newer render (token) owns the image and the
    // fill by the time this runs, so it only revokes the blob it was holding.
    serialLayout(async () => {
      if (mine === token) {
        try {
          await window.Plotly.restyle(gd, { fill: 'toself', fillcolor: landFill(theme) }, [0]);
        } catch {
          // The relayout below still clears the image.
        }
        if (mine === token) {
          try {
            await window.Plotly.relayout(gd, { images: [] });
          } catch {
            // Nothing more to fall back on.
          }
        }
      }
      if (url) URL.revokeObjectURL(url);
    });
  }

  /**
   * Puts one painted raster into the layout. Runs in the serialized queue, so it starts only
   * after every earlier layout change has settled; a render that has overtaken it by then
   * (token) costs only its own blob. The image is registered as live before the relayout so
   * a clear or a newer paint that follows always sees and removes it; the previous image is
   * revoked once this one is in the layout.
   */
  async function apply(mine, blob, theme) {
    const url = URL.createObjectURL(blob);
    if (mine !== token) {
      URL.revokeObjectURL(url);
      return;
    }
    const spec = imageSpec(url);
    const prev = currentImageUrl;
    const prevSpec = currentSpec;
    currentImageUrl = url;
    currentSpec = spec;
    try {
      await window.Plotly.relayout(gd, { images: [spec] });
    } catch (err) {
      if (currentImageUrl === url) {
        currentImageUrl = prev;
        currentSpec = prevSpec;
      }
      URL.revokeObjectURL(url);
      if (mine === token) failed(err, theme, mine);
      return;
    }
    if (prev) URL.revokeObjectURL(prev);
    // A newer render took over while the image went in: it re-applies or removes the image
    // and sets the fill itself, so this one leaves the fill and the shared state alone.
    if (mine !== token) return;
    try {
      await window.Plotly.restyle(gd, { fill: 'none' }, [0]);
    } catch (err) {
      if (mine === token) failed(err, theme, mine);
      return;
    }
    if (mine === token) count += 1;
  }

  /**
   * Paints the splat behind one requestAnimationFrame; the render token discards a paint a
   * newer render has overtaken, and the previous image stays in place until the new one is in.
   * @param {() => Promise<Blob>} paint resolves to the raster blob
   * @param {() => boolean} isCurrent false once the caller has moved on to a newer render
   * @param {string} theme
   */
  function schedule(paint, isCurrent, theme) {
    const mine = ++token;
    requestAnimationFrame(async () => {
      if (mine !== token || !isCurrent()) return;
      try {
        const blob = await paint();
        if (mine !== token) return;
        await serialLayout(() => apply(mine, blob, theme));
      } catch (err) {
        if (mine === token) failed(err, theme);
      }
    });
  }

  /**
   * Invalidates in-flight paints, then (through the serial chain, after any layout change already
   * queued) removes the live raster from the layout before revoking its blob URL, so a later
   * Plotly redraw of the div never shows a dead blob. Resolves once the layout is clean.
   */
  function destroy() {
    token += 1;
    const url = currentImageUrl;
    currentImageUrl = null;
    currentSpec = null;
    if (!url) return Promise.resolve();
    return serialLayout(async () => {
      try {
        // A purged div has no layout left to clean.
        if (gd._fullLayout) await window.Plotly.relayout(gd, { images: [] });
      } catch {
        // The URL is revoked either way.
      } finally {
        URL.revokeObjectURL(url);
      }
    });
  }

  return {
    schedule,
    clear,
    destroy,
    get currentSpec() {
      return currentSpec;
    },
    get count() {
      return count;
    },
  };
}
