# Plan: NukesDragons-Style Visual Build Board for Fallout 76 Build Generator

## Requirements Summary

Shift the UI from a "manual planner first" experience into a **NukesDragons-style visual build board** where the user enters preferences and the app **auto-generates** the build using Kimi (via Ollama `kimi-k2.6:cloud`), then displays it in an interactive SPECIAL/perk board with validation badges.

Core flow change:

```
OLD: User fills dropdowns → deterministic archetype chosen → Kimi refines text only
NEW: User enters build goals → Kimi proposes complete build → validator checks legality → repair layer fixes → UI displays in NukesDragons-style board
```

**Key constraints:**
- Keep the deterministic engine as the backbone. Kimi is a constrained refinement specialist only.
- Leave `/planner` and `/compare` untouched.
- Never trust LLM output directly; every perk/SPECIAL/legendary pick must pass deterministic validation.
- Do not copy code/assets from nukesdragons.com (UX reference only).

## Acceptance Criteria

1. The `/` page renders a three-zone build board: left (build brief), center (SPECIAL + perk board), right (build summary).
2. The center board shows seven vertical SPECIAL columns with colored headers, perk cards stacked under each, rank indicators, and validation badges.
3. The build brief supports a free-text "Build goal" field as the primary LLM intent.
4. Generation mode defaults to `hybrid` (deterministic baseline + Kimi candidate + validator/repair).
5. Kimi receives the actual allowed perk database in the prompt (not just general knowledge).
6. A deterministic repair layer (`app/services/repair.py`) fixes hallucinated/illegal LLM output and stores `repair_notes`.
7. The build summary panel shows: build name, health/armor/weapon recommendations, legendary perks, mutations, gear, weaknesses, swap cards, validation status, repair notes, and Kimi reasoning summary.
8. The planner (`/planner`) is preserved as an advanced manual editor.
9. "Regenerate" and revision buttons are available (More Damage, More Tanky, Lower Maintenance, etc.).
10. All existing tests pass; new tests are added for repair layer and LLM build pipeline.
11. No external code/assets are copied from nukesdragons.com.

## RALPLAN-DR Summary

### Principles
1. **Safety first**: Never trust LLM output directly; every perk/SPECIAL/legendary pick must pass deterministic validation.
2. **Evolve, don't rewrite**: Reuse existing archetype engine, perk database, validation, and UI components.
3. **LLM as candidate generator, not sole authority**: Kimi proposes; validator+repair finalizes.
4. **Transparency**: Every build displays validation status, repairs applied, and reasoning source.

### Decision Drivers
1. **Reliability**: Prevent illegal/hallucinated builds from being presented as valid.
2. **User experience**: One-click auto-generation with visual NukesDragons-style layout.
3. **Maintainability**: Keep deterministic engine as the safety net; LLM layer is swappable.

### Viable Options

| Option | Approach | Pros | Cons |
|--------|----------|------|------|
| A. Full LLM generation | Kimi proposes everything, no deterministic safety net | Maximum flexibility | Risk of hallucinated perks, illegal budgets, no reproducibility |
| B. Deterministic + LLM refinement (current) | Archetype engine generates, Kimi refines text only | Safe and reproducible | LLM cannot improve perk selection itself |
| **C. Hybrid LLM candidate + validator/repair (chosen)** | Kimi proposes full build candidate; deterministic validator checks; repair layer fixes | Best of both worlds | More complexity in orchestration |

**Invalidated options:**
- **Option A** rejected: hallucination risk too high.
- **Option B** rejected: does not meet the goal of auto-generating perk selections.
- **Option C chosen**: Hybrid balances AI flexibility with deterministic correctness.

## ADR

### Decision
Adopt Option C: Hybrid LLM candidate generation with deterministic validation and repair.

### Drivers
- User wants Kimi to auto-generate perk selections, not just refine text.
- User wants a NukesDragons-style visual board.
- Deterministic engine already exists and is well-tested.

### Why Chosen
Hybrid gives AI-assisted build generation while preserving the deterministic safety net. The repair layer converts LLM output into a guaranteed-legal build.

### Consequences
- New backend services: `llm_builder.py`, `repair.py`, `prompting.py`, `build_pipeline.py`.
- Frontend redesign: `/` becomes the main auto-build board.
- `/planner` becomes the advanced manual editor.

## Detailed Specifications

### 1. revision_intent Behavior

`revision_intent` is a **request-scoped modifier**. It must not permanently mutate `avoid_list`, `goal`, `preferred_weapons`, or saved user constraints.

