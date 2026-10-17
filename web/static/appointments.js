"use strict";

const form = document.getElementById("appointment-form");
const faculty = document.getElementById("faculty");
const date = document.getElementById("appointment-date");
const duration = form.elements.duration;
const refresh = document.getElementById("find-times");
const message = document.getElementById("times-message");
const list = document.getElementById("times-list");
const start = document.getElementById("appointment-start");
const selected = document.getElementById("selected-time");
const submit = document.getElementById("submit-appointment");
const manual = document.getElementById("manual-time");
const validation = document.getElementById("appointment-validation");
let controller;
let sequence = 0;
let debounce;

function feedback(text, error = false) {
    message.textContent = text;
    message.setAttribute("role", error ? "alert" : "status");
    message.closest(".booking-times-state")?.classList.toggle("is-error", error);
}

function showValidation() {
    if (!validation) return;
    const errors = [...form.elements].filter(field => field.willValidate && !field.validity.valid);
    const items = validation.querySelector("ul");
    items.replaceChildren();
    errors.forEach(field => {
        field.setAttribute("aria-invalid", "true");
        const item = document.createElement("li");
        const label = field.labels?.[0]?.textContent.trim().replace(/\s+/g, " ") || field.name;
        item.textContent = `${label}: ${field.validationMessage}`;
        items.append(item);
    });
    validation.hidden = errors.length === 0;
}

function ready() {
    return faculty.value && form.querySelector('[name="professorIds"]:checked') &&
        date.value && date.validity.valid && duration.validity.valid;
}

function invalidate() {
    sequence += 1;
    controller?.abort();
    clearTimeout(debounce);
    start.value = "";
    selected.textContent = "No time selected.";
    selected.classList.remove("is-selected");
    submit.disabled = true;
    refresh.disabled = false;
    list.replaceChildren();
    list.setAttribute("aria-busy", "false");
}

function updatePickers() {
    form.querySelectorAll(".participant-picker").forEach(picker => {
        const query = picker.querySelector(".picker-search").value.trim().toLocaleLowerCase();
        const choices = [...picker.querySelectorAll(".picker-option")];
        choices.forEach(option => {
            const input = option.querySelector("input");
            const eligible = !option.dataset.faculty || option.dataset.faculty === faculty.value;
            input.disabled = !eligible;
            if (!eligible) input.checked = false;
            option.hidden = !eligible || !option.textContent.toLocaleLowerCase().includes(query);
        });
        const chosen = choices.filter(option => option.querySelector("input").checked);
        picker.querySelector(".picker-count").textContent = `${chosen.length} selected`;
        picker.querySelector(".picker-hint").textContent = picker.dataset.picker === "professorIds" && !faculty.value ?
            "Select a faculty first." : choices.some(option => !option.hidden) ?
                (picker.dataset.picker === "professorIds" ? "All selected professors must approve." : "Invitations are optional.") : "No matching people.";
        const chips = form.querySelector(`[data-selected="${picker.dataset.picker}"]`);
        chips.replaceChildren();
        chosen.forEach(option => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "participant-chip";
            const name = option.querySelector("strong").textContent;
            button.textContent = `${name} \u00d7`;
            button.setAttribute("aria-label", `Remove ${name}`);
            button.addEventListener("click", () => {
                option.querySelector("input").checked = false;
                changed();
            });
            chips.append(button);
        });
    });
}

async function loadTimes() {
    invalidate();
    if (!ready()) {
        feedback("Choose a faculty, at least one professor, a duration and one date.");
        return;
    }
    const current = sequence;
    controller = new AbortController();
    refresh.disabled = true;
    list.setAttribute("aria-busy", "true");
    feedback("Checking your calendar and required professors' availability...");
    const data = new FormData(form);
    if (manual.value) data.set("preferredStart", `${date.value}T${manual.value}`);
    try {
        const response = await fetch(refresh.dataset.url, {method: "POST", body: data, signal: controller.signal});
        if (!response.headers.get("content-type")?.includes("application/json")) {
            throw new Error("Availability could not be loaded. Check your sign-in and retry shortly.");
        }
        const result = await response.json();
        if (current !== sequence) return;
        if (!response.ok) throw new Error(result.error || "Availability could not be checked.");
        feedback(result.items.length ?
            "Choose a time. Suggestions are ranked by invited-student availability, your preferred time, then earliest start." : result.reason);
        result.items.forEach(item => {
            const choice = document.createElement("button");
            choice.type = "button";
            choice.className = "appointment-choice";
            choice.setAttribute("aria-pressed", "false");
            choice.textContent = item.label.slice(11);
            choice.title = item.reason;
            choice.addEventListener("click", () => {
                list.querySelectorAll("button").forEach(button => button.setAttribute("aria-pressed", "false"));
                choice.setAttribute("aria-pressed", "true");
                start.value = item.localStart;
                manual.value = "";
                selected.textContent = `Selected: ${item.label}. ${item.reason}`;
                selected.classList.add("is-selected");
                submit.disabled = false;
            });
            list.append(choice);
        });
    } catch (error) {
        if (current === sequence && error.name !== "AbortError") feedback(error.message, true);
    } finally {
        if (current === sequence) {
            refresh.disabled = false;
            list.setAttribute("aria-busy", "false");
        }
    }
}

function changed() {
    invalidate();
    manual.value = "";
    updatePickers();
    feedback(ready() ? "Updating available times..." : "Choose a faculty and professors to see available times.");
    if (ready()) debounce = setTimeout(loadTimes, 200);
}

faculty.addEventListener("change", changed);
date.addEventListener("change", changed);
duration.addEventListener("input", changed);
form.querySelectorAll('.participant-picker input[type="checkbox"]').forEach(input => input.addEventListener("change", changed));
form.querySelectorAll(".picker-search").forEach(input => input.addEventListener("input", updatePickers));
refresh.addEventListener("click", loadTimes);
manual.addEventListener("input", () => {
    invalidate();
    if (ready() && manual.value && manual.validity.valid) {
        start.value = `${date.value}T${manual.value}`;
        selected.textContent = `Proposed: ${date.value} ${manual.value}. Availability will be validated on submission.`;
        selected.classList.add("is-selected");
        submit.disabled = false;
    }
});
form.addEventListener("submit", event => {
    if (!ready() || !start.value) {
        event.preventDefault();
        feedback("Select an available time or enter a proposal before submitting.", true);
        message.scrollIntoView({block: "center"});
    }
});
form.addEventListener("invalid", showValidation, true);
form.addEventListener("input", event => {
    if (event.target.validity?.valid) event.target.removeAttribute("aria-invalid");
    if (validation && !validation.hidden) showValidation();
});
updatePickers();
