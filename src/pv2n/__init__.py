from __future__ import annotations

import importlib.resources
import json
import logging
import os
import shutil

# import tomllib # from 3.11
import toml  # to 3.10

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, cast

import whisper
from whisper.model import Whisper
from whisper.utils import get_writer

from scenedetect import FrameTimecode

Segment = dict[str, Any]
Frame = dict[str, Any]
Section = dict[str, Any]

CONFIG_FILENAME: str = "pv2n.toml"

PARAMETER_DESCRIPTIONS = {}

DEFAULT_OUTPUT_DIR: str = "output"
PARAMETER_DESCRIPTIONS["output_dir"] = ("Default output directory, relative to the current working directory", )

DEFAULT_CACHE_DIR: str = "output/cache"
PARAMETER_DESCRIPTIONS["cache_dir"] = ("Default cache directory, relative to the current working directory", )

DEFAULT_TRANSCRIBE_LANGUAGE: str = "en"
PARAMETER_DESCRIPTIONS["transcribe_language"] = \
    ("[pv2n transcribe] Default transcription language code passed to Whisper",)

DEFAULT_WHISPER_MODEL: str = "medium"
PARAMETER_DESCRIPTIONS["whisper_model_name"] = \
    ('[pv2n transcribe] Default Whisper model size: one of "tiny", "base", "small", "medium", or "large"',)

DEFAULT_THRESHOLD: float = 2.0
PARAMETER_DESCRIPTIONS["threshold"] = \
    ("[pv2n extract-keyframes] Scene-cut sensitivity. Lower values capture more frames; higher values capture fewer frames.",)

DEFAULT_MIN_SCENE_LEN: float = 5.0
PARAMETER_DESCRIPTIONS["min_scene_len"] = \
    ("[pv2n extract-keyframes] Minimum interval, in seconds, between detected keyframes",)

DEFAULT_CAPTURE_OFFSETS: list[float] = [1]
PARAMETER_DESCRIPTIONS["capture_offsets"] = \
    ("[pv2n extract-keyframes] Time offsets, in seconds, applied to each detected keyframe timestamp.",
    "For example, specify 1 or 2 seconds to skip slide transition animations.",
    "For example, specify -1 and 1 seconds to capture both before and after slide transition animations.")

DEFAULT_CAPTURE_POSITIONS: list[float] = []
PARAMETER_DESCRIPTIONS["capture_positions"] = \
    ("[pv2n extract-keyframes] Relative positions within each scene to capture, where 0.0 is the start and 1.0 is the end.",
    "For example, specify 0.0, 0.5, and 1.0 to capture the start, middle, and end of each scene.")

_LOGGER: logging.Logger = logging.getLogger(__name__)

################################################################################
# Config


def _default_config_path() -> str:
    return os.path.join(os.getcwd(), CONFIG_FILENAME)


