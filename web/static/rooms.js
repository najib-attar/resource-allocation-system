"use strict";
const form = document.getElementById("room-request-form");
const message = document.getElementById("room-message");
const candidates = document.getElementById("room-candidates");
const alternatives = document.getElementById("room-alternatives");
const room = document.getElementById("selected-room");
const selection = document.getElementById("room-selection");
const submit = document.getElementById("submit-room");
const refresh = document.getElementById("find-rooms");
let controller, timer;
let sequence = 0;

function invalidate() {
    sequence += 1;
    controller?.abort();
    clearTimeout(timer);
    room.value = "";
    submit.disabled = true;
    refresh.disabled = false;
    candidates.replaceChildren();
    const waiting = document.getElementById("room-waiting-option");
    if (waiting) waiting.hidden = true;
    alternatives.replaceChildren();
    selection.textContent = "No room selected.";
}

function choose(value, button) {
    candidates.querySelectorAll("button").forEach(item => item.setAttribute("aria-pressed", "false"));
    button.setAttribute("aria-pressed", "true");
    room.value = value.roomId;
    submit.disabled = false;
    selection.textContent = `Selected: ${value.name}, ${value.facultyName}. ${value.localStart.replace("T", " ")} to ${value.localEnd.replace("T", " ")}.`;
}

async function load() {
    invalidate();
    if (!form.checkValidity()) {
        message.textContent = "Enter your purpose, attendee count, date/time and duration.";
        return;
    }
    const current = sequence;
    controller = new AbortController();
    refresh.disabled = true;
    message.textContent = "Checking policies and academic, appointment and room commitments...";
    try {
        const response = await fetch(form.dataset.url, {method: "POST", body: new FormData(form), signal: controller.signal});
        if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("Could not check rooms. Check sign-in, database migrations and engine setup, then retry.");
        const result = await response.json();
        if (current !== sequence) return;
        if (!response.ok) throw new Error(result.error || "Room evaluation failed.");
        message.textContent = result.candidates.length ? "Review the recommended room or choose another eligible candidate." : result.messages.join(" ") || "No eligible room was found.";
        const waiting = document.getElementById("room-waiting-option");
        if (waiting) waiting.hidden = result.candidates.length > 0;
        result.candidates.forEach((value, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "room-candidate";
            button.setAttribute("aria-pressed", "false");
            const heading = document.createElement("strong");
            heading.textContent = `${index === 0 ? "Recommended: " : "Alternative: "}${value.name}`;
            const description = document.createElement("span");
            description.textContent = `${value.type} | ${value.building} | ${value.facultyName} | ${value.capacity} seats`;
            const reason = document.createElement("small");
            reason.textContent = value.reason;
            button.append(heading, description, reason);
            button.addEventListener("click", () => choose(value, button));
            candidates.append(button);
            if (index === 0) choose(value, button);
        });
        if (result.alternatives.length) {
            const title = document.createElement("h3");
            title.textContent = "Feasible alternative times";
            alternatives.append(title);
            result.alternatives.forEach(value => {
                const button = document.createElement("button");
                button.type = "button";
                button.textContent = `${value.localStart.replace("T", " ")} - ${value.localEnd.replace("T", " ")}: ${value.name}`;
                button.addEventListener("click", () => {
                    form.elements.start.value = value.localStart;
                    load();
                });
                alternatives.append(button);
            });
        }
    } catch (error) {
        if (current === sequence && error.name !== "AbortError") message.textContent = error.message;
    } finally {
        if (current === sequence) refresh.disabled = false;
    }
}

form.querySelectorAll("input:not([type=hidden]):not([type=search]),select,textarea").forEach(input => input.addEventListener("input", () => {
    if (input.closest('#room-waiting-option')) return;
    invalidate();
    message.textContent = "Requirements changed; checking updated candidates...";
    if (form.checkValidity()) timer = setTimeout(load, 300);
}));
document.getElementById("room-professor-search").addEventListener("input", event => {
    const query = event.target.value.trim().toLocaleLowerCase();
    event.target.closest(".participant-picker").querySelectorAll(".picker-option").forEach(option => { option.hidden = !option.textContent.toLocaleLowerCase().includes(query); });
});
refresh.addEventListener("click", load);
form.addEventListener("submit", event => {
    if (event.submitter?.value === "wait") {
        if (!form.elements.waitingFaculty.value || !form.elements.acceptWaiting.checked) {
            event.preventDefault();
            message.textContent = "Choose an owning faculty and explicitly accept the waiting-list policy.";
        }
        return;
    }
    if (!room.value) { event.preventDefault(); message.textContent = "Review a verified room candidate first."; }
});
if (form.checkValidity()) load();
