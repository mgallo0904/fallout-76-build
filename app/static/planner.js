const SPECIALS = ['Strength', 'Perception', 'Endurance', 'Charisma', 'Intelligence', 'Agility', 'Luck'];
const SPECIAL_BUDGET = 56;

const $ = (id) => document.getElementById(id);

const state = {
  archetypes: [],
  perks: [],
  perksById: {},
  legendaryPerks: [],
  archetypeId: null,
  baseline: null,
  special: Object.fromEntries(SPECIALS.map((s) => [s, 1])),
  // selected: { card_id: rank }
  selected: {},
  search: '',
  user: {
    armor_type: 'Power Armor',
    health_model: 'Full health',
    combat_style: 'Balanced',
  },
};

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

function rankCost(card, rank) {
  if (!card) return 0;
  const r = String(rank);
  return Number(card.rank_costs?.[r] ?? card.rank_costs?.[rank] ?? 0);
}

function spentPerSpecial() {
  const out = Object.fromEntries(SPECIALS.map((s) => [s, 0]));
  for (const [cardId, rank] of Object.entries(state.selected)) {
    const card = state.perksById[cardId];
    if (!card) continue;
    out[card.special] += rankCost(card, rank);
  }
  return out;
}

function totalSpecial() {
  return SPECIALS.reduce((acc, s) => acc + Number(state.special[s] || 0), 0);
}

function renderBadge() {
  const total = totalSpecial();
  $('budgetTotal').textContent = total;
  $('budgetMax').textContent = SPECIAL_BUDGET;
  $('budgetTotal').style.color = total > SPECIAL_BUDGET ? '#ef6464' : '';
}

function renderSpecialSliders() {
  const grid = $('specialGrid');
  const spent = spentPerSpecial();
  grid.innerHTML = SPECIALS.map((s) => {
    const value = state.special[s];
    const over = spent[s] > value;
    return `
      <div class="special-tile ${over ? 'over' : ''}" data-special="${s}">
        <header><span>${s[0]}</span><span class="spent">${spent[s]}/${value}</span></header>
        <input type="range" min="1" max="15" step="1" value="${value}" data-special="${s}">
        <small>${escapeHtml(s)}</small>
      </div>
    `;
  }).join('');
  grid.querySelectorAll('input[type="range"]').forEach((input) => {
    input.addEventListener('input', (event) => {
      const special = event.target.dataset.special;
      state.special[special] = Number(event.target.value);
      renderBadge();
      renderSpecialSliders();
      runValidation();
    });
  });
  renderBadge();
}

function renderPerkColumns() {
  const wrapper = $('perkColumns');
  const spent = spentPerSpecial();
  const search = state.search.trim().toLowerCase();
  wrapper.innerHTML = SPECIALS.map((special) => {
    const cards = state.perks
      .filter((p) => p.special === special && p.status === 'verified')
      .filter((p) => !search || p.name.toLowerCase().includes(search) || p.id.includes(search))
      .sort((a, b) => a.level_required - b.level_required);
    return `
      <div class="perk-column" data-special="${special}">
        <h3>${special} - ${spent[special]}/${state.special[special]}</h3>
        ${cards.map((card) => renderPerkTile(card)).join('') || '<small style="color:#7a7d83">no matches</small>'}
      </div>
    `;
  }).join('');

  wrapper.querySelectorAll('.perk-tile').forEach((tile) => {
    const cardId = tile.dataset.cardId;
    tile.addEventListener('click', (event) => {
      if (event.target.closest('.rank-row')) return;
      togglePerk(cardId);
    });
    tile.querySelector('[data-rank-up]')?.addEventListener('click', (event) => {
      event.stopPropagation();
      bumpRank(cardId, +1);
    });
    tile.querySelector('[data-rank-down]')?.addEventListener('click', (event) => {
      event.stopPropagation();
      bumpRank(cardId, -1);
    });
  });
}

function renderPerkTile(card) {
  const selectedRank = state.selected[card.id];
  const isSelected = Number.isInteger(selectedRank);
  const rank = isSelected ? selectedRank : 0;
  const effect = card.effect_by_rank?.[rank] || card.effect_by_rank?.['1'] || '';
  const overBudget = isSelected && spentPerSpecial()[card.special] > state.special[card.special];
  return `
    <div class="perk-tile ${isSelected ? 'selected' : ''} ${overBudget ? 'over' : ''}" data-card-id="${card.id}">
      <strong>${escapeHtml(card.name)} <span style="opacity:.7;font-weight:400">L${card.level_required}</span></strong>
      <small>${escapeHtml(effect)}</small>
      ${isSelected ? `
        <div class="rank-row">
          <button type="button" data-rank-down>-</button>
          <span>rank ${rank} / ${card.max_rank} (cost ${rankCost(card, rank)})</span>
          <button type="button" data-rank-up>+</button>
        </div>
      ` : `<small style="opacity:.6">click to add at rank 1</small>`}
    </div>
  `;
}