@dataclass
class Config:
    """Project configuration, loaded from ``pv2n.toml``."""

    output_dir: str = DEFAULT_OUTPUT_DIR
    cache_dir: str = DEFAULT_CACHE_DIR
    whisper_model_name: str = DEFAULT_WHISPER_MODEL
    transcribe_language: str = DEFAULT_TRANSCRIBE_LANGUAGE
    threshold: float = DEFAULT_THRESHOLD
    min_scene_len: float = DEFAULT_MIN_SCENE_LEN
    capture_offsets: list[float] = field(default_factory=lambda: DEFAULT_CAPTURE_OFFSETS)
    capture_positions: list[float] = field(default_factory=lambda: DEFAULT_CAPTURE_POSITIONS)

    @classmethod
    def load(cls, \
        config_path: Optional[str] = None,
        output_dir: Optional[str] = None,
        cache_dir: Optional[str] = None,
        whisper_model_name: Optional[str] = None,
        transcribe_language: Optional[str] = None,
        threshold: Optional[float] = None,
        min_scene_len: Optional[float] = None,
        capture_offsets: Optional[list[float]] = None,
        capture_positions: Optional[list[float]] = None,
    ) -> Config:
        """Load ``pv2n.toml`` and return a :class:`Config`.

        If the file does not exist the default values are used.
        """
        config: Config
        path: str = config_path or _default_config_path()
        if not os.path.isfile(path):
            config = Config()
        else:
            _LOGGER.info("Loading config from %s ...", path)
            with open(path, "r", encoding="utf-8") as fh:
                data: dict[str, Any] = toml.load(fh)
            known: set[str] = set(cls.__dataclass_fields__)
            config = Config(**{k: v for k, v in data.items() if k in known})

        if output_dir is not None:
            config.output_dir = output_dir
        if cache_dir is not None:
            config.cache_dir = cache_dir
        if whisper_model_name is not None:
            config.whisper_model_name = whisper_model_name
        if transcribe_language is not None:
            config.transcribe_language = transcribe_language
        if threshold is not None:
            config.threshold = threshold
        if min_scene_len is not None:
            config.min_scene_len = min_scene_len
        if capture_offsets is not None:
            config.capture_offsets = capture_offsets
        if capture_positions is not None:
            config.capture_positions = capture_positions

        os.makedirs(config.output_dir, exist_ok=True)
        os.makedirs(config.cache_dir, exist_ok=True)

        return config

    def save(self, config_path: Optional[str] = None) -> None:
        """Write this config to *config_path* as a TOML file.

        Only scalar values and lists of scalars are supported (sufficient for
        the flat ``pv2n.toml`` schema).
        """

        def _toml_value(v: Any) -> str:
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, str):
                return f'"{v}"'
            if isinstance(v, list):
                items = ", ".join(_toml_value(i) for i in v)
                return f"[{items}]"
            return str(v)

        path: str = config_path or _default_config_path()
        lines: list[str] = ["# pv2n configuration — generated by `pv2n init`\n", "\n"]
        for key, value in asdict(self).items():
            if key in PARAMETER_DESCRIPTIONS:
                descriptions = PARAMETER_DESCRIPTIONS[key]
                for description in descriptions:
                    lines.append(f"# {description}\n")
            lines.append(f"{key} = {_toml_value(value)}\n")
            lines.append("\n")
        _LOGGER.info("Writing config to %s ...", path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)


################################################################################
# Init
_INIT_RESOURCES_FOR_SKILL: list[str] = [
    "transcript-to-notes.md",
]


