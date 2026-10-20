# -*- coding: utf-8 -*-
"""Record automation into the Arrangement by playing curves on parameters.

Live 10's API can't write Arrangement automation, but Live records parameter changes made
by a script while Arrangement record + Automation Arm are on. So a take is:
  start(): validate, snapshot transport + arms, disarm every track (so no audio/MIDI is
           recorded), loop off, Automation Arm on, play.
  tick():  (every update_display, ~10 Hz) on the first tick Live is playing, jump the
           playhead to `preroll_bars` before `start_bar` (setting it while stopped doesn't
           move where playback starts); punch in when it reaches start_bar, write each
           lane's value at the current beat, punch out at the end, stop and restore the
           snapshot. Stopping playback in Live aborts the take.
The params are only written from the punch-in on, so the automation Live keeps before
start_bar is the value they had before the take.

Pure Python 2.7 / 3 compatible, no Live imports (like lom.py and ops.py).
"""
from __future__ import absolute_import, division

import time

try:
    from . import curves
    from . import lom
    from . import ops
except (ImportError, ValueError):  # tests import it as a top-level module
    import curves
    import lom
    import ops

_text = lom._text
RUNNING = ("preroll", "recording")
START_TIMEOUT_TICKS = 50  # ~5 s for Live to report is_playing after start_playing()


