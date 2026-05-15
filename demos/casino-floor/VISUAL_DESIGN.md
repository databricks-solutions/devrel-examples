# Frontend Visual Direction

This note scopes the visual layer for the casino-floor demo. The simulation is now assumed to be **Mesa-first event generation** with an **AppKit replay UI**. Users observe and inspect the floor; they do not play games.

## Recommendation

Use **PixiJS with `@pixi/react` for the replay canvas**, **React/AppKit for controls and inspectors**, and **Tiled for authoring the floor map**.

The front end should feel like a small top-down 8-bit/Pokemon-style operations replay:

- A tile-based casino floor with slot banks, bar, entrance/exit, walls, carpet, and signage.
- Patron sprites moving between sampled positions from the generated run.
- Machine sprites that visually indicate status: active, idle, faulted, jackpot, selected.
- A replay timeline with play/pause, speed, scrub, and jump-to-event controls.
- A side inspector for selected patron, machine, or event.
- A telemetry feed synchronized with the replay time.

Pixi should own the visual floor. React should own the app chrome.

## Why PixiJS

PixiJS is a 2D WebGL/canvas renderer optimized for sprites, layers, atlases, tinting, filters, and animation. `@pixi/react` lets us integrate Pixi into a React app without making the whole app feel like a game engine.

Why it fits:

- It is strong at rendering many sprites and tile-like layers.
- It keeps the floor visually rich without turning the whole AppKit app into Phaser.
- It pairs well with React side panels and AppKit UI controls.
- It can smoothly interpolate patron sprites between Mesa-generated position samples.
- It supports sprite sheets, texture atlases, tinting, and outlines for highlights.

The replay loop is simple:

1. React owns `replayTime`.
2. Pixi receives floor layout, entities, and sampled positions.
3. Pixi interpolates patrons between samples and highlights entities referenced by nearby events.
4. React side panels show the selected event, patron, machine, and metrics.

## Library Options

### PixiJS + `@pixi/react`

Best default.

Use for:

- Tile floor rendering.
- Patron sprites.
- Slot/bar/prop sprites.
- Highlight effects.
- Smooth replay interpolation.

Tradeoffs:

- We need to manage the render loop and asset loading explicitly.
- Tiled support is not as turnkey as Phaser, but the map format is simple enough for our scoped floor.

### Phaser

Good alternative if we want a full game engine.

Pros:

- Excellent Tiled map support.
- Built-in animation, cameras, scenes, collision, and asset pipelines.
- Official React + TypeScript templates exist.

Cons:

- Heavier than needed for a non-playable replay app.
- More engine lifecycle complexity inside an AppKit app.
- React and Phaser need an event bus boundary.

Use Phaser if:

- We decide the floor should behave like a game scene with richer camera work and editor-driven interactions.
- Tiled map authoring becomes central enough that Phaser's native support matters.

### SVG Or CSS Grid

Good for wireframes, not the polished visual target.

Pros:

- Easy DOM inspection and tooltips.
- Very fast to prototype.
- Works well for a static schematic view.

Cons:

- Less appealing for sprite animation.
- Pixel-perfect scaling and layering get fiddly.
- It will look more like a dashboard than an 8-bit floor.

Use this only for an early fallback or debug view.

### Canvas / Konva

Viable but less specialized than Pixi.

Pros:

- React-friendly.
- Good for simple shapes and moderate sprite counts.
- Easier mental model than a game engine.

Cons:

- Less mature for sprite atlas/tilemap workflows.
- We would rebuild more rendering behavior ourselves.

Use this if Pixi integration proves too much for the first visual slice.

### React Three Fiber

Not recommended for v1.

It would be useful if the aesthetic becomes isometric/3D, but it is overkill for crisp top-down pixel art.

## Map Authoring

Use **Tiled** as the map editor once the basic floor view exists.

Tiled gives us:

- Orthogonal tile maps.
- Layers for floor, walls, props, and overlays.
- Object layers for machines, bar seats, entrance, exit, waypoints, and zones.
- JSON export that the app can load.

Recommended first map:

- 16x16 or 32x32 tile size.
- 4 slot banks with 5 machines each.
- One bar/lounge area.
- One entrance/exit.
- A few decorative zones: carpet paths, wall edges, signage, plants, ropes.

The map should be visually authored, but entity IDs should come from data:

- `machine_id` maps to a Tiled object.
- `zone_id` maps to Tiled polygons or rectangles.
- Patron positions come from generated samples, not from Tiled.

## Asset Strategy

### Start With Licensed Packs

The fastest safe path is to start with a small licensed pixel-art pack and customize it.

Good sources to evaluate:

- Itch.io asset packs, especially top-down casino or indoor RPG tilesets.
- OpenGameArt for slot-machine and indoor pixel assets.
- Kenney assets for CC0 UI/props, even if casino-specific assets are limited.

The current preferred source is **2D Top-Down Pixel Art Tileset: Casino** by Jephed / Game Between The Lines. The creator states that the pack is free for commercial and non-commercial use, with suggested credit: `Jephed, Game Between The Lines, https://gamebetweenthelines.com/`.

