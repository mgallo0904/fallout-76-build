const inputIds = [
  'goal',
  'generation_mode',
  'character_level',
  'character_type',
  'primary_playstyle',
  'primary_weapon_type',
  'preferred_weapons',
  'armor_type',
  'health_model',
  'combat_style',
  'team_preference',
  'qol_preference',
  'legendary_perk_availability',
  'current_gear',
  'avoid_list',
];

const state = {
  perksById: {},
  legendaryPerks: [],
  legendaryPerksById: {},
  brainPollTimers: {},
  currentBuild: null,
  revisionIntent: null,
  legendaryLoadout: [],
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
    let value = $(id).value;
    if (id === 'character_type' && value === 'Playable Ghoul') {
      value = 'Ghoul';
    }
    body[id] = value;
  });
  body.mutation_preference = selectedMutationPreference();
  body.revision_intent = state.revisionIntent || null;
  body.legendary_loadout = getLegendaryLoadout();
  return body;
}

function selectedMutationPreference() {
  const checked = [...document.querySelectorAll('#mutation_preference_group input[type="checkbox"]:checked')]
    .map((input) => input.value);
  if (checked.includes('No mutations')) return 'No mutations';
  const specific = checked.filter((value) => value !== 'Use mutations');
  return specific.length ? `Specific mutations: ${specific.join(', ')}` : 'Use mutations';
}

