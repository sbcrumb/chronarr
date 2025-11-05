// Chronarr Web Interface JavaScript

// Global state
let currentTab = 'dashboard';
let currentMoviesPage = 1;
let currentSeriesPage = 1;
let dashboardData = null;

// Initialize app
document.addEventListener('DOMContentLoaded', function() {
    initializeTabs();
    initializeEventListeners();
    checkAuthStatus();  // Check authentication status on page load
    loadDashboard();
    loadSeriesSources();
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
    document.getElementById('movies-search').addEventListener('input', debounce(loadMovies, 500));
    document.getElementById('movies-imdb-search').addEventListener('input', debounce(loadMovies, 500));
    document.getElementById('series-search').addEventListener('input', debounce(loadSeries, 500));
    document.getElementById('series-imdb-search').addEventListener('input', debounce(loadSeries, 500));
    
    // Filter dropdowns
    document.getElementById('movies-filter-date').addEventListener('change', loadMovies);
    document.getElementById('movies-filter-source').addEventListener('change', loadMovies);
    document.getElementById('series-filter-date').addEventListener('change', loadSeries);
    document.getElementById('series-filter-source').addEventListener('change', loadSeries);
    
    // Forms
    document.getElementById('edit-form').addEventListener('submit', handleEditSubmit);
    document.getElementById('bulk-update-form').addEventListener('submit', handleBulkUpdate);
    document.getElementById('manual-scan-form').addEventListener('submit', handleManualScan);
    document.getElementById('populate-form').addEventListener('submit', handlePopulateDatabase);
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
    const hasDate = document.getElementById('movies-filter-date').value;
    const sourceFilter = document.getElementById('movies-filter-source').value;
    
    const skip = (page - 1) * 100;
    console.log(`DEBUG: loadMovies called with page=${page}, calculated skip=${skip}`);
    
    const params = new URLSearchParams({
        skip: skip,
        limit: 100
    });
    
    if (search) params.append('search', search);
    if (imdbSearch) params.append('imdb_search', imdbSearch);
    if (hasDate) params.append('has_date', hasDate);
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
        
        return `
            <tr>
                <td>${escapeHtml(movie.title)}</td>
                <td><code>${movie.imdb_id}</code></td>
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
        tbody.innerHTML = '<tr><td colspan="6" class="text-center">No series found</td></tr>';
        return;
    }
    
    tbody.innerHTML = data.series.map(series => {
        const progressPercent = series.total_episodes > 0 ? 
            ((series.episodes_with_dates / series.total_episodes) * 100).toFixed(1) : 0;
        
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
                <td>
                    <button class="btn btn-sm btn-primary" onclick="viewSeriesEpisodes('${series.imdb_id}')">
                        <i class="fas fa-list"></i> Episodes
                    </button>
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
                        <button id="bulk-delete-selected" class="btn btn-sm btn-danger" onclick="bulkDeleteSelected()" style="margin-left: 10px;" disabled>
                            <i class="fas fa-trash"></i> Delete Selected (<span id="selected-count">0</span>)
                        </button>
                    </div>
                    <div class="table-container">
                        <table class="data-table">
                            <thead>
                                <tr>
                                    <th width="40px">
                                        <input type="checkbox" id="select-all-checkbox" onchange="toggleSelectAll()">
                                    </th>
                                    <th>Episode</th>
                                    <th>Aired</th>
                                    <th>Date Added</th>
                                    <th>Source</th>
                                    <th>Video</th>
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
            <button type="submit" class="btn btn-primary" onclick="handleEnhancedEditSubmit(event)">Save Changes</button>
        </div>
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
    
    const modal = document.getElementById('edit-modal');
    const options = JSON.parse(modal.dataset.options);
    const imdbId = options.imdb_id;
    const mediaType = document.getElementById('edit-media-type').value;
    const dateadded = document.getElementById('edit-dateadded').value;
    const source = document.getElementById('edit-source').value;
    
    if (!dateadded) {
        showToast('Please enter a date', 'warning');
        return;
    }
    
    // Convert datetime-local to ISO string with error handling
    let isoDateadded = null;
    try {
        isoDateadded = new Date(dateadded).toISOString();
    } catch (e) {
        showToast('Invalid date format', 'error');
        return;
    }
    
    try {
        if (mediaType === 'movie') {
            await updateMovieDate(imdbId, isoDateadded, source);
        } else {
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
    
    const imdbId = document.getElementById('edit-imdb-id').value;
    const mediaType = document.getElementById('edit-media-type').value;
    const season = document.getElementById('edit-season').value;
    const episode = document.getElementById('edit-episode').value;
    const dateadded = document.getElementById('edit-dateadded').value;
    const source = document.getElementById('edit-source').value;
    
    // Convert datetime-local to ISO string
    const isoDateadded = dateadded ? new Date(dateadded).toISOString() : null;
    
    try {
        if (mediaType === 'movie') {
            await updateMovieDate(imdbId, isoDateadded, source);
        } else {
            await updateEpisodeDate(imdbId, parseInt(season), parseInt(episode), isoDateadded, source);
        }
        
        closeModal();
    } catch (error) {
        console.error('Update failed:', error);
    }
}

// Update functions
async function updateMovieDate(imdbId, dateadded, source) {
    try {
        const result = await apiCall(`/api/movies/${imdbId}`, {
            method: 'PUT',
            body: JSON.stringify({
                dateadded: dateadded,
                source: source
            })
        });
        
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
    const selectedCountSpan = document.getElementById('selected-count');
    
    if (selectedCountSpan) {
        selectedCountSpan.textContent = selectedCount;
    }
    
    if (bulkDeleteButton) {
        bulkDeleteButton.disabled = selectedCount === 0;
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

// ---------------------------
// Database Population Functions
// ---------------------------

async function handlePopulateDatabase(event) {
    event.preventDefault();

    const mediaType = document.getElementById('populate-media-type').value;

    // Validate input
    if (!mediaType) {
        showToast('❌ Please select media type', 'error');
        return;
    }

    // Confirm with user
    const confirmMsg = `Are you sure you want to populate the database with ${mediaType}? This will query Radarr/Sonarr and may take several minutes.`;
    if (!confirm(confirmMsg)) {
        return;
    }

    try {
        // Show populate status
        showPopulateStatus();

        // Start the population
        showToast('🚀 Starting database population...', 'info');
        const response = await fetch(`/admin/populate-database?media_type=${mediaType}`, {
            method: 'POST',
            credentials: 'include'
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();

        if (result.status === 'started') {
            showToast('✅ Population started successfully', 'success');
            // Start polling for status
            startPopulatePolling();
        } else {
            showToast(`ℹ️ ${result.message || 'Population completed'}`, 'info');
            hidePopulateStatus();
        }

    } catch (error) {
        console.error('Database population failed:', error);
        showToast(`❌ Population failed: ${error.message}`, 'error');
        hidePopulateStatus();
    }
}

function showPopulateStatus() {
    const populateStatus = document.getElementById('populate-status');
    const progressBar = document.getElementById('populate-progress-bar');
    const operationText = document.getElementById('populate-current-operation');
    const progressText = document.getElementById('populate-progress-text');
    const resultsDiv = document.getElementById('populate-results');

    populateStatus.style.display = 'block';
    progressBar.style.width = '0%';
    operationText.textContent = 'Initializing...';
    progressText.textContent = '0%';
    resultsDiv.innerHTML = '';
}

function hidePopulateStatus() {
    const populateStatus = document.getElementById('populate-status');
    if (populateStatus) {
        populateStatus.style.display = 'none';
    }
}

function startPopulatePolling() {
    // Poll every 2 seconds for populate status
    window.populatePollingInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/populate/status');
            if (!response.ok) {
                throw new Error('Failed to get populate status');
            }

            const status = await response.json();
            updatePopulateProgress(status);

            // Stop polling if population is complete
            if (!status.running && status.completed) {
                stopPopulatePolling();
                showToast('✅ Database population completed!', 'success');
            }

        } catch (error) {
            console.error('Failed to poll populate status:', error);
            // Don't show error toast repeatedly, just stop polling
            stopPopulatePolling();
        }
    }, 2000);
}

function stopPopulatePolling() {
    if (window.populatePollingInterval) {
        clearInterval(window.populatePollingInterval);
        window.populatePollingInterval = null;
    }
}

function updatePopulateProgress(status) {
    const progressBar = document.getElementById('populate-progress-bar');
    const operationText = document.getElementById('populate-current-operation');
    const progressText = document.getElementById('populate-progress-text');
    const resultsDiv = document.getElementById('populate-results');

    if (status.error) {
        progressBar.style.width = '100%';
        progressBar.style.backgroundColor = '#e74c3c';
        operationText.textContent = 'Error occurred';
        progressText.textContent = 'Failed';
        resultsDiv.innerHTML = `<p style="color: #e74c3c;">Error: ${status.error}</p>`;
        return;
    }

    if (!status.running && status.completed) {
        progressBar.style.width = '100%';
        operationText.textContent = 'Population completed';
        progressText.textContent = '100%';

        // Display results
        let resultsHTML = '<h4>Population Results:</h4>';

        if (status.movies && status.movies.stats) {
            const m = status.movies.stats;
            resultsHTML += `
                <div style="margin: 10px 0;">
                    <strong>Movies:</strong><br>
                    Total: ${m.total || 0} | Added: ${m.added || 0} | Skipped: ${m.skipped || 0} | Errors: ${m.errors || 0}<br>
                    Duration: ${m.duration ? m.duration.toFixed(2) : 0}s
                </div>
            `;
        }

        if (status.tv && status.tv.stats) {
            const t = status.tv.stats;
            resultsHTML += `
                <div style="margin: 10px 0;">
                    <strong>TV Shows:</strong><br>
                    Series: ${t.total_series || 0} | Episodes: ${t.total_episodes || 0}<br>
                    Added: ${t.added || 0} | Skipped: ${t.skipped || 0} | Errors: ${t.errors || 0}<br>
                    Duration: ${t.duration ? t.duration.toFixed(2) : 0}s
                </div>
            `;
        }

        resultsDiv.innerHTML = resultsHTML;
        return;
    }

    // Update progress based on status
    let totalProgress = 0;
    let progressDetails = '';

    if (status.movies && status.movies.status === 'running') {
        totalProgress = 50;
        progressDetails = 'Processing movies...';
    } else if (status.movies && status.movies.status === 'completed') {
        totalProgress = 50;
        progressDetails = 'Movies completed, processing TV...';
    }

    if (status.tv && status.tv.status === 'running') {
        totalProgress = 75;
        progressDetails = 'Processing TV shows...';
    } else if (status.tv && status.tv.status === 'completed') {
        totalProgress = 100;
        progressDetails = 'Completed';
    }

    progressBar.style.width = `${totalProgress}%`;
    operationText.textContent = progressDetails;
    progressText.textContent = `${totalProgress}%`;
}