function togglePerk(cardId) {
  if (state.selected[cardId]) {
    delete state.selected[cardId];
  } else {
    state.selected[cardId] = 1;
  }
  rerenderInteractive();
}

function bumpRank(cardId, delta) {
  const card = state.perksById[cardId];
  if (!card) return;
  const current = state.selected[cardId] || 0;
  const next = current + delta;
  if (next <= 0) {
    delete state.selected[cardId];
  } else if (next > card.max_rank) {
    return;
  } else {
    state.selected[cardId] = next;
  }
  rerenderInteractive();
}

function rerenderInteractive() {
  renderSpecialSliders();
  renderPerkColumns();
  runValidation();
}

function renderLegendary() {
  const wrap = $('legendaryList');
  if (!wrap) return;
  wrap.innerHTML = state.legendaryPerks.map((card) => {
    const rank = card.selectedRank || 1;
    return `
    <div class="perk-tile" data-card-id="${card.id}">
      <strong>${escapeHtml(card.name)}</strong>
      <small>${escapeHtml(card.effect_by_rank?.[String(rank)] || card.effect_by_rank?.['1'] || '')}</small>
      <div class="rank-row legendary-rank-row">
        <button type="button" data-legendary-rank-down>-</button>
        <span>rank ${rank} / ${card.max_rank}</span>
        <button type="button" data-legendary-rank-up>+</button>
      </div>
    </div>
  `;
  }).join('');
  wrap.querySelectorAll('.perk-tile').forEach((tile) => {
    const cardId = tile.dataset.cardId;
    tile.querySelector('[data-legendary-rank-up]')?.addEventListener('click', (event) => {
      event.stopPropagation();
      bumpLegendaryRank(cardId, +1);
    });
    tile.querySelector('[data-legendary-rank-down]')?.addEventListener('click', (event) => {
      event.stopPropagation();
      bumpLegendaryRank(cardId, -1);
    });
  });
}

function bumpLegendaryRank(cardId, delta) {
  const card = state.legendaryPerks.find((c) => c.id === cardId);
  if (!card) return;
  const current = card.selectedRank || 1;
  const next = current + delta;
  if (next < 1 || next > card.max_rank) return;
  card.selectedRank = next;
  renderLegendary();
}

function buildPayloadForValidation() {
  const perksBySpecial = Object.fromEntries(SPECIALS.map((s) => [s, []]));
  for (const [cardId, rank] of Object.entries(state.selected)) {
    const card = state.perksById[cardId];
    if (!card) continue;
    perksBySpecial[card.special].push({
      card_id: cardId,
      rank,
      role: '',
      why: '',
    });
  }
  const baseline = state.baseline || {};
  return {
    id: baseline.id || 'planner-preview',
    build_name: baseline.build_name || 'Custom Planner Build',
    user_inputs: {
      character_level: '50+',
      primary_playstyle: state.archetypeId || 'Power Armor Heavy',
      primary_weapon_type: 'Heavy energy',
      preferred_weapons: '',
      armor_type: state.user.armor_type,
      health_model: state.user.health_model,
      combat_style: state.user.combat_style,
      team_preference: 'Public team',
      mutation_preference: 'Use mutations',
      qol_preference: 'Balanced',
      legendary_perk_availability: 'Some',
      current_gear: '',
      avoid_list: '',
    },
    assumptions: baseline.assumptions || ['Custom planner build'],
    special_allocation: { ...state.special },
    perk_cards_by_special: perksBySpecial,
    legendary_perks: state.legendaryPerks.map((card) => ({
      name: card.name,
      priority: 'Selected',
      reason: 'User selected in planner',
      rank: card.selectedRank || 1,
    })) || [],
    mutations: baseline.mutations || [],
    gear: baseline.gear || {},
    variants: baseline.variants || {},
    swap_cards: baseline.swap_cards || {},
    weaknesses: baseline.weaknesses?.length ? baseline.weaknesses : ['Custom build - track tradeoffs.'],
    validation_status: 'pending',
    source_verification_notes: baseline.source_verification_notes || [],
    created_at: baseline.created_at || new Date().toISOString(),
    logic_engine: 'planner',
    brain_notes: [],
    web_search_results: [],
  };
}

let validationTimer = null;
function runValidation() {
  clearTimeout(validationTimer);
  validationTimer = setTimeout(async () => {
    try {
      const response = await fetch('/api/build/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPayloadForValidation()),
      });
      const issues = await response.json();
      const ul = $('validationList');
      const panel = ul.parentElement;
      if (!Array.isArray(issues) || !issues.length) {
        panel.classList.add('passed');
        ul.innerHTML = '<li>No issues. Build looks legal.</li>';
        $('validationStatus').textContent = 'passed';
        $('validationStatus').style.color = '#92e2a8';
      } else {
        panel.classList.remove('passed');
        ul.innerHTML = issues.map((issue) => `<li>${escapeHtml(issue)}</li>`).join('');
        $('validationStatus').textContent = `${issues.length} issue${issues.length === 1 ? '' : 's'}`;
        $('validationStatus').style.color = '#ef9090';
      }
    } catch (error) {
      $('validationStatus').textContent = 'unreachable';
    }
  }, 200);
}

