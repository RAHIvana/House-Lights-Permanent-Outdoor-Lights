// The login page: send the password; on success go back to the page that asked for it.
const $ = s => document.querySelector(s);

// Only a path on this site (no "//host", no backslash), and never the login page itself.
const next = (() => {
  const n = new URLSearchParams(location.search).get("next") || "/";
  return /^\/(?![\/\\])/.test(n) && !/^\/login(\?|$)/.test(n) ? n : "/";
})();

$("#form").onsubmit = async e => {
  e.preventDefault();
  $("#go").disabled = true;
  $("#msg").textContent = "";
  try {
    const res = await fetch("/api/login", {method: "POST", headers: {"Content-Type": "application/json"},
                                           body: JSON.stringify({password: $("#pw").value})});
    const data = await res.json().catch(() => ({}));
    if (res.ok) { location.replace(next); return; }
    $("#msg").textContent = data.detail || `HTTP ${res.status}`;
    $("#pw").select();
  } catch (err) {
    $("#msg").textContent = "Could not reach the server.";
  }
  $("#go").disabled = false;
};
