// Small enhancements only; every page works without this file.
(function () {
  "use strict";

  // Stop a double tap from sending a form twice. The server is idempotent anyway,
  // but a second tap shouldn't produce a confusing second result page.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form.dataset.submitting === "true") {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = "true";
    // Disable after this tick so the clicked button's name/value is still sent.
    window.setTimeout(function () {
      form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (btn) {
        if (!btn.disabled) {
          btn.disabled = true;
          btn.dataset.autoDisabled = "true";
        }
      });
    }, 0);
  });

  // A page restored with the Back button should have working buttons again,
  // but buttons that were disabled on purpose (e.g. a full shift) stay disabled.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-submitting]").forEach(function (form) {
      delete form.dataset.submitting;
    });
    document.querySelectorAll("[data-auto-disabled]").forEach(function (btn) {
      btn.disabled = false;
      delete btn.dataset.autoDisabled;
    });
  });

  // "Show PIN" button next to each PIN box, because typing blind is hard.
  document.querySelectorAll('input[data-show-pin="true"]').forEach(function (input) {
    var row = document.createElement("div");
    row.className = "pin-row";
    input.parentNode.insertBefore(row, input);
    row.appendChild(input);
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--secondary";
    button.textContent = "Show PIN";
    button.setAttribute("aria-pressed", "false");
    button.setAttribute("aria-controls", input.id);
    button.addEventListener("click", function () {
      var showing = input.type === "text";
      input.type = showing ? "password" : "text";
      button.textContent = showing ? "Show PIN" : "Hide PIN";
      button.setAttribute("aria-pressed", showing ? "false" : "true");
    });
    row.appendChild(button);
  });
})();