Add to `BuildInput`:
```python
revision_intent: Literal[
    "more_damage",
    "more_tanky",
    "avoid_power_armor",
    "avoid_bloodied",
] | None = None
```

| revision_intent | Engine behavior | Brain behavior |
|-----------------|----------------|----------------|
| `more_damage` | Prefer offense-focused perk allocation where valid. Favor damage/crit/scaling perks over QOL. Do not violate survivability hard rules. | Prefer damage-oriented gear, mutations, legendary perks, and swap cards from allowed lists. Explain tradeoffs. |
| `more_tanky` | Prefer defensive allocation. Increase survivability emphasis through Endurance, Agility, defensive perks, and defensive Legendary Perks where valid. | Prefer defensive legendaries such as Electric Absorption for PA, Funky Duds/Sizzling Style where relevant, What Rads? when allowed, and sustain gear. Explain damage tradeoff. |
| `avoid_power_armor` | Treat Power Armor as excluded for this request only. Do not select PA archetypes. If current build requires PA, route to closest non-PA fallback and add an assumption. | Do not recommend PA gear or PA-only Legendary Perks as active recommendations. May mention them only as excluded. |
| `avoid_bloodied` | Treat Bloodied/Low Health as excluded for this request only. Do not select Bloodied archetypes, Unyielding assumptions, or low-health-only perk logic. | Do not recommend Bloodied weapons, Unyielding armor, Nerd Rage-centered logic, or low-health rad management as active build requirements. |

**Important:** `avoid_power_armor` and `avoid_bloodied` are temporary request modifiers. They should not be appended to `avoid_list`. They should not persist after the request unless the user explicitly typed those exclusions.

### 2. summarize_effect(perk)

Deterministic summary behavior. Do not leave this to the coding agent.

```python
def summarize_effect(perk: PerkCard) -> str:
    """
    Return a compact prompt-safe effect summary for a Legendary Perk.
    Prefer rank 4 text because it represents full investment.
    Prefix with 'Rank 4:' so Kimi understands this is the max-rank effect.
    If rank 4 is missing, use the highest available rank and mark it.
    """
```

Exact behavior:
- If `effect_by_rank[4]` exists: return `"Rank 4: <rank 4 effect text>"`
- Else: use highest available rank: return `"Highest verified rank <n>: <effect text>"`
- If no rank effect text exists: return `"Effect summary unavailable; use source data only."`

Do not synthesize a new one-liner. Synthesis creates another hallucination surface.

### 3. What Rads? Handling

Default data model entry:
```json
{
  "id": "what_rads",
  "name": "What Rads?",
  "character_restriction": "Any",
  "status": "uncertain",
  "notes": [
    "Bethesda Ghoul Within release notes reported inconsistent transformed-character behavior involving What Rads?, Action Diet, and Feral Rage."
  ]
}
```

Reasoning: Bethesda's release notes explicitly mention inconsistent behavior after ghoul transformation involving What Rads?, Action Diet, and Feral Rage. The notes describe What Rads? as a Human Legendary Perk in that context, while also saying the behavior may not lock correctly after transformation. Marking it `Any` with `status: uncertain` is the least brittle default until live data is verified.

Brain note template:
> What Rads? has known Ghoul transformation behavior caveats in Bethesda's Ghoul Within notes. Verify in-game behavior before treating it as final for this character.

### 4. Fallback Templates for XP/Leveling and Crafting/Utility

**Do not invent full archetypes for these in the first pass.** Implement documented fallback templates only.

#### XP / Leveling Fallback

Purpose: Maximize XP gain while keeping the build playable.

Default assumptions:
- Primary emphasis: Intelligence
- Secondary emphasis: survivability and tagging
- Preferred team context: Casual public team
- Preferred mutations if allowed: Egg Head, Herd Mentality, Herbivore or Carnivore depending food assumptions
- Preferred Legendary Perks: Legendary Intelligence first, then Legendary Luck/Endurance depending build
- Avoid making this a fragile Bloodied build unless `health_model` explicitly says Bloodied / Low Health

Engine behavior:
- If `primary_playstyle = XP / Leveling`: use a general-purpose combat baseline based on `preferred_weapons` if provided.
- If no preferred weapon is provided: use Commando or Heavy Gunner fallback depending `armor_type`.
- Add assumption: `"XP / Leveling is a goal overlay, so the engine used the closest combat archetype and emphasized Intelligence/XP support."`

Brain behavior:
- Kimi may recommend XP-supporting mutations, food/team assumptions, Inspirational-style team logic, and Legendary Intelligence.
- Kimi must still return a playable combat build.

#### Crafting / Utility Fallback

