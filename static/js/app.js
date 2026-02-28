// Delete confirmation modal
document.addEventListener('DOMContentLoaded', function () {
    const deleteModal = document.getElementById('deleteModal');
    if (deleteModal) {
        deleteModal.addEventListener('show.bs.modal', function (event) {
            const button = event.relatedTarget;
            const resourceId = button.getAttribute('data-resource-id');
            const deleteUrl = button.getAttribute('data-delete-url');
            const resourceType = button.getAttribute('data-resource-type') || 'resource';

            deleteModal.querySelector('.resource-id-display').textContent = resourceId;
            deleteModal.querySelector('.resource-type-display').textContent = resourceType;
            deleteModal.querySelector('form').setAttribute('action', deleteUrl);
            deleteModal.querySelector('input[name="confirm"]').value = '';
        });
    }

    // Auto-refresh sync log
    const syncLog = document.getElementById('syncLogContainer');
    if (syncLog && syncLog.dataset.autoRefresh === 'true') {
        setInterval(function () {
            fetch('/sync/log')
                .then(r => r.json())
                .then(entries => {
                    if (!entries.length) return;
                    let html = '';
                    entries.forEach(e => {
                        const cls = e.level === 'ERROR' ? 'log-error' :
                                    e.level === 'WARNING' ? 'log-warning' : 'log-info';
                        html += '<div class="' + cls + '">' +
                                e.timestamp + ' [' + e.level + '] ' + e.message +
                                '</div>';
                    });
                    syncLog.innerHTML = html;
                    syncLog.scrollTop = syncLog.scrollHeight;
                })
                .catch(() => {});
        }, 5000);
    }
});