def run_init() -> None:
    Config().save()
    for filename in _INIT_RESOURCES_FOR_SKILL:
        src = importlib.resources.files("pv2n.resources").joinpath(filename)

        basename = Path(filename).stem
        dest_dir: Path = Path.cwd() / "agents" / "skills" / basename
        dest: Path = dest_dir / "SKILL.md"

        _LOGGER.info("Ensuring the parent directory: %s", dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        _LOGGER.info("Writing %s ...", dest)
        with importlib.resources.as_file(src) as src_path:
            shutil.copy(src_path, dest)


################################################################################
# Movie Context
@dataclass
class MovieContext:

    config: Config
    filepath: str
    filestem: str

    rebuild_cache: bool = False

    @classmethod
    def create(
        cls,
        config: Config,
        filepath: str,
        rebuild_cache: Optional[bool] = False,
    ) -> MovieContext:

        if not os.path.isfile(filepath):
            _LOGGER.error("Input file not found: %s", filepath)
            raise FileNotFoundError("Input file not found: %s" % filepath)

        filestem: str = os.path.splitext(os.path.basename(filepath))[0]
        rebuild_cache = True if rebuild_cache else False
        return MovieContext(config, filepath, filestem, rebuild_cache)

    @property
    def whisper_json(self) -> str:
        return os.path.join(self.config.cache_dir, f"{self.filestem}_whisper.json")

    @property
    def whisper_vtt(self) -> str:
        return os.path.join(self.config.output_dir, f"{self.filestem}.vtt")

    @property
    def assets_dir(self) -> str:
        assets_dir: str = os.path.join(self.config.output_dir, f"{self.filestem}.assets")
        os.makedirs(assets_dir, exist_ok=True)
        return assets_dir

    @property
    def transcript_md(self) -> str:
        return os.path.join(self.config.output_dir, f"{self.filestem}_transcript.md")


################################################################################
# Transcribe


def _clear_transcription_cache(movie_context: MovieContext) -> None:

    # Delete the Whisper JSON file if it exists
    if os.path.isfile(movie_context.whisper_json):
        os.remove(movie_context.whisper_json)
    if os.path.isfile(movie_context.whisper_vtt):
        os.remove(movie_context.whisper_vtt)


def _load_transcript(movie_context) -> Optional[list[Segment]]:
    if os.path.isfile(movie_context.whisper_json) \
        and os.path.isfile(movie_context.whisper_vtt):
        _LOGGER.info("Using cached transcript: %s and %s", movie_context.whisper_json, movie_context.whisper_vtt)
        with open(movie_context.whisper_json, encoding="utf-8") as f:
            return json.load(f)
    return None


def _transcribe_audio(
    movie_context: MovieContext,
    output_dir: str,
    whisper_model_name: str,
    transcribe_language: str,
) -> list[Segment]:

    # Return early if a cached transcript already exists
    _segments: Optional[list[Segment]] = _load_transcript(movie_context)
    if _segments is not None:
        return _segments

    # Load the model weights into memory and run transcription, if not already cached
    _LOGGER.info("Loading Whisper model '%s'...", whisper_model_name)
    model: Whisper = whisper.load_model(whisper_model_name)

    _LOGGER.info("Transcribing audio from '%s' (language=%s)...", movie_context.filepath, transcribe_language)
    result: dict[str, Any] = model.transcribe(movie_context.filepath, language=transcribe_language, verbose=False)

    # Normalise the raw output to a flat list of {start, end, text} dicts
    raw_segments: list[dict[str, Any]] = cast(list[dict[str, Any]], result["segments"])
    segments: list[Segment] = [{"start": s["start"], "end": s["end"], "text": s["text"].strip()} for s in raw_segments]

    # Persist the result so subsequent runs skip transcription
    _LOGGER.info("Writing transcript cache to %s ...", movie_context.whisper_json)
    with open(movie_context.whisper_json, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    _LOGGER.info("Transcript cache written (%d segments).", len(segments))

    _LOGGER.info("Writing transcript vtt to %s ...", movie_context.whisper_vtt)
    vtt_writer = cast(Callable[[dict, str, dict], None], get_writer("vtt", output_dir))
    vtt_writer(result, movie_context.filepath, {})

    return segments


def run_transcribe(
    filepath: str,
    rebuild_cache: bool = False,
    output_dir: Optional[str] = None,
    cache_dir: Optional[str] = None,
    whisper_model: Optional[str] = None,
    transcribe_language: Optional[str] = None,
    config_path: Optional[str] = None,
) -> list[Segment]:

    config: Config = Config.load(config_path, output_dir=output_dir, cache_dir=cache_dir, whisper_model_name=whisper_model, transcribe_language=transcribe_language)
    movie_context: MovieContext = MovieContext.create(config, filepath=filepath, rebuild_cache=rebuild_cache)

    # Optionally invalidate the existing Whisper cache to force re-transcription
    if movie_context.rebuild_cache:
        _LOGGER.info("Clearing transcription cache and output for '%s'...", movie_context.filestem)
        _clear_transcription_cache(movie_context)

    # Transcribe the audio (uses cache if available)
    segments: list[Segment] = _transcribe_audio(
        movie_context, \
        output_dir=config.output_dir,
        whisper_model_name=config.whisper_model_name,
        transcribe_language=config.transcribe_language)

    return segments


################################################################################
# Extract key frames
def _clear_frames_cache(movie_context: MovieContext) -> None:

    # Recursively remove the entire frames cache directory
    if os.path.isdir(movie_context.assets_dir):
        shutil.rmtree(movie_context.assets_dir)


def _hhmmss_to_sec(hhmmss: str) -> float:
    """Parse ``HH-MM-SS.SSS`` back to total seconds."""
    hh, mm, ss = hhmmss.split("-")
    return int(hh) * 3600 + int(mm) * 60 + float(ss)


def _sec_to_hhmmss(seconds: float) -> str:
    """Format total seconds as ``HH-MM-SS.SSS`` (HH zero-padded to 2 digits, but may exceed 99)."""
    hh = int(seconds) // 3600
    mm = (int(seconds) % 3600) // 60
    ss = seconds % 60
    return f"{hh:02d}-{mm:02d}-{ss:06.3f}"


def _load_cached_frames(movie_context: MovieContext) -> Optional[list[Frame]]:

    if os.path.isdir(movie_context.assets_dir):
        _LOGGER.info("Using existing key frames: %s", movie_context.assets_dir)

        frames: list[Frame] = []
        for name in os.listdir(movie_context.assets_dir):
            # Only process files that follow the expected frame_H-MM-SS.SSS.png naming scheme
            if name.startswith("frame_") and name.endswith(".png"):
                # Recover the original timestamp by parsing the HH-MM-SS.SSS suffix
                timestamp_sec: float = _hhmmss_to_sec(name[len("frame_"):-len(".png")])
                frames.append({
                    "timestamp_sec": timestamp_sec,
                    "image_path": os.path.join(movie_context.assets_dir, name),
                })
        # Sort by timestamp value (not filename string) to handle variable-width HH
        frames.sort(key=lambda f: f["timestamp_sec"])

        if len(frames) > 0:
            return frames

    return None


def _capture_frame_at(
    cap: Any,
    frames_dir: str,
    timestamp_sec: float,
    label: str,
) -> Optional[Frame]:
    """Seek *cap* to *timestamp_sec*, write a PNG to *frames_dir*, and return a
    :class:`Frame` dict, or ``None`` if the read fails.

    Args:
        cap:           An open ``cv2.VideoCapture`` instance positioned at the
                       start of the video.
        frames_dir:    Directory in which the PNG will be written.
        timestamp_sec: Absolute position in the video (seconds).
        label:         Human-readable label used only in the log message
                       (e.g. ``"pos=0.50"`` or ``"offset=+2.00s"``).
    """
    import cv2

    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000)
    ok: bool
    frame: Any
    ok, frame = cap.read()
    if not ok:
        return None
    image_path: str = os.path.join(frames_dir, f"frame_{_sec_to_hhmmss(timestamp_sec)}.png")
    _LOGGER.info("Writing frame at %.2fs (%s) → %s ...", timestamp_sec, label, image_path)
    cv2.imwrite(image_path, frame)
    return {"timestamp_sec": timestamp_sec, "image_path": image_path}


def _extract_keyframes(
    movie_context: MovieContext,
    threshold: float,
    min_scene_len: float,
    capture_positions: list[float],
    capture_offsets: list[float],
) -> list[Frame]:
    """Extract key frames from a video and save them as PNGs, with caching.

    If cached frames already exist for `stem` in `cache_dir`, they are
    reused and extraction is skipped. Otherwise, PySceneDetect's
    ContentDetector is used to find scene cuts, and the corresponding
    frames are extracted with OpenCV and saved as PNGs.

    Args:
        capture_positions: Relative positions within each scene at which to
            capture a frame. 0.0 = scene start, 0.5 = midpoint, 1.0 = scene end.
            Multiple values produce multiple frames per scene (e.g. [0.0, 0.5, 1.0]).
        capture_offsets: Absolute seconds from scene start at which to also
            capture a frame (e.g. [2.0, 5.0]). Timestamps that fall outside the
            scene's duration are silently skipped.
    """

    # Return early if frames have already been extracted and cached
    _frames: Optional[list[Frame]] = _load_cached_frames(movie_context)
    if _frames is not None:
        return _frames

    import cv2
    from scenedetect import ContentDetector, detect

    # Run PySceneDetect to find all scene-cut timestamps
    # min_scene_len must be float (seconds); an int would be interpreted as frame count
    detector: ContentDetector = ContentDetector(
        threshold=threshold,
        min_scene_len=min_scene_len,
    )
    _LOGGER.info(
        "Detecting scene cuts in '%s' (threshold=%.1f, min_scene_len=%.2fs)...",
        movie_context.filepath,
        threshold,
        min_scene_len,
    )
    scene_list: list[tuple[FrameTimecode, FrameTimecode]] = detect(movie_context.filepath, detector=detector)
    _LOGGER.info("Detected %d scene(s). Extracting frames...", len(scene_list))

    scene_start: FrameTimecode
    scene_end: FrameTimecode

    # Phase 1: Build the list of timestamps to capture from scene_list.
    timestamps: list[tuple[float, str]] = []  # (timestamp_sec, label)
    for scene_start, scene_end in scene_list:
        _LOGGER.debug("Detected scene_start=%s, scene_end=%s", scene_start, scene_end)
        start_sec: float = scene_start.get_seconds()
        end_sec: float = scene_end.get_seconds()

        for pos in capture_positions:
            # Interpolate: pos=0.0 → start, pos=0.5 → midpoint, pos=1.0 → end
            timestamp_sec: float = start_sec + pos * (end_sec - start_sec)
            timestamps.append((timestamp_sec, f"pos={pos:.2f}"))

        for offset in capture_offsets:
            # Absolute offset from scene start (negative values are allowed)
            timestamp_sec = start_sec + offset
            if timestamp_sec < 0:
                _LOGGER.debug("Skipping offset %+.2fs (%.2fs) — before start of video", offset, timestamp_sec)
                continue
            if timestamp_sec >= end_sec:
                _LOGGER.debug("Skipping offset %+.2fs (%.2fs) — outside scene [%.2fs, %.2fs)", offset, timestamp_sec, start_sec, end_sec)
                continue
            timestamps.append((timestamp_sec, f"offset={offset:+.2f}s"))

    # Open the video and capture frames at each requested position within every scene
    frames: list[Frame] = []

    cap: Any = cv2.VideoCapture(movie_context.filepath)
    try:
        # Phase 2: Capture frames for each collected timestamp.
        for timestamp_sec, label in timestamps:
            captured = _capture_frame_at(cap, movie_context.assets_dir, timestamp_sec, label)
            if captured:
                frames.append(captured)

    finally:
        cap.release()

    if not frames:
        # No cuts detected: fall back to the first frame of the video.
        _LOGGER.info("No scene cuts found; falling back to first frame.")
        cap: Any = cv2.VideoCapture(movie_context.filepath)
        try:
            ok, frame = cap.read()
            if ok:
                image_path: str = os.path.join(movie_context.assets_dir, "frame_00-00-00.000.png")
                _LOGGER.info("Writing fallback frame → %s ...", image_path)
                cv2.imwrite(image_path, frame)
                frames.append({"timestamp_sec": 0.0, "image_path": image_path})
        finally:
            cap.release()

    _LOGGER.info("Extracted %d key frame(s).", len(frames))
    return frames


def run_extract_keyframes(
    filepath: str,
    rebuild_cache: bool = False,
    output_dir: Optional[str] = None,
    cache_dir: Optional[str] = None,
    threshold: Optional[float] = None,
    min_scene_len: Optional[float] = None,
    capture_positions: Optional[list[float]] = None,
    capture_offsets: Optional[list[float]] = None,
    config_path: Optional[str] = None,
) -> None:

    config: Config = Config.load(config_path, \
        output_dir=output_dir,
        cache_dir=cache_dir,
        threshold = threshold,
        min_scene_len = min_scene_len,
        capture_positions = capture_positions,
        capture_offsets = capture_offsets)

    movie_context: MovieContext = MovieContext.create(config, filepath=filepath, rebuild_cache=rebuild_cache)

    # Optionally invalidate the existing frame cache to force re-extraction
    if rebuild_cache:
        _LOGGER.info("Rebuilding frames cache for '%s'...", movie_context.filestem)
        _clear_frames_cache(movie_context)

    # Extract keyframes (uses cache if available)
    _extract_keyframes(movie_context, \
        threshold = config.threshold,
        min_scene_len = config.min_scene_len,
        capture_positions = config.capture_positions,
        capture_offsets = config.capture_offsets)


################################################################################
# capture


def _parse_timestamp(value: str) -> float:
    """Parse a timestamp string into seconds.

    Accepted formats:

    * ``MM:SS``           e.g. ``05:06``         → 306.0
    * ``MM:SS.mmm``       e.g. ``05:06.500``     → 306.5
    * ``HH:MM:SS``        e.g. ``01:05:06``      → 3906.0
    * ``HH:MM:SS.mmm``    e.g. ``01:05:06.123``  → 3906.123
    """
    # Split on ":" to distinguish MM:SS from HH:MM:SS formats
    parts: list[str] = value.split(":")
    hour_sec: float
    min_part: str
    sec_part: str
    if len(parts) == 2:
        # MM:SS — no hours component
        hour_sec = 0.0
        min_part, sec_part = parts[0], parts[1]
    elif len(parts) == 3:
        # HH:MM:SS — convert hours to seconds up front
        hour_sec = int(parts[0]) * 3600.0
        min_part, sec_part = parts[1], parts[2]
    else:
        raise ValueError(f"Invalid timestamp '{value}': expected MM:SS or HH:MM:SS (with optional .mmm)")
    # Parse minutes as integer and seconds as float (handles optional .mmm)
    try:
        minutes: int = int(min_part)
        seconds: float = float(sec_part)
    except ValueError:
        raise ValueError(f"Invalid timestamp '{value}': expected MM:SS or HH:MM:SS (with optional .mmm)")
    # Validate ranges to catch obviously wrong user input early
    if minutes < 0:
        raise ValueError(f"Invalid timestamp '{value}': minutes must be >= 0")
    if seconds < 0 or seconds >= 60:
        raise ValueError(f"Invalid timestamp '{value}': seconds must be in [0, 60)")
    return hour_sec + minutes * 60.0 + seconds


def run_capture_frame(
    filepath: str,
    timestamp_strs: list[str],
    rebuild_cache: bool = False,
    output_dir: Optional[str] = None,
    cache_dir: Optional[str] = None,
    config_path: Optional[str] = None,
) -> None:

    config: Config = Config.load(config_path, \
        output_dir=output_dir,
        cache_dir=cache_dir)

    movie_context: MovieContext = MovieContext.create(config, filepath=filepath, rebuild_cache=rebuild_cache)

    import cv2

    # Parse and validate all timestamp strings up-front before opening the video
    timestamp_secs: list[float] = []
    for ts in timestamp_strs:
        try:
            timestamp_secs.append(_parse_timestamp(ts))
        except ValueError as e:
            _LOGGER.error("%s", e)
            raise

    cap: Any = cv2.VideoCapture(movie_context.filepath)
    try:
        ok: bool
        frame: Any
        for ts_str, timestamp_sec in zip(timestamp_strs, timestamp_secs):
            # Seek to the requested position and capture one frame
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000)
            ok, frame = cap.read()

            # If seek/read failed, report the error and continue with remaining timestamps
            if not ok:
                _LOGGER.error("Could not read frame at %s (%.3fs) from %s", ts_str, timestamp_sec, filepath)
                continue

            # Write the captured frame as a PNG using the standard naming convention
            image_path: str = os.path.join(movie_context.assets_dir, f"frame_{_sec_to_hhmmss(timestamp_sec)}.png")
            _LOGGER.info("Writing captured frame → %s ...", image_path)
            cv2.imwrite(image_path, frame)
            _LOGGER.info("Saved frame to %s", image_path)
    finally:
        cap.release()