Purpose: Support crafting, repairing, ammo production, lockpicking/hacking, CAMP/vendor convenience, and carry weight.

Default assumptions:
- This is not a primary combat build.
- Use a utility loadout assumption.
- Preferred Legendary Perks: Ammo Factory for ammo crafting, Master Infiltrator for lockpicking/hacking convenience, Legendary Intelligence if crafting/XP overlap matters.
- Do not over-optimize for boss DPS.

Engine behavior:
- If `primary_playstyle = Crafting / Utility`: use a non-combat utility baseline.
- If the app requires a combat shell: use user's `preferred_weapons` or a safe general fallback.
- Add assumption: `"Crafting / Utility is a non-combat loadout; combat performance is secondary."`

Brain behavior:
- Kimi should recommend utility perks, crafting swaps, ammo/repair/carry-weight support, and clearly label this as a non-combat or secondary loadout.

**Scope correction:** Phase 2.3 is "add only the minimum missing combat archetypes required for routing." For XP / Leveling and Crafting / Utility, implement documented fallback templates and assumption strings in this pass. Do not attempt to fully solve every combination.

### 5. Character-Type Change UX

**Warn, do not silently remove.**

When the user changes `character_type`:
- Re-filter available options for new rows.
- Keep already selected Legendary Perks visible.
- Mark invalid selected rows with warning text.
- Disable submit until invalid rows are removed or `character_type` is changed back.
- Do not silently delete selected rows.

Example warning:
> Action Diet is Ghoul-only and cannot be used by a Human character. Remove it or switch character type back to Ghoul.

### 6. Primary Playstyle Constrained Dropdown

Use a `<select>`, not free text.

Allowed values only:
- Commando
- Rifleman
- Heavy Gunner
- Shotgunner
- Gunslinger
- Guerrilla
- Bow / Archer
- One-Handed Melee
- Two-Handed Melee
- Unarmed
- Auto Melee
- Explosives
- Energy Weapons
- Power Armor Tank
- Support / Team Utility
- XP / Leveling
- Crafting / Utility
- Hybrid

Implementation rule:
- Frontend renders these exact values.
- Backend validates against the same enum/list.
- Unknown values return a clear validation error.

### 7. Existing-Build Compatibility

Expected behavior for old builds:
- `character_type` missing → default to `"Human"`
- `goal` missing → default to `None`
- `legendary_loadout` missing → default to `[]`
- `revision_intent` missing → default to `None`
- `primary_weapon_type` present → map to `preferred_weapons` if `preferred_weapons` is empty
- `legendary_perk_availability` present → ignore/deprecate; do not error

Storage handling:
- Inspect `app/services/db.py` and `app/services/repository.py` to confirm whether `GeneratedBuild` and `BuildInput` snapshots are stored as JSON blobs or structured SQLite columns.
- Add a migration only if structured storage requires it.
- JSON blob storage should handle old builds via defaults.

### 8. UI Smoke Test

Add to the frontend smoke checklist:
- Force or mock a Kimi response that recommends an illegal Legendary Perk.
- Confirm the backend drops it.
- Confirm the Kimi reasoning section renders the `brain_note` explaining the drop.

This confirms that sanity filter transparency actually reaches the user.

### 9. Legendary Perks Endpoint Cache

Add to the API spec:
- `GET /api/legendary-perks` should return `Cache-Control: max-age=3600`.
- Optional: allow `no-cache` in dev mode if data is edited frequently.

## Implementation Steps

### Phase 1: Backend Schema & LLM Pipeline

1. **Inspect storage** (`app/services/db.py`, `app/services/repository.py`)
   - Confirm JSON blob vs structured column storage.
   - Add migration only if structured columns require it.

2. **Update `PerkCard` model** (`app/models.py`)
   - Add `character_restriction: Literal["Any", "Human", "Ghoul"] = "Any"`
   - Action Diet and Feral Rage are Ghoul-only Legendary Perks, not regular perk cards.

3. **Update `BuildInput` model** (`app/models.py`)
   - Add `character_type: Literal["Human", "Ghoul"] = "Human"`
   - Add `goal: str | None = None`
   - Replace `legendary_perk_availability` with `legendary_loadout: List[Dict[str, Any]] = Field(default_factory=list)`
   - Add `revision_intent: Literal["more_damage", "more_tanky", "avoid_power_armor", "avoid_bloodied"] | None = None`
   - Keep backward compatibility: missing fields get defaults; deprecated fields are ignored.

4. **Add `BuildCandidate` schema** (`app/models.py`)
   - `build_name`, `special_allocation`, `perk_cards_by_special`, `legendary_perks`, `mutations`, `gear`, `variants`, `swap_cards`, `assumptions`, `weaknesses`, `reasoning_summary`.

