"use strict";

// Floating AI greenhouse advisor widget. Talks only to /api/public/advisor.
// History lives in sessionStorage; attribution rides along like the forms.
(function () {
  const KEY = "mgs_advisor_history";

  function history() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || "[]"); } catch (e) { return []; }
  }
  function saveHistory(h) {
    try { sessionStorage.setItem(KEY, JSON.stringify(h.slice(-30))); } catch (e) {}
  }
  function attribution() {
    try { return JSON.parse(sessionStorage.getItem("mgs_attrib") || "{}"); } catch (e) { return {}; }
  }

  // ---- DOM ----
  const launcher = document.createElement("button");
  launcher.id = "adv-launch";
  launcher.type = "button";
  launcher.innerHTML = "🌿 Ask the greenhouse advisor";
  launcher.setAttribute("aria-label", "Open the greenhouse advisor chat");

  const panel = document.createElement("div");
  panel.id = "adv-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Greenhouse advisor chat");
  panel.innerHTML =
    '<div id="adv-head"><b>Greenhouse advisor</b>' +
    '<span class="adv-note">AI assistant — answers come from our real catalog</span>' +
    '<button id="adv-close" type="button" aria-label="Close chat">×</button></div>' +
    '<div id="adv-msgs"></div>' +
    '<form id="adv-form"><input id="adv-input" autocomplete="off" maxlength="2000" ' +
    'placeholder="e.g. What would a 20 ft greenhouse cost?" />' +
    '<button id="adv-send" type="submit">Send</button></form>';

  document.body.appendChild(launcher);
  document.body.appendChild(panel);

  const msgsEl = panel.querySelector("#adv-msgs");
  const inputEl = panel.querySelector("#adv-input");
  const sendEl = panel.querySelector("#adv-send");

  function bubble(role, text) {
    const div = document.createElement("div");
    div.className = "adv-msg adv-" + role;
    div.textContent = text;
    msgsEl.appendChild(div);
    msgsEl.scrollTop = msgsEl.scrollHeight;
    return div;
  }

  function render() {
    msgsEl.innerHTML = "";
    const h = history();
    if (!h.length) {
      bubble("assistant", "Hi! I can help you pick a greenhouse, price any size or layout, and send your configuration to our team. What are you looking to grow?");
    } else {
      h.forEach((m) => bubble(m.role, m.content));
    }
  }

  launcher.addEventListener("click", () => {
    panel.classList.add("open");
    launcher.classList.add("hidden-launch");
    render();
    inputEl.focus();
  });
  panel.querySelector("#adv-close").addEventListener("click", () => {
    panel.classList.remove("open");
    launcher.classList.remove("hidden-launch");
  });

  panel.querySelector("#adv-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = inputEl.value.trim();
    if (!text || sendEl.disabled) return;
    inputEl.value = "";

    const h = history();
    h.push({ role: "user", content: text });
    saveHistory(h);
    bubble("user", text);

    sendEl.disabled = true;
    const typing = bubble("assistant", "…");
    try {
      const res = await fetch("/api/public/advisor", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: h, attribution: attribution() }),
      });
      const data = await res.json();
      typing.remove();
      if (!res.ok) {
        bubble("assistant", data.detail || "Sorry — something went wrong. Please try the quote form.");
      } else {
        h.push({ role: "assistant", content: data.reply });
        saveHistory(h);
        bubble("assistant", data.reply);
      }
    } catch (err) {
      typing.remove();
      bubble("assistant", "Sorry — I couldn't reach the server. Please try again.");
    } finally {
      sendEl.disabled = false;
      inputEl.focus();
    }
  });
})();
