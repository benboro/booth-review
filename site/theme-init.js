(function () {
  var K = 'bl-theme', r = document.documentElement;
  var N = { light: 'Switch to dark theme', dark: 'Switch to light theme' };
  function stored() {
    try { return localStorage.getItem(K) === 'dark' ? 'dark' : 'light'; } catch (e) { return 'light'; }
  }
  function apply(t) {
    if (r.getAttribute('data-theme') !== t) r.setAttribute('data-theme', t);
    var m = document.querySelector('meta[name="color-scheme"]');
    if (m) m.setAttribute('content', t);
    var b = document.getElementById('theme-toggle');
    if (b) { b.setAttribute('aria-label', N[t]); b.title = N[t]; b.hidden = false; }
  }
  apply(stored());
  document.addEventListener('DOMContentLoaded', function () {
    apply(r.getAttribute('data-theme') === 'dark' ? 'dark' : 'light');
  });
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) apply(stored());
  });
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('#theme-toggle');
    if (!b) return;
    var t = r.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    apply(t);
    try { localStorage.setItem(K, t); } catch (x) {}
  });
})();
