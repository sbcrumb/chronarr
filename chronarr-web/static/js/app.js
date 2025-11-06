// Chronarr Web Interface JavaScript

// Global state
let currentTab = 'dashboard';
let currentMoviesPage = 1;
let currentSeriesPage = 1;
let dashboardData = null;

// Initialize app
document.addEventListener('DOMContentLoaded', function() {
    try {
        initializeTabs();
    } catch (error) {
        console.error('Error initializing tabs:', error);
    }

    try {
        initializeEventListeners();
    } catch (error) {
        console.error('Error initializing event listeners:', error);
    }

    try {
        checkAuthStatus();  // Check authentication status on page load
    } catch (error) {
        console.error('Error checking auth status:', error);
    }

    try {
        loadDashboard();
    } catch (error) {
        console.error('Error loading dashboard:', error);
    }

    try {
        loadSeriesSources();
    } catch (error) {
        console.error('Error loading series sources:', error);
    }
});

// Tab management
function initializeTabs() {
    const tabButtons = document.querySelectorAll('.nav-tab');
    const tabContents = document.querySelectorAll('.tab-content');
    
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const tabName = this.dataset.tab;
            switchTab(tabName);
        });
    });
}

function switchTab(tabName) {
    // Update button states
    document.querySelectorAll('.nav-tab').forEach(btn => btn.classList.remove('active'));
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
    
    // Update content
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    document.getElementById(tabName).classList.add('active');
    
    currentTab = tabName;
    
    // Load tab-specific data
    switch(tabName) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'movies':
            loadMovies();
            break;
        case 'tv':
            loadSeries();
            break;
        case 'reports':
            loadReport();
            break;
        case 'tools':
            loadDetailedStats();
            break;
    }
}

// Event listeners
function initializeEventListeners() {
    // Search inputs
    const moviesSearch = document.getElementById('movies-search');
    const moviesImdbSearch = document.getElementById('movies-imdb-search');
    const seriesSearch = document.getElementById('series-search');
    const seriesImdbSearch = document.getElementById('series-imdb-search');

    if (moviesSearch) moviesSearch.addEventListener('input', debounce(loadMovies, 500));
    if (moviesImdbSearch) moviesImdbSearch.addEventListener('input', debounce(loadMovies, 500));
    if (seriesSearch) seriesSearch.addEventListener('input', debounce(loadSeries, 500));
    if (seriesImdbSearch) seriesImdbSearch.addEventListener('input', debounce(loadSeries, 500));

    // Filter dropdowns
    const moviesFilterDate = document.getElementById('movies-filter-date');
    const moviesFilterSource = document.getElementById('movies-filter-source');
    const seriesFilterDate = document.getElementById('series-filter-date');
    const seriesFilterSource = document.getElementById('series-filter-source');

    if (moviesFilterDate) moviesFilterDate.addEventListener('change', loadMovies);
    if (moviesFilterSource) moviesFilterSource.addEventListener('change', loadMovies);
    if (seriesFilterDate) seriesFilterDate.addEventListener('change', loadSeries);
    if (seriesFilterSource) seriesFilterSource.addEventListener('change', loadSeries);

    // Forms
    const editForm = document.getElementById('edit-form');
    const bulkUpdateForm = document.getElementById('bulk-update-form');
    const manualScanForm = document.getElementById('manual-scan-form');
    const manualCleanupForm = document.getElementById('manual-cleanup-form');
    const populateForm = document.getElementById('populate-form');

    if (editForm) editForm.addEventListener('submit', handleEditSubmit);
    if (bulkUpdateForm) bulkUpdateForm.addEventListener('submit', handleBulkUpdate);
    if (manualScanForm) manualScanForm.addEventListener('submit', handleManualScan);
    if (manualCleanupForm) manualCleanupForm.addEventListener('submit', handleManualCleanup);
    if (populateForm) populateForm.addEventListener('submit', handlePopulateDatabase);
}

