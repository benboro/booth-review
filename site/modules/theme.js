/**
 * Theme hook (SHELL-01, SHELL-02): the `data-theme` attribute on <html> is
 * the single source of truth for light/dark. Phase 13 writes it statically
 * ("light"); Phase 17 adds the toggle. No script reads the OS colour scheme.
 *
 * Anything other than the literal "dark" reads as "light", and the value
 * never flows into markup (T-13-05).
 */

/**
 * The current theme, read live from the data-theme attribute.
 * @returns {"light"|"dark"}
 */
export function currentTheme() {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

/**
 * Calls `cb(theme)` whenever the data-theme attribute changes.
 * @param {(theme: "light"|"dark") => void} cb
 * @returns {() => void} disconnect function
 */
export function onThemeChange(cb) {
  const observer = new MutationObserver(() => cb(currentTheme()));
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  });
  return () => observer.disconnect();
}