Bundling policy:

- Do not commit the full downloaded asset pack by default.
- Commit only the cropped PNGs or frames the replay UI actually imports.
- Keep attribution beside the vendored assets.
- Revisit the asset subset when the Tiled map or sprite animation plan expands.

License checklist:

- Is commercial use allowed?
- Is attribution required?
- Can the raw assets be committed to a public repo?
- Can assets be modified?
- Are generated derivatives allowed?
- Are there any restrictions around gambling-themed use?

### Use AI As Concept And Drafting Help

AI can help, but should not be treated as a one-shot production asset generator.

Best use:

- Generate mood boards or single reference sprites.
- Explore palettes, carpet patterns, machine silhouettes, bar props, and patron archetypes.
- Create rough drafts that are then cleaned up manually.

Avoid:

- Asking for a complete sprite sheet and assuming it is usable.
- Referencing Pokemon or other protected IP directly in prompts.
- Using AI output without a licensing/provenance decision for public demo assets.

Practical workflow:

1. Pick a tile size: 16x16 for retro density or 32x32 for readability.
2. Pick a palette from Lospec or another permissive palette source.
3. Generate or source a single style reference.
4. Create a small asset list:
   - Floor tiles.
   - Wall tiles.
   - Slot machine idle/active/fault/jackpot.
   - Bar counter and stools.
   - Entrance/exit.
   - Patron sprites: 4 directions, 2-4 walking frames each.
5. Clean and align in Aseprite, LibreSprite, or Piskel.
6. Export sprite sheets with metadata.
7. Load the sprite sheets into Pixi.

AI sprite-sheet caveat:

General image models often produce inconsistent frames, uneven grids, and bad transparency. Treat AI frames as raw material, then normalize size, baseline, transparency, and palette in a pixel editor.

## Visual Style

Aim for:

- Top-down, orthogonal, 16-bit-ish rather than exact Pokemon imitation.
- Warm casino palette: deep carpet reds/purples, gold accents, neon blues, dark walls.
- Clear status language:
  - Green/blue glow: active.
  - Yellow pulse: jackpot/progressive event.
  - Red/orange icon: fault.
  - White outline: selected.
  - Grey tint: out of service.
- Patrons as readable colored sprites with minimal detail.
- Machines as slightly larger or brighter objects than patrons.

Avoid:

- Real casino brand marks.
- Recognizable Pokemon-style characters or tiles.
- Visuals that imply the user can play a slot.

## Replay Data Contract

The visual layer needs two streams:

### Entity Metadata

Static or slowly changing:

```json
{
  "machines": [
    {
      "machine_id": "slot-014",
      "x": 12,
      "y": 8,
      "facing": "south",
      "bank_id": "bank-c",
      "theme": "Neon Buffalo"
    }
  ],
  "zones": [
    { "zone_id": "bar", "type": "bar", "bounds": [2, 12, 7, 15] }
  ]
}
```

### Replay Samples

Time-indexed visual state:

```json
{
  "run_id": "run-001",
  "sim_ts": "2026-05-13T12:00:05Z",
  "patrons": [
    {
      "patron_id": "patron-042",
      "x": 10.25,
      "y": 7.5,
      "facing": "east",
      "activity": "WALKING",
      "target_id": "slot-014"
    }
  ],
  "machines": [
    {
      "machine_id": "slot-014",
      "status": "IN_SERVICE",
      "active_session_id": "session-123",
      "highlight": null
    }
  ]
}
```

Accounting events remain separate:

```json
{
  "event_id": "run-001-000123",
  "sim_ts": "2026-05-13T12:00:05Z",
  "event_type": "BET_SETTLED",
  "machine_id": "slot-014",
  "patron_id": "patron-042",
  "payload": {
    "bet_cents": 100,
    "win_cents": 0
  }
}
```

The UI joins these by `sim_ts`, `machine_id`, `patron_id`, and `session_id`.

## First Visual Slice

Build a thin vertical slice:

1. Static Tiled or JSON floor with 20 machines, bar, entrance, and exit.
2. Pixi canvas embedded in the AppKit React app.
3. Placeholder assets:
   - Colored patron circles or simple sprites.
   - Basic slot-machine rectangles or placeholder sprites.
   - Simple floor/wall tiles.
4. Replay controller:
   - Play/pause.
   - Speed selector.
   - Scrubber.
   - Current simulation timestamp.
5. A fake or generated sample replay file with a few patrons moving.
6. Click machine/patron to populate React inspector.
7. Event feed highlights referenced entities on the Pixi floor.

Only after this works should we spend time on final pixel art.

## Decision

Use **PixiJS + `@pixi/react` + Tiled-authored maps** for the first polished visual direction.

Use licensed placeholder assets first, then improve with a small custom or AI-assisted asset pipeline. Keep React/AppKit responsible for controls, inspectors, and analytics panels.

