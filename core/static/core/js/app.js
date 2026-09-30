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
})();
