# -*- coding: utf-8 -*-
"""Command handlers. Run on Live's main thread from update_display()."""
from __future__ import absolute_import

import time

import Live

from . import lom
from . import ops as batch

SCRIPT_VERSION = "0.3.0"


class Commands(object):
    def __init__(self, surface):
        self.surface = surface
        self.loader = EffectLoader(self)
        self.table = {
            "ping": self.ping,
            "get_session": self.get_session,
            "get_device_params": self.get_device_params,
            "get_meters": self.get_meters,
            "apply": self.apply,
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
            "script_version": SCRIPT_VERSION,
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

    def apply(self, ops):
        t0 = time.time()
        result = batch.apply(self.song, ops, self.loader)
        result["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        return result


class EffectLoader(object):
    """Loads stock audio effects through Live's browser (the `loader` ops.py expects).

    `browser.load_item` loads onto the selected track, next to the selected device, so:
    select the target track and its neighbour device, clear hotswap, set the insert
    mode, load, then restore the user's track/device selection and the insert mode.
    """

    def __init__(self, commands):
        self.commands = commands
        self._cache = None

    def _find(self, name):
        if self._cache is None:
            cache = {}
            for child in self.commands.app.browser.audio_effects.children:
                cache[unicode(child.name).lower()] = child
            self._cache = cache
        item = self._cache.get(unicode(name).lower())
        if item is not None and item.is_loadable:
            return item
        return None

    def check(self, name):
        if self._find(name) is None:
            raise LookupError(u"stock effect not found in browser: %s (have: %s)"
                              % (name, u", ".join(sorted(self._cache or {}))))

    def load(self, track, name, position=None):
        song = self.commands.song
        item = self._find(name)
        if item is None:
            raise LookupError(u"stock effect not found in browser: %s" % name)
        before = list(track.devices)
        modes = Live.Track.DeviceInsertMode
        mode = modes.default
        neighbour = None
        if before:
            if position is None or position >= len(before):
                neighbour, mode = before[-1], modes.selected_right
            elif position == 0:
                neighbour, mode = before[0], modes.selected_left
            else:
                neighbour, mode = before[position - 1], modes.selected_right
        prev_track = song.view.selected_track
        prev_device = prev_track.view.selected_device if prev_track is not None else None
        browser = self.commands.app.browser
        try:
            song.view.selected_track = track
            if neighbour is not None:
                song.view.select_device(neighbour)
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
        new = [d for d in track.devices if d not in before]
        if not new:
            raise RuntimeError(u"load_item did not add %s to %s" % (name, unicode(track.name)))
        return new[0]
