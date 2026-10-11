#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from argparse import _SubParsersAction, ArgumentParser, Namespace
import logging
import sys

from pv2n import (
    CONFIG_FILENAME,
    DEFAULT_CACHE_DIR,
    DEFAULT_CAPTURE_OFFSETS,
    DEFAULT_CAPTURE_POSITIONS,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TRANSCRIBE_LANGUAGE,
    DEFAULT_MIN_SCENE_LEN,
    DEFAULT_THRESHOLD,
    DEFAULT_WHISPER_MODEL,
    run_init,
    run_transcribe,
    run_extract_keyframes,
    run_capture_frame,
    run_generate_transcript_markdown,
    run_resize,
)

_LOG_FORMAT: str = '%(asctime)s p%(process)d %(threadName)s %(name)s %(levelname)s %(message)s'
_LOGGER: logging.Logger = logging.getLogger(__name__)


########################################
# pv2n init
def _cmd_init(args: Namespace) -> None:
    _LOGGER.info("Running init ...")
    run_init()


########################################
# pv2n transcribe
def _cmd_transcribe(args: Namespace) -> None:
    _LOGGER.info("Running transcribe ...")

    for input in args.inputs:
        run_transcribe( \
            filepath=input,
            rebuild_cache=args.rebuild_cache,
            output_dir=args.output_dir,
            cache_dir=args.cache_dir,
            whisper_model=args.whisper_model,
            transcribe_language=args.transcribe_language,
            config_path=args.config_path)


########################################
# pv2n extract-keyframes FILE
def _cmd_extract_keyframes(args: argparse.Namespace) -> None:
    _LOGGER.info("Running extract keyframes ...")

    for input in args.inputs:
        run_extract_keyframes( \
            filepath=input,
            rebuild_cache=args.rebuild_cache,
            output_dir=args.output_dir,
            cache_dir=args.cache_dir,
            threshold=args.threshold,
            min_scene_len=args.min_scene_len,
            capture_positions=args.capture_positions,
            capture_offsets=args.capture_offsets,
            config_path=args.config_path)


########################################
# pv2n capture-frame FILE
def _cmd_capture_frame(args: argparse.Namespace) -> None:

    _LOGGER.info("Capturing frames with specified timestamp...")

    run_capture_frame( \
        filepath=args.input,
        timestamp_strs=args.timestamps,
        rebuild_cache=args.rebuild_cache,
        output_dir=args.output_dir,
        cache_dir=args.cache_dir,
        config_path=args.config_path)


########################################
# pv2n md FILE
def _cmd_md(args: argparse.Namespace) -> None:
    _LOGGER.info("Running generation of transcript markdown ...")

    for input in args.inputs:
        run_generate_transcript_markdown( \
            filepath=input,
            rebuild_cache=args.rebuild_cache,
            output_dir=args.output_dir,
            cache_dir=args.cache_dir,
            config_path=args.config_path)


########################################
# pv2n resize
def _cmd_resize(args: argparse.Namespace) -> None:
    _LOGGER.info("Running resize ...")
    run_resize(directory=args.directory, ratio=args.ratio)


########################################
# argument utils


def _add_input_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "input",
        nargs=None,
        metavar="INPUT",
        help="Path to input MP4 file.",
    )


def _add_inputs_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "inputs",
        nargs="+",
        metavar="INPUT",
        help="Path(s) to input MP4 file(s). Multiple files are processed in order.",
    )


def _add_loglevel_args(parser: ArgumentParser) -> None:
    """Add arguments common to all subcommands (e.g. --loglevel)."""
    parser.add_argument("--loglevel", default="INFO", metavar="LEVEL", help="Logging level (default: INFO).")


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        metavar="FILE",
        help=f"Path to the TOML config file (default: {CONFIG_FILENAME} in the current directory).",
    )


def _add_output_dir_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,  # resolved after config is loaded
        help="Output directory (default: value from pv2n.toml, or ./output).",
    )
    parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        default=None,  # resolved after config is loaded
        help="Cache directory (default: value from pv2n.toml, or ./output/cache).",
    )
    parser.add_argument(
        "--rebuild-cache",
        action="store_true",
        help="Clear cache for this input and recompute from scratch.",
    )


def _add_whisper_args(parser: argparse.ArgumentParser, no_lang: bool = False) -> None:
    """Add the --whisper-model and --language arguments shared by transcribe and md subcommands."""
    parser.add_argument(
        "--whisper-model",
        default=None,  # resolved after config is loaded
        choices=["tiny", "base", "small", "medium", "large"],
        metavar="MODEL",
        help=f"Whisper model size to use: tiny, base, small, medium, large "
             f"(default: value from pv2n.toml, or {DEFAULT_WHISPER_MODEL}).",
    )
    parser.add_argument(
        "--language",
        dest="transcribe_language",
        default=None,  # resolved after config is loaded
        help=f"Transcription language code "
                f"(default: value from pv2n.toml, or {DEFAULT_TRANSCRIBE_LANGUAGE}).",
    )