class Recorder(object):
    def __init__(self, clock=time.time, log=None):
        self._clock = clock
        self._log = log or (lambda msg: None)
        self.state = "idle"
        self._reset()

    def _reset(self):
        self._song = None
        self._lanes = []
        self._snap = None
        self._begin = self._end = 0.0
        self._start_bar = self._bars = None
        self._seen_playing = False
        self._preroll_beat = 0.0
        self._ticks = 0
        self._points = 0
        self._tick_times = []
        self._beat = None
        self.error = None

    # -- control -------------------------------------------------------------
    def start(self, song, lanes, start_bar, bars, preroll_bars=1, overwrite=False):
        if self.state in RUNNING:
            raise RuntimeError(u"a take is already running (bar %s)" % self.status()["bar"])
        self._check_song(song)
        start_bar, bars, preroll_bars = float(start_bar), float(bars), float(preroll_bars)
        if start_bar < 1 or bars <= 0 or preroll_bars < 0:
            raise ValueError(u"need start_bar >= 1, bars > 0, preroll_bars >= 0")
        compiled = self._compile(song, lanes, start_bar, bars, overwrite)

        self._reset()
        self._song, self._lanes = song, compiled
        self._start_bar, self._bars = start_bar, bars
        self._begin = curves.bar_to_beat(start_bar)
        self._end = curves.bar_to_beat(start_bar + bars)
        self._snap = {
            "record_mode": song.record_mode,
            "session_automation_record": song.session_automation_record,
            "loop": song.loop,
            "current_song_time": song.current_song_time,
            "armed": [t for t in song.tracks if getattr(t, "can_be_armed", False) and t.arm],
        }
        self._preroll_beat = max(0.0, curves.bar_to_beat(start_bar - preroll_bars))
        try:
            for t in self._snap["armed"]:
                t.arm = False
            song.loop = False
            song.session_automation_record = True
            self.state = "preroll"
            song.start_playing()
        except Exception as e:
            self._fail(u"setup failed: %s" % _text(e))
            raise
        self._log(u"take armed: %d lane(s), bars %s-%s" % (len(compiled), start_bar, start_bar + bars))
        return self.status()

    def abort(self, reason=u"aborted"):
        if self.state in RUNNING:
            self._finish("aborted", reason)
        return self.status()

    def tick(self):
        if self.state not in RUNNING:
            return
        self._ticks += 1
        self._tick_times.append(self._clock())
        song = self._song
        try:
            playing = bool(song.is_playing)
            if playing and not self._seen_playing:
                self._seen_playing = True
                song.current_song_time = self._preroll_beat  # the pre-roll starts here
                return
            if not playing and self._seen_playing:
                self._finish("aborted", u"playback stopped in Live at bar %s" % self._bar())
                return
            if not playing:
                if self._ticks > START_TIMEOUT_TICKS:
                    self._fail(u"Live did not start playing")
                return
            beat = self._beat = float(song.current_song_time)
            if self.state == "preroll":
                if beat < self._begin:
                    return
                song.record_mode = True
                self.state = "recording"
            if beat >= self._end:
                for lane in self._lanes:
                    self._write(lane, self._end)
                self._finish("done")
                return
            for lane in self._lanes:
                self._write(lane, beat)
        except Exception as e:
            self._fail(_text(e))

    def status(self):
        span = self._end - self._begin
        progress = 0.0
        if self.state == "done":
            progress = 1.0
        elif self._beat is not None and span > 0 and self.state != "idle":
            progress = max(0.0, min(1.0, (self._beat - self._begin) / span))
        gaps = [b - a for a, b in zip(self._tick_times, self._tick_times[1:])]
        return {
            "state": self.state,
            "bar": self._bar(),
            "start_bar": self._start_bar,
            "bars": self._bars,
            "progress": round(progress, 3),
            "lanes": [{"param": l["name"], "track": l["track"]} for l in self._lanes],
            "points_written": self._points,
            "ticks": self._ticks,
            "mean_tick_ms": round(1000.0 * sum(gaps) / len(gaps), 1) if gaps else None,
            "error": self.error,
        }

    # -- internals -------------------------------------------------------------
    def _bar(self):
        if self._beat is None:
            return None
        return round(self._beat / curves.BEATS_PER_BAR + 1, 2)

    @staticmethod
    def _check_song(song):
        if song.is_playing:
            raise RuntimeError(u"Live is playing: stop playback first, the take starts it itself")
        if song.record_mode:
            raise RuntimeError(u"Arrangement record is on: turn it off first")
        if (getattr(song, "signature_numerator", 4), getattr(song, "signature_denominator", 4)) != (4, 4):
            raise ValueError(u"only 4/4 is supported (song is %s/%s)"
                             % (song.signature_numerator, song.signature_denominator))
        if getattr(song, "back_to_arranger", False):
            raise RuntimeError(u"Session clips are overriding the Arrangement: press "
                               u"'Back to Arrangement' first")

    @staticmethod
    def _compile(song, lanes, start_bar, bars, overwrite):
        if not lanes:
            raise ValueError(u"give at least one lane")
        out, seen = [], set()
        for n, lane in enumerate(lanes):
            where = u"lane %d" % n
            try:
                track = lom.resolve_track(song, lane.get("kind", "track"), lane.get("index", 0))
                device = lom.resolve_device(track, lane.get("device_path"))
                param = ops.find_param(device, lane["param"])
                if not getattr(param, "is_enabled", True):
                    raise ValueError(u"'%s' is disabled (macro-mapped or locked)" % _text(param.name))
                if getattr(param, "automation_state", 0) and not overwrite:
                    raise ValueError(u"'%s' already has automation; recording would replace it in "
                                     u"bars %s-%s (pass overwrite=true)"
                                     % (_text(param.name), start_bar, start_bar + bars))
                compiled = curves.compile_lane(param, lane.get("segments"), song.tempo)
            except KeyError as e:
                raise ValueError(u"%s: missing %s" % (where, _text(e)))
            except (LookupError, ValueError) as e:
                raise ValueError(u"%s: %s" % (where, _text(e)))
            segs = compiled["segments"]
            if segs[0]["b0"] < curves.bar_to_beat(start_bar) or \
                    segs[-1]["b1"] > curves.bar_to_beat(start_bar + bars):
                raise ValueError(u"%s: segments must lie within bars %s-%s"
                                 % (where, start_bar, start_bar + bars))
            key = id(param)
            if key in seen:
                raise ValueError(u"%s: '%s' is already in another lane" % (where, _text(param.name)))
            seen.add(key)
            compiled.update(param=param, last=None, name=_text(device.name) + u": " + _text(param.name),
                            track=_text(track.name))
            out.append(compiled)
        return out

    def _write(self, lane, beat):
        v = curves.value_at(lane, beat)
        if v != lane["last"]:
            lane["param"].value = v
            lane["last"] = v
            self._points += 1

    def _fail(self, msg):
        self._finish("error", msg)

    def _finish(self, state, reason=None):
        self.state = state
        if reason:
            self.error = reason
        errors = self._restore()
        if errors:
            self.error = u"; ".join(filter(None, [self.error, u"restore: " + u", ".join(errors)]))
        self._log(u"take %s%s" % (state, (u": " + self.error) if self.error else u""))

    def _restore(self):
        """Put the transport and arms back. Every step runs even if another fails."""
        song, snap, errors = self._song, self._snap, []
        if song is None or snap is None:
            return errors

        def attempt(what, fn):
            try:
                fn()
            except Exception as e:
                errors.append(u"%s (%s)" % (what, _text(e)))

        attempt(u"record off", lambda: setattr(song, "record_mode", False))
        attempt(u"stop", song.stop_playing)
        attempt(u"automation arm", lambda: setattr(song, "session_automation_record",
                                                   snap["session_automation_record"]))
        attempt(u"loop", lambda: setattr(song, "loop", snap["loop"]))
        attempt(u"playhead", lambda: setattr(song, "current_song_time", snap["current_song_time"]))
        for t in snap["armed"]:
            attempt(u"re-arm %s" % _text(t.name), lambda t=t: setattr(t, "arm", True))
        if snap["record_mode"]:
            attempt(u"record mode", lambda: setattr(song, "record_mode", True))
        self._snap = None
        return errors
