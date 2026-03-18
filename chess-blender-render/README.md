# Chess Animation Pipeline

This repository renders a 3D chess move animation from two FEN positions and encodes the result to MP4.

The pipeline:

1. Parses two FEN strings as `before` and `after`.
2. Diffs the positions to infer the move.
3. Builds a Blender scene with board, pieces, hand, and captured-piece staging.
4. Renders a PNG frame sequence in Docker using `linuxserver/blender`.
5. Encodes the sequence to H.264 MP4 with local `ffmpeg`.

## Repository Layout

- [`scripts/run_pipeline.py`](/Users/dennis/customers/me/chessanimation/scripts/run_pipeline.py)
  Host-side entrypoint. Runs Docker, invokes Blender, and encodes MP4.
- [`scripts/render_chess_blender.py`](/Users/dennis/customers/me/chessanimation/scripts/render_chess_blender.py)
  Blender Python scene builder and animation logic.
- [`assets/source/chess-3d-models`](/Users/dennis/customers/me/chessanimation/assets/source/chess-3d-models)
  Vendored chess piece and board source assets.
- [`assets/source/leapjs-rigged-hand`](/Users/dennis/customers/me/chessanimation/assets/source/leapjs-rigged-hand)
  Vendored rigged hand asset.
- [`assets/ATTRIBUTION.md`](/Users/dennis/customers/me/chessanimation/assets/ATTRIBUTION.md)
  Asset provenance and license references.
- `tmp/`
  Intermediate frame sequences. Created by the runner.
- `renders/`
  Final MP4 outputs.

## Requirements

- Python 3
- Docker
- `ffmpeg`

The runner automatically pulls `lscr.io/linuxserver/blender:latest` if it is not already present locally.

## Quick Start

Example:

```bash
python3 scripts/run_pipeline.py \
  --before-fen "r1bqkb1r/ppp1nppp/2np4/4p3/4P3/2PP1N2/PP3PPP/RNBQKB1R w KQkq - 0 1" \
  --after-fen "r1bqkb1r/ppp1nppp/2np4/4N3/4P3/2PP4/PP3PPP/RNBQKB1R b KQkq - 0 1" \
  --output renders/capture-test.mp4 \
  --seconds 3.5 \
  --fps 24 \
  --width 1280 \
  --height 720 \
  --samples 48
```

Output:

- MP4: `renders/capture-test.mp4`
- Intermediate frames: removed automatically unless `--keep-frames` is set

## CLI Reference

`python3 scripts/run_pipeline.py [options]`

Required arguments:

- `--before-fen`
  Full FEN for the starting position.
- `--after-fen`
  Full FEN for the ending position.
- `--output`
  Output MP4 path. Relative paths are resolved from the repo root.

Optional arguments:

- `--seconds`
  Total animation duration in seconds. Default: `3.5`
- `--fps`
  Output frame rate. Default: `24`
- `--width`
  Render width in pixels. Default: `1280`
- `--height`
  Render height in pixels. Default: `720`
- `--samples`
  Blender render samples. Default: `48`
- `--engine`
  Blender render engine. Default: `BLENDER_EEVEE`
- `--docker-image`
  Blender image to use. Default: `lscr.io/linuxserver/blender:latest`
- `--keep-frames`
  Keep the PNG frame sequence under `tmp/<output-stem>/`

## Recommended Settings

Fast iteration:

```bash
python3 scripts/run_pipeline.py \
  --before-fen "<before>" \
  --after-fen "<after>" \
  --output renders/dev.mp4 \
  --seconds 1.5 \
  --fps 12 \
  --width 640 \
  --height 360 \
  --samples 8 \
  --keep-frames
```

Final output:

```bash
python3 scripts/run_pipeline.py \
  --before-fen "<before>" \
  --after-fen "<after>" \
  --output renders/final.mp4 \
  --seconds 3.5 \
  --fps 24 \
  --width 1280 \
  --height 720 \
  --samples 48
```

## How Move Detection Works

The animation does not take SAN or UCI directly. It infers the move by comparing the two FEN positions.

Supported cases:

- normal moves
- captures
- castling
- promotion

Important assumption:

- The two FENs must represent a single legal chess move transition.

If the board diff does not match a single supported move transition, the Blender script exits with an error.

## Current Scene Behavior

- The board is rendered from a diagonal camera angle.
- White and black pieces are placed from the `before` FEN.
- The moving side is taken from the active-color field in the `before` FEN.
- A rigged hand enters from the moving side, grips the moving piece, carries it, and releases it.
- Captured pieces are placed on side trays according to the resulting board state.
- The final MP4 is encoded as H.264 `yuv420p` for broad compatibility.

## Rendering Internals

The host runner launches Blender like this, conceptually:

1. Mounts the repo into `/workspace` in the container.
2. Runs Blender headless with [`scripts/render_chess_blender.py`](/Users/dennis/customers/me/chessanimation/scripts/render_chess_blender.py).
3. Writes PNGs into `tmp/<output-name>/`.
4. Runs `ffmpeg` locally to encode the PNG sequence to MP4.

The Dockerized Blender stage is used because the repository assumes Blender is provided by the container rather than installed directly on the host.

## Assets

Vendored chess assets:

- Source repo: `soda-without-bekerman/chess-3d-models`
- License: MIT

Vendored hand asset:

- Source repo: `leapmotion/leapjs-rigged-hand`
- License: Apache-2.0

See [`assets/ATTRIBUTION.md`](/Users/dennis/customers/me/chessanimation/assets/ATTRIBUTION.md) for details.

## Limitations

- The move must be inferable as a single transition from `before` to `after`.
- The current captured-piece tray layout is functional, not final art direction.
- The board, camera, and hand choreography are tuned for this repo’s current presentation, not for every possible cinematic style.
- The pipeline does not yet take SAN, UCI, PGN, audio, or multi-move sequences.

## Troubleshooting

If Docker fails:

- Confirm Docker Desktop or the Docker daemon is running.
- Confirm you can run `docker ps`.

If MP4 encoding fails:

- Confirm `ffmpeg` is installed and on `PATH`.

If the move is rejected:

- Check that the two FENs differ by exactly one supported chess move.
- Check that the active side in the `before` FEN matches the mover.

If you want to inspect frames:

- Render with `--keep-frames`
- Review the generated PNGs in `tmp/<output-stem>/`

## Cleanup

Remove intermediate frames manually if you rendered with `--keep-frames`:

```bash
rm -rf tmp/<output-stem>
```

Remove generated MP4s manually:

```bash
rm -f renders/<name>.mp4
```
