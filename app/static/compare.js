const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function readRecentBuilds() {
  try {
    return JSON.parse(localStorage.getItem('fo76RecentBuilds') || '[]');
  } catch {
    return [];
  }
}

function renderBrainBadge(status) {
  const badge = $('brainBadge');
  if (!badge) return;
  if (status.enabled) {
    badge.textContent = `Brain: ${status.model}`;
    badge.classList.add('online');
    return;
  }
  badge.textContent = status.has_api_key ? 'Brain disabled' : 'Brain offline';
  badge.classList.remove('online');
}

async function loadBrainStatus() {
  try {
    const response = await fetch('/api/brain/status');
    renderBrainBadge(await response.json());
  } catch {
    renderBrainBadge({ enabled: false, has_api_key: false });
  }
}

function renderRecentBuilds() {
  const recent = readRecentBuilds();
  const target = $('recentBuilds');
  if (!recent.length) {
    target.innerHTML = '<span>No saved browser history yet</span>';
    return;
  }
  target.innerHTML = recent.map((build) => `
    <button class="mini-button" type="button" data-id="${escapeHtml(build.id)}">
      ${escapeHtml(build.id)}
    </button>
  `).join('');
  target.querySelectorAll('button').forEach((button) => {
    button.addEventListener('click', () => {
      const ids = $('ids');
      const current = ids.value.split(',').map((item) => item.trim()).filter(Boolean);
      if (!current.includes(button.dataset.id)) {
        ids.value = [...current, button.dataset.id].join(', ');
      }
    });
  });
}

function parseIds() {
  return $('ids').value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function renderComparison(payload) {
  const target = $('compareOut');
  target.classList.remove('hidden');
  const specialNames = ['Strength', 'Perception', 'Endurance', 'Charisma', 'Intelligence', 'Agility', 'Luck'];
  target.innerHTML = `
    <div class="section-head">
      <div>
        <p class="eyebrow">Comparison</p>
        <h1>${payload.build_ids.length} builds loaded</h1>
      </div>
    </div>

    <section class="result-section full">
      <h2>SPECIAL Spread</h2>
      <table class="compare-table">
        <thead>
          <tr>
            <th>Build</th>
            ${specialNames.map((name) => `<th>${escapeHtml(name[0])}</th>`).join('')}
          </tr>
        </thead>
        <tbody>
          ${payload.build_ids.map((id) => `
            <tr>
              <td>${escapeHtml(id)}</td>
              ${specialNames.map((name) => `<td>${escapeHtml(payload.special_diff[id]?.[name] ?? 0)}</td>`).join('')}
            </tr>
          `).join('')}
        </tbody>
      </table>
    </section>

    <section class="result-section full">
      <h2>Core Perk Lanes</h2>
      <div class="gear-grid">
        ${payload.build_ids.map((id) => `
          <div class="gear-card">
            <strong>${escapeHtml(id)}</strong>
            <ul>${(payload.core_perk_diff[id] || []).map((perk) => `<li>${escapeHtml(perk)}</li>`).join('')}</ul>
          </div>
        `).join('')}
      </div>
    </section>

    <section class="result-section full">
      <h2>Raw Payload</h2>
      <pre class="raw-json">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
    </section>
  `;
  target.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderError(error) {
  const target = $('compareOut');
  target.classList.remove('hidden');
  target.innerHTML = `
    <div class="warning-card">
      <h2>Compare failed</h2>
      <p>${escapeHtml(error.message || error)}</p>
    </div>
  `;
}

async function compareBuilds() {
  const buildIds = parseIds();
  if (buildIds.length < 2 || buildIds.length > 4) {
    renderError(new Error('Enter 2 to 4 build IDs.'));
    return;
  }

  const button = $('compareBtn');
  button.disabled = true;
  button.textContent = 'Comparing...';
  try {
    const response = await fetch('/api/build/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ build_ids: buildIds }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || 'Compare failed');
    }
    renderComparison(payload);
  } catch (error) {
    renderError(error);
  } finally {
    button.disabled = false;
    button.textContent = 'Compare';
  }
}

function init() {
  $('compareBtn').addEventListener('click', compareBuilds);
  renderRecentBuilds();
  loadBrainStatus();
}

init();