// API calls
async function apiCall(endpoint, options = {}) {
    try {
        const response = await fetch(endpoint, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API call failed:', error);
        showToast(`API Error: ${error.message}`, 'error');
        throw error;
    }
}

// Dashboard
async function loadDashboard() {
    try {
        dashboardData = await apiCall('/api/dashboard');
        updateDashboardStats();
        updateDashboardCharts();
    } catch (error) {
        console.error('Failed to load dashboard:', error);
    }
}

function updateDashboardStats() {
    if (!dashboardData) return;
    
    // Debug: Log dashboard data to see what fields are available
    console.log('Dashboard data received:', dashboardData);
    
    const moviesTotal = dashboardData.movies_total || 0;
    const moviesWithDates = dashboardData.movies_with_dates || 0;
    const moviesWithoutDates = dashboardData.movies_without_dates || (moviesTotal - moviesWithDates);
    
    const episodesTotal = dashboardData.episodes_total || 0;
    const episodesWithDates = dashboardData.episodes_with_dates || 0;
    const episodesWithoutDates = dashboardData.episodes_without_dates || (episodesTotal - episodesWithDates);
    
    document.getElementById('movies-total').textContent = moviesTotal;
    document.getElementById('movies-with-dates').textContent = `${moviesWithDates} with dates, ${moviesWithoutDates} without`;
    
    document.getElementById('series-total').textContent = dashboardData.series_count || 0;
    document.getElementById('episodes-total').textContent = `${episodesTotal} episodes (${episodesWithDates} with dates, ${episodesWithoutDates} without)`;
    
    const missingTotal = moviesWithoutDates + episodesWithoutDates;
    document.getElementById('missing-dates-total').textContent = missingTotal;
    
    const noValidTotal = (dashboardData.movies_no_valid_source || 0) + (dashboardData.episodes_no_valid_source || 0);
    document.getElementById('no-valid-source-total').textContent = `${moviesWithoutDates} movies, ${episodesWithoutDates} episodes without dates`;
    
    document.getElementById('recent-activity').textContent = dashboardData.recent_activity_count || 0;

    // Skipped items
    const skippedMovies = dashboardData.movies_skipped || 0;
    const skippedEpisodes = dashboardData.episodes_skipped || 0;
    const skippedTotal = dashboardData.total_skipped || (skippedMovies + skippedEpisodes);
    document.getElementById('skipped-total').textContent = skippedTotal;
    document.getElementById('skipped-breakdown').textContent = `${skippedMovies} movies, ${skippedEpisodes} episodes`;
}

function showSkippedItems() {
    // Switch to Movies tab and filter to show only skipped items
    switchTab('movies');
    // Set the filter dropdown to "skipped"
    const moviesFilter = document.getElementById('movies-filter-date');
    if (moviesFilter) {
        moviesFilter.value = 'skipped';
        refreshMovies();
    }
}

function updateDashboardCharts() {
    if (!dashboardData) return;
    
    // Movie sources chart
    const movieChart = document.getElementById('movie-sources-chart');
    if (dashboardData.movie_sources && dashboardData.movie_sources.length > 0) {
        movieChart.innerHTML = createSimpleChart(dashboardData.movie_sources);
    } else {
        movieChart.innerHTML = '<p>No movie source data available</p>';
    }
    
    // Episode sources chart
    const episodeChart = document.getElementById('episode-sources-chart');
    if (dashboardData.episode_sources && dashboardData.episode_sources.length > 0) {
        episodeChart.innerHTML = createSimpleChart(dashboardData.episode_sources);
    } else {
        episodeChart.innerHTML = '<p>No episode source data available</p>';
    }
}

function createSimpleChart(data) {
    const total = data.reduce((sum, item) => sum + item.count, 0);
    let html = '<div class="simple-chart">';
    
    data.forEach((item, index) => {
        const percentage = ((item.count / total) * 100).toFixed(1);
        const color = getChartColor(index);
        html += `
            <div class="chart-item" style="background-color: ${color}20; border-left: 4px solid ${color};">
                <span class="chart-label">${item.source}</span>
                <span class="chart-value">${item.count} (${percentage}%)</span>
            </div>
        `;
    });
    
    html += '</div>';
    return html;
}

function getChartColor(index) {
    const colors = ['#007bff', '#28a745', '#ffc107', '#dc3545', '#6c757d', '#17a2b8', '#6f42c1'];
    return colors[index % colors.length];
}

// Movies
async function loadMovies(page = 1) {
    // Ensure page is a valid number
    if (isNaN(page) || page < 1) {
        page = 1;
    }
    
    const search = document.getElementById('movies-search').value;
    const imdbSearch = document.getElementById('movies-imdb-search').value;
    const dateFilter = document.getElementById('movies-filter-date').value;
    const sourceFilter = document.getElementById('movies-filter-source').value;

    const skip = (page - 1) * 100;
    console.log(`DEBUG: loadMovies called with page=${page}, calculated skip=${skip}`);

    const params = new URLSearchParams({
        skip: skip,
        limit: 100
    });

    if (search) params.append('search', search);
    if (imdbSearch) params.append('imdb_search', imdbSearch);

    // Handle different filter values
    if (dateFilter === 'skipped') {
        params.append('skipped', 'true');
    } else if (dateFilter) {
        params.append('has_date', dateFilter);
    }

    if (sourceFilter) params.append('source_filter', sourceFilter);
    
    try {
        const data = await apiCall(`/api/movies?${params}`);
        updateMoviesTable(data);
        updateMoviesPagination(data);
        updateMoviesSourceFilter(data);
        currentMoviesPage = (isNaN(page) || page < 1) ? 1 : page;
    } catch (error) {
        console.error('Failed to load movies:', error);
    }
}

function updateMoviesTable(data) {
    const tbody = document.getElementById('movies-tbody');
    
    if (!data.movies || data.movies.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center">No movies found</td></tr>';
        return;
    }
    
    tbody.innerHTML = data.movies.map(movie => {
        const dateadded = movie.dateadded ? formatDateTime(movie.dateadded) : '';
        const hasVideoBadge = movie.has_video_file ? 
            '<span class="badge badge-success">Yes</span>' : 
            '<span class="badge badge-secondary">No</span>';
        
        // Determine date type based on source and dates
        let dateType = 'Unknown';
        let dateTypeBadge = 'badge-secondary';
        
        if (movie.source === 'digital_release') {
            dateType = 'Digital Release';
            dateTypeBadge = 'badge-success';
        } else if (movie.source && movie.source.includes('radarr') && movie.source.includes('import')) {
            dateType = 'Radarr Import';
            dateTypeBadge = 'badge-warning';
        } else if (movie.source === 'manual') {
            dateType = 'Manual';
            dateTypeBadge = 'badge-info';
        } else if (movie.source === 'nfo_file_existing') {
            dateType = 'Existing NFO';
            dateTypeBadge = 'badge-secondary';
        } else if (movie.source === 'no_valid_date_source') {
            dateType = 'No Valid Source';
            dateTypeBadge = 'badge-danger';
        } else if (movie.source && movie.source.toLowerCase().includes('tmdb:theatrical')) {
            dateType = 'TMDB Theatrical';
            dateTypeBadge = 'badge-primary';
        } else if (movie.source && movie.source.toLowerCase().includes('tmdb:digital')) {
            dateType = 'TMDB Digital';
            dateTypeBadge = 'badge-primary';
        } else if (movie.source && movie.source.toLowerCase().includes('tmdb:physical')) {
            dateType = 'TMDB Physical';
            dateTypeBadge = 'badge-primary';
        } else if (movie.source && movie.source.toLowerCase().includes('tmdb:')) {
            dateType = 'TMDB Release';
            dateTypeBadge = 'badge-primary';
        } else if (movie.source && movie.source.toLowerCase().includes('omdb:')) {
            dateType = 'OMDb Release';
            dateTypeBadge = 'badge-info';
        } else if (movie.source && movie.source.toLowerCase().includes('webhook:')) {
            dateType = 'Webhook/API';
            dateTypeBadge = 'badge-warning';
        }
        
        // Check if skipped and if IMDb ID is placeholder
        const isSkipped = movie.skipped === true;
        const isPlaceholder = movie.imdb_id && movie.imdb_id.startsWith('missing-');
        const skipReasonBadge = isSkipped ? `<br><span class="badge badge-warning" title="${escapeHtml(movie.skip_reason || 'Skipped')}"">Skipped</span>` : '';

        // Add Update IMDb ID button for placeholder IDs
        const updateImdbButton = isPlaceholder ? `
            <button class="btn btn-sm btn-info" onclick="updateMovieImdbId('${movie.imdb_id}')" title="Update IMDb ID" style="margin-left: 5px;">
                <i class="fas fa-id-card"></i> Update IMDb
            </button>
        ` : '';

        return `
            <tr>
                <td>${escapeHtml(movie.title)}</td>
                <td><code>${movie.imdb_id}</code>${skipReasonBadge}</td>
                <td>${movie.released || '-'}</td>
                <td>${dateadded || '-'}</td>
                <td><span class="badge badge-secondary">${movie.source_description || movie.source || 'Unknown'}</span></td>
                <td><span class="badge ${dateTypeBadge}">${dateType}</span></td>
                <td>${hasVideoBadge}</td>
                <td>
                    <button class="btn btn-sm btn-primary" onclick="editMovie('${movie.imdb_id}', '${dateadded}', '${movie.source || ''}')">
                        <i class="fas fa-edit"></i> Edit
                    </button>
                    <button class="btn btn-sm btn-secondary" onclick="debugMovie('${movie.imdb_id}')" title="Debug Data">
                        <i class="fas fa-bug"></i>
                    </button>
                    ${updateImdbButton}
                    <button class="btn btn-sm btn-danger" onclick="deleteMovie('${movie.imdb_id}')" style="margin-left: 5px;" title="Delete Movie">
                        <i class="fas fa-trash"></i> Delete
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

function updateMoviesPagination(data) {
    const pagination = document.getElementById('movies-pagination');
    
    if (data.pages <= 1) {
        pagination.innerHTML = '';
        return;
    }
    
    let html = '';
    
    if (data.has_prev) {
        html += `<button class="btn btn-secondary btn-sm" onclick="loadMovies(${data.page - 1})">
            <i class="fas fa-chevron-left"></i> Previous
        </button>`;
    }
    
    html += `<span class="page-info">Page ${data.page} of ${data.pages}</span>`;
    
    if (data.has_next) {
        html += `<button class="btn btn-secondary btn-sm" onclick="loadMovies(${data.page + 1})">
            Next <i class="fas fa-chevron-right"></i>
        </button>`;
    }
    
    pagination.innerHTML = html;
}

function updateMoviesSourceFilter(data) {
    // This would be populated from dashboard data
    if (dashboardData && dashboardData.movie_sources) {
        const select = document.getElementById('movies-filter-source');
        const currentValue = select.value;
        
        select.innerHTML = '<option value="">All Sources</option>';
        dashboardData.movie_sources.forEach(source => {
            select.innerHTML += `<option value="${source.source}">${source.source} (${source.count})</option>`;
        });
        
        select.value = currentValue;
    }
}

async function loadSeriesSources() {
    try {
        const data = await apiCall('/api/series/sources');
        const select = document.getElementById('series-filter-source');
        const currentValue = select.value;
        
        select.innerHTML = '<option value="">All Sources</option>';
        data.sources.forEach(source => {
            select.innerHTML += `<option value="${source}">${source}</option>`;
        });
        
        select.value = currentValue;
    } catch (error) {
        console.error('Failed to load series sources:', error);
    }
}

function refreshMovies() {
    loadMovies(isNaN(currentMoviesPage) ? 1 : currentMoviesPage);
}

// TV Series
async function loadSeries(page = 1) {
    // Ensure page is a valid number
    if (isNaN(page) || page < 1) {
        page = 1;
    }
    
    const search = document.getElementById('series-search').value;
    const imdbSearch = document.getElementById('series-imdb-search').value;
    const dateFilter = document.getElementById('series-filter-date').value;
    const sourceFilter = document.getElementById('series-filter-source').value;
    
    const skip = (page - 1) * 50;
    console.log(`DEBUG: loadSeries called with page=${page}, calculated skip=${skip}`);
    
    const params = new URLSearchParams({
        skip: skip,
        limit: 50
    });
    
    if (search) params.append('search', search);
    if (imdbSearch) params.append('imdb_search', imdbSearch);
    if (dateFilter) params.append('date_filter', dateFilter);
    if (sourceFilter) params.append('source_filter', sourceFilter);
    
    try {
        const data = await apiCall(`/api/series?${params}`);
        updateSeriesTable(data);
        updateSeriesPagination(data);
        currentSeriesPage = (isNaN(page) || page < 1) ? 1 : page;
    } catch (error) {
        console.error('Failed to load series:', error);
    }
}

function updateSeriesTable(data) {
    const tbody = document.getElementById('series-tbody');
    
    if (!data.series || data.series.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">No series found</td></tr>';
        return;
    }
    
    tbody.innerHTML = data.series.map(series => {
        const progressPercent = series.total_episodes > 0 ?
            ((series.episodes_with_dates / series.total_episodes) * 100).toFixed(1) : 0;

        // Check if IMDb ID is placeholder
        const isPlaceholder = series.imdb_id && series.imdb_id.startsWith('missing-');

        // Add Update IMDb ID button for placeholder IDs
        const updateImdbButton = isPlaceholder ? `
            <button class="btn btn-sm btn-info" onclick="updateSeriesImdbId('${series.imdb_id}')" title="Update IMDb ID" style="margin-left: 5px;">
                <i class="fas fa-id-card"></i> Update IMDb
            </button>
        ` : '';

        return `
            <tr>
                <td>${escapeHtml(series.title)}</td>
                <td><code>${series.imdb_id}</code></td>
                <td>${series.total_episodes}</td>
                <td>
                    ${series.episodes_with_dates}
                    <small class="text-muted">(${progressPercent}%)</small>
                </td>
                <td>${series.episodes_with_video}</td>
                <td>${series.episodes_skipped || 0}</td>
                <td>
                    <button class="btn btn-sm btn-primary" onclick="viewSeriesEpisodes('${series.imdb_id}')">
                        <i class="fas fa-list"></i> Episodes
                    </button>
                    ${updateImdbButton}
                </td>
            </tr>
        `;
    }).join('');
}

function updateSeriesPagination(data) {
    const pagination = document.getElementById('series-pagination');
    
    if (data.pages <= 1) {
        pagination.innerHTML = '';
        return;
    }
    
    let html = '';
    
    if (data.has_prev) {
        html += `<button class="btn btn-secondary btn-sm" onclick="loadSeries(${data.page - 1})">
            <i class="fas fa-chevron-left"></i> Previous
        </button>`;
    }
    
    html += `<span class="page-info">Page ${data.page} of ${data.pages}</span>`;
    
    if (data.has_next) {
        html += `<button class="btn btn-secondary btn-sm" onclick="loadSeries(${data.page + 1})">
            Next <i class="fas fa-chevron-right"></i>
        </button>`;
    }
    
    pagination.innerHTML = html;
}

function refreshSeries() {
    loadSeries(isNaN(currentSeriesPage) ? 1 : currentSeriesPage);
}

async function viewSeriesEpisodes(imdbId) {
    try {
        const data = await apiCall(`/api/series/${imdbId}/episodes`);
        showEpisodesModal(data);
    } catch (error) {
        console.error('Failed to load episodes:', error);
    }
}

function showEpisodesModal(data) {
    // Calculate statistics
    const totalEpisodes = data.episodes.length;
    const episodesWithDates = data.episodes.filter(ep => ep.dateadded && ep.dateadded.trim() !== '').length;
    const episodesWithoutDates = totalEpisodes - episodesWithDates;
    const episodesWithVideo = data.episodes.filter(ep => ep.has_video_file).length;
    
    const modalHtml = `
        <div class="modal active" id="episodes-modal">
            <div class="modal-content" style="max-width: 900px;">
                <div class="modal-header">
                    <h3>${escapeHtml(data.series.title)} - Episodes</h3>
                    <button class="modal-close" onclick="closeEpisodesModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="episode-stats" style="display: flex; gap: 20px; margin-bottom: 20px; padding: 15px; background: #f8f9fa; border-radius: 5px;">
                        <div><strong>Total Episodes:</strong> ${totalEpisodes}</div>
                        <div><strong>With Dates:</strong> ${episodesWithDates}</div>
                        <div style="color: #dc3545;"><strong>Missing Dates:</strong> ${episodesWithoutDates}</div>
                        <div><strong>With Video:</strong> ${episodesWithVideo}</div>
                    </div>
                    
                    <div class="episode-filters" style="margin-bottom: 15px;">
                        <label style="margin-right: 15px;">
                            <input type="radio" name="episode-filter" value="all" checked onchange="filterEpisodes('all')"> Show All
                        </label>
                        <label style="margin-right: 15px;">
                            <input type="radio" name="episode-filter" value="missing" onchange="filterEpisodes('missing')"> Missing Dates Only
                        </label>
                        <label>
                            <input type="radio" name="episode-filter" value="has-dates" onchange="filterEpisodes('has-dates')"> With Dates Only
                        </label>
                    </div>
                    
                    <div class="mb-3">
                        <button id="bulk-select-all" class="btn btn-sm btn-secondary" onclick="toggleSelectAll()">
                            <i class="fas fa-check-square"></i> Select All
                        </button>
                        <button id="bulk-update-dates" class="btn btn-sm btn-primary" onclick="showBulkUpdateModal()" style="margin-left: 10px;" disabled>
                            <i class="fas fa-calendar"></i> Update Dates (<span id="update-count">0</span>)
                        </button>
                        <button id="bulk-delete-selected" class="btn btn-sm btn-danger" onclick="bulkDeleteSelected()" style="margin-left: 10px;" disabled>
                            <i class="fas fa-trash"></i> Delete Selected (<span id="selected-count">0</span>)
                        </button>
                    </div>

                    <!-- Bulk Update Dates Modal -->
                    <div id="bulk-update-modal" class="modal" style="display: none;">
                        <div class="modal-content" style="max-width: 500px;">
                            <div class="modal-header">
                                <h3>Bulk Update Episode Dates</h3>
                                <button class="close-button" onclick="closeBulkUpdateModal()">&times;</button>
                            </div>
                            <div class="modal-body">
                                <p>Update <strong><span id="modal-selected-count">0</span></strong> selected episode(s) to:</p>
                                <div class="form-group">
                                    <label>Date Source:</label>
                                    <select id="bulk-date-source" class="form-control">
                                        <option value="airdate">Air Date (from Sonarr)</option>
                                        <option value="import">Import Date (from Sonarr history)</option>
                                        <option value="custom">Custom Date</option>
                                    </select>
                                </div>
                                <div id="custom-date-input" style="display: none; margin-top: 10px;">
                                    <label>Custom Date:</label>
                                    <input type="datetime-local" id="bulk-custom-date" class="form-control">
                                </div>
                            </div>
                            <div class="modal-footer">
                                <button class="btn btn-secondary" onclick="closeBulkUpdateModal()">Cancel</button>
                                <button class="btn btn-primary" onclick="executeBulkUpdate()">
                                    <i class="fas fa-save"></i> Update Dates
                                </button>
                            </div>
                        </div>
                    </div>
                    <div class="table-container">
                        <table class="data-table sortable-table">
                            <thead>
                                <tr>
                                    <th width="40px">
                                        <input type="checkbox" id="select-all-checkbox" onchange="toggleSelectAll()">
                                    </th>
                                    <th class="sortable" onclick="sortTable('episodes-table-body', 1, 'text')" style="cursor: pointer;">
                                        Episode <i class="fas fa-sort"></i>
                                    </th>
                                    <th class="sortable" onclick="sortTable('episodes-table-body', 2, 'date')" style="cursor: pointer;">
                                        Aired <i class="fas fa-sort"></i>
                                    </th>
                                    <th class="sortable" onclick="sortTable('episodes-table-body', 3, 'date')" style="cursor: pointer;">
                                        Date Added <i class="fas fa-sort"></i>
                                    </th>
                                    <th class="sortable" onclick="sortTable('episodes-table-body', 4, 'text')" style="cursor: pointer;">
                                        Source <i class="fas fa-sort"></i>
                                    </th>
                                    <th class="sortable" onclick="sortTable('episodes-table-body', 5, 'text')" style="cursor: pointer;">
                                        Video <i class="fas fa-sort"></i>
                                    </th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody id="episodes-table-body">
                                ${data.episodes.map(episode => {
                                    const dateadded = episode.dateadded ? formatDateTime(episode.dateadded) : '';
                                    const hasVideoBadge = episode.has_video_file ? 
                                        '<span class="badge badge-success">Yes</span>' : 
                                        '<span class="badge badge-secondary">No</span>';
                                    
                                    const missingDate = !episode.dateadded || episode.dateadded.trim() === '';
                                    const rowClass = missingDate ? 'missing-date-row' : '';
                                    const dateCell = missingDate ? 
                                        '<td style="background-color: #ffebee; color: #c62828;"><strong>MISSING</strong></td>' : 
                                        `<td>${dateadded}</td>`;
                                    
                                    return `
                                        <tr class="${rowClass}" data-has-date="${!missingDate}" data-imdb="${data.series.imdb_id}" data-season="${episode.season}" data-episode="${episode.episode}">
                                            <td>
                                                <input type="checkbox" class="episode-checkbox" onchange="updateBulkDeleteButton()">
                                            </td>
                                            <td>S${episode.season.toString().padStart(2, '0')}E${episode.episode.toString().padStart(2, '0')}</td>
                                            <td>${episode.aired || '-'}</td>
                                            ${dateCell}
                                            <td><span class="badge badge-secondary">${episode.source_description || episode.source || 'Unknown'}</span></td>
                                            <td>${hasVideoBadge}</td>
                                            <td>
                                                <button class="btn btn-sm btn-primary" onclick="editEpisode('${data.series.imdb_id}', ${episode.season}, ${episode.episode}, '${dateadded}', '${episode.source || ''}')">
                                                    <i class="fas fa-edit"></i> Edit
                                                </button>
                                                <button class="btn btn-sm btn-danger" onclick="deleteEpisode('${data.series.imdb_id}', ${episode.season}, ${episode.episode})" style="margin-left: 5px;">
                                                    <i class="fas fa-trash"></i> Delete
                                                </button>
                                            </td>
                                        </tr>
                                    `;
                                }).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

function filterEpisodes(filterType) {
    const rows = document.querySelectorAll('#episodes-table-body tr');
    
    rows.forEach(row => {
        const hasDate = row.getAttribute('data-has-date') === 'true';
        let shouldShow = true;
        
        switch (filterType) {
            case 'missing':
                shouldShow = !hasDate;
                break;
            case 'has-dates':
                shouldShow = hasDate;
                break;
            case 'all':
            default:
                shouldShow = true;
                break;
        }
        
        row.style.display = shouldShow ? '' : 'none';
    });
}

function closeEpisodesModal() {
    const modal = document.getElementById('episodes-modal');
    if (modal) {
        modal.remove();
    }
}

// Reports
async function loadReport() {
    try {
        const data = await apiCall('/api/reports/missing-dates');
        updateReportSummary(data.summary);
        updateReportTables(data);
    } catch (error) {
        console.error('Failed to load report:', error);
    }
}

function updateReportSummary(summary) {
    document.getElementById('report-movies-with').textContent = summary.movies_with_dates;
    document.getElementById('report-movies-missing').textContent = summary.movies_missing_dates;
    document.getElementById('report-episodes-with').textContent = summary.episodes_with_dates;
    document.getElementById('report-episodes-missing').textContent = summary.episodes_missing_dates;
}

function updateReportTables(data) {
    // Movies missing dates
    const moviesTbody = document.getElementById('report-movies-tbody');
    if (data.movies_missing.length === 0) {
        moviesTbody.innerHTML = '<tr><td colspan="5" class="text-center">No movies missing dates</td></tr>';
    } else {
        moviesTbody.innerHTML = data.movies_missing.map(movie => `
            <tr>
                <td>${escapeHtml(movie.title)}</td>
                <td><code>${movie.imdb_id}</code></td>
                <td>${movie.released || '-'}</td>
                <td><span class="badge badge-warning">${movie.source_description || movie.source || 'Unknown'}</span></td>
                <td>
                    <button class="btn btn-sm btn-success" onclick="smartFixMovie('${movie.imdb_id}')">
                        <i class="fas fa-magic"></i> Smart Fix
                    </button>
                </td>
            </tr>
        `).join('');
    }
    
    // Episodes missing dates
    const episodesTbody = document.getElementById('report-episodes-tbody');
    if (data.episodes_missing.length === 0) {
        episodesTbody.innerHTML = '<tr><td colspan="6" class="text-center">No episodes missing dates</td></tr>';
    } else {
        episodesTbody.innerHTML = data.episodes_missing.map(episode => `
            <tr>
                <td>${escapeHtml(episode.series_title)}</td>
                <td>S${episode.season.toString().padStart(2, '0')}E${episode.episode.toString().padStart(2, '0')}</td>
                <td><code>${episode.imdb_id}</code></td>
                <td>${episode.aired || '-'}</td>
                <td><span class="badge badge-warning">${episode.source_description || episode.source || 'Unknown'}</span></td>
                <td>
                    <button class="btn btn-sm btn-success" onclick="smartFixEpisode('${episode.imdb_id}', ${episode.season}, ${episode.episode})">
                        <i class="fas fa-magic"></i> Smart Fix
                    </button>
                </td>
            </tr>
        `).join('');
    }
}

function refreshReport() {
    loadReport();
}

// Smart fix functions
async function smartFixMovie(imdbId) {
    try {
        console.log('🔍 SMART FIX: Loading options for movie', imdbId);
        const options = await apiCall(`/api/movies/${imdbId}/date-options`);
        console.log('🔍 SMART FIX: Received options:', options);
        showSmartFixModal('movie', options);
    } catch (error) {
        console.error('Failed to load movie options:', error);
        showToast('Failed to load movie options', 'error');
    }
}

async function smartFixEpisode(imdbId, season, episode) {
    // Validate parameters
    if (!imdbId || season === undefined || season === null || episode === undefined || episode === null) {
        console.error('smartFixEpisode: Invalid parameters:', {imdbId, season, episode});
        showToast('Invalid episode parameters', 'error');
        return;
    }
    
    try {
        const options = await apiCall(`/api/episodes/${imdbId}/${season}/${episode}/date-options`);
        showSmartFixModal('episode', options);
    } catch (error) {
        console.error('Failed to load episode options:', error);
        showToast('Failed to load episode options', 'error');
    }
}

function showSmartFixModal(mediaType, options) {
    console.log('🔍 SMART FIX: Showing modal for', mediaType, 'with options:', options);
    
    const modal = document.getElementById('smart-fix-modal');
    const title = document.getElementById('smart-fix-title');
    const content = document.getElementById('smart-fix-content');
    
    if (!modal || !title || !content) {
        console.error('❌ SMART FIX: Modal elements not found!', {modal, title, content});
        alert('Smart Fix modal not found - check console for details');
        return;
    }
    
    console.log('✅ SMART FIX: Modal elements found, proceeding to show Smart Fix modal');
    
    if (mediaType === 'movie') {
        title.textContent = `Fix Date for Movie: ${options.imdb_id}`;
    } else {
        // Add validation for episode data
        const season = options.season || 0;
        const episode = options.episode || 0;
        title.textContent = `Fix Date for Episode: ${options.imdb_id} S${season.toString().padStart(2, '0')}E${episode.toString().padStart(2, '0')}`;
    }
    
    // Build options HTML
    let optionsHtml = '<div class="smart-fix-options">';
    
    options.options.forEach((option, index) => {
        const isChecked = index === 0 ? 'checked' : '';
        const dateInput = option.type === 'manual' ? 
            `<input type="datetime-local" id="manual-date-${index}" class="manual-date-input" style="margin-top: 0.5rem;">` : '';
        
        optionsHtml += `
            <div class="option-card">
                <label class="option-label">
                    <input type="radio" name="date-option" value="${index}" ${isChecked}>
                    <div class="option-content">
                        <h4>${option.label}</h4>
                        <p>${option.description}</p>
                        ${option.date ? `<small><strong>Date:</strong> ${formatDateTime(option.date)}</small>` : ''}
                        ${dateInput}
                    </div>
                </label>
            </div>
        `;
    });
    
    optionsHtml += '</div>';
    
    optionsHtml += `
        <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeSmartFixModal()">Cancel</button>
            <button type="button" class="btn btn-success" onclick="applySmartFix('${mediaType}', ${JSON.stringify(options).replace(/'/g, "&apos;")})">
                <i class="fas fa-magic"></i> Apply Fix
            </button>
        </div>
    `;
    
    content.innerHTML = optionsHtml;
    modal.classList.add('active');
}

function closeSmartFixModal() {
    document.getElementById('smart-fix-modal').classList.remove('active');
}

async function applySmartFix(mediaType, options) {
    const selectedRadio = document.querySelector('input[name="date-option"]:checked');
    if (!selectedRadio) {
        showToast('Please select a date option', 'warning');
        return;
    }
    
    const selectedIndex = selectedRadio.value;
    const selectedOption = options.options[selectedIndex];
    
    let dateadded = selectedOption.date;
    let source = selectedOption.source;
    
    // Handle manual date entry
    if (selectedOption.type === 'manual') {
        const manualDateInput = document.getElementById(`manual-date-${selectedIndex}`);
        if (manualDateInput && manualDateInput.value) {
            try {
                dateadded = new Date(manualDateInput.value).toISOString();
            } catch (e) {
                showToast('Invalid date format', 'error');
                return;
            }
        } else {
            showToast('Please enter a date for manual option', 'warning');
            return;
        }
    } else if (dateadded) {
        // Fix date format for non-manual options
        try {
            let dateValue = dateadded;
            
            // Handle timezone offsets
            if (dateValue.includes('+00:00')) {
                dateValue = dateValue.replace('+00:00', 'Z');
            }
            
            const date = new Date(dateValue);
            if (isNaN(date.getTime())) {
                showToast('Invalid date from server', 'error');
                return;
            }
            dateadded = date.toISOString();
        } catch (e) {
            console.error('Date conversion error:', e, dateadded);
            showToast('Date conversion error', 'error');
            return;
        }
    }
    
    // Debug logging
    console.log('🔍 SMART FIX DEBUG:', {
        mediaType,
        imdb_id: options.imdb_id,
        selectedOption,
        dateadded,
        source,
        originalDate: selectedOption.date
    });
    
    try {
        if (mediaType === 'movie') {
            await updateMovieDate(options.imdb_id, dateadded, source);
        } else {
            await updateEpisodeDate(options.imdb_id, options.season, options.episode, dateadded, source);
        }
        closeSmartFixModal();
    } catch (error) {
        console.error('Smart fix failed:', error);
        showToast('Smart fix failed: ' + error.message, 'error');
    }
}

// Tools
async function loadDetailedStats() {
    try {
        const data = await apiCall('/api/dashboard');
        const statsHtml = `
            <div class="stats-grid">
                <div class="stat-row">
                    <strong>Database Size:</strong> ${data.database_size_mb} MB
                </div>
                <div class="stat-row">
                    <strong>Total Movies:</strong> ${data.movies_total} (${data.movies_with_video} with video files)
                </div>
                <div class="stat-row">
                    <strong>Movies with Dates:</strong> ${data.movies_with_dates} (${((data.movies_with_dates / data.movies_total) * 100).toFixed(1)}%)
                </div>
                <div class="stat-row">
                    <strong>Total Series:</strong> ${data.series_count}
                </div>
                <div class="stat-row">
                    <strong>Total Episodes:</strong> ${data.episodes_total} (${data.episodes_with_video} with video files)
                </div>
                <div class="stat-row">
                    <strong>Episodes with Dates:</strong> ${data.episodes_with_dates} (${((data.episodes_with_dates / data.episodes_total) * 100).toFixed(1)}%)
                </div>
                <div class="stat-row">
                    <strong>Processing History:</strong> ${data.processing_history_count} events
                </div>
            </div>
        `;
        document.getElementById('detailed-stats').innerHTML = statsHtml;
    } catch (error) {
        console.error('Failed to load detailed stats:', error);
    }
}

async function handleBulkUpdate(event) {
    event.preventDefault();
    
    const mediaType = document.getElementById('bulk-media-type').value;
    const oldSource = document.getElementById('bulk-old-source').value;
    const newSource = document.getElementById('bulk-new-source').value;
    
    if (!mediaType || !oldSource || !newSource) {
        showToast('Please fill in all fields', 'warning');
        return;
    }
    
    if (!confirm(`This will update all ${mediaType} with source "${oldSource}" to "${newSource}". Continue?`)) {
        return;
    }
    
    try {
        const result = await apiCall('/api/bulk/update-source', {
            method: 'POST',
            body: JSON.stringify({
                media_type: mediaType,
                old_source: oldSource,
                new_source: newSource
            })
        });
        
        showToast(result.message, 'success');
        
        // Reset form
        document.getElementById('bulk-update-form').reset();
        
        // Refresh current tab
        if (currentTab === 'movies') loadMovies(currentMoviesPage);
        if (currentTab === 'tv') loadSeries(currentSeriesPage);
        if (currentTab === 'reports') loadReport();
        if (currentTab === 'dashboard') loadDashboard();
        
    } catch (error) {
        console.error('Bulk update failed:', error);
    }
}

// Edit modal functions
async function editMovie(imdbId, dateadded, source) {
    try {
        // Load movie options to populate available dates
        const options = await apiCall(`/api/movies/${imdbId}/date-options`);
        showEnhancedEditModal('movie', options, dateadded, source);
    } catch (error) {
        console.error('Failed to load movie options for edit:', error);
        // Fallback to basic edit modal
        showBasicEditModal('movie', imdbId, dateadded, source);
    }
}

function showEnhancedEditModal(mediaType, options, currentDateadded, currentSource) {
    const modal = document.getElementById('edit-modal');
    const title = document.getElementById('modal-title');
    const modalBody = document.querySelector('#edit-modal .modal-body');

    if (mediaType === 'movie') {
        title.textContent = `Edit Movie: ${options.imdb_id}`;
    } else {
        // Add validation for episode data
        const season = options.season || 0;
        const episode = options.episode || 0;
        title.textContent = `Edit Episode: ${options.imdb_id} S${season.toString().padStart(2, '0')}E${episode.toString().padStart(2, '0')}`;
    }

    // Build enhanced edit form with date options
    let formHtml = `
        <form id="edit-form-enhanced" onsubmit="handleEnhancedEditSubmit(event); return false;">
        <input type="hidden" id="edit-imdb-id" value="${options.imdb_id}">
        <input type="hidden" id="edit-media-type" value="${mediaType}">
        ${mediaType === 'episode' ? `
            <input type="hidden" id="edit-season" value="${options.season}">
            <input type="hidden" id="edit-episode" value="${options.episode}">
        ` : `
            <input type="hidden" id="edit-season" value="">
            <input type="hidden" id="edit-episode" value="">
        `}

        <div class="form-group">
            <label>Choose Date Source:</label>
            <div class="date-options">
    `;

    // Add available date options
    options.options.forEach((option, index) => {
        const isSelected = option.source === currentSource ? 'checked' : '';
        const optionId = `date-option-${index}`;

        formHtml += `
            <div class="date-option-card">
                <label class="date-option-label">
                    <input type="radio" name="edit-date-option" value="${index}" ${isSelected}
                           onchange="updateEditDateFromOption(${index}, ${JSON.stringify(option).replace(/"/g, '&quot;')})">
                    <div class="date-option-content">
                        <h4>${option.label}</h4>
                        <p>${option.description}</p>
                        ${option.date ? `<small><strong>Date:</strong> ${formatDateTime(option.date)}</small>` : ''}
                    </div>
                </label>
            </div>
        `;
    });

    formHtml += `
            </div>
        </div>

        <div class="form-group">
            <label for="edit-dateadded">Date Added:</label>
            <input type="datetime-local" id="edit-dateadded" required>
            <small>Adjust the date/time as needed</small>
        </div>

        <div class="form-group">
            <label for="edit-source">Source:</label>
            <select id="edit-source" required>
                <option value="manual">Manual</option>
                <option value="airdate">Air Date</option>
                <option value="digital_release">Digital Release</option>
                <option value="radarr:db.history.import">Radarr Import</option>
                <option value="sonarr:history.import">Sonarr Import</option>
                <option value="no_valid_date_source">No Valid Source</option>
            </select>
        </div>

        <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            <button type="submit" class="btn btn-primary">Save Changes</button>
        </div>
        </form>
    `;

    modalBody.innerHTML = formHtml;


    // Set current values
    if (currentDateadded && currentDateadded !== '-') {
        try {
            const date = new Date(currentDateadded);
            document.getElementById('edit-dateadded').value = date.toISOString().slice(0, 16);
        } catch (e) {
            document.getElementById('edit-dateadded').value = '';
        }
    }

    document.getElementById('edit-source').value = currentSource || 'manual';

    // Store options for later use
    modal.dataset.options = JSON.stringify(options);

    modal.classList.add('active');
}

function showBasicEditModal(mediaType, imdbId, dateadded, source) {
    // Fallback to original basic edit modal
    document.getElementById('modal-title').textContent = `Edit ${mediaType}: ${imdbId}`;
    document.getElementById('edit-imdb-id').value = imdbId;
    document.getElementById('edit-media-type').value = mediaType;
    
    if (dateadded && dateadded !== '-') {
        try {
            const date = new Date(dateadded);
            document.getElementById('edit-dateadded').value = date.toISOString().slice(0, 16);
        } catch (e) {
            document.getElementById('edit-dateadded').value = '';
        }
    } else {
        document.getElementById('edit-dateadded').value = '';
    }
    
    document.getElementById('edit-source').value = source || 'manual';
    document.getElementById('edit-modal').classList.add('active');
}

function updateEditDateFromOption(optionIndex, option) {
    const dateInput = document.getElementById('edit-dateadded');
    const sourceSelect = document.getElementById('edit-source');
    
    if (option.date) {
        // Convert to datetime-local format with better date parsing
        try {
            let dateValue = option.date;
            
            // Handle timezone offsets by converting to local time
            if (dateValue.includes('+00:00') || dateValue.includes('Z')) {
                dateValue = dateValue.replace('+00:00', 'Z');
            }
            
            const date = new Date(dateValue);
            if (isNaN(date.getTime())) {
                console.error('Invalid date:', dateValue);
                dateInput.value = '';
            } else {
                // Convert to local datetime-local format
                const localDateTime = new Date(date.getTime() - (date.getTimezoneOffset() * 60000));
                dateInput.value = localDateTime.toISOString().slice(0, 16);
            }
        } catch (e) {
            console.error('Date parsing error:', e, option.date);
            dateInput.value = '';
        }
    } else {
        // Manual option - clear the date for user input
        dateInput.value = '';
    }
    
    sourceSelect.value = option.source;
}

async function handleEnhancedEditSubmit(event) {
    event.preventDefault();

    console.log('🔍 Enhanced Edit Submit called');

    const modal = document.getElementById('edit-modal');
    const options = JSON.parse(modal.dataset.options);
    const imdbId = options.imdb_id;
    const mediaType = document.getElementById('edit-media-type').value;
    const dateadded = document.getElementById('edit-dateadded').value;
    const source = document.getElementById('edit-source').value;

    console.log('🔍 Form values:', {
        imdbId,
        mediaType,
        dateadded,
        dateaddedType: typeof dateadded,
        dateaddedLength: dateadded ? dateadded.length : 0,
        source
    });

    if (!dateadded) {
        console.log('❌ Date field is empty!');
        showToast('Please enter a date', 'warning');
        return;
    }

    // Convert datetime-local to ISO string with error handling
    let isoDateadded = null;
    try {
        isoDateadded = new Date(dateadded).toISOString();
        console.log('✅ Converted to ISO:', isoDateadded);
    } catch (e) {
        console.error('❌ Date conversion error:', e);
        showToast('Invalid date format', 'error');
        return;
    }

    try {
        if (mediaType === 'movie') {
            console.log('📤 Calling updateMovieDate with:', { imdbId, isoDateadded, source });
            await updateMovieDate(imdbId, isoDateadded, source);
        } else {
            console.log('📤 Calling updateEpisodeDate with:', { imdbId, season: options.season, episode: options.episode, isoDateadded, source });
            await updateEpisodeDate(imdbId, options.season, options.episode, isoDateadded, source);
        }

        closeModal();
    } catch (error) {
        console.error('Enhanced edit failed:', error);
        showToast('Update failed: ' + error.message, 'error');
    }
}

async function editEpisode(imdbId, season, episode, dateadded, source) {
    // Validate parameters
    if (!imdbId || season === undefined || season === null || episode === undefined || episode === null) {
        console.error('editEpisode: Invalid parameters:', {imdbId, season, episode});
        showToast('Invalid episode parameters', 'error');
        return;
    }
    
    try {
        // Load episode options to populate available dates
        const options = await apiCall(`/api/episodes/${imdbId}/${season}/${episode}/date-options`);
        showEnhancedEditModal('episode', options, dateadded, source);
    } catch (error) {
        console.error('Failed to load episode options for edit:', error);
        // Fallback to basic edit modal
        showBasicEditModal('episode', imdbId, dateadded, source, season, episode);
    }
}

function closeModal() {
    document.getElementById('edit-modal').classList.remove('active');
}

async function handleEditSubmit(event) {
    event.preventDefault();

    console.log('🔍 Basic Edit Submit called (OLD HANDLER)');

    const imdbId = document.getElementById('edit-imdb-id').value;
    const mediaType = document.getElementById('edit-media-type').value;
    const season = document.getElementById('edit-season').value;
    const episode = document.getElementById('edit-episode').value;
    const dateadded = document.getElementById('edit-dateadded').value;
    const source = document.getElementById('edit-source').value;

    console.log('🔍 OLD Form values:', {
        imdbId,
        mediaType,
        dateadded,
        dateaddedType: typeof dateadded,
        dateaddedLength: dateadded ? dateadded.length : 0,
        source
    });

    // Convert datetime-local to ISO string
    const isoDateadded = dateadded ? new Date(dateadded).toISOString() : null;

    console.log('🔍 OLD isoDateadded:', isoDateadded);

    try {
        if (mediaType === 'movie') {
            console.log('📤 OLD calling updateMovieDate with:', { imdbId, isoDateadded, source });
            await updateMovieDate(imdbId, isoDateadded, source);
        } else {
            console.log('📤 OLD calling updateEpisodeDate');
            await updateEpisodeDate(imdbId, parseInt(season), parseInt(episode), isoDateadded, source);
        }

        closeModal();
    } catch (error) {
        console.error('Update failed:', error);
    }
}

// Update functions
async function updateMovieDate(imdbId, dateadded, source) {
    console.log('🔍 updateMovieDate called with:', {
        imdbId,
        dateadded,
        dateaddedType: typeof dateadded,
        dateaddedValue: dateadded,
        source
    });

    try {
        const payload = {
            dateadded: dateadded,
            source: source
        };

        console.log('📤 Sending API request with payload:', JSON.stringify(payload));

        const result = await apiCall(`/api/movies/${imdbId}`, {
            method: 'PUT',
            body: JSON.stringify(payload)
        });

        console.log('✅ API response:', result);

        showToast(result.message, 'success');

        // Refresh current view
        if (currentTab === 'movies') loadMovies(currentMoviesPage);
        if (currentTab === 'reports') loadReport();
        if (currentTab === 'dashboard') loadDashboard();

    } catch (error) {
        console.error('Movie update failed:', error);
    }
}

async function updateEpisodeDate(imdbId, season, episode, dateadded, source) {
    try {
        const result = await apiCall(`/api/episodes/${imdbId}/${season}/${episode}`, {
            method: 'PUT',
            body: JSON.stringify({
                dateadded: dateadded,
                source: source
            })
        });
        
        showToast(result.message, 'success');
        
        // Refresh current view
        if (currentTab === 'tv') loadSeries(currentSeriesPage);
        if (currentTab === 'reports') loadReport();
        if (currentTab === 'dashboard') loadDashboard();
        
        // Refresh episodes modal if open
        const episodesModal = document.getElementById('episodes-modal');
        if (episodesModal) {
            closeEpisodesModal();
            setTimeout(() => viewSeriesEpisodes(imdbId), 100);
        }
        
    } catch (error) {
        console.error('Episode update failed:', error);
    }
}

// Utility functions
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function formatDateTime(dateString) {
    try {
        const date = new Date(dateString);
        return date.toLocaleString();
    } catch (e) {
        return dateString;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <div class="toast-content">
            <span>${escapeHtml(message)}</span>
        </div>
    `;
    
    container.appendChild(toast);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
    }, 5000);
    
    // Remove on click
    toast.addEventListener('click', () => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
    });
}

// Debug function
async function debugMovie(imdbId) {
    try {
        const data = await apiCall(`/api/debug/movie/${imdbId}/raw`);
        
        const debugInfo = `
DEBUG INFO for ${imdbId}:

Raw Database Data:
- imdb_id: ${data.raw_data.imdb_id}
- path: ${data.raw_data.path}
- released: ${data.raw_data.released}
- dateadded: ${data.raw_data.dateadded}
- source: ${data.raw_data.source}
- has_video_file: ${data.raw_data.has_video_file}
- last_updated: ${data.raw_data.last_updated}

Analysis:
- Movie Released: ${data.raw_data.released || 'Not set'}
- Library Import Date: ${data.raw_data.dateadded || 'Not set'}
- Date Source: ${data.raw_data.source_description || data.raw_data.source || 'Unknown'}
        `;
        
        alert(debugInfo);
        console.log('🔍 Debug data for', imdbId, data);
        
    } catch (error) {
        console.error('Debug failed:', error);
        showToast('Debug failed: ' + error.message, 'error');
    }
}

// Episode deletion functionality
async function deleteEpisode(imdbId, season, episode) {
    // Validate parameters
    if (!imdbId || season === undefined || season === null || episode === undefined || episode === null) {
        console.error('deleteEpisode: Invalid parameters:', {imdbId, season, episode});
        showToast('Invalid episode parameters', 'error');
        return;
    }
    
    const episodeStr = `S${season.toString().padStart(2, '0')}E${episode.toString().padStart(2, '0')}`;
    
    // Confirmation dialog
    if (!confirm(`⚠️ Delete Episode ${episodeStr}?\n\nThis will permanently remove the episode from the database.\n\nAre you sure you want to continue?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/episodes/${imdbId}/${season}/${episode}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            showToast(`✅ Episode ${episodeStr} deleted successfully`, 'success');
            
            // Remove the row from the table
            const rows = document.querySelectorAll('#episodes-table-body tr');
            rows.forEach(row => {
                const episodeCell = row.querySelector('td:first-child');
                if (episodeCell && episodeCell.textContent === episodeStr) {
                    row.remove();
                }
            });
            
            // Update episode counts in modal header
            updateEpisodeModalCounts();
            
        } else {
            const errorMsg = result.message || result.error || 'Unknown error';
            showToast(`❌ Failed to delete episode: ${errorMsg}`, 'error');
        }
        
    } catch (error) {
        console.error('Delete episode failed:', error);
        showToast(`❌ Delete failed: ${error.message}`, 'error');
    }
}

// Movie deletion functionality
async function deleteMovie(imdbId) {
    // Confirmation dialog
    if (!confirm(`⚠️ Delete Movie?\n\nThis will permanently remove the movie (${imdbId}) from the database.\n\nAre you sure you want to continue?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/movies/${imdbId}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            showToast(`✅ Movie deleted successfully`, 'success');
            
            // Refresh the movies table
            loadMovies(currentMoviesPage);
            
        } else {
            const errorMsg = result.message || result.error || 'Unknown error';
            showToast(`❌ Failed to delete movie: ${errorMsg}`, 'error');
        }
        
    } catch (error) {
        console.error('Delete movie failed:', error);
        showToast(`❌ Delete failed: ${error.message}`, 'error');
    }
}

async function updateMovieImdbId(oldImdbId) {
    // Prompt for new IMDb ID
    const newImdbId = prompt(`Update IMDb ID\n\nCurrent: ${oldImdbId}\n\nEnter the correct IMDb ID (with or without 'tt' prefix):`);

    if (!newImdbId || newImdbId.trim() === '') {
        return;
    }

    const cleanImdbId = newImdbId.trim();

    // Confirmation
    if (!confirm(`Update IMDb ID?\n\nOld: ${oldImdbId}\nNew: ${cleanImdbId}\n\nThis will migrate the movie record to the new IMDb ID. Continue?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/movies/${oldImdbId}/migrate-imdb`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ new_imdb_id: cleanImdbId })
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showToast(`✅ IMDb ID updated successfully to ${result.new_imdb_id}`, 'success');

            // Refresh the movies table
            loadMovies(currentMoviesPage);

        } else {
            const errorMsg = result.message || result.detail || 'Unknown error';
            showToast(`❌ Failed to update IMDb ID: ${errorMsg}`, 'error');
        }

    } catch (error) {
        console.error('Update IMDb ID failed:', error);
        showToast(`❌ Update failed: ${error.message}`, 'error');
    }
}

async function updateSeriesImdbId(oldImdbId) {
    // Prompt for new IMDb ID
    const newImdbId = prompt(`Update Series IMDb ID\n\nCurrent: ${oldImdbId}\n\nEnter the correct IMDb ID (with or without 'tt' prefix):`);

    if (!newImdbId || newImdbId.trim() === '') {
        return;
    }

    const cleanImdbId = newImdbId.trim();

    // Confirmation
    if (!confirm(`Update Series IMDb ID?\n\nOld: ${oldImdbId}\nNew: ${cleanImdbId}\n\nThis will migrate the series and ALL its episodes to the new IMDb ID. Continue?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/series/${oldImdbId}/migrate-imdb`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ new_imdb_id: cleanImdbId })
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showToast(`✅ Series IMDb ID updated successfully to ${result.new_imdb_id}`, 'success');

            // Refresh the series table
            loadSeries(currentSeriesPage);

        } else {
            const errorMsg = result.message || result.detail || 'Unknown error';
            showToast(`❌ Failed to update IMDb ID: ${errorMsg}`, 'error');
        }

    } catch (error) {
        console.error('Update series IMDb ID failed:', error);
        showToast(`❌ Update failed: ${error.message}`, 'error');
    }
}

// Update episode counts in modal after deletion
function updateEpisodeModalCounts() {
    const remainingRows = document.querySelectorAll('#episodes-table-body tr');
    const totalEpisodes = remainingRows.length;
    const episodesWithDates = Array.from(remainingRows).filter(row => 
        row.getAttribute('data-has-date') === 'true'
    ).length;
    const episodesWithoutDates = totalEpisodes - episodesWithDates;
    
    // Update the stats in the modal
    const statsDiv = document.querySelector('.episode-stats');
    if (statsDiv) {
        // Keep the existing "With Video" count by finding it
        const videoCountDiv = statsDiv.querySelector('div:nth-child(4)');
        const videoCountText = videoCountDiv ? videoCountDiv.innerHTML : '<div><strong>With Video:</strong> -</div>';
        
        statsDiv.innerHTML = `
            <div><strong>Total Episodes:</strong> ${totalEpisodes}</div>
            <div><strong>With Dates:</strong> ${episodesWithDates}</div>
            <div style="color: #dc3545;"><strong>Missing Dates:</strong> ${episodesWithoutDates}</div>
            ${videoCountText}
        `;
    }
}

// ===========================
// Authentication Functions
// ===========================

async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth/status');
        const authStatus = await response.json();
        
        const authStatusDiv = document.getElementById('auth-status');
        const authUsernameSpan = document.getElementById('auth-username');
        
        if (authStatus.auth_enabled && authStatus.authenticated) {
            // Show authentication status with username
            authUsernameSpan.textContent = authStatus.username;
            authStatusDiv.style.display = 'flex';
        } else if (authStatus.auth_enabled && !authStatus.authenticated) {
            // This shouldn't happen if middleware is working, but handle it
            console.warn('Auth enabled but not authenticated - middleware may be misconfigured');
        } else {
            // Authentication disabled - hide auth status
            authStatusDiv.style.display = 'none';
        }
        
    } catch (error) {
        console.error('Failed to check authentication status:', error);
        // Hide auth status on error
        document.getElementById('auth-status').style.display = 'none';
    }
}

// Manual Scan Functions
async function handleManualScan(event) {
    event.preventDefault();
    
    const scanType = document.getElementById('scan-type').value;
    const scanMode = document.getElementById('scan-mode').value;
    const scanPath = document.getElementById('scan-path').value.trim();
    
    // Validate inputs
    if (!scanType || !scanMode) {
        showToast('❌ Please select scan type and mode', 'error');
        return;
    }
    
    // Build query parameters
    const params = new URLSearchParams({
        scan_type: scanType,
        scan_mode: scanMode
    });
    
    if (scanPath) {
        params.append('path', scanPath);
    }
    
    try {
        // Show scan status
        showScanStatus();
        
        // Start the scan
        showToast('🚀 Starting manual scan...', 'info');
        const response = await fetch(`/manual/scan?${params}`, {
            method: 'POST',
            credentials: 'include'
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const result = await response.json();
        
        if (result.status === 'started') {
            showToast('✅ Scan started successfully', 'success');
            // Start polling for status
            startScanPolling();
        } else {
            showToast(`ℹ️ ${result.message || 'Scan completed'}`, 'info');
            hideScanStatus();
        }
        
    } catch (error) {
        console.error('Manual scan failed:', error);
        showToast(`❌ Scan failed: ${error.message}`, 'error');
        hideScanStatus();
    }
}

function showScanStatus() {
    const scanStatus = document.getElementById('scan-status');
    const progressBar = document.getElementById('scan-progress-bar');
    const operationText = document.getElementById('scan-current-operation');
    const progressText = document.getElementById('scan-progress-text');
    
    // Reset and show
    progressBar.style.width = '0%';
    operationText.textContent = 'Initializing scan...';
    progressText.textContent = '0%';
    scanStatus.style.display = 'block';
}

function hideScanStatus() {
    document.getElementById('scan-status').style.display = 'none';
    if (window.scanPollingInterval) {
        clearInterval(window.scanPollingInterval);
        window.scanPollingInterval = null;
    }
}

function stopScanPolling() {
    hideScanStatus();
}

function startScanPolling() {
    // Poll every 2 seconds for scan status
    window.scanPollingInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/scan/status');
            if (!response.ok) {
                throw new Error('Failed to get scan status');
            }
            
            const status = await response.json();
            updateScanProgress(status);
            
            // Stop polling if scan is complete
            if (!status.scanning) {
                stopScanPolling();
                showToast('✅ Scan completed!', 'success');
            }
            
        } catch (error) {
            console.error('Failed to poll scan status:', error);
            // Don't show error toast repeatedly, just stop polling
            stopScanPolling();
        }
    }, 2000);
}

function updateScanProgress(status) {
    const progressBar = document.getElementById('scan-progress-bar');
    const operationText = document.getElementById('scan-current-operation');
    const progressText = document.getElementById('scan-progress-text');
    
    if (!status.scanning) {
        progressBar.style.width = '100%';
        operationText.textContent = 'Scan completed';
        progressText.textContent = '100%';
        return;
    }
    
    // Calculate overall progress
    let totalProgress = 0;
    let progressDetails = '';
    
    if (status.scan_type === 'both' || status.scan_type === 'tv') {
        const tvProgress = status.tv_series_total > 0 ? 
            ((status.tv_series_processed + status.tv_series_skipped) / status.tv_series_total) * 50 : 0;
        totalProgress += tvProgress;
        
        if (status.tv_series_total > 0) {
            progressDetails += `TV: ${status.tv_series_processed + status.tv_series_skipped}/${status.tv_series_total} `;
        }
    }
    
    if (status.scan_type === 'both' || status.scan_type === 'movies') {
        const movieProgress = status.movies_total > 0 ? 
            ((status.movies_processed + status.movies_skipped) / status.movies_total) * 50 : 0;
        totalProgress += movieProgress;
        
        if (status.movies_total > 0) {
            progressDetails += `Movies: ${status.movies_processed + status.movies_skipped}/${status.movies_total}`;
        }
    }
    
    // For single type scans, use full 100%
    if (status.scan_type !== 'both') {
        totalProgress *= 2;
    }
    
    // Update progress bar
    progressBar.style.width = `${Math.min(totalProgress, 100)}%`;
    progressText.textContent = `${Math.round(totalProgress)}%`;
    
    // Update operation text
    if (status.current_operation) {
        operationText.textContent = status.current_operation;
    } else if (status.current_item) {
        operationText.textContent = `Processing: ${status.current_item}`;
    } else {
        operationText.textContent = progressDetails || 'Scanning...';
    }
}

// Manual Cleanup Functions
async function handleManualCleanup(event) {
    event.preventDefault();

    const checkMovies = document.getElementById('cleanup-movies').checked;
    const checkSeries = document.getElementById('cleanup-series').checked;
    const checkFilesystem = document.getElementById('cleanup-filesystem').checked;
    const checkDatabase = document.getElementById('cleanup-database').checked;
    const dryRun = document.getElementById('cleanup-dry-run').checked;

    // Validate at least one media type is selected
    if (!checkMovies && !checkSeries) {
        showToast('❌ Please select at least one media type to check', 'error');
        return;
    }

    // Validate at least one validation method is selected
    if (!checkFilesystem && !checkDatabase) {
        showToast('❌ Please select at least one validation method', 'error');
        return;
    }

    try {
        // Show cleanup status
        showCleanupStatus();

        // Start the cleanup
        const mode = dryRun ? 'Preview' : 'Cleanup';
        showToast(`🧹 Starting ${mode.toLowerCase()}...`, 'info');

        const response = await fetch('/manual/cleanup-orphaned', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                check_movies: checkMovies,
                check_series: checkSeries,
                check_filesystem: checkFilesystem,
                check_database: checkDatabase,
                dry_run: dryRun
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();

        if (result.success) {
            showToast(`✅ ${mode} completed successfully`, 'success');
            displayCleanupResults(result.report, dryRun);
        } else {
            showToast(`❌ ${mode} failed: ${result.message || 'Unknown error'}`, 'error');
            hideCleanupStatus();
        }

    } catch (error) {
        console.error('Manual cleanup failed:', error);
        showToast(`❌ Cleanup failed: ${error.message}`, 'error');
        hideCleanupStatus();
    }
}

function showCleanupStatus() {
    const cleanupStatus = document.getElementById('cleanup-status');
    const cleanupResults = document.getElementById('cleanup-results');

    // Reset and show
    cleanupResults.innerHTML = '<p><i class="fas fa-spinner fa-spin"></i> Running cleanup...</p>';
    cleanupStatus.style.display = 'block';
}

function hideCleanupStatus() {
    document.getElementById('cleanup-status').style.display = 'none';
}

function displayCleanupResults(report, dryRun) {
    const cleanupResults = document.getElementById('cleanup-results');

    const mode = dryRun ? 'Would be removed' : 'Removed';
    const modeClass = dryRun ? 'warning' : 'danger';

    let html = `
        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-top: 10px;">
            <h4 style="margin-top: 0; color: #333;">
                <i class="fas fa-${dryRun ? 'eye' : 'check-circle'}"></i>
                ${dryRun ? 'Preview Results' : 'Cleanup Results'}
            </h4>
    `;

    // Movies section
    if (report.movies) {
        html += `
            <div style="margin-bottom: 15px;">
                <h5 style="color: #666; margin-bottom: 8px;">
                    <i class="fas fa-film"></i> Movies
                </h5>
                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; padding-left: 20px;">
                    <div>Total checked: <strong>${report.movies.total_checked || 0}</strong></div>
                    <div class="badge badge-${modeClass}">${mode}: <strong>${report.movies.removed || 0}</strong></div>
                    <div>Missing from filesystem: ${report.movies.missing_filesystem || 0}</div>
                    <div>Missing from database: ${report.movies.missing_database || 0}</div>
                </div>
        `;

        if (report.movies.removed_items && report.movies.removed_items.length > 0) {
            html += `
                <details style="margin-top: 10px;">
                    <summary style="cursor: pointer; color: #007bff;">View ${mode} items (${report.movies.removed_items.length})</summary>
                    <ul style="margin-top: 10px; padding-left: 20px; max-height: 200px; overflow-y: auto;">
            `;
            report.movies.removed_items.forEach(item => {
                html += `<li style="font-size: 0.9em; margin-bottom: 5px;">${escapeHtml(item)}</li>`;
            });
            html += `
                    </ul>
                </details>
            `;
        }

        html += `</div>`;
    }

    // TV Series section
    if (report.series) {
        html += `
            <div style="margin-bottom: 15px;">
                <h5 style="color: #666; margin-bottom: 8px;">
                    <i class="fas fa-tv"></i> TV Series
                </h5>
                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; padding-left: 20px;">
                    <div>Total checked: <strong>${report.series.total_checked || 0}</strong></div>
                    <div class="badge badge-${modeClass}">${mode}: <strong>${report.series.removed || 0}</strong></div>
                    <div>Episodes removed: <strong>${report.series.removed_episodes || 0}</strong></div>
                    <div>Missing from database: ${report.series.missing_database || 0}</div>
                </div>
        `;

        if (report.series.removed_items && report.series.removed_items.length > 0) {
            html += `
                <details style="margin-top: 10px;">
                    <summary style="cursor: pointer; color: #007bff;">View ${mode} series (${report.series.removed_items.length})</summary>
                    <ul style="margin-top: 10px; padding-left: 20px; max-height: 200px; overflow-y: auto;">
            `;
            report.series.removed_items.forEach(item => {
                html += `<li style="font-size: 0.9em; margin-bottom: 5px;">${escapeHtml(item)}</li>`;
            });
            html += `
                    </ul>
                </details>
            `;
        }

        html += `</div>`;
    }

    // Summary
    const totalRemoved = (report.movies?.removed || 0) + (report.series?.removed || 0) + (report.series?.removed_episodes || 0);
    html += `
        <div style="margin-top: 15px; padding-top: 15px; border-top: 2px solid #dee2e6;">
            <strong>Total ${mode}:</strong>
            <span style="color: ${dryRun ? '#ff9800' : '#dc3545'}; font-size: 1.2em;">
                ${totalRemoved} items
            </span>
        </div>
    `;

    if (dryRun) {
        html += `
            <div style="margin-top: 10px; padding: 10px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;">
                <i class="fas fa-info-circle"></i> This was a <strong>dry run</strong>. No changes were made. Uncheck "Dry Run" to perform actual cleanup.
            </div>
        `;
    }

    html += `</div>`;

    cleanupResults.innerHTML = html;
}

async function logout() {
    if (!confirm('Are you sure you want to logout?')) {
        return;
    }
    
    try {
        const response = await fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'same-origin'
        });
        
        if (response.ok) {
            showToast('✅ Logged out successfully', 'success');
            // Reload page to trigger authentication prompt
            setTimeout(() => {
                window.location.reload();
            }, 1500);
        } else {
            showToast('❌ Logout failed', 'error');
        }
        
    } catch (error) {
        console.error('Logout failed:', error);
        showToast('❌ Logout error', 'error');
    }
}

// Bulk delete functions for TV episodes
function toggleSelectAll() {
    const selectAllCheckbox = document.getElementById('select-all-checkbox');
    const episodeCheckboxes = document.querySelectorAll('.episode-checkbox');
    
    if (selectAllCheckbox && episodeCheckboxes.length > 0) {
        const shouldCheck = selectAllCheckbox.checked;
        episodeCheckboxes.forEach(checkbox => {
            checkbox.checked = shouldCheck;
        });
        updateBulkDeleteButton();
    }
}

function updateBulkDeleteButton() {
    const selectedCheckboxes = document.querySelectorAll('.episode-checkbox:checked');
    const selectedCount = selectedCheckboxes.length;
    const bulkDeleteButton = document.getElementById('bulk-delete-selected');
    const bulkUpdateButton = document.getElementById('bulk-update-dates');
    const selectedCountSpan = document.getElementById('selected-count');
    const updateCountSpan = document.getElementById('update-count');

    if (selectedCountSpan) {
        selectedCountSpan.textContent = selectedCount;
    }

    if (updateCountSpan) {
        updateCountSpan.textContent = selectedCount;
    }

    if (bulkDeleteButton) {
        bulkDeleteButton.disabled = selectedCount === 0;
    }

    if (bulkUpdateButton) {
        bulkUpdateButton.disabled = selectedCount === 0;
    }

    // Update select all checkbox state
    const selectAllCheckbox = document.getElementById('select-all-checkbox');
    const allCheckboxes = document.querySelectorAll('.episode-checkbox');
    if (selectAllCheckbox && allCheckboxes.length > 0) {
        selectAllCheckbox.checked = selectedCount === allCheckboxes.length;
        selectAllCheckbox.indeterminate = selectedCount > 0 && selectedCount < allCheckboxes.length;
    }
}

async function bulkDeleteSelected() {
    const selectedCheckboxes = document.querySelectorAll('.episode-checkbox:checked');
    const selectedCount = selectedCheckboxes.length;
    
    if (selectedCount === 0) {
        showToast('❌ No episodes selected', 'error');
        return;
    }
    
    if (!confirm(`Are you sure you want to delete ${selectedCount} episode(s)? This action cannot be undone.`)) {
        return;
    }
    
    const bulkDeleteButton = document.getElementById('bulk-delete-selected');
    const originalText = bulkDeleteButton.innerHTML;
    bulkDeleteButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Deleting...';
    bulkDeleteButton.disabled = true;
    
    let successCount = 0;
    let failCount = 0;
    
    // Process deletions
    for (const checkbox of selectedCheckboxes) {
        const row = checkbox.closest('tr');
        const imdbId = row.getAttribute('data-imdb');
        const season = parseInt(row.getAttribute('data-season'));
        const episode = parseInt(row.getAttribute('data-episode'));
        
        try {
            const response = await apiCall(`/api/episodes/${imdbId}/${season}/${episode}`, {
                method: 'DELETE'
            });
            
            if (response.success) {
                // Remove the row from the table
                row.remove();
                successCount++;
            } else {
                failCount++;
                console.error(`Failed to delete S${season.toString().padStart(2, '0')}E${episode.toString().padStart(2, '0')}:`, response.message);
            }
        } catch (error) {
            failCount++;
            console.error(`Error deleting S${season.toString().padStart(2, '0')}E${episode.toString().padStart(2, '0')}:`, error);
        }
    }
    
    // Update UI
    updateEpisodeModalCounts();
    updateBulkDeleteButton();

    // Reset button
    bulkDeleteButton.innerHTML = originalText;
    bulkDeleteButton.disabled = true;

    // Show results
    if (successCount > 0 && failCount === 0) {
        showToast(`✅ Successfully deleted ${successCount} episode(s)`, 'success');
    } else if (successCount > 0 && failCount > 0) {
        showToast(`⚠️ Deleted ${successCount} episode(s), ${failCount} failed`, 'warning');
    } else {
        showToast(`❌ Failed to delete ${failCount} episode(s)`, 'error');
    }
}

// Bulk update dates functions
function showBulkUpdateModal() {
    const selectedCheckboxes = document.querySelectorAll('.episode-checkbox:checked');
    const selectedCount = selectedCheckboxes.length;

    if (selectedCount === 0) {
        showToast('❌ No episodes selected', 'error');
        return;
    }

    const modal = document.getElementById('bulk-update-modal');
    const modalSelectedCount = document.getElementById('modal-selected-count');
    const dateSourceSelect = document.getElementById('bulk-date-source');
    const customDateInput = document.getElementById('custom-date-input');

    if (modalSelectedCount) {
        modalSelectedCount.textContent = selectedCount;
    }

    // Show/hide custom date input based on selection
    if (dateSourceSelect) {
        dateSourceSelect.onchange = function() {
            if (customDateInput) {
                customDateInput.style.display = this.value === 'custom' ? 'block' : 'none';
            }
        };
    }

    if (modal) {
        modal.style.display = 'flex';
    }
}

function closeBulkUpdateModal() {
    const modal = document.getElementById('bulk-update-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

async function executeBulkUpdate() {
    const selectedCheckboxes = document.querySelectorAll('.episode-checkbox:checked');
    const selectedCount = selectedCheckboxes.length;
    const dateSource = document.getElementById('bulk-date-source').value;
    const customDate = document.getElementById('bulk-custom-date').value;

    if (selectedCount === 0) {
        showToast('❌ No episodes selected', 'error');
        return;
    }

    if (dateSource === 'custom' && !customDate) {
        showToast('❌ Please enter a custom date', 'error');
        return;
    }

    // Close modal
    closeBulkUpdateModal();

    // Collect selected episodes
    const episodes = [];
    selectedCheckboxes.forEach(checkbox => {
        const row = checkbox.closest('tr');
        episodes.push({
            imdb_id: row.getAttribute('data-imdb'),
            season: parseInt(row.getAttribute('data-season')),
            episode: parseInt(row.getAttribute('data-episode'))
        });
    });

    // Show progress
    showToast(`⏳ Updating ${selectedCount} episode(s)...`, 'info');

    try {
        const response = await apiCall('/api/episodes/bulk-update-dates', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                episodes: episodes,
                date_source: dateSource,
                custom_date: customDate || null
            })
        });

        if (response.success) {
            showToast(`✅ Successfully updated ${response.updated || selectedCount} episode(s)`, 'success');

            // Reload the current series to show updated dates
            const currentImdbId = currentTVSeries;
            if (currentImdbId) {
                loadEpisodes(currentImdbId);
            }

            // Clear selections
            selectedCheckboxes.forEach(checkbox => checkbox.checked = false);
            updateBulkDeleteButton();
        } else {
            showToast(`❌ ${response.message || 'Failed to update episodes'}`, 'error');
        }
    } catch (error) {
        console.error('Bulk update error:', error);
        showToast('❌ Error updating episodes', 'error');
    }
}

// ==================== Database Population Functions ====================

let populatePollingInterval = null;

async function handlePopulateDatabase(event) {
    event.preventDefault();

    const mediaType = document.getElementById('populate-media-type').value;
    const submitButton = event.target.querySelector('button[type="submit"]');
    const originalText = submitButton.innerHTML;

    // Confirm action
    const confirmMsg = mediaType === 'both'
        ? 'This will populate the database with ALL movies and TV episodes from Radarr/Sonarr. Continue?'
        : mediaType === 'movies'
        ? 'This will populate the database with ALL movies from Radarr. Continue?'
        : 'This will populate the database with ALL TV episodes from Sonarr. Continue?';

    if (!confirm(confirmMsg)) {
        return;
    }

    // Disable button and show loading
    submitButton.disabled = true;
    submitButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';

    try {
        const response = await fetch('/admin/populate-database', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ media_type: mediaType })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        if (data.status === 'started') {
            showPopulateStatus();
            startPopulatePolling();
        } else {
            throw new Error('Failed to start population');
        }

    } catch (error) {
        console.error('Error starting population:', error);
        showToast('❌ Failed to start database population', 'error');
        submitButton.disabled = false;
        submitButton.innerHTML = originalText;
    }
}

function showPopulateStatus() {
    const statusDiv = document.getElementById('populate-status');
    const resultsDiv = document.getElementById('populate-results');
    const progressBar = document.getElementById('populate-progress-bar');
    const progressText = document.getElementById('populate-progress-text');

    if (statusDiv) {
        statusDiv.style.display = 'block';
    }

    if (progressBar) {
        progressBar.style.width = '0%';
    }

    if (progressText) {
        progressText.textContent = 'Starting...';
    }

    if (resultsDiv) {
        resultsDiv.style.display = 'none';
    }
}

function hidePopulateStatus() {
    const statusDiv = document.getElementById('populate-status');
    if (statusDiv) {
        statusDiv.style.display = 'none';
    }
}

function startPopulatePolling() {
    // Clear any existing interval
    if (populatePollingInterval) {
        clearInterval(populatePollingInterval);
    }

    // Poll every 2 seconds
    populatePollingInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/populate/status');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const status = await response.json();
            updatePopulateProgress(status);

            // Stop polling if complete or error (API returns "completed": true/false and "error": string)
            if (status.completed || status.error) {
                stopPopulatePolling();

                // Re-enable submit button
                const submitButton = document.querySelector('#populate-form button[type="submit"]');
                if (submitButton) {
                    submitButton.disabled = false;
                    submitButton.innerHTML = '<i class="fas fa-play"></i> Start Population';
                }
            }

        } catch (error) {
            console.error('Error polling populate status:', error);
            stopPopulatePolling();

            // Re-enable submit button
            const submitButton = document.querySelector('#populate-form button[type="submit"]');
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.innerHTML = '<i class="fas fa-play"></i> Start Population';
            }
        }
    }, 2000);
}

function stopPopulatePolling() {
    if (populatePollingInterval) {
        clearInterval(populatePollingInterval);
        populatePollingInterval = null;
    }
}

function updatePopulateProgress(status) {
    const progressBar = document.getElementById('populate-progress-bar');
    const progressText = document.getElementById('populate-progress-text');
    const resultsDiv = document.getElementById('populate-results');

    // Handle running status (API returns "running": true/false)
    if (status.running && !status.completed) {
        if (progressBar) {
            // Show indeterminate progress
            progressBar.style.width = '50%';
        }
        if (progressText) {
            progressText.textContent = 'Populating database...';
        }
    } else if (status.completed) {
        if (progressBar) {
            progressBar.style.width = '100%';
        }
        if (progressText) {
            progressText.textContent = 'Complete!';
        }

        // Show results (API returns movies/tv with nested stats)
        if (resultsDiv && (status.movies || status.tv)) {
            let html = '<h4>Population Results</h4>';

            // Movies
            if (status.movies && status.movies.stats) {
                const m = status.movies.stats;
                html += '<div class="populate-section">';
                html += '<h5><i class="fas fa-film"></i> Movies</h5>';
                html += '<ul>';
                html += `<li>Total found: ${m.total || 0}</li>`;
                html += `<li>Added: ${m.added || 0}</li>`;
                html += `<li>Skipped: ${m.skipped || 0}</li>`;
                html += `<li>Errors: ${m.errors || 0}</li>`;
                html += `<li>Duration: ${(m.duration || 0).toFixed(2)}s</li>`;
                html += '</ul>';
                // Show skipped items if any
                if (m.skipped_items && m.skipped_items.length > 0) {
                    html += '<details style="margin-top: 10px;"><summary>Skipped Movies (' + m.skipped_items.length + ')</summary><ul>';
                    m.skipped_items.forEach(item => {
                        html += `<li><strong>${item.title || 'Unknown'}</strong> (${item.year || 'N/A'}) [${item.imdb_id || 'No IMDb'}] - ${item.reason}</li>`;
                    });
                    html += '</ul></details>';
                }
                html += '</div>';
            }

            // TV Episodes
            if (status.tv && status.tv.stats) {
                const tv = status.tv.stats;
                html += '<div class="populate-section">';
                html += '<h5><i class="fas fa-tv"></i> TV Shows</h5>';
                html += '<ul>';
                html += `<li>Series: ${tv.total_series || 0}</li>`;
                html += `<li>Episodes: ${tv.total_episodes || 0}</li>`;
                html += `<li>Added: ${tv.added || 0}</li>`;
                html += `<li>Skipped: ${tv.skipped || 0}</li>`;
                html += `<li>Errors: ${tv.errors || 0}</li>`;
                html += `<li>Duration: ${(tv.duration || 0).toFixed(2)}s</li>`;
                html += '</ul>';
                // Show skipped items if any
                if (tv.skipped_items && tv.skipped_items.length > 0) {
                    html += '<details style="margin-top: 10px;"><summary>Skipped Episodes (' + tv.skipped_items.length + ')</summary><ul>';
                    tv.skipped_items.forEach(item => {
                        html += `<li><strong>${item.title || 'Unknown'}</strong> S${String(item.season).padStart(2,'0')}E${String(item.episode).padStart(2,'0')} - ${item.reason}</li>`;
                    });
                    html += '</ul></details>';
                }
                html += '</div>';
            }

            resultsDiv.innerHTML = html;
            resultsDiv.style.display = 'block';
        }

        showToast('✅ Database population completed successfully', 'success');

    } else if (status.status === 'error') {
        if (progressFill && progressText) {
            progressFill.style.width = '100%';
            progressFill.style.backgroundColor = '#dc3545';
            progressText.textContent = 'Error!';
        }

        const errorMsg = status.error || 'Unknown error occurred';
        showToast(`❌ Database population failed: ${errorMsg}`, 'error');

        if (resultsDiv) {
            resultsDiv.innerHTML = `<p class="error">Error: ${errorMsg}</p>`;
            resultsDiv.style.display = 'block';
        }
    }
}

// ==================== Table Sorting Functions ====================

let sortDirections = {}; // Track sort direction for each table column

function sortTable(tableBodyId, columnIndex, dataType) {
    const tbody = document.getElementById(tableBodyId);
    if (!tbody) return;

    const sortKey = `${tableBodyId}-${columnIndex}`;

    // Toggle sort direction
    if (!sortDirections[sortKey]) {
        sortDirections[sortKey] = 'asc';
    } else {
        sortDirections[sortKey] = sortDirections[sortKey] === 'asc' ? 'desc' : 'asc';
    }

    const rows = Array.from(tbody.querySelectorAll('tr'));

    rows.sort((a, b) => {
        const aCell = a.cells[columnIndex];
        const bCell = b.cells[columnIndex];

        if (!aCell || !bCell) return 0;

        let aValue = aCell.textContent.trim();
        let bValue = bCell.textContent.trim();

        // Handle MISSING values - always sort to bottom
        if (aValue === 'MISSING') return 1;
        if (bValue === 'MISSING') return -1;

        // Handle different data types
        if (dataType === 'date') {
            // Parse dates for comparison
            aValue = aValue === '-' ? '' : aValue;
            bValue = bValue === '-' ? '' : bValue;

            if (!aValue && !bValue) return 0;
            if (!aValue) return 1;
            if (!bValue) return -1;

            const aDate = new Date(aValue);
            const bDate = new Date(bValue);

            if (sortDirections[sortKey] === 'asc') {
                return aDate - bDate;
            } else {
                return bDate - aDate;
            }
        } else if (dataType === 'number') {
            const aNum = parseFloat(aValue) || 0;
            const bNum = parseFloat(bValue) || 0;

            if (sortDirections[sortKey] === 'asc') {
                return aNum - bNum;
            } else {
                return bNum - aNum;
            }
        } else {
            // Text comparison
            if (sortDirections[sortKey] === 'asc') {
                return aValue.localeCompare(bValue);
            } else {
                return bValue.localeCompare(aValue);
            }
        }
    });

    // Re-append sorted rows
    rows.forEach(row => tbody.appendChild(row));

    // Update sort icons
    updateSortIcons(tableBodyId, columnIndex, sortDirections[sortKey]);
}

function updateSortIcons(tableBodyId, activeColumn, direction) {
    // Find the table and update icons
    const tbody = document.getElementById(tableBodyId);
    if (!tbody) return;

    const table = tbody.closest('table');
    if (!table) return;

    const headers = table.querySelectorAll('th.sortable');
    headers.forEach((header, index) => {
        const icon = header.querySelector('i');
        if (!icon) return;

        // +1 to account for checkbox column
        if (index + 1 === activeColumn) {
            icon.className = direction === 'asc' ? 'fas fa-sort-up' : 'fas fa-sort-down';
        } else {
            icon.className = 'fas fa-sort';
        }
    });
}
