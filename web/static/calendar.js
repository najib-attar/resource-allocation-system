"use strict";
// Native Tab scrolling can leave an inline day link partly clipped by the
// timetable's horizontal scrollport. Reveal its complete focus indicator.
document.querySelectorAll(".calendar-table-scroll").forEach(scrollport => {
    scrollport.addEventListener("focusin", event => {
        if (event.target === scrollport) return;
        const target = event.target.getBoundingClientRect();
        const bounds = scrollport.getBoundingClientRect();
        const left = bounds.left + scrollport.clientLeft + 6;
        const right = bounds.left + scrollport.clientLeft + scrollport.clientWidth - 6;
        if (target.width > right - left) return;
        if (target.left < left) scrollport.scrollLeft += target.left - left;
        else if (target.right > right) scrollport.scrollLeft += target.right - right;
    });
});
