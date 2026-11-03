"use strict";
document.querySelectorAll('[data-recurrence]').forEach(section => {
    const select = section.querySelector('[name=reservationMode]');
    const fields = section.querySelector('[data-weekly-fields]');
    // Rooms take their recurring start from the weekly fields. Equipment still
    // uses pickup/due to derive each occurrence's duration, so leave those alone.
    const oneTimeStart = section.closest('form').querySelector('[data-one-time-start]');
    function update() {
        const weekly = select.value === 'weekly';
        fields.hidden = !weekly;
        if (oneTimeStart) {
            oneTimeStart.hidden = weekly;
            oneTimeStart.querySelector('input').disabled = weekly;
        }
        fields.querySelectorAll('input,select').forEach(input => {
            input.disabled = !weekly;
            input.required = weekly && input.type !== 'checkbox';
        });
    }
    select.addEventListener('change', update);
    update();
});