################################################################################
# generate transcript markdown


def _build_sections(frames: list[Frame], segments: list[Segment]) -> list[Section]:
    """Associate each detected frame with the transcript segments spoken
    while that frame's slide was on screen.
    """
    # Sort frames chronologically so window boundaries are computed correctly
    sorted_frames: list[Frame] = sorted(frames, key=lambda f: f["timestamp_sec"])
    sections: list[Section] = []
    for i, frame in enumerate(sorted_frames):
        start: float = frame["timestamp_sec"]
        # The section ends at the next frame's timestamp, or the end of the video
        end: float = sorted_frames[i + 1]["timestamp_sec"] if i + 1 < len(sorted_frames) else float("inf")
        # Collect all transcript segments that fall within this frame's time window
        texts: list[str] = [s["text"] for s in segments if start <= s["start"] < end]
        sections.append({
            "timestamp_sec": start,
            "image_path": frame["image_path"],
            # Join all matching segment texts into a single transcript string
            "transcript": " ".join(texts).strip(),
        })
    return sections


def _format_timestamp(seconds: float) -> str:
    """Format a number of seconds as an `H:MM:SS` string."""
    # Truncate to whole seconds before splitting into hours/minutes/seconds
    total: int = int(seconds)
    h: int
    rem: int
    m: int
    s: int
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _generate_markdown(
    movie_context: MovieContext,
    sections: list[Section],
) -> str:

    # Build the Markdown document header with title and table of contents
    lines: list[str] = [
        f"# Transcription of Video with Screen Captures",
        "",
        "---",
        f"- Input file: {movie_context.filepath}",
        "---",
        "",
    ]
    # Append one section per keyframe, embedding the image and transcript text
    for i, section in enumerate(sections, start=1):
        frame_name = os.path.basename(section["image_path"])
        # Build a relative path from the report file to the assets directory
        rel_image_path = f"{os.path.basename(movie_context.assets_dir)}/{frame_name}"
        label = _format_timestamp(section["timestamp_sec"])
        lines.append("")
        lines.append("")
        lines.append(f"## {label}")
        lines.append("")
        lines.append(f"![Screen capture {i}]({rel_image_path})")
        lines.append("")
        lines.append("")
        # Fall back to a placeholder if no speech was detected for this slide
        lines.append(section["transcript"] or "(Silent section)")
        lines.append("")

    # Write all accumulated lines to the Markdown output file
    _LOGGER.info("Writing transcript Markdown to %s ...", movie_context.transcript_md)
    with open(movie_context.transcript_md, "wt", encoding="utf-8") as f:
        f.write("\n".join(lines))
    _LOGGER.info("Wrote %s", movie_context.transcript_md)
    return movie_context.transcript_md


