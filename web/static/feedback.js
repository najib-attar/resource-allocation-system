"use strict";
(() => {
    const form = document.getElementById('feedback-form');
    if (!form) return;
    const resource = form.elements.resourceId;
    const category = form.elements.category;
    const urgent = form.elements.urgent;
    const help = document.getElementById('feedback-eligibility');
    function update() {
        const completed = resource.selectedOptions[0]?.dataset.completed === 'true';
        for (const option of category.options) option.disabled = option.value !== 'problem' && !completed;
        if (!completed) category.value = 'problem';
        urgent.disabled = category.value !== 'problem';
        if (urgent.disabled) urgent.checked = false;
        help.textContent = completed ?
            'Use completed or return verified. You may report a problem, suggest an improvement or give general feedback.' :
            'This resource is in active use. Problem reports are available; improvements and general feedback require completed use or verified return.';
    }
    resource.addEventListener('change', update);
    category.addEventListener('change', update);
    update();
})();
