"use strict";
(() => {
    const root = document.querySelector("[data-notifications]");
    if (!root) return;
    const toggle = root.querySelector(".notification-toggle");
    const panel = root.querySelector(".notification-panel");
    const badge = root.querySelector(".notification-badge");
    const status = root.querySelector(".notification-status");
    const content = root.querySelector("[data-notification-content]");
    const markAll = root.querySelector("[data-mark-all]");
    let boundary = 0;
    let loading = false;
    async function load() {
        if (loading) return;
        loading = true;
        try {
            const response = await fetch(root.dataset.feedUrl, {headers: {Accept: "application/json"}, cache: "no-store"});
            if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) throw new Error();
            const data = await response.json();
            // Same-origin fragment uses the shared, autoescaped Jinja notification partial.
            content.innerHTML = data.html;
            boundary = data.throughId;
            badge.textContent = data.unreadCount > 99 ? "99+" : String(data.unreadCount);
            badge.hidden = data.unreadCount === 0;
            toggle.setAttribute("aria-label", `Notifications, ${data.unreadCount} unread`);
            status.textContent = data.unreadCount ? `${data.unreadCount} unread updates` : "You are all caught up.";
            markAll.disabled = data.unreadCount === 0;
        } catch {
            status.textContent = "Notifications are temporarily unavailable. Refresh to retry.";
            badge.hidden = true;
            markAll.disabled = true;
            toggle.setAttribute("aria-label", "Notifications temporarily unavailable");
        } finally { loading = false; }
    }
    async function read(values) {
        const response = await fetch(root.dataset.readUrl, {method: "POST", body: new URLSearchParams(values),
            headers: {Accept: "application/json", "X-CSRF-Token": root.dataset.csrf}});
        if (!response.ok) throw new Error("Could not save notification read status.");
    }
    toggle.addEventListener("click", () => {
        panel.hidden = !panel.hidden;
        toggle.setAttribute("aria-expanded", String(!panel.hidden));
        if (!panel.hidden) load();
    });
    markAll.addEventListener("click", async () => {
        markAll.disabled = true;
        try { await read({throughId: String(boundary)}); await load(); }
        catch (error) { status.textContent = error.message; markAll.disabled = false; }
    });
    document.addEventListener("click", event => {
        if (!root.contains(event.target)) { panel.hidden = true; toggle.setAttribute("aria-expanded", "false"); }
    });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && !panel.hidden) { panel.hidden = true; toggle.setAttribute("aria-expanded", "false"); toggle.focus(); }
    });
    document.addEventListener("click", async event => {
        const link = event.target.closest("a[data-notification-id]");
        if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
        event.preventDefault();
        try { await read({id: link.dataset.notificationId}); }
        catch { /* Opening a permitted request must not depend on read-state persistence. */ }
        window.location.assign(link.href);
    });
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(); });
    window.addEventListener("focus", load);
    window.setInterval(() => { if (document.visibilityState === "visible") load(); }, 60000);
    load();
})();
