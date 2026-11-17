// Runs first, before the page is drawn, so the remembered light or dark look doesn't flash.
// (A file of its own, not an inline script, so the page's security policy can forbid inline scripts.)
try { const t = localStorage.getItem("hl-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
