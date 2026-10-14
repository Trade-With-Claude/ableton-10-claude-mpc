"""Master analysis: BlackHole capture + spectrum-advisor one-shot analysis (sync, run in a thread).

spectrum_advisor (librosa/scipy) is imported lazily so the MCP server starts fast.
"""

import time
from pathlib import Path

MIN_SECONDS = 10
MAX_SECONDS = 60
DEFAULT_BPM = 174.0


class AnalysisError(RuntimeError):
    """An anticipated analysis failure whose message tells the user how to fix it."""


def clamp_seconds(seconds) -> int:
    return max(MIN_SECONDS, min(int(seconds), MAX_SECONDS))


def resolve_reference(arg: str | None) -> tuple[Path | None, str | None]:
    """Reference track: tool argument -> spectrum-advisor's last used -> none."""
    if arg:
        path = Path(arg).expanduser()
        if not path.is_file():
            raise AnalysisError(f"Reference file not found: {path}")
        return path, "arg"
    from spectrum_advisor.ui import session

    last = session.load().last_reference_path
    if last and Path(last).expanduser().is_file():
        return Path(last).expanduser(), "last_used"
    return None, None


def run(seconds: int, reference: str | None, bpm: float | None) -> dict:
    from spectrum_advisor.analysis import oneshot
    from spectrum_advisor.audio import capture
    from spectrum_advisor.audio.samplerate import DeviceNotFoundError, SampleRateMismatchError

    seconds = clamp_seconds(seconds)
    ref_path, ref_source = resolve_reference(reference)
    t0 = time.perf_counter()
    try:
        profile = oneshot.load_reference_profile(ref_path) if ref_path else None
    except Exception as exc:
        raise AnalysisError(f"Could not load reference {ref_path}: {exc}") from exc
    try:
        frames = capture.record(seconds)
        result = oneshot.analyze_buffer(frames, ref=profile, mode="coach", bpm=bpm)
    except (DeviceNotFoundError, SampleRateMismatchError, oneshot.SilentCaptureError) as exc:
        raise AnalysisError(str(exc)) from exc
    result["seconds"] = seconds
    result["bpm"] = bpm
    result["reference_used"] = {"path": str(ref_path), "source": ref_source} if ref_path else None
    result["elapsed_s"] = round(time.perf_counter() - t0, 1)
    return result
