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

function feedback(text, error = false) {
    message.textContent = text;
    message.setAttribute('role', error ? 'alert' : 'status');
}

function invalidate() {
    sequence += 1;
    controller?.abort();
    clearTimeout(timer);
    room.value = "";
    submit.disabled = true;
    refresh.disabled = false;
    candidates.replaceChildren();
    candidates.setAttribute('aria-busy', 'false');
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
        feedback("Enter your purpose, attendee count, date/time and duration.", true);
        return;
    }
    const current = sequence;
    controller = new AbortController();
    refresh.disabled = true;
    candidates.setAttribute('aria-busy', 'true');
    feedback("Checking policies and academic, appointment and room commitments...");
    try {
        const response = await fetch(form.dataset.url, {method: "POST", body: new FormData(form), signal: controller.signal});
        if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("Could not check rooms. Check sign-in, database migrations and engine setup, then retry.");
        const result = await response.json();
        if (current !== sequence) return;
        if (!response.ok) throw new Error(result.error || "Room evaluation failed.");
        feedback(result.candidates.length ? "Review the recommended room or choose another eligible candidate." : result.messages.join(" ") || "No eligible room was found.");
        const waiting = document.getElementById("room-waiting-option");
        if (waiting) waiting.hidden = result.candidates.length > 0 || !!result.recurrence;
        if (result.occurrences) {
            const preview = document.createElement('ol');
            preview.setAttribute('aria-label', 'All recurring dates');
            result.occurrences.forEach(period => {
                const li = document.createElement('li');
                li.textContent = `${period.localStart} to ${period.localEnd}: ${period.feasible ? 'Eligible rooms found' : period.messages.join(' ') || period.reasonCode}.`;
                preview.append(li);
            });
            alternatives.append(preview);
            if (!result.feasible) message.textContent += form.elements.approvalMode.value === 'partial'
                ? ' Partial approval is allowed: only selected feasible dates can be confirmed. Review each date.'
                : ' Every required date must be available before the entire series can be confirmed.';
        }
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
            const option = document.createElement('article');
            option.className = 'room-candidate-option';
            const availability = document.createElement('a');
            const address = new URL(form.dataset.availabilityUrl.replace(/0$/, String(value.roomId)), location.origin);
            address.searchParams.set('date', value.localStart.slice(0, 10));
            availability.href = address.href;
            availability.target = '_blank';
            availability.rel = 'noopener';
            availability.textContent = `View ${value.name} busy/free (new tab)`;
            option.append(button, availability);
            candidates.append(option);
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
                    if (result.recurrence) form.elements.recurrenceTime.value = value.localStart.slice(11,16);
                    else form.elements.start.value = value.localStart;
                    load();
                });
                alternatives.append(button);
            });
        }
    } catch (error) {
        if (current === sequence && error.name !== "AbortError") feedback(error.message, true);
    } finally {
        if (current === sequence) { refresh.disabled = false; candidates.setAttribute('aria-busy', 'false'); }
    }
}

form.querySelectorAll("input:not([type=hidden]):not([type=search]),select,textarea").forEach(input => input.addEventListener("input", () => {
    if (input.closest('#room-waiting-option')) return;
    invalidate();
    feedback("Requirements changed; checking updated candidates...");
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
            feedback("Choose an owning faculty and explicitly accept the waiting-list policy.", true);
        }
        return;
    }
    if (!room.value) { event.preventDefault(); feedback("Review a verified room candidate first.", true); }
});
if (form.checkValidity()) load();