function initMutationPicker() {
  const group = $('mutation_preference_group');
  if (!group) return;
  group.addEventListener('change', (event) => {
    const changed = event.target;
    if (!(changed instanceof HTMLInputElement)) return;
    const boxes = [...group.querySelectorAll('input[type="checkbox"]')];
    const noMutations = boxes.find((box) => box.value === 'No mutations');
    const useMutations = boxes.find((box) => box.value === 'Use mutations');
    if (changed.value === 'No mutations' && changed.checked) {
      boxes.forEach((box) => {
        if (box !== changed) box.checked = false;
      });
      return;
    }
    if (changed.checked && noMutations) {
      noMutations.checked = false;
    }
    const hasSpecific = boxes.some((box) => box.checked && !['Use mutations', 'No mutations'].includes(box.value));
    if (useMutations) {
      useMutations.checked = !hasSpecific && !noMutations?.checked;
    }
  });
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
  badge.textContent = 'Brain unreachable';
  badge.style.color = '#ef6464';
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

async function loadLegendaryPerks() {
  try {
    const characterType = $('character_type')?.value || 'Human';
    const response = await fetch(`/api/legendary-perks?character_type=${encodeURIComponent(characterType)}`);
    const perks = await response.json();
    state.legendaryPerks = perks;
    state.legendaryPerksById = Object.fromEntries(perks.map((p) => [p.id, p]));
  } catch {
    state.legendaryPerks = [];
    state.legendaryPerksById = {};
  }
}

function perkCost(card) {
  const perk = state.perksById[card.card_id];
  return Number(perk?.rank_costs?.[card.rank] ?? perk?.rank_costs?.[String(card.rank)] ?? card.rank ?? 0);
}

function renderSpecialColumns(build) {
  const order = ['Strength', 'Perception', 'Endurance', 'Charisma', 'Intelligence', 'Agility', 'Luck'];
  const data = build.perk_cards_by_special || {};
  const allocation = build.special_allocation || {};
  return `
    <div class="special-columns">
      ${order.map((special) => {
        const cards = data[special] || [];
        const budget = Number(allocation[special] ?? 0);
        const spent = cards.reduce((total, card) => total + perkCost(card), 0);
        const headerClass = special.toLowerCase();
        const overspent = spent > budget;
        return `
          <div class="special-column">
            <div class="special-header ${headerClass}">${escapeHtml(special)}</div>
            <div class="special-value">${budget}</div>
            <div class="special-budget" style="${overspent ? 'color:var(--red);font-weight:700' : ''}">${spent} / ${budget}</div>
            ${cards.map((card) => renderPerkCard(card, state.perksById[card.card_id])).join('')}
            ${!cards.length ? '<small style="opacity:.55">No cards</small>' : ''}
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function renderPerkCard(card, perk) {
  const effect = perk?.effect_by_rank?.[card.rank] || perk?.effect_by_rank?.[String(card.rank)] || card.why;
  return `
    <div class="perk-card-board">
      <span class="rank-badge">${escapeHtml(card.rank)}</span>
      <div class="card-name">${escapeHtml(perk?.name || card.card_id)}</div>
      <div class="card-role">${escapeHtml(card.role)} - ${escapeHtml(effect)}</div>
    </div>
  `;
}

function renderLegendaryPerks(build) {
  const perks = build.legendary_perks || [];
  if (!perks.length) return '';
  return `
    <section class="summary-block">
      <div class="block-title">Legendary Perks</div>
      <div class="perk-grid">
        ${perks.map((lp) => `
          <div class="gear-card">
            <strong>${escapeHtml(lp.name || 'Unknown')}</strong>
            <small>${escapeHtml(lp.priority || '')} - Rank ${escapeHtml(lp.rank || 1)} - ${escapeHtml(lp.reason || '')}</small>
          </div>
        `).join('')}
      </div>
    </section>
  `;
}

function renderValidationBadge(build, payload) {
  const status = build.validation_status || 'unknown';
  const issues = payload.issues || [];
  const repairs = build.repair_notes?.length || 0;
  const pass = status === 'passed' && !issues.length;
  const cls = pass ? 'pass' : issues.length ? 'fail' : 'warn';
  const label = pass ? 'Passed' : issues.length ? `Failed (${issues.length})` : status;
  return `
    <span class="validation-indicator ${cls}">
      Validation: ${escapeHtml(label)}
      ${repairs > 0 ? ` | Repairs: ${repairs}` : ''}
    </span>
  `;
}

function renderRepairNotes(build) {
  const notes = build.repair_notes || [];
  if (!notes.length) return '';
  return `
    <section class="summary-block">
      <div class="block-title">Repair Notes</div>
      <div class="repair-notes">
        <ul class="clean-list">${notes.map((n) => `<li>${escapeHtml(n)}</li>`).join('')}</ul>
      </div>
    </section>
  `;
}

function renderBuildSummary(build, payload) {
  const brainNotes = [
    ...(build.brain_notes || []),
    ...((payload.brain?.notes || []).filter((note) => !(build.brain_notes || []).includes(note))),
  ];
  const status = build.brain_status || (build.brain_confirmed ? 'complete' : 'not_requested');
  const brainLabels = {
    pending: 'Brain queued',
    running: 'Brain refining',
    complete: 'Brain complete',
    failed: 'Brain failed',
  };
  const engineLabel = build.logic_engine || 'deterministic';

  return `
    <div class="summary-head">
      <h2>${escapeHtml(build.build_name)}</h2>
      <div class="summary-meta">
        ${renderValidationBadge(build, payload)}
        <span class="validation-indicator ${status === 'complete' ? 'pass' : status === 'failed' ? 'fail' : 'warn'}">
          ${escapeHtml(brainLabels[status] || status)}
        </span>
        <span class="validation-indicator">${escapeHtml(engineLabel)}</span>
      </div>
      <button id="copyBuildId" class="secondary-action" type="button" style="margin-top:10px;">Copy Build ID</button>
    </div>

    ${renderLegendaryPerks(build)}

    ${renderDictList('Mutations', build.mutations)}
    ${renderObjectLists('Gear', build.gear)}
    ${renderObjectLists('Variants', build.variants)}
    ${renderObjectLists('Swap Cards', build.swap_cards)}

    <section class="summary-block">
      <div class="block-title">Assumptions</div>
      <ul class="clean-list">${(build.assumptions || []).map((a) => `<li>${escapeHtml(a)}</li>`).join('')}</ul>
    </section>

    <section class="summary-block">
      <div class="block-title">Weaknesses</div>
      <div class="warning-card">
        <ul class="clean-list">${(build.weaknesses || []).map((w) => `<li>${escapeHtml(w)}</li>`).join('')}</ul>
      </div>
    </section>

    ${renderRepairNotes(build)}

    <section class="summary-block">
      <div class="block-title">Brain Notes</div>
      ${brainNotes.length ? `<ul class="clean-list">${brainNotes.map((n) => `<li>${escapeHtml(n)}</li>`).join('')}</ul>` : '<p class="empty-state">No brain notes.</p>'}
    </section>

    ${renderSearchResults(build.web_search_results)}

    <section class="summary-block">
      <button class="transcript-toggle" id="toggleRaw" type="button">Show raw payload</button>
      <pre id="rawPayload" class="raw-json hidden" style="margin-top:8px;">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
    </section>
  `;
}

function renderDictList(title, items, primaryKey = 'name') {
  if (!items?.length) return '';
  return `
    <section class="summary-block">
      <div class="block-title">${escapeHtml(title)}</div>
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

function renderObjectLists(title, value) {
  const entries = Object.entries(value || {});
  if (!entries.length) return '';
  return `
    <section class="summary-block">
      <div class="block-title">${escapeHtml(title)}</div>
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

function renderSearchResults(results) {
  if (!results?.length) return '';
  return `
    <section class="summary-block">
      <div class="block-title">Web Search Evidence</div>
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

function isBrainActive(build) {
  return ['pending', 'running'].includes(build?.brain_status);
}

function scheduleBrainPoll(build) {
  if (!isBrainActive(build) || state.brainPollTimers[build.id]) return;
  let attempts = 80;
  const poll = async () => {
    try {
      const response = await fetch(`/api/build/${encodeURIComponent(build.id)}`);
      if (!response.ok) throw new Error('Build refresh failed');
      const updated = await response.json();
      renderBuild(updated, { preserveScroll: true });
      if (isBrainActive(updated) && attempts > 0) {
        attempts -= 1;
        state.brainPollTimers[build.id] = window.setTimeout(poll, 3000);
        return;
      }
    } catch {
      if (attempts > 0) {
        attempts -= 1;
        state.brainPollTimers[build.id] = window.setTimeout(poll, 5000);
        return;
      }
    }
    delete state.brainPollTimers[build.id];
  };
  state.brainPollTimers[build.id] = window.setTimeout(poll, 3000);
}

function renderBuild(payload, options = {}) {
  const build = payload.build || payload;
  state.currentBuild = build;

  const specialBoard = $('specialBoard');
  const buildSummary = $('buildSummary');
  const revisionActions = $('revisionActions');
  const legendaryPicker = $('legendaryPicker');
  const resultPanel = $('resultPanel');

  // Hide legacy result panel
  if (resultPanel) resultPanel.classList.add('hidden');

  // Populate center board
  specialBoard.innerHTML = `
    <div class="section-head">
      <div>
        <p class="eyebrow">SPECIAL Board</p>
        <h1>${escapeHtml(build.build_name)}</h1>
      </div>
    </div>
    ${renderSpecialColumns(build)}
  `;

  // Populate right summary
  buildSummary.innerHTML = renderBuildSummary(build, payload);

  // Wire copy button
  $('copyBuildId')?.addEventListener('click', async () => {
    await navigator.clipboard?.writeText(build.id);
  });

  // Wire raw payload toggle
  $('toggleRaw')?.addEventListener('click', () => {
    const pre = $('rawPayload');
    if (!pre) return;
    const hidden = pre.classList.toggle('hidden');
    $('toggleRaw').textContent = hidden ? 'Show raw payload' : 'Hide raw payload';
  });

  // Show revision actions and legendary picker
  revisionActions.classList.remove('hidden');
  legendaryPicker.classList.remove('hidden');

  saveRecentBuild(build);
  scheduleBrainPoll(build);
  if (!options.preserveScroll) {
    specialBoard.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function renderError(error) {
  const specialBoard = $('specialBoard');
  specialBoard.innerHTML = `
    <div class="warning-card">
      <h2>Build request failed</h2>
      <p>${escapeHtml(error.message || error)}</p>
    </div>
  `;
  $('resultPanel')?.classList.add('hidden');
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
    state.revisionIntent = null;
  }
}

/* ===== Character type warnings ===== */
function getCharacterTypeRestrictedPerks() {
  const type = $('character_type')?.value || 'Human';
  const restricted = [];
  state.legendaryPerks.forEach((p) => {
    const restriction = p.character_restriction || 'Any';
    if (restriction !== 'Any' && restriction !== type) {
      restricted.push(p);
    }
  });
  return restricted;
}

function updateCharacterTypeWarnings() {
  const container = $('characterTypeWarnings');
  if (!container) return;
  const restricted = getCharacterTypeRestrictedPerks();
  if (!restricted.length) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = `
    <div class="msg warn">
      Character type change warning: ${restricted.map((p) => escapeHtml(p.name)).join(', ')} cannot be used by the selected character type.
      Remove them from your Legendary Perk loadout or change the character type back.
    </div>
  `;
}

/* ===== Legendary perk picker ===== */
function getLegendaryLoadout() {
  return state.legendaryLoadout.map((row) => ({
    perk_id: row.perk_id,
    rank: Number(row.rank),
    equipped: Boolean(row.equipped),
  }));
}

function updateLegendaryCounter() {
  const equipped = state.legendaryLoadout.filter((r) => r.equipped).length;
  const counter = $('legendaryCounter');
  if (counter) counter.textContent = `${equipped} / 6`;
}

function renderLegendaryPickerRows() {
  const rows = $('legendaryRows');
  if (!rows) return;
  const available = state.legendaryPerks;
  rows.innerHTML = state.legendaryLoadout.map((row, index) => {
    const selected = available.find((p) => p.id === row.perk_id);
    const maxRank = selected?.max_rank || 4;
    const invalid = selected && selected.character_restriction && selected.character_restriction !== 'Any' && selected.character_restriction !== ($('character_type')?.value || 'Human');
    return `
      <div class="legendary-row" data-index="${index}">
        <select class="legendary-select">
          <option value="">-- Select perk --</option>
          ${available.map((p) => `<option value="${escapeHtml(p.id)}" ${p.id === row.perk_id ? 'selected' : ''}>${escapeHtml(p.name)}${p.character_restriction && p.character_restriction !== 'Any' ? ` [${escapeHtml(p.character_restriction)}]` : ''}</option>
          `).join('')}
        </select>
        <select class="legendary-rank">
          ${Array.from({ length: maxRank }, (_, i) => `<option value="${i + 1}" ${String(i + 1) === String(row.rank) ? 'selected' : ''}>Rank ${i + 1}</option>
          `).join('')}
        </select>
        <label class="check-pill" style="padding:0 6px;min-height:28px;">
          <input type="checkbox" class="legendary-equipped" ${row.equipped ? 'checked' : ''}>
          <span>On</span>
        </label>
        <button class="remove-btn" type="button" title="Remove">×</button>
        ${invalid ? `<div class="msg" style="grid-column:1 / -1;margin-top:2px;">${escapeHtml(selected.name)} is ${escapeHtml(selected.character_restriction)}-only and cannot be used by this character type.</div>` : ''}
      </div>
    `;
  }).join('');

  // Wire events
  rows.querySelectorAll('.legendary-row').forEach((rowEl) => {
    const idx = Number(rowEl.dataset.index);
    const select = rowEl.querySelector('.legendary-select');
    const rank = rowEl.querySelector('.legendary-rank');
    const equipped = rowEl.querySelector('.legendary-equipped');
    const remove = rowEl.querySelector('.remove-btn');

    select?.addEventListener('change', () => {
      state.legendaryLoadout[idx].perk_id = select.value;
      const perk = state.legendaryPerksById[select.value];
      if (perk) {
        state.legendaryLoadout[idx].rank = Math.min(state.legendaryLoadout[idx].rank, perk.max_rank);
      }
      renderLegendaryPickerRows();
      updateLegendaryCounter();
      updateCharacterTypeWarnings();
    });
    rank?.addEventListener('change', () => {
      state.legendaryLoadout[idx].rank = Number(rank.value);
      updateLegendaryCounter();
    });
    equipped?.addEventListener('change', () => {
      state.legendaryLoadout[idx].equipped = equipped.checked;
      updateLegendaryCounter();
    });
    remove?.addEventListener('click', () => {
      state.legendaryLoadout.splice(idx, 1);
      renderLegendaryPickerRows();
      updateLegendaryCounter();
      updateCharacterTypeWarnings();
    });
  });
}

function addLegendaryRow() {
  state.legendaryLoadout.push({ perk_id: '', rank: 1, equipped: true });
  renderLegendaryPickerRows();
  updateLegendaryCounter();
}

/* ===== Revision buttons ===== */
function initRevisionButtons() {
  const bar = $('revisionActions');
  if (!bar) return;
  bar.addEventListener('click', (e) => {
    const btn = e.target.closest('.revision-btn');
    if (!btn) return;
    const intent = btn.dataset.intent;
    if (intent === 'regenerate') {
      state.revisionIntent = null;
    } else {
      state.revisionIntent = intent;
    }
    generateBuild();
  });
}

/* ===== Character type change handler ===== */
function initCharacterTypeHandler() {
  const select = $('character_type');
  if (!select) return;
  select.addEventListener('change', async () => {
    await loadLegendaryPerks();
    renderLegendaryPickerRows();
    updateCharacterTypeWarnings();
  });
}

async function init() {
  initMutationPicker();
  initRevisionButtons();
  initCharacterTypeHandler();
  $('generateBtn').addEventListener('click', generateBuild);
  $('addLegendaryRow')?.addEventListener('click', addLegendaryRow);
  await Promise.all([loadBrainStatus(), loadSources(), loadPerks(), loadLegendaryPerks()]);
  renderLegendaryPickerRows();
}

init();
