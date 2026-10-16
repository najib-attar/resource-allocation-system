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
})();
