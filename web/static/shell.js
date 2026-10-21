"use strict";
(() => {
    const sidebar = document.getElementById("app-sidebar");
    const toggle = document.querySelector("[data-navigation-toggle]");
    const close = document.querySelector("[data-navigation-close]");
    const backdrop = document.querySelector("[data-navigation-backdrop]");
    if (!sidebar || !toggle) return;
    const mobile = window.matchMedia("(max-width: 1050px)");
    let previousFocus;
    function setOpen(open, restore = true) {
        const drawer = mobile.matches;
        if (drawer && open) previousFocus = document.activeElement;
        sidebar.hidden = drawer && !open;
        toggle.setAttribute("aria-expanded", String(drawer && open));
        backdrop.hidden = !drawer || !open;
        document.body.classList.toggle("navigation-open", drawer && open);
        document.querySelector(".app-workspace").inert = drawer && open;
        if (drawer && open) {
            sidebar.setAttribute("role", "dialog");
            sidebar.setAttribute("aria-modal", "true");
            close.focus();
        } else {
            sidebar.removeAttribute("role");
            sidebar.removeAttribute("aria-modal");
            if (drawer && restore && previousFocus) previousFocus.focus();
        }
    }
    function resize() {
        toggle.hidden = !mobile.matches;
        close.hidden = !mobile.matches;
        setOpen(false, false);
    }
    toggle.addEventListener("click", () => setOpen(true));
    close.addEventListener("click", () => setOpen(false));
    backdrop.addEventListener("click", () => setOpen(false));
    sidebar.addEventListener("keydown", event => {
        if (!mobile.matches || sidebar.hidden) return;
        if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
        if (event.key === "Tab") {
            const links = [...sidebar.querySelectorAll("a, button, summary")].filter(node => !node.hidden && node.getClientRects().length);
            const first = links[0], last = links[links.length - 1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
    });
    const account = document.querySelector("[data-account-menu]");
    document.addEventListener("click", event => { if (account && !account.contains(event.target)) account.open = false; });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && account?.open) { account.open = false; account.querySelector("summary").focus(); }
    });
    mobile.addEventListener("change", resize);
    resize();
})();
