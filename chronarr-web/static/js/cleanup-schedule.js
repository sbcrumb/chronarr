/**
 * Scheduled Cleanup Management for Chronarr Web Interface
 * Add this code to app.js or include as separate script
 */

// ==========================================
// Scheduled Scan/Cleanup Modal Functions
// ==========================================

function openScheduleModal() {
    document.getElementById('schedule-id').value = '';
    document.getElementById('schedule-modal-title').textContent = 'Add New Schedule';
    document.getElementById('schedule-submit-text').textContent = 'Create Schedule';
    document.getElementById('schedule-form').reset();
    document.getElementById('schedule-enabled').checked = true;
    document.getElementById('schedule-modal').style.display = 'flex';
}

function closeScheduleModal() {
    document.getElementById('schedule-modal').style.display = 'none';
}

function openCleanupModal() {
    document.getElementById('cleanup-id').value = '';
    document.getElementById('cleanup-modal-title').textContent = 'Add New Cleanup Schedule';
    document.getElementById('cleanup-submit-text').textContent = 'Create Cleanup Schedule';
    document.getElementById('cleanup-form').reset();
    document.getElementById('cleanup-enabled').checked = true;
    document.getElementById('cleanup-check-movies').checked = true;
    document.getElementById('cleanup-check-series').checked = true;
    document.getElementById('cleanup-check-filesystem').checked = true;
    document.getElementById('cleanup-check-database').checked = true;
    document.getElementById('cleanup-modal').style.display = 'flex';
}

function closeCleanupModal() {
    document.getElementById('cleanup-modal').style.display = 'none';
}

// ==========================================
// Cron Builder Functions
// ==========================================

function openCronBuilder() {
    // Store the target (for cleanup or schedule)
    if (!window.cronBuilderTarget) {
        window.cronBuilderTarget = 'schedule';
    }

    // Reset to default values
    document.getElementById('cron-minute').value = '0';
    document.getElementById('cron-hour').value = '2';
    document.getElementById('cron-day').value = '*';
    document.getElementById('cron-month').value = '*';
    document.getElementById('cron-dow').value = '*';

    updateCronPreview();
    document.getElementById('cron-builder-modal').style.display = 'flex';
}

function closeCronBuilder() {
    document.getElementById('cron-builder-modal').style.display = 'none';
    window.cronBuilderTarget = null;
}

function openCleanupCronBuilder() {
    // Store that we're building for cleanup, not regular schedule
    window.cronBuilderTarget = 'cleanup';
    openCronBuilder();
}

function setCronPreset(expression) {
    const parts = expression.split(' ');
    if (parts.length === 5) {
        document.getElementById('cron-minute').value = parts[0];
        document.getElementById('cron-hour').value = parts[1];
        document.getElementById('cron-day').value = parts[2];
        document.getElementById('cron-month').value = parts[3];
        document.getElementById('cron-dow').value = parts[4];
        updateCronPreview();
    }
}

function updateCronPreview() {
    const minute = document.getElementById('cron-minute').value;
    const hour = document.getElementById('cron-hour').value;
    const day = document.getElementById('cron-day').value;
    const month = document.getElementById('cron-month').value;
    const dow = document.getElementById('cron-dow').value;

    const expression = `${minute} ${hour} ${day} ${month} ${dow}`;
    document.getElementById('cron-preview-text').textContent = expression;

    // Generate human-readable description
    let description = 'Runs ';

    if (day === '*' && month === '*' && dow === '*') {
        description += 'every day';
    } else if (dow !== '*') {
        const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
        description += `every ${days[parseInt(dow)]}`;
    } else if (day !== '*') {
        description += `on day ${day} of every month`;
    }

    if (hour === '*' && minute === '*') {
        description += ' every minute';
    } else if (hour === '*') {
        description += ` at minute ${minute} of every hour`;
    } else if (minute === '0') {
        description += ` at ${hour}:00`;
    } else {
        description += ` at ${hour}:${minute}`;
    }

    document.getElementById('cron-description').textContent = description;
}

