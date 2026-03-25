// Proxy fetch requests from content script to the local backend.
// This avoids mixed-content (HTTPS page -> HTTP localhost) blocking.

browser.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action !== "fetch") return false;

  const opts = { method: msg.method || "GET", headers: {} };
  if (msg.body) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = msg.body;
  }

  fetch(msg.url, opts)
    .then(async (r) => {
      const text = await r.text();
      sendResponse({ ok: r.ok, status: r.status, body: text });
    })
    .catch((e) => {
      sendResponse({ ok: false, status: 0, body: "", error: e.message });
    });

  return true; // keep message channel open for async response
});