def _add_extract_keyframes_args(parser: argparse.ArgumentParser) -> None:
    """Add the --threshold argument shared by extract and md subcommands."""
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=None,  # resolved after config is loaded
        help=f"Scene detection sensitivity (default: value from pv2n.toml, or {DEFAULT_THRESHOLD}).",
    )

    parser.add_argument(
        "--min-scene-len",
        type=float,
        default=None,  # resolved after config is loaded
        dest="min_scene_len",
        help=(
            "Minimum duration in seconds between scene cuts "
            f"(default: value from pv2n.toml, or {DEFAULT_MIN_SCENE_LEN}). "
            "Must be a float — an integer would be treated as a frame count by PySceneDetect."
        ),
    )

    parser.add_argument(
        "--capture-positions", "-p",
        type=float,
        nargs="+",
        default=None,  # resolved after config is loaded
        dest="capture_positions",
        metavar="POS",
        help=(
            "One or more relative positions within each scene at which to capture a frame "
            "(0.0=start, 0.5=midpoint, 1.0=end). "
            f"Accepts multiple values (e.g. --capture-positions 0.0 0.5 1.0). "
            f"Default: value from pv2n.toml, or {DEFAULT_CAPTURE_POSITIONS}."
        ),
    )

    parser.add_argument(
        "--capture-offsets", "-o",
        type=float,
        nargs="+",
        default=None,  # resolved after config is loaded
        dest="capture_offsets",
        metavar="SEC",
        help=(
            "One or more offsets in seconds from the scene start at which to also capture a frame. "
            "Frames whose computed timestamp falls outside the scene are skipped. "
            f"Accepts multiple values (e.g. --capture-offsets 2.0 5.0). "
            f"Default: value from pv2n.toml, or {DEFAULT_CAPTURE_OFFSETS}."
        ),
    )


def _build_parser() -> ArgumentParser:
    """Build the `pv2n` argument parser with its subcommands."""

    # width=160: wide enough for large displays, prevents help text from wrapping too early.
    # max_help_position=40: the longest option string is 35 chars ("--threshold THRESHOLD, -t THRESHOLD"),
    # so 35 + 2 (padding) = 37 is the minimum; 40 gives a small margin.
    def fmt(prog: str) -> argparse.HelpFormatter:
        return argparse.HelpFormatter(prog, max_help_position=40, width=160)

    parser: ArgumentParser = ArgumentParser(
        prog="pv2n",
        description="Presentation Video to Notes (PV2N) turns recorded presentations into structured, visual notes.",
        formatter_class=fmt,
    )
    subparsers: _SubParsersAction[ArgumentParser] = parser.add_subparsers(dest="command", required=True)

    ########################################
    # init command
    init_parser = subparsers.add_parser(
        name="init",
        help="Initialise the project: write pv2n.toml, workflow.md, and agent skill files.",
        formatter_class=fmt,
    )
    init_parser.set_defaults(func=_cmd_init)
    _add_loglevel_args(init_parser)

    ########################################
    # transcribe command
    transcribe_parser = subparsers.add_parser(
        "transcribe",
        aliases=["t"],
        help="Transcribe one or more videos' audio and write {stem}.vtt.",
        formatter_class=fmt,
    )
    transcribe_parser.set_defaults(func=_cmd_transcribe)
    _add_inputs_args(transcribe_parser)
    _add_output_dir_args(transcribe_parser)
    _add_loglevel_args(transcribe_parser)
    _add_config_args(transcribe_parser)
    _add_whisper_args(transcribe_parser)

    ########################################
    # extract-keyframes command
    extract_parser = subparsers.add_parser(
        "extract-keyframes",
        aliases=["extract", "e"],
        help="Extract key frames from one or more videos and write {stem}.assets/.",
        formatter_class=fmt,
    )
    extract_parser.set_defaults(func=_cmd_extract_keyframes)
    _add_inputs_args(extract_parser)
    _add_output_dir_args(extract_parser)
    _add_loglevel_args(extract_parser)
    _add_config_args(extract_parser)
    _add_extract_keyframes_args(extract_parser)

    ########################################
    # capture-frame command
    capture_frame_parser = subparsers.add_parser(
        "capture-frame",
        aliases=["capture", "c"],
        help="Capture one or more frames at given timestamps and save them to the {stem}.assets/.",
        formatter_class=fmt,
    )
    capture_frame_parser.set_defaults(func=_cmd_capture_frame)
    _add_input_args(capture_frame_parser)
    capture_frame_parser.add_argument(
        "timestamps",
        nargs="+",
        metavar="TIMESTAMP",
        help="One or more timestamps to capture: MM:SS, MM:SS.mmm, HH:MM:SS, or HH:MM:SS.mmm (e.g. 05:06 01:05:06.123).",
    )
    _add_output_dir_args(capture_frame_parser)
    _add_loglevel_args(capture_frame_parser)
    _add_config_args(capture_frame_parser)

    ########################################
    # md command
    md_parser = subparsers.add_parser(
        "md",
        aliases=["m"],
        help="generate videos into Markdown reports.",
        formatter_class=fmt,
    )
    md_parser.set_defaults(func=_cmd_md)
    _add_inputs_args(md_parser)
    _add_output_dir_args(md_parser)
    _add_loglevel_args(md_parser)
    _add_config_args(md_parser)

    ########################################
    # resize command
    resize_parser = subparsers.add_parser(
        "resize",
        aliases=["r"],
        help="Resize all images in a directory. Renames <dir> to <dir>.bk and writes resized images to <dir>.",
        formatter_class=fmt,
    )
    resize_parser.set_defaults(func=_cmd_resize)
    resize_parser.add_argument(
        "directory",
        metavar="DIR",
        help="Path to the directory containing images to resize.",
    )
    resize_parser.add_argument(
        "--ratio",
        type=float,
        default=0.5,
        metavar="RATIO",
        help="Scale factor applied to both width and height (default: 0.5, i.e. 1/4 the area).",
    )
    _add_loglevel_args(resize_parser)

    return parser


########################################
# main


def main() -> int:
    """Entry point for the `pv2n` console script."""
    parser: ArgumentParser = _build_parser()
    args: Namespace = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.loglevel.upper(), logging.INFO),
        format=_LOG_FORMAT,
    )
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
