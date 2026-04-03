# Scene Config Format

This project supports scene definitions via JSON files (for example `assets/*/scene.json`).

## Overview

Scene config has two top-level sections:

1. `sprites`: sprite catalog used by the scene.
2. `composition`: how to build the background using `layers`.

Current layer types:

1. `corridor`
2. `sky_horizon`
3. `roof01`

The engine renders layers in array order.

## Full Skeleton

```json
{
  "sprites": [
    {
      "id": "example_sprite",
      "kind": "static",
      "image": "example.png",
      "size": [32, 32]
    }
  ],
  "composition": {
    "layers": []
  }
}
```

## Sprites

Each entry in `sprites`:

1. `id` (string, required): unique sprite id.
2. `kind` (string, optional): `static`, `static_alpha`, or `animated_strip`. Default `static`.
3. `image` (string, required): path relative to the scene JSON file.
4. `frame_count` (int, optional): required for animated strips; defaults to `1`.
5. `size` ([w, h], optional): expected sprite/frame size for validation.

Notes:

1. `static` and `static_alpha` must use `frame_count = 1`.
2. `animated_strip` loads horizontal strip frames from one image.

## Composition Layers

`composition.layers` must be a non-empty array.

### `sky_horizon` layer

```json
{
  "type": "sky_horizon",
  "sky_sprite_id": "sky_main",
  "sky_scroll_divisor": 1,
  "horizon_base_y": 25,
  "horizon_scroll_divisor": 3,
  "horizon_offsets": [0, 0, -1, -1, -2, -1, 0, 1]
}
```

Fields:

1. `sky_sprite_id` (sprite id, required)
2. `sky_scroll_divisor` (int > 0, optional, default `1`)
3. `horizon_base_y` (int, required)
4. `horizon_scroll_divisor` (int > 0, optional, default `3`)
5. `horizon_offsets` (non-empty int array, required)

### `roof01` layer

```json
{
  "type": "roof01",
  "floor_sprite_id": "ledge_floor",
  "floor_height": 10,
  "roof_eli_sprite_id": "eli_main"
}
```

Fields:

1. `floor_sprite_id` (sprite id, required)
2. `floor_height` (int >= 0, required)
3. `roof_eli_sprite_id` (sprite id, required)

### `corridor` layer

```json
{
  "type": "corridor",
  "wall_brick_sprite_ids": ["brick_base", "brick_alt_1"],
  "floor_sprite_id": "floor_main",
  "floor_height": 9,
  "brick_start_offset_x": 7,
  "brick_start_offset_y": 3,
  "wall_underlay": {
    "sprite_id": "wall_underlay_sky",
    "scroll_divisor": 3,
    "horizon_base_y": 23,
    "horizon_scroll_divisor": 5,
    "horizon_offsets": [0, 0, -1, -2, -1, 0, 1]
  },
  "placements": [
    {
      "sprite_id": "door_main",
      "y_anchor": "floor_top",
      "clear_under_sprite": true,
      "distribution": {
        "mode": "segmented_random",
        "interval_px": 256,
        "count_per_interval": 1,
        "bootstrap_intervals": 1
      }
    }
  ]
}
```

Fields:

1. `wall_brick_sprite_ids` (non-empty sprite id array, required)
2. `floor_sprite_id` (sprite id, required)
3. `floor_height` (int >= 0, required)
4. `brick_start_offset_x` (int >= 0, optional, default `0`)
5. `brick_start_offset_y` (int >= 0, optional, default `0`)
6. `wall_underlay` (optional object, same shape as sky-horizon-with-renamed keys):
   1. `sprite_id`
   2. `scroll_divisor`
   3. `horizon_base_y`
   4. `horizon_scroll_divisor`
   5. `horizon_offsets`
7. `placements` (optional array, default `[]`)

## Placement Rule Format

Each item in `placements`:

1. `sprite_id` (sprite id, required)
2. `y_anchor` (optional): `wall_center` or `floor_top`, default `wall_center`
3. `clear_under_sprite` (optional bool, default `false`)
4. `composite_mode` (optional): `normal` or `transparent_cutout`, default `normal`
5. `avoid_overlap_with` (optional sprite id array, default `[]`)
6. `overlap_margin` (optional int >= 0, default `0`)
7. `distribution` (required object):
   1. `mode`: `segmented_random` or `repeat_every`
   2. `interval_px`: int > 0
   3. `count_per_interval`: int > 0, default `1`
   4. `bootstrap_intervals`: int >= 0, default `0`

## Legacy Compatibility

Old configs using `composition.mode` are still supported.

Legacy modes:

1. `brick_floor`
2. `sky_horizon`
3. `roof01`

They are internally adapted to equivalent `composition.layers`.

For new scenes, prefer `composition.layers`.

## Tips For New Scenes

1. Start from one of the existing `assets/*/scene.json` files.
2. Keep sprite ids stable and descriptive.
3. Add `size` to catch asset mistakes early.
4. Build scene in one layer first, then add more layers if needed.
5. Use small `placements` sets first; tune overlap/distribution after visual test.
