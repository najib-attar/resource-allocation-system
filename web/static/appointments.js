"use strict";

const form = document.getElementById("appointment-form");
const faculty = document.getElementById("faculty");
faculty.addEventListener("change", () => {
    document.querySelectorAll(".professor-option").forEach(option => {
        const visible = option.dataset.faculty === faculty.value;
        option.hidden = !visible;
        const input = option.querySelector("input");
        input.disabled = !visible;
        if (!visible) input.checked = false;
    });
});
document.getElementById("find-times").addEventListener("click", async event => {
    const button = event.currentTarget;
    const message = document.getElementById("times-message");
    const list = document.getElementById("times-list");
    button.disabled = true;
    list.replaceChildren();
    message.textContent = "Checking mandatory calendars...";
    try {
        const response = await fetch(button.dataset.url, {method: "POST", body: new FormData(form)});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Availability could not be checked.");
        message.textContent = result.reason;
        result.items.forEach(item => {
            const choice = document.createElement("button");
            choice.type = "button";
            choice.className = "appointment-choice";
            choice.textContent = `${item.label} - ${item.availableInvitees.length} invited students free`;
            choice.addEventListener("click", () => {
                document.getElementById("appointment-start").value = item.localStart;
                message.textContent = `Selected ${item.label}. ${item.reason}`;
            });
            list.append(choice);
        });
    } catch (error) {
        message.textContent = error.message;
    } finally {
        button.disabled = false;
    }
});
