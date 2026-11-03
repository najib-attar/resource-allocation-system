"use strict";
(() => {
    const form = document.querySelector("[data-academic-form]");
    if (!form) return;
    const resource = form.querySelector("[data-resource-select]");
    const summary = form.querySelector("[data-resource-summary]");
    function showResource() {
        const option = resource.selectedOptions[0];
        summary.hidden = !option?.value;
        if (!option?.value) return;
        const data = option.dataset;
        summary.textContent = `${data.name} · ${data.type} · Capacity ${data.capacity} · Building: ${data.building || "Not specified"} · Facilities: ${data.features || "None recorded"} · ${data.available === "true" ? "In service" : "Out of service"}. This is not a reservation.`;
    }
    resource.addEventListener("change", showResource); showResource();
    const helper = form.querySelector("[data-weekly-helper]");
    if (helper) {
        helper.hidden = false;
        helper.querySelector("[data-add-slot]").addEventListener("click", () => {
            const day = helper.querySelector("[data-slot-day]").value;
            const start = helper.querySelector("[data-slot-start]").value;
            const end = helper.querySelector("[data-slot-end]").value.trim();
            const status = helper.querySelector("[data-slot-status]");
            if (!start || !end) { status.textContent = "Choose a weekday, start and end time before adding a slot."; return; }
            const field = form.elements.timeData;
            field.value = [field.value.trim(),`${day}-${start}-${end}`].filter(Boolean).join(";");
            status.textContent = "Weekly slot added. Review the list before submitting; scheduling constraints are checked by the service.";
            field.dispatchEvent(new Event("input", {bubbles:true}));
        });
    }
    const search = form.querySelector("[data-participant-search]");
    if (search) {
        const rows = [...form.querySelectorAll("[data-participant-row]")];
        function filter() {
            const term = search.value.trim().toLocaleLowerCase();
            let selected = 0, visible = 0;
            for (const row of rows) {
                const checked = row.querySelector('[type="checkbox"]').checked;
                if (checked) selected++;
                row.hidden = !checked && !row.textContent.toLocaleLowerCase().includes(term);
                if (!row.hidden) visible++;
            }
            form.querySelector("[data-participant-count]").textContent = `(${selected} selected)`;
            form.querySelector("[data-participant-status]").textContent = `${visible} participants shown. Selected participants remain visible.`;
        }
        search.addEventListener("input", filter);
        form.addEventListener("change", filter); filter();
    }
})();
