"use strict";
const password = document.getElementById("password");
document.getElementById("show-password").addEventListener("change", event => {
    password.type = event.target.checked ? "text" : "password";
});
document.querySelector(".login-error")?.focus();
document.getElementById("login-form").addEventListener("invalid", event => {
    event.target.setAttribute("aria-invalid", "true");
}, true);
document.getElementById("login-form").addEventListener("input", event => {
    if (event.target.validity.valid) event.target.removeAttribute("aria-invalid");
});