function applyCronExpression() {
    const minute = document.getElementById('cron-minute').value;
    const hour = document.getElementById('cron-hour').value;
    const day = document.getElementById('cron-day').value;
    const month = document.getElementById('cron-month').value;
    const dow = document.getElementById('cron-dow').value;

    const cronExpression = `${minute} ${hour} ${day} ${month} ${dow}`;
    const target = window.cronBuilderTarget || 'schedule';

    if (target === 'cleanup') {
        document.getElementById('cleanup-cron').value = cronExpression;
    } else {
        document.getElementById('schedule-cron').value = cronExpression;
    }

    closeCronBuilder();
}

// ==========================================
// Scheduled Scan Functions
// ==========================================

async function loadScheduledScans() {
    try {
        const response = await fetch('/api/admin/scheduled-scans');
        const data = await response.json();

        if (data.success) {
            displaySchedules(data.scans);
            loadScheduleExecutions();
        } else {
            showError('Failed to load scheduled scans: ' + data.message);
        }
    } catch (error) {
        console.error('Error loading scheduled scans:', error);
        showError('Failed to load scheduled scans');
    }
}

function displaySchedules(scans) {
    const tbody = document.getElementById('schedules-table-body');
    tbody.innerHTML = '';

    if (!scans || scans.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 20px; color: #888;">No scheduled scans configured. Click "Add Schedule" to create one.</td></tr>';
        return;
    }

    scans.forEach(scan => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${escapeHtml(scan.name)}</td>
            <td><span class="badge badge-${scan.media_type === 'both' ? 'purple' : scan.media_type === 'movies' ? 'blue' : 'green'}">${scan.media_type}</span></td>
            <td><span class="badge badge-gray">${scan.scan_mode}</span></td>
            <td><code>${scan.cron_expression}</code></td>
            <td>${scan.last_run_at ? formatDate(scan.last_run_at) : 'Never'}</td>
            <td>${scan.next_run_at ? formatDate(scan.next_run_at) : 'N/A'}</td>
            <td>
                <label class="toggle-switch">
                    <input type="checkbox" ${scan.enabled ? 'checked' : ''} onchange="toggleSchedule(${scan.id}, this.checked, 'scan')">
                    <span class="toggle-slider"></span>
                </label>
            </td>
            <td>
                <button class="btn btn-sm btn-primary" onclick="triggerSchedule(${scan.id}, 'scan')" title="Run Now">
                    <i class="fas fa-play"></i>
                </button>
                <button class="btn btn-sm btn-danger" onclick="deleteSchedule(${scan.id}, 'scan')" title="Delete">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

async function loadScheduleExecutions() {
    try {
        const response = await fetch('/api/admin/schedule-executions?limit=20');
        const data = await response.json();

        if (data.success) {
            displayScheduleExecutions(data.executions);
        }
    } catch (error) {
        console.error('Error loading schedule executions:', error);
    }
}

function displayScheduleExecutions(executions) {
    const tbody = document.getElementById('executions-table-body');
    tbody.innerHTML = '';

    if (!executions || executions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 20px; color: #888;">No execution history available yet.</td></tr>';
        return;
    }

    executions.forEach(exec => {
        const statusClass = exec.status === 'completed' ? 'success' : exec.status === 'failed' ? 'danger' : 'warning';
        const duration = exec.execution_time_seconds ? `${exec.execution_time_seconds}s` : 'N/A';

        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${escapeHtml(exec.schedule_name || 'Unknown')}</td>
            <td>${formatDate(exec.started_at)}</td>
            <td>${duration}</td>
            <td><span class="badge badge-${statusClass}">${exec.status}</span></td>
            <td>${exec.items_processed || 0}</td>
            <td>${exec.items_skipped || 0}</td>
            <td>${exec.items_failed || 0}</td>
            <td>
                ${exec.error_message ? `<button class="btn btn-sm btn-warning" onclick="showExecutionError('${escapeHtml(exec.error_message)}')" title="View Error"><i class="fas fa-exclamation-triangle"></i></button>` : ''}
            </td>
        `;
        tbody.appendChild(row);
    });
}

// ==========================================
// Scheduled Cleanup Functions
// ==========================================

async function loadScheduledCleanups() {
    try {
        const response = await fetch('/api/admin/scheduled-cleanups');
        const data = await response.json();

        if (data.success) {
            displayCleanups(data.cleanups);
            loadCleanupExecutions();
        } else {
            showError('Failed to load scheduled cleanups: ' + data.message);
        }
    } catch (error) {
        console.error('Error loading scheduled cleanups:', error);
        showError('Failed to load scheduled cleanups');
    }
}

function displayCleanups(cleanups) {
    const tbody = document.getElementById('cleanups-table-body');
    tbody.innerHTML = '';

    if (!cleanups || cleanups.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 20px; color: #888;">No scheduled cleanups configured. Click "Add Cleanup Schedule" to create one.</td></tr>';
        return;
    }

    cleanups.forEach(cleanup => {
        const validation = [];
        if (cleanup.check_filesystem) validation.push('Filesystem');
        if (cleanup.check_database) validation.push('Database');
        const validationText = validation.join(' + ');

        const types = [];
        if (cleanup.check_movies) types.push('Movies');
        if (cleanup.check_series) types.push('Series');
        const typesText = types.join(', ');

        // Get last execution stats if available
        const lastRemoved = cleanup.last_movies_removed || cleanup.last_series_removed || cleanup.last_episodes_removed ?
            `${cleanup.last_movies_removed || 0}M / ${cleanup.last_series_removed || 0}S / ${cleanup.last_episodes_removed || 0}E` :
            'N/A';

        const row = document.createElement('tr');
        row.innerHTML = `
            <td>
                ${escapeHtml(cleanup.name)}
                <br><small style="color: #888;">${typesText}</small>
            </td>
            <td><span class="badge badge-info">${validationText}</span></td>
            <td><code>${cleanup.cron_expression}</code></td>
            <td>${cleanup.last_run_at ? formatDate(cleanup.last_run_at) : 'Never'}</td>
            <td>${cleanup.next_run_at ? formatDate(cleanup.next_run_at) : 'N/A'}</td>
            <td><small>${lastRemoved}</small></td>
            <td>
                <label class="toggle-switch">
                    <input type="checkbox" ${cleanup.enabled ? 'checked' : ''} onchange="toggleSchedule(${cleanup.id}, this.checked, 'cleanup')">
                    <span class="toggle-slider"></span>
                </label>
            </td>
            <td>
                <button class="btn btn-sm btn-primary" onclick="triggerSchedule(${cleanup.id}, 'cleanup')" title="Run Now">
                    <i class="fas fa-play"></i>
                </button>
                <button class="btn btn-sm btn-danger" onclick="deleteSchedule(${cleanup.id}, 'cleanup')" title="Delete">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

async function loadCleanupExecutions() {
    try {
        const response = await fetch('/api/admin/cleanup-executions?limit=20');
        const data = await response.json();

        if (data.success) {
            displayCleanupExecutions(data.executions);
        }
    } catch (error) {
        console.error('Error loading cleanup executions:', error);
    }
}

function displayCleanupExecutions(executions) {
    const tbody = document.getElementById('cleanup-executions-table-body');
    tbody.innerHTML = '';

    if (!executions || executions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 20px; color: #888;">No cleanup execution history available yet.</td></tr>';
        return;
    }

    executions.forEach(exec => {
        const statusClass = exec.status === 'completed' ? 'success' : exec.status === 'failed' ? 'danger' : 'warning';
        const duration = exec.execution_time_seconds ? `${exec.execution_time_seconds}s` : 'N/A';

        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${escapeHtml(exec.schedule_name || 'Manual')}</td>
            <td>${formatDate(exec.started_at)}</td>
            <td>${duration}</td>
            <td><span class="badge badge-${statusClass}">${exec.status}</span></td>
            <td>${exec.movies_removed || 0}</td>
            <td>${exec.series_removed || 0}</td>
            <td>${exec.episodes_removed || 0}</td>
            <td>
                ${exec.error_message ? `<button class="btn btn-sm btn-warning" onclick="showExecutionError('${escapeHtml(exec.error_message)}')" title="View Error"><i class="fas fa-exclamation-triangle"></i></button>` : ''}
                ${exec.report_json ? `<button class="btn btn-sm btn-info" onclick="showCleanupReport(${exec.id})" title="View Report"><i class="fas fa-file-alt"></i></button>` : ''}
            </td>
        `;
        tbody.appendChild(row);
    });
}

// ==========================================
// Schedule/Cleanup Actions
// ==========================================

async function toggleSchedule(id, enabled, type) {
    try {
        const endpoint = type === 'cleanup' ? '/api/admin/scheduled-cleanups' : '/api/admin/scheduled-scans';
        const response = await fetch(`${endpoint}/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        });

        const data = await response.json();
        if (data.success) {
            showSuccess(`Schedule ${enabled ? 'enabled' : 'disabled'} successfully`);
            if (type === 'cleanup') {
                loadScheduledCleanups();
            } else {
                loadScheduledScans();
            }
        } else {
            showError('Failed to toggle schedule: ' + data.message);
        }
    } catch (error) {
        console.error('Error toggling schedule:', error);
        showError('Failed to toggle schedule');
    }
}

async function triggerSchedule(id, type) {
    if (!confirm(`Are you sure you want to run this ${type} now?`)) {
        return;
    }

    try {
        const endpoint = type === 'cleanup' ? '/api/admin/scheduled-cleanups' : '/api/admin/scheduled-scans';
        const response = await fetch(`${endpoint}/${id}/trigger`, {
            method: 'POST'
        });

        const data = await response.json();
        if (data.success) {
            showSuccess(`${type === 'cleanup' ? 'Cleanup' : 'Scan'} started successfully`);
            // Reload after a delay to show the execution
            setTimeout(() => {
                if (type === 'cleanup') {
                    loadCleanupExecutions();
                } else {
                    loadScheduleExecutions();
                }
            }, 2000);
        } else {
            showError('Failed to trigger: ' + data.message);
        }
    } catch (error) {
        console.error('Error triggering schedule:', error);
        showError('Failed to trigger');
    }
}

async function deleteSchedule(id, type) {
    if (!confirm(`Are you sure you want to delete this ${type}? This cannot be undone.`)) {
        return;
    }

    try {
        const endpoint = type === 'cleanup' ? '/api/admin/scheduled-cleanups' : '/api/admin/scheduled-scans';
        const response = await fetch(`${endpoint}/${id}`, {
            method: 'DELETE'
        });

        const data = await response.json();
        if (data.success) {
            showSuccess('Schedule deleted successfully');
            if (type === 'cleanup') {
                loadScheduledCleanups();
            } else {
                loadScheduledScans();
            }
        } else {
            showError('Failed to delete schedule: ' + data.message);
        }
    } catch (error) {
        console.error('Error deleting schedule:', error);
        showError('Failed to delete schedule');
    }
}

// ==========================================
// Form Submissions
// ==========================================

// Add event listener for cleanup form
document.getElementById('cleanup-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const cleanupId = document.getElementById('cleanup-id').value;
    const isEdit = cleanupId !== '';

    const formData = {
        name: document.getElementById('cleanup-name').value,
        description: document.getElementById('cleanup-description').value || null,
        cron_expression: document.getElementById('cleanup-cron').value,
        check_movies: document.getElementById('cleanup-check-movies').checked,
        check_series: document.getElementById('cleanup-check-series').checked,
        check_filesystem: document.getElementById('cleanup-check-filesystem').checked,
        check_database: document.getElementById('cleanup-check-database').checked,
        enabled: document.getElementById('cleanup-enabled').checked
    };

    try {
        const url = isEdit ? `/api/admin/scheduled-cleanups/${cleanupId}` : '/api/admin/scheduled-cleanups';
        const method = isEdit ? 'PUT' : 'POST';

        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });

        const data = await response.json();
        if (data.success) {
            showSuccess(isEdit ? 'Cleanup schedule updated successfully' : 'Cleanup schedule created successfully');
            closeCleanupModal();
            loadScheduledCleanups();
        } else {
            showError('Failed to save cleanup schedule: ' + data.message);
        }
    } catch (error) {
        console.error('Error saving cleanup schedule:', error);
        showError('Failed to save cleanup schedule');
    }
});

// ==========================================
// Form Submissions
// ==========================================

// Add event listener for schedule scan form
document.getElementById('schedule-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const scheduleId = document.getElementById('schedule-id').value;
    const isEdit = scheduleId !== '';

    const formData = {
        name: document.getElementById('schedule-name').value,
        description: document.getElementById('schedule-description').value || null,
        cron_expression: document.getElementById('schedule-cron').value,
        media_type: document.getElementById('schedule-media-type').value,
        scan_mode: document.getElementById('schedule-scan-mode').value,
        specific_paths: document.getElementById('schedule-paths').value || null,
        enabled: document.getElementById('schedule-enabled').checked
    };

    try {
        const url = isEdit ? `/api/admin/scheduled-scans/${scheduleId}` : '/api/admin/scheduled-scans';
        const method = isEdit ? 'PUT' : 'POST';

        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });

        const data = await response.json();
        if (data.success) {
            showSuccess(isEdit ? 'Schedule updated successfully' : 'Schedule created successfully');
            closeScheduleModal();
            loadScheduledScans();
        } else {
            showError('Failed to save schedule: ' + data.message);
        }
    } catch (error) {
        console.error('Error saving schedule:', error);
        showError('Failed to save schedule');
    }
});

