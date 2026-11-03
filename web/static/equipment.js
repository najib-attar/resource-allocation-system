(() => {
    'use strict';
    const faculty = document.getElementById('equipment-faculty');
    if (!faculty) return;
    const update = () => {
        document.querySelectorAll('[data-equipment-faculty]').forEach(card => {
            const matches = card.dataset.equipmentFaculty === faculty.value;
            card.hidden = Boolean(faculty.value) && !matches;
            card.querySelectorAll('input').forEach(input => { input.disabled = !matches; });
        });
    };
    faculty.addEventListener('change', update);
    update();
    const form = document.getElementById('equipment-borrow-form');
    const waitingButton = form.querySelector('button[value=wait]');
    const waitingReason = document.getElementById('equipment-waiting-reason');
    function updateWaiting() {
        const weekly = form.elements.reservationMode.value === 'weekly';
        waitingButton.disabled = weekly;
        waitingReason.hidden = !weekly;
        if (weekly) waitingButton.setAttribute('aria-describedby', waitingReason.id);
        else waitingButton.removeAttribute('aria-describedby');
    }
    form.elements.reservationMode.addEventListener('change', updateWaiting);
    updateWaiting();
    // Server-generated recommendations retain entered values and move focus to
    // their real result, including a complete signed recurring preview.
    const result = document.getElementById('equipment-result');
    result?.focus();
    document.getElementById('equipment-borrow-form')?.addEventListener('input', () => {
        if (!result) return;
        const preview = document.querySelector('[name=previewToken]');
        if (preview) preview.value = '';
        result.classList.add('is-stale');
        result.querySelector('h2').textContent = 'Selection changed. Check equipment and alternatives again.';
    });
})();
