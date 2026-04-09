## Prototype 2 (Godot):

### Phase 1 — Concept and Foundation

- [x] Define core concept: moral parsimony as maze navigation
- [x] Research moral foundations (Haidt, deontological/consequentialist traditions)
- [x] Select principles that guide perk creation
- [x] Write loss messages for when each principle is dropped
- [x] Research GDScript, read relevant documentation, consult LLM.
- [x] Set up project structure (scripts, scenes, assets directories)
- [x] Configure project.godot (autoloads, input mapping, display settings)

### Phase 2 — Maze Generation

- [x] Implement block-grid data model (0 = floor, 1 = wall, 2 = tagged wall)
- [x] Implement room-to-block coordinate conversion
- [x] Implement recursive backtracker corridor carving (learned that from my Mo maze Maker days)
- [x] Implement BFS distance measurement from start room (good old days)
- [x] Implement dead-end detection (rooms with one open passage)
- [x] Implement principle-tagged shortcut walls (conditional passages)
- [x] Implement goal placement (farthest room from start...but not sure I know enough to do that)
- [x] Parameterize generation with config dictionary (width, height, shortcut chance, thresholds)

### Phase 3 — Rendering

- [x] Implement isometric projection (grid position to screen coordinates)
- [x] Draw floor tiles as diamond polygons for open cells, draw walls as isometric cubes (easy option, stripped down)
- [x] Draw start, intersection, and end markers
- [x] Implement wall visibility refresh when principles change
- [x] Implement principle-drop wall flash (walls reappear in the dropped principle's color)
- [x] Draw floors under tagged walls (visible when wall disappears)

### Phase 4 — Player and Movement

- [x] Implement grid-based movement (WASD, pretty standard)
- [x] Implement move cooldown to prevent sliding (constraint movement)
- [x] Implement collision checking against maze grid
- [x] Implement bump animation when hitting walls (for that extra zing)
- [x] Implement win detection (reaching goal cell)
- [x] Implement threshold (the intersection markers) detection and drop flow (what happens when players drops a principle)
- [x] Implement smooth-follow isometric camera (not very difficult from the tutorials I saw)

### Phase 5 — Principle Abilities

- [x] Design six unique abilities tied to moral principles
- [x] Implement charge system (spend/refill per principle) to add a sense of scarcity
- [x] 1.Implement Pulse Scan: BFS to find nearby dead ends, flash entire corridor
- [x] 1.2.Implement dead-end corridor tracing (walk backward from dead end until junction)
- [x] 2.Implement Phase Walk: toggle phasing state, pass through one wall on next move
- [x] 3.Implement Break Wall: destroy nearest adjacent solid wall cell
- [x] 4.Implement Compass: BFS shortest path to goal, staggered flash visualization
- [x] 5.Implement Breadcrumbs: toggle visited-cell trail markers
- [x] 6.Implement Restore: add one charge to all other held abilities
- [x] Register number keys 1-6 as ability activation inputs (sounds logical?)
- [x] Implement ability failure feedback (no charges, no valid target)

### Phase 6 — Threshold System

- [x] Implement threshold placement at intersection junctions (3+ open passages), did learn that from my Unreal prototype...I suppose will be easier here.
- [x] Space thresholds evenly across distance tiers (trying to balance randomness with consistency)
- [x] Implement forced principle drop at threshold (pause player, show selection, resume)
- [x] Remove used thresholds so they do not re-trigger
- [x] Trigger maze visibility refresh after drop (if does not work maybe leave the threshold marker but deactivate it somehow)

### Phase 7 — Level Progression

- [x] Define five level configurations (maze size, pick count, threshold count, shortcut density)
- [x] Implement level reset (clear held principles, refill charges, reset thresholds)
- [x] Implement full game reset (level 1, clean state)
- [x] Implement level completion flow (goal reached, show end screen, next level button)
- [x] Implement final level ending (reflection text, return to menu)

### Phase 8 — UI

- [x] Build main menu (title, subtitle, start button, tutorial button)
- [x] Build tutorial screen (movement, principles, abilities, thresholds, levels)
- [x] Build principle selection screen (pick mode and drop mode)
- [x] Build principle cards with name, description, ability info, and charge count
- [x] Build card toggle selection with visual highlight
- [x] Build HUD bar (level indicator, held principles with ability names and charges)
- [x] Build ability feedback text (activation confirmation, failure messages)
- [x] Build loss overlay (dimmer + loss message when principle dropped)
- [x] Build end screen (kept principles, dropped principles with loss messages)
- [x] Build level transition (continue to next level / return to menu)

### Phase 9 — Cuts and Simplification

- [x] Remove moral dilemma encounter system (text scenarios, encounter UI, encounter data)
- [x] Remove encounter_system.gd, encounter_ui.gd, encounter.gd, encounter_response.gd, maze_cell.gd
- [x] Remove encounter placement from maze generator
- [x] Remove encounter detection from player movement
