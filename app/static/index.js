const inputIds = [
  'character_level',
  'primary_playstyle',
  'primary_weapon_type',
  'preferred_weapons',
  'armor_type',
  'health_model',
  'combat_style',
  'team_preference',
  'mutation_preference',
  'qol_preference',
  'legendary_perk_availability',
  'current_gear',
  'avoid_list',
];

const state = {
  perksById: {},
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function titleFromKey(key) {
  return String(key)
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function buildRequestBody() {
  const body = {};
  inputIds.forEach((id) => {
    body[id] = $(id).value;
  });
  return body;
}

function setLoading(isLoading) {
  const button = $('generateBtn');
  button.disabled = isLoading;
  button.textContent = isLoading ? 'Creating...' : 'Create Build';
}

function saveRecentBuild(build) {
  try {
    const current = JSON.parse(localStorage.getItem('fo76RecentBuilds') || '[]');
    const next = [
      {
        id: build.id,
        name: build.build_name,
        status: build.validation_status,
        logic_engine: build.logic_engine,
      },
      ...current.filter((item) => item.id !== build.id),
    ].slice(0, 6);
    localStorage.setItem('fo76RecentBuilds', JSON.stringify(next));
  } catch {
    return;
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

async function loadSources() {
  const list = $('sourceList');
  if (!list) return;
  try {
    const response = await fetch('/api/sources');
    const sources = await response.json();
    list.innerHTML = sources.map((source) => `
      <a href="${escapeHtml(source.source_url)}" target="_blank" rel="noreferrer">
        <strong>${escapeHtml(source.source_name)}</strong>
        <small>${escapeHtml(source.source_type)} - reliability ${escapeHtml(source.reliability_score)}</small>
      </a>
    `).join('');
  } catch {
    list.innerHTML = '<p class="empty-state">Source registry unavailable.</p>';
  }
}

async function loadPerks() {
  try {
    const response = await fetch('/api/perks');
    const perks = await response.json();
    state.perksById = Object.fromEntries(perks.map((perk) => [perk.id, perk]));
  } catch {
    state.perksById = {};
  }
}

function renderSpecial(allocation) {
  const order = ['Strength', 'Perception', 'Endurance', 'Charisma', 'Intelligence', 'Agility', 'Luck'];
  return `
    <div class="special-grid">
      ${order.map((name) => {
        const value = Number(allocation?.[name] ?? 0);
        const width = Math.max(0, Math.min(100, (value / 15) * 100));
        return `
          <div class="special-row">
            <strong>${escapeHtml(name[0])}</strong>
            <div class="bar" aria-label="${escapeHtml(name)} ${value}">
              <span style="width:${width}%"></span>
            </div>
            <span>${value}</span>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function renderPerks(perksBySpecial) {
  const entries = Object.entries(perksBySpecial || {}).filter(([, cards]) => cards.length);
  if (!entries.length) {
    return '<p class="empty-state">No perk cards returned.</p>';
  }
  return `
    <div class="perk-grid">
      ${entries.map(([special, cards]) => `
        <div class="perk-special">
          <strong>${escapeHtml(special)}</strong>
          ${cards.map((card) => {
            const perk = state.perksById[card.card_id];
            const effect = perk?.effect_by_rank?.[card.rank] || perk?.effect_by_rank?.[String(card.rank)] || card.why;
            return `
              <div class="perk-card">
                <strong>${escapeHtml(perk?.name || card.card_id)} rank ${escapeHtml(card.rank)}</strong>
                <small>${escapeHtml(card.role)} - ${escapeHtml(effect)}</small>
              </div>
            `;
          }).join('')}
        </div>
      `).join('')}
    </div>
  `;
}

function renderObjectLists(title, value) {
  const entries = Object.entries(value || {});
  if (!entries.length) return '';
  return `
    <section class="result-section full">
      <h2>${escapeHtml(title)}</h2>
      <div class="gear-grid">
        ${entries.map(([key, items]) => `
          <div class="gear-card">
            <strong>${escapeHtml(titleFromKey(key))}</strong>
            <ul>${(items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
          </div>
        `).join('')}
      </div>
    </section>
  `;
}

function renderDictList(title, items, primaryKey = 'name') {
  if (!items?.length) return '';
  return `
    <section class="result-section">
      <h2>${escapeHtml(title)}</h2>
      <div class="perk-grid">
        ${items.map((item) => `
          <div class="gear-card">
            <strong>${escapeHtml(item[primaryKey] || item.card_id || 'Entry')}</strong>
            <small>${Object.entries(item)
              .filter(([key]) => key !== primaryKey)
              .map(([key, value]) => `${titleFromKey(key)}: ${value}`)
              .map(escapeHtml)
              .join(' - ')}</small>
          </div>
        `).join('')}
      </div>
    </section>
  `;
}

function renderCleanList(title, items, warning = false) {
  if (!items?.length) return '';
  return `
    <section class="result-section ${warning ? 'full' : ''}">
      <h2>${escapeHtml(title)}</h2>
      <div class="${warning ? 'warning-card' : ''}">
        <ul class="clean-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
      </div>
    </section>
  `;
}

function renderSearchResults(results) {
  if (!results?.length) return '';
  return `
    <section class="result-section full">
      <h2>Web Search Evidence</h2>
      <div class="source-list">
        ${results.map((result) => `
          <a href="${escapeHtml(result.url)}" target="_blank" rel="noreferrer">
            <strong>${escapeHtml(result.title)}</strong>
            <small>${escapeHtml(result.content || result.url)}</small>
          </a>
        `).join('')}
      </div>
    </section>
  `;
}

function renderBuild(payload) {
  const build = payload.build;
  const panel = $('resultPanel');
  const brainNotes = [
    ...(build.brain_notes || []),
    ...((payload.brain?.notes || []).filter((note) => !(build.brain_notes || []).includes(note))),
  ];
  panel.classList.remove('hidden');
  panel.innerHTML = `
    <div class="section-head">
      <div>
        <p class="eyebrow">Generated build</p>
        <h1>${escapeHtml(build.build_name)}</h1>
        <div class="meta-row">
          <span>${escapeHtml(build.id)}</span>
          <span>${escapeHtml(build.validation_status)}</span>
          <span>${escapeHtml(build.logic_engine)}</span>
        </div>
      </div>
      <button id="copyBuildId" class="secondary-action" type="button">Copy ID</button>
    </div>

    <div class="result-grid">
      <section class="result-section">
        <h2>SPECIAL</h2>
        ${renderSpecial(build.special_allocation)}
      </section>

      <section class="result-section">
        <h2>Core Perks</h2>
        ${renderPerks(build.perk_cards_by_special)}
      </section>

      ${renderDictList('Legendary Perks', build.legendary_perks)}
      ${renderDictList('Mutations', build.mutations)}
      ${renderObjectLists('Gear', build.gear)}
      ${renderObjectLists('Variants', build.variants)}
      ${renderObjectLists('Swap Cards', build.swap_cards)}
      ${renderCleanList('Assumptions', build.assumptions)}
      ${renderCleanList('Weaknesses', build.weaknesses, true)}
      ${renderCleanList('Validation Issues', payload.issues, true)}
      ${renderCleanList('Brain Notes', brainNotes)}
      ${renderSearchResults(build.web_search_results)}
      ${renderCleanList('Source Verification', build.source_verification_notes)}

      <section class="result-section full">
        <h2>Raw Payload</h2>
        <pre class="raw-json">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
      </section>
    </div>
  `;
  $('copyBuildId')?.addEventListener('click', async () => {
    await navigator.clipboard?.writeText(build.id);
  });
  saveRecentBuild(build);
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderError(error) {
  const panel = $('resultPanel');
  panel.classList.remove('hidden');
  panel.innerHTML = `
    <div class="warning-card">
      <h2>Build request failed</h2>
      <p>${escapeHtml(error.message || error)}</p>
    </div>
  `;
}

async function generateBuild() {
  setLoading(true);
  try {
    const response = await fetch('/api/build/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildRequestBody()),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || 'Build generation failed');
    }
    renderBuild(payload);
  } catch (error) {
    renderError(error);
  } finally {
    setLoading(false);
  }
}

async function init() {
  $('generateBtn').addEventListener('click', generateBuild);
  await Promise.all([loadBrainStatus(), loadSources(), loadPerks()]);
}

init();
