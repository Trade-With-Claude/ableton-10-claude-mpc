# -*- coding: utf-8 -*-
"""Command handlers. Run on Live's main thread from update_display()."""
from __future__ import absolute_import

import time

import Live

from . import build
from . import lom
from . import ops as batch
from . import wavetable
from .recorder import Recorder

SCRIPT_VERSION = "0.6.1"


class Commands(object):
    def __init__(self, surface):
        self.surface = surface
        self.loader = EffectLoader(self)
        self.recorder = Recorder(log=surface._log)
        self.table = {
            "ping": self.ping,
            "get_session": self.get_session,
            "get_device_params": self.get_device_params,
            "get_meters": self.get_meters,
            "apply": self.apply,
            "transport": self.transport,
            "automation_record": self.automation_record,
            "automation_status": self.automation_status,
            "automation_abort": self.automation_abort,
            "create_instrument_track": self.create_instrument_track,
            "wavetable_get": self.wavetable_get,
            "wavetable_set": self.wavetable_set,
        }

    @property
    def song(self):
        return self.surface.song()

    @property
    def app(self):
        return Live.Application.get_application()

    def __call__(self, cmd, params):
        fn = self.table.get(cmd)
        if fn is None:
            raise KeyError(u"unknown command: %s" % cmd)
        return fn(**params)

    # -- commands ----------------------------------------------------------
    def ping(self):
        app = self.app
        return {
            "live_version": "%d.%d.%d" % (app.get_major_version(), app.get_minor_version(),
                                          app.get_bugfix_version()),
            "tempo": self.song.tempo,
            "is_playing": bool(self.song.is_playing),
            "script_version": SCRIPT_VERSION,
            "recorder_state": self.recorder.state,
            # the playhead (the Arrangement insert marker when stopped), 1-based 4/4 bars
            "position_bar": round(self.song.current_song_time / 4.0 + 1, 2),
        }

    def get_session(self):
        t0 = time.time()
        result = lom.serialize_session(self.song)
        result["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        return result

    def get_device_params(self, kind, index=0, path=None, query=None):
        track = lom.resolve_track(self.song, kind, index)
        device = lom.resolve_device(track, path)
        return {
            "track": lom._text(track.name),
            "device": lom.serialize_device(device, path if isinstance(path, list) else [path]),
            "params": lom.serialize_params(device, query),
        }

    def get_meters(self):
        return lom.read_meters(self.song)

    def transport(self, play):
        """Start (from the insert marker, looping if the loop is on) or stop playback."""
        if play:
            self.song.start_playing()
        else:
            self.song.stop_playing()
        return {"is_playing": bool(self.song.is_playing)}

    def automation_record(self, lanes, start_bar, bars, preroll_bars=1, overwrite=False):
        """Start a take: play the lanes' curves while Arrangement record is on (see recorder.py)."""
        return self.recorder.start(self.song, lanes, start_bar, bars, preroll_bars, overwrite)

    def automation_status(self):
        return self.recorder.status()

    def automation_abort(self):
        return self.recorder.abort(u"aborted by request")

    def tick(self):
        """Called on every update_display(): advances a running take."""
        try:
            self.recorder.tick()
        except Exception as e:
            self.surface._log("recorder tick error: %r" % (e,))

    def create_instrument_track(self, name, instrument, index=None, clip=None):
        t0 = time.time()
        result = build.create_instrument_track(self.song, self.loader, name, instrument, index, clip)
        result["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        return result

    def _device(self, kind, index, path):
        return lom.resolve_device(lom.resolve_track(self.song, kind, index), path)

    def wavetable_get(self, kind, index=0, path=None):
        return wavetable.read(self._device(kind, index, path))

    def wavetable_set(self, kind, index=0, path=None, settings=None):
        return wavetable.apply(self.song, self._device(kind, index, path), settings)

    def apply(self, ops):
        t0 = time.time()
        result = batch.apply(self.song, ops, self.loader)
        result["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        return result


class EffectLoader(object):
    """Loads stock audio effects and instruments through Live's browser (the `loader`
    ops.py and build.py expect).

    `browser.load_item` loads onto the selected track, next to the selected device, so:
    select the target track and its neighbour device, clear hotswap, set the insert
    mode, load, then restore the user's track/device selection and the insert mode.
    Approach after ahujasid/ableton-mcp (MIT); written from scratch for Live 10.
    """

    def __init__(self, commands):
        self.commands = commands
        self._caches = {}

    def _find(self, name, category="audio_effects"):
        cache = self._caches.get(category)
        if cache is None:
            cache = {}
            for child in getattr(self.commands.app.browser, category).children:
                cache[unicode(child.name).lower()] = child
            self._caches[category] = cache
        item = cache.get(unicode(name).lower())
        if item is not None and item.is_loadable:
            return item
        return None

    def check(self, name, category="audio_effects"):
        if self._find(name, category) is None:
            what = u"instrument" if category == "instruments" else u"effect"
            raise LookupError(u"stock %s not found in browser: %s (have: %s)"
                              % (what, name, u", ".join(sorted(self._caches.get(category) or {}))))

    def check_instrument(self, name):
        self.check(name, "instruments")

    def load_instrument(self, track, name):
        return self.load(track, name, category="instruments")

    def load(self, track, name, position=None, chain=None, category="audio_effects"):
        song = self.commands.song
        item = self._find(name, category)
        if item is None:
            raise LookupError(u"stock device not found in browser: %s" % name)
        holder = chain if chain is not None else track
        before = list(holder.devices)
        before_track = list(track.devices)
        neighbour_i, mode_name = batch.insert_plan(before, position)
        modes = Live.Track.DeviceInsertMode
        mode = getattr(modes, mode_name)
        folds = lom.fold_snapshot(track)
        prev_track = song.view.selected_track
        prev_device = prev_track.view.selected_device if prev_track is not None else None
        browser = self.commands.app.browser
        try:
            song.view.selected_track = track
            if neighbour_i is not None:
                song.view.select_device(before[neighbour_i])
            browser.hotswap_target = None
            track.view.device_insert_mode = mode
            browser.load_item(item)
        finally:
            try:
                track.view.device_insert_mode = modes.default
            except Exception:
                pass
            song.view.selected_track = prev_track
            if prev_device is not None:
                try:
                    song.view.select_device(prev_device)
                except Exception:
                    pass
            lom.restore_folds(folds)
        new = [d for d in holder.devices if d not in before]
        if new:
            return new[0]
        if chain is not None:
            # Live put it somewhere else on the track: remove it rather than leave it misplaced
            stray = [i for i, d in enumerate(track.devices) if d not in before_track]
            for i in reversed(stray):
                track.delete_device(i)
            if stray:
                raise RuntimeError(u"Live loaded %s outside chain '%s' (removed it)"
                                   % (name, unicode(chain.name)))
            raise RuntimeError(u"load_item did not add %s to chain '%s'" % (name, unicode(chain.name)))
        raise RuntimeError(u"load_item did not add %s to %s" % (name, unicode(track.name)))