def run_generate_transcript_markdown(
    filepath: str,
    rebuild_cache: bool = False,
    output_dir: Optional[str] = None,
    cache_dir: Optional[str] = None,
    config_path: Optional[str] = None,
) -> None:

    config: Config = Config.load(config_path, \
        output_dir=output_dir,
        cache_dir=cache_dir)

    movie_context: MovieContext = MovieContext.create(config, filepath=filepath, rebuild_cache=rebuild_cache)

    # Step 1: transcribe the audio track
    segments: Optional[list[Segment]] = _load_transcript(movie_context)
    if segments is None:
        raise ValueError("Failed to load transcript. Do 'pv2n t %s'" % filepath)

    # Step 2: detect and extract keyframes from the video
    frames: Optional[list[Frame]] = _load_cached_frames(movie_context)
    if frames is None:
        raise ValueError("Failed to load screen captures. Do 'pv2n e %s'" % filepath)

    # Step 3: align frames with transcript segments to form sections
    sections: list[Section] = _build_sections(frames, segments)

    # Step 4: write the Markdown report with embedded images
    _generate_markdown(movie_context, sections)


# ---------------------------------------------------------------------------
# resize command
# ---------------------------------------------------------------------------

_IMAGE_SUFFIXES: frozenset[str] = frozenset({
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
})


