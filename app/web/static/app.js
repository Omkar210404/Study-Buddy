// Study Buddy: theme toggle, card flip and keyboard shortcuts. Everything else is HTML and HTMX.
(function () {
  "use strict";

  var root = document.documentElement;

  function currentTheme() {
    if (root.dataset.theme) return root.dataset.theme;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function paintToggle() {
    var toggle = document.getElementById("theme-toggle");
    if (toggle) toggle.textContent = currentTheme() === "dark" ? "Light mode" : "Dark mode";
  }

  function stage() {
    return document.getElementById("stage");
  }

  function visible(element) {
    return element && !element.disabled && !element.closest("[hidden]");
  }

  // Show the back of the card and the rating buttons.
  function reveal() {
    var area = stage();
    if (!area) return;
    area.querySelectorAll("[data-back]").forEach(function (element) { element.hidden = false; });
    area.querySelectorAll("[data-front-only]").forEach(function (element) { element.hidden = true; });
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("#theme-toggle")) {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem("theme", next); } catch (error) { /* private window: keep it for this page only */ }
      paintToggle();
      return;
    }
    if (event.target.closest("[data-flip]")) reveal();
  });

  // Space flips. 1-4 rate a card or pick a quiz option. Enter goes to the next question.
  document.addEventListener("keydown", function (event) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    var target = event.target;
    var tag = (target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable) return;
    var area = stage();
    if (!area) return;

    if (event.key === " " || event.code === "Space") {
      if (tag === "button" || tag === "a") return; // let the focused control do its own thing
      var flip = area.querySelector("[data-flip]");
      if (visible(flip)) {
        event.preventDefault();
        reveal();
      }
      return;
    }
    if (/^[1-4]$/.test(event.key)) {
      var choice = area.querySelector('[data-key="' + event.key + '"]');
      if (visible(choice)) {
        event.preventDefault();
        choice.click();
      }
      return;
    }
    if (event.key === "Enter" && tag !== "button" && tag !== "a") {
      var next = area.querySelector("[data-next]");
      if (visible(next)) {
        event.preventDefault();
        next.click();
      }
    }
  });

  // After a new question arrives, put the cursor in the answer field.
  document.addEventListener("htmx:afterSwap", function () {
    var area = stage();
    var field = area && area.querySelector("[data-autofocus]");
    if (field) field.focus();
  });

  document.addEventListener("DOMContentLoaded", function () {
    paintToggle();
    var area = stage();
    var field = area && area.querySelector("[data-autofocus]");
    if (field) field.focus();
  });
})();
