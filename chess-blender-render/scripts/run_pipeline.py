#!/usr/bin/env python3
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_IMAGE = "lscr.io/linuxserver/blender:latest"


def parse_args():
    parser = argparse.ArgumentParser(description="Render a chess move animation from two FEN strings.")
    parser.add_argument("--before-fen", required=True)
    parser.add_argument("--after-fen", required=True)
    parser.add_argument("--output", required=True, help="Output MP4 path")
    parser.add_argument("--seconds", type=float, default=3.5)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--samples", type=int, default=48)
    parser.add_argument("--engine", default="BLENDER_EEVEE")
    parser.add_argument("--docker-image", default=DEFAULT_IMAGE)
    parser.add_argument("--keep-frames", action="store_true")
    return parser.parse_args()


def run(command, cwd):
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def ensure_tool(name):
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required tool: {name}")


def ensure_docker_image(image, cwd):
    inspect = subprocess.run(
        ["docker", "image", "inspect", image],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if inspect.returncode == 0:
        return
    run(["docker", "pull", image], cwd)


def encode_mp4(frames_dir, output_path, fps, cwd):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "frame_%04d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        cwd,
    )


def render_with_blender(args, repo_root, frames_dir):
    uid = str(os.getuid())
    gid = str(os.getgid())
    blender_script = "/workspace/scripts/render_chess_blender.py"
    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{uid}:{gid}",
        "--shm-size=1gb",
        "-v",
        f"{repo_root}:/workspace",
        "-w",
        "/workspace",
        "--entrypoint",
        "blender",
        args.docker_image,
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        blender_script,
        "--",
        "--before-fen",
        args.before_fen,
        "--after-fen",
        args.after_fen,
        "--output-dir",
        f"/workspace/{frames_dir.relative_to(repo_root)}",
        "--fps",
        str(args.fps),
        "--seconds",
        str(args.seconds),
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--samples",
        str(args.samples),
        "--engine",
        args.engine,
        "--asset-root",
        "/workspace/assets/source/chess-3d-models",
    ]
    run(command, repo_root)


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = repo_root / output_path

    frames_dir = repo_root / "tmp" / output_path.stem
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    ensure_tool("docker")
    ensure_tool("ffmpeg")
    ensure_docker_image(args.docker_image, repo_root)
    render_with_blender(args, repo_root, frames_dir)
    encode_mp4(frames_dir, output_path, args.fps, repo_root)

    if not args.keep_frames:
        shutil.rmtree(frames_dir, ignore_errors=True)

    print(f"MP4 written to {output_path}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}", file=sys.stderr)
        raise