def run_resize(directory: str, ratio: float) -> None:

    import cv2

    src_path: Path = Path(directory).resolve()
    if not src_path.is_dir():
        raise ValueError("Not a directory: %s" % src_path)

    bk_path: Path = src_path.parent / (src_path.name + ".bk")

    _LOGGER.info("Renaming %s → %s ...", src_path, bk_path)
    src_path.rename(bk_path)

    _LOGGER.info("Creating output directory %s ...", src_path)
    src_path.mkdir(parents=True, exist_ok=False)

    image_files: list[Path] = sorted(bk_path.rglob("*"))
    for src_file in image_files:
        if not src_file.is_file():
            continue

        rel: Path = src_file.relative_to(bk_path)
        dst_file: Path = src_path / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)

        if src_file.suffix.lower() in _IMAGE_SUFFIXES:
            _LOGGER.info("Resizing %s ...", rel)
            img = cv2.imread(str(src_file), cv2.IMREAD_UNCHANGED)
            if img is None:
                _LOGGER.warning("cv2 could not read %s — copying as-is.", src_file)
                shutil.copy2(src_file, dst_file)
                continue
            resized = cv2.resize(
                img,
                dsize=(0, 0),
                fx=ratio,
                fy=ratio,
                interpolation=cv2.INTER_AREA,
            )
            cv2.imwrite(str(dst_file), resized)
        else:
            _LOGGER.info("Copying non-image file %s ...", rel)
            shutil.copy2(src_file, dst_file)

    _LOGGER.info("Resize complete. Original preserved in %s", bk_path)