async function loadBrainStatus() {
  try {
    const response = await fetch('/api/brain/status');
    const status = await response.json();
    const badge = $('brainBadge');
    if (status.enabled) {
      badge.textContent = `Brain: ${status.model}`;
      badge.classList.add('online');
    } else {
      badge.textContent = 'Brain unreachable';
      badge.style.color = '#ef6464';
      badge.classList.remove('online');
    }
  } catch {}
}

async function loadArchetypes() {
  const response = await fetch('/api/archetypes');
  state.archetypes = await response.json();
  const select = $('archetypeSelect');
  select.innerHTML = state.archetypes
    .map((arch) => `<option value="${arch.id}">${escapeHtml(arch.name)}</option>`)
    .join('');
  state.archetypeId = state.archetypes[0]?.id;
}

async function loadPerks() {
  const [perks, leg] = await Promise.all([
    fetch('/api/perks').then((r) => r.json()),
    fetch('/api/legendary-perks').then((r) => r.json()),
  ]);
  state.perks = perks;
  state.perksById = Object.fromEntries(perks.map((p) => [p.id, p]));
  state.legendaryPerks = leg;
}

async function loadBaseline() {
  const archetype = $('archetypeSelect').value;
  const aliasMap = {
    power_armor_heavy_energy: { primary_playstyle: 'Power Armor Heavy', primary_weapon_type: 'Heavy energy' },
    bullet_storm_heavy: { primary_playstyle: 'Bullet Storm Heavy', primary_weapon_type: 'Heavy ballistic' },
    cremator_pyro: { primary_playstyle: 'Pyromaniac', primary_weapon_type: 'Cremator' },
    onslaught_commando: { primary_playstyle: 'Commando', primary_weapon_type: 'Auto rifle' },
    rifleman: { primary_playstyle: 'Rifleman', primary_weapon_type: 'Non-automatic rifle' },
    bow_stealth: { primary_playstyle: 'Bow Stealth', primary_weapon_type: 'Bow', preferred_weapons: 'Compound Bow, Crossbow' },
    shotgunner: { primary_playstyle: 'Shotgunner', primary_weapon_type: 'Shotgun' },
    pepper_shaker_stealth: { primary_playstyle: 'Stealth Shotgun', primary_weapon_type: 'Fancy Pump-Action', preferred_weapons: 'Fancy Pump-Action, Pepper Shaker' },
    gunslinger: { primary_playstyle: 'Gunslinger', primary_weapon_type: 'Pistol' },
    melee: { primary_playstyle: 'Melee', primary_weapon_type: 'Melee' },
    playable_ghoul: { primary_playstyle: 'Ghoul Heavy', primary_weapon_type: 'Heavy energy' },
    ghoul_commando: { primary_playstyle: 'Ghoul Commando', primary_weapon_type: 'Auto rifle' },
    ghoul_melee: { primary_playstyle: 'Ghoul Melee', primary_weapon_type: 'Melee' },
  };
  const overrides = aliasMap[archetype] || {};
  const payload = {
    armor_type: state.user.armor_type,
    health_model: state.user.health_model,
    combat_style: state.user.combat_style,
    ...overrides,
  };
  const response = await fetch('/api/build/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const build = await response.json();
  if (!response.ok) {
    alert(build.detail || 'Failed to load baseline');
    return;
  }
  state.archetypeId = archetype;
  state.baseline = build;
  state.special = { ...build.special_allocation };
  state.selected = {};
  for (const cards of Object.values(build.perk_cards_by_special)) {
    for (const card of cards || []) {
      state.selected[card.card_id] = card.rank;
    }
  }
  rerenderInteractive();
}

async function saveBuild() {
  const payload = buildPayloadForValidation();
  const response = await fetch('/api/build/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload.user_inputs),
  });
  const build = await response.json();
  if (!response.ok) {
    alert(build.detail || 'Save failed');
    return;
  }
  alert(`Saved baseline build: ${build.id}`);
}

function bindControls() {
  $('archetypeSelect').addEventListener('change', (e) => {
    state.archetypeId = e.target.value;
  });
  $('healthModel').addEventListener('change', (e) => { state.user.health_model = e.target.value; runValidation(); });
  $('armorType').addEventListener('change', (e) => { state.user.armor_type = e.target.value; runValidation(); });
  $('combatStyle').addEventListener('change', (e) => { state.user.combat_style = e.target.value; runValidation(); });
  $('loadBaselineBtn').addEventListener('click', loadBaseline);
  $('saveBuildBtn').addEventListener('click', saveBuild);
  $('perkSearch').addEventListener('input', (e) => {
    state.search = e.target.value;
    renderPerkColumns();
  });
}

async function init() {
  await Promise.all([loadArchetypes(), loadPerks(), loadBrainStatus()]);
  bindControls();
  await loadBaseline();
  renderLegendary();
}

init();