5. **Add `GenerationMode` enum** (`app/models.py`)
   - `deterministic`, `llm`, `hybrid`.

6. **Create `app/services/prompting.py`**
   - Constructs the strict prompt for Kimi with:
     - Rules (only `allowed_perks`, legal ranks, legal SPECIAL budgets).
     - User input JSON.
     - Allowed perks compact list (id, name, special, max_rank, rank_costs, tags).
     - Allowed legendary perks compact list with `summarize_effect()`.
     - Return schema.

7. **Create `app/services/llm_builder.py`**
   - Calls Ollama API with the constructed prompt.
   - Parses JSON response into `BuildCandidate`.
   - Handles parsing errors gracefully (returns empty candidate on failure).
   - Implements JSON retry: if malformed JSON, retry once. If retry fails, keep deterministic build unchanged.

8. **Create `app/services/repair.py`**
   - `repair_build(candidate, perk_db, legendary_db)`:
     - Drop unknown perk IDs.
     - Cap ranks at `max_rank`.
     - Ensure total card cost per SPECIAL does not exceed allocation.
     - Remove cards incompatible with armor/health/ghoul/VATS/stealth flags.
     - Remove character-restricted perks selected by wrong character type.
     - Add deterministic fallback picks if a column is underfilled.
     - Return `repair_notes`.

9. **Create `app/services/build_pipeline.py`**
   - Orchestrates the full pipeline:
     ```
     normalize_inputs(user_input)
       → determine_mode(generation_mode)
       → if hybrid: deterministic_baseline + llm_candidate
       → validator.validate(candidate)
       → repair.repair_build(candidate)
       → save GeneratedBuild
       → queue brain refinement (optional)
     ```

10. **Modify `app/services/brain.py`**
    - Keep low-level Ollama API calls.
    - Add `generate_build_candidate()` for full-build LLM generation.
    - Add sanity filtering: drop hallucinated/illegal Legendary Perks and mutations; append `brain_notes` explaining each drop.
    - Preserve existing `refine_saved_build_with_brain()` for backward compatibility.

11. **Modify `app/services/engine.py`**
    - Keep deterministic archetype engine as fallback/safety net.
    - Add `get_baseline_for_inputs()` to produce a deterministic baseline for hybrid mode.
    - Implement XP/Leveling and Crafting/Utility fallback templates with documented assumptions.

12. **Modify `app/main.py`**
    - Update `POST /api/build/generate` to accept `generation_mode` (default `hybrid`).
    - Route to `build_pipeline` instead of directly to `engine`.
    - Add `GET /api/build/{id}/repair-notes` endpoint.
    - Update `GET /api/legendary-perks` to support `character_type` filtering and return `Cache-Control: max-age=3600`.
    - Add JSON retry and sanity filtering to the brain path.

### Phase 2: Frontend Redesign

13. **Modify `app/static/index.html`**
    - Replace the large form with a compact three-zone layout:
      - Left panel: Build Brief (compact form sections: Build Goal, Character Setup, Weapons + Armor, Preferences, Restrictions, Generate button).
      - Center panel: SPECIAL + Perk Board (7 vertical columns, colored headers, perk cards, rank badges, validation indicators).
      - Right panel: Build Summary (dynamic intel rail with build name, recommendations, legendary perks, mutations, gear, weaknesses, swap cards, reasoning summary, validation status, repair notes).
    - Add Legendary Perk picker with searchable perk name, rank 1-4, equipped checkbox, duplicate validation, character-type filtering, and X of 6 equipped counter.
    - Keep the existing dark vault-tec theme.

14. **Modify `app/static/index.js`**
    - Add render functions:
      - `renderBuildBrief()`
      - `renderSpecialColumns(build)`
      - `renderPerkCard(card, perkData)`
      - `renderLegendaryPerks(build)`
      - `renderBuildSummary(build)`
      - `renderValidationBadge(build)`
      - `renderRepairNotes(build)`
    - Add revision buttons: "Regenerate", "More Damage", "More Tanky", "Lower Maintenance", "Use My Gear", "Avoid Bloodied", "Avoid Power Armor".
    - Add export/share buttons: "Export JSON", "Copy Build ID".
    - Character-type change: do not silently remove invalid Legendary Perks. Keep visible, mark invalid, block submit.
    - Preserve brain polling every 3 seconds for background refinement.

15. **Modify `app/static/styles.css`**
    - Add `.build-board`, `.special-column`, `.perk-card`, `.rank-badge`, `.validation-indicator` styles.
    - Ensure responsive collapse to single column under 960px.

