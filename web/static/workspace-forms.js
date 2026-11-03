"use strict";
// Native POST forms keep their backend fields, validation and redirect behavior.
(() => {
    const selector = ".professor-shell form";
    function reset(form) {
        delete form.dataset.submitting;
        form.removeAttribute("aria-busy");
        form.querySelectorAll("[data-submit-mirror], [data-submit-status]").forEach(node => node.remove());
        form.querySelectorAll("[data-submit-disabled]").forEach(button => {
            button.disabled = false;
            delete button.dataset.submitDisabled;
        });
    }
    document.addEventListener("submit", event => {
        const form = event.target;
        if (!form.matches(selector) || form.method.toLowerCase() !== "post" || event.defaultPrevented) return;
        if (form.dataset.submitting) { event.preventDefault(); return; }
        form.dataset.submitting = "true";
        form.setAttribute("aria-busy", "true");
        const submitter = event.submitter;
        if (submitter?.name) {
            const mirror = document.createElement("input");
            mirror.type = "hidden"; mirror.name = submitter.name; mirror.value = submitter.value;
            mirror.dataset.submitMirror = "true"; form.append(mirror);
        }
        form.querySelectorAll("button:not([type]),button[type=submit],input[type=submit]").forEach(button => {
            if (!button.disabled) { button.dataset.submitDisabled = "true"; button.disabled = true; }
        });
        const status = document.createElement("p");
        status.dataset.submitStatus = "true"; status.setAttribute("role", "status");
        status.textContent = "Submitting…"; form.append(status);
    });
    window.addEventListener("pageshow", () => document.querySelectorAll(selector).forEach(reset));
})();
