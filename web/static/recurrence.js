"use strict";
document.querySelectorAll('[data-recurrence]').forEach(section => {
    const select = section.querySelector('[name=reservationMode]');
    const fields = section.querySelector('[data-weekly-fields]');
    function update() {
        const weekly = select.value === 'weekly';
        fields.hidden = !weekly;
        fields.querySelectorAll('input,select').forEach(input => {
            input.disabled = !weekly;
            input.required = weekly && input.type !== 'checkbox';
        });
    }
    select.addEventListener('change', update);
    update();
});