16. **Preserve `app/static/planner.html` and `app/static/planner.js`**
    - Keep the manual planner as the advanced editor.
    - Add a link from the main board: "Open in Manual Planner".

### Phase 3: Integration & Polish

17. **Wire frontend to new pipeline**
    - `POST /api/build/generate` returns the full `GeneratedBuild`.
    - Frontend immediately renders the three-zone board with the response.
    - Brain refinement continues in background if enabled.

18. **Add source/validation transparency**
    - Display in the right panel:
      - `Generated by: kimi-k2.6:cloud + deterministic validator`
      - `Validation: Passed / Failed`
      - `Repairs applied: N`
      - `Uncertain assumptions: N`

19. **Update tests**
    - `tests/test_repair.py`: Test repair layer edge cases (unknown perks, over-budget, incompatible cards, character restrictions).
    - `tests/test_llm_builder.py`: Mock Ollama responses; test parsing, error handling, JSON retry.
    - `tests/test_build_pipeline.py`: Test full pipeline orchestration.
    - Update `tests/test_api.py`: Add `generation_mode` parameter tests, `character_type` filtering tests.

20. **Manual smoke tests**
    - Run at 1280px and 768px.
    - Include a smoke test confirming that a dropped hallucinated/illegal Kimi recommendation appears in the UI's Kimi reasoning section.
    - Confirm `/planner` and `/compare` remain unchanged.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Kimi hallucinates perk IDs despite allowed list | Medium | High | Repair layer drops unknown IDs; fallback deterministic picks fill gaps |
| LLM latency too high for good UX | Medium | Medium | Return deterministic baseline immediately; stream LLM candidate when ready |
| SPECIAL budget violated by LLM | Medium | High | Validator caps ranks; repair layer rebalances |
| Ghoul/armor/health conflict in LLM output | Low | High | Repair layer removes incompatible cards; validator flags conflicts |
| Frontend rewrite breaks existing planner | Low | High | Keep `/planner` as separate manual editor; only redesign `/` |
| Ollama API unavailable | Low | Medium | Gracefully degrade to deterministic-only mode |

## Verification Steps

1. Run `pytest` and confirm all existing tests pass.
2. Run new tests: `pytest tests/test_repair.py`, `tests/test_llm_builder.py`, `tests/test_build_pipeline.py`.
3. Start the server: `uvicorn app.main:app --reload`.
4. Open `http://localhost:8000/` and submit a build goal.
5. Verify the center board shows 7 SPECIAL columns with perk cards.
6. Verify the right panel shows build summary, validation status, and repair notes.
7. Click "Regenerate" and verify a new build is generated.
8. Verify `/planner` still works as a manual editor.
9. Disable Ollama (remove `OLLAMA_API_KEY`) and verify deterministic fallback works.
10. Test with a Playable Ghoul build and verify ghoul restrictions are enforced.
11. Mock a Kimi response recommending an illegal Legendary Perk; confirm backend drops it and UI shows the brain_note.

## Taxonomy Rules for Coding Agent

Do not treat weapons, regular perk cards, Legendary Perks, or meta labels as primary playstyles.

- **Specific weapons** (Plasma Caster, Cremator, Pepper Shaker, Railway Rifle, Fixer, Handmade, Auto Axe, Chainsaw, Gauss Shotgun, Cold Shoulder, Alien Blaster, Tesla Rifle, Gatling Plasma, Gatling Laser, Holy Fire) belong in `preferred_weapons`, `current_gear`, gear recommendations, or LLM interpretation.
- **Regular perk cards** (Bullet Storm, Pyromaniac, Onslaught, Stabilized, Tank Killer, Demolition Expert, Grenadier, Tenderizer, Adrenaline, Concentrated Fire, Science cards) are generated output, not Legendary Perks and not primary playstyles.
- **Legendary Perks** (Electric Absorption, Funky Duds, Sizzling Style, Legendary SPECIAL perks, What Rads?, Ammo Factory, Master Infiltrator, Taking One For The Team, Follow Through, Hack and Slash, Action Diet, Feral Rage) must remain in the separate Legendary Perk layer.
- Do not hard-code target counts (22 or 26) for legendary perks. Refresh against live sources.

## Changelog

- 2026-05-06: Initial plan drafted.
- 2026-05-06: Addendum applied — explicit `revision_intent` behavior, `summarize_effect()`, `What Rads?` handling, XP/Crafting fallback templates, character-type change UX, constrained playstyle dropdown, existing-build compatibility, UI smoke test, cache behavior.