// ==========================================
// Event Listeners for Buttons
// ==========================================

document.getElementById('add-schedule-btn').addEventListener('click', openScheduleModal);
document.getElementById('add-cleanup-btn').addEventListener('click', openCleanupModal);

// Cron builder button event listener
document.getElementById('cron-builder-btn').addEventListener('click', () => {
    window.cronBuilderTarget = 'schedule';
    openCronBuilder();
});

// Add event listeners for cron input fields to update preview in real-time
document.addEventListener('DOMContentLoaded', () => {
    ['cron-minute', 'cron-hour', 'cron-day', 'cron-month', 'cron-dow'].forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.addEventListener('input', updateCronPreview);
        }
    });
});

// Load scheduled cleanups when the tab is activated
document.addEventListener('DOMContentLoaded', () => {
    // Find the scheduled-cleanups nav button and add event listener
    const cleanupTabBtn = document.querySelector('[data-tab="scheduled-cleanups"]');
    if (cleanupTabBtn) {
        cleanupTabBtn.addEventListener('click', () => {
            loadScheduledCleanups();
        });
    }

    // Load scheduled scans when that tab is activated
    const scanTabBtn = document.querySelector('[data-tab="scheduled-scans"]');
    if (scanTabBtn) {
        scanTabBtn.addEventListener('click', () => {
            loadScheduledScans();
        });
    }
});

// Helper function to show execution errors
function showExecutionError(errorMessage) {
    alert('Execution Error:\n\n' + errorMessage);
}

function showCleanupReport(executionId) {
    // Fetch and display the full cleanup report
    fetch(`/api/admin/cleanup-executions?execution_id=${executionId}`)
        .then(r => r.json())
        .then(data => {
            if (data.success && data.executions && data.executions[0]) {
                const exec = data.executions[0];
                const report = JSON.parse(exec.report_json || '{}');
                alert(`Cleanup Report:\n\nMovies Removed: ${exec.movies_removed}\nSeries Removed: ${exec.series_removed}\nEpisodes Removed: ${exec.episodes_removed}\n\nDuration: ${exec.execution_time_seconds}s`);
            }
        })
        .catch(err => showError('Failed to load report'));
}
