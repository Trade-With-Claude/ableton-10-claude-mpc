"""Duck-typed fakes of the Live 10 Object Model, enough for lom.py."""


class Param:
    def __init__(self, name, value, lo=0.0, hi=1.0, quantized=False, items=(), fmt=None):
        self.name = name
        self.value = value
        self.min = lo
        self.max = hi
        self.is_quantized = quantized
        self.value_items = list(items)
        self.is_enabled = True
        self._fmt = fmt or (lambda v: "%.2f" % v)

    def str_for_value(self, v):
        if self.is_quantized and self.value_items:
            return self.value_items[int(v)]
        return self._fmt(v)

    def __str__(self):
        return self.str_for_value(self.value)


def db(v):
    return "%.1f dB" % v


def on_param(on=True):
    return Param("Device On", 1.0 if on else 0.0, quantized=True, items=["Off", "On"])


class Device:
    def __init__(self, name, class_name, params=(), type=2, chains=None, on=True):
        self.name = name
        self.class_name = class_name
        self.type = type
        self.parameters = [on_param(on)] + list(params)
        self.can_have_chains = chains is not None
        self.chains = chains or []


class Chain:
    def __init__(self, name, devices=(), mute=False, solo=False):
        self.name = name
        self.devices = list(devices)
        self.mute = mute
        self.solo = solo


class Mixer:
    def __init__(self, vol_db=0.0, pan=0.0, sends=()):
        self.volume = Param("Track Volume", vol_db, -70.0, 6.0, fmt=db)
        self.panning = Param("Track Panning", pan, -1.0, 1.0)
        self.sends = [Param("Send", v, -70.0, 0.0, fmt=db) for v in sends]


class Routing:
    def __init__(self, name):
        self.display_name = name


class Track:
    def __init__(self, name, devices=(), sends=(), midi=False, foldable=False, group=None,
                 output="Master", meters=(0.5, 0.4), audio_out=True, armable=True):
        self.name = name
        self.color = 0x00FF8800
        self.devices = list(devices)
        self.mixer_device = Mixer(sends=sends)
        self.mute = False
        self.solo = False
        self.has_midi_input = midi
        self.is_foldable = foldable
        self.fold_state = 0
        self.group_track = group
        self.can_be_armed = armable and not foldable
        self.arm = False
        self.output_routing_type = Routing(output)
        self.has_audio_output = audio_out
        self.output_meter_left, self.output_meter_right = meters


class Song:
    def __init__(self, tracks, returns, master, tempo=174.0):
        self.tracks = tracks
        self.return_tracks = returns
        self.master_track = master
        self.tempo = tempo


def dnb_song():
    """Group 'DRUMS' (Kick, Snare) + 'Bässe ✦ Sub', 2 returns, master with Glue + plugin."""
    drums = Track("DRUMS", foldable=True, sends=(-70.0, -70.0),
                  devices=[Device("Glue Compressor", "GlueCompressor",
                                  [Param("Threshold", -12.0, -40.0, 0.0, fmt=db),
                                   Param("Ratio", 1, quantized=True, items=["2", "4", "10"])])])
    kick = Track("Kick", group=drums, sends=(-70.0, -70.0), output="DRUMS")
    snare = Track("Snare", group=drums, sends=(-12.0, -70.0), output="DRUMS")
    rack = Device("Bass Rack", "AudioEffectGroupDevice", chains=[
        Chain("Sub", [Device("EQ Eight", "Eq8", [Param("1 Frequency A", 0.3)])]),
        Chain("Mid", [Device("Saturator", "Saturator", [Param("Drive", 6.0, 0.0, 36.0, fmt=db)]),
                      Device("Inner", "AudioEffectGroupDevice",
                             chains=[Chain("Deep", [Device("Utility", "StereoGain")])])]),
    ])
    bass = Track("Bässe ✦ Sub", midi=True, sends=(-70.0, -70.0),
                 devices=[Device("Serum", "AuPluginDevice", [Param("Macro 1", 0.25)], type=1), rack])
    ret_a = Track("A-Reverb", sends=(-70.0, -70.0), armable=False,
                  devices=[Device("Reverb", "Reverb")])
    ret_b = Track("B-Delay", sends=(-70.0, -70.0), armable=False)
    master = Track("Master", armable=False, meters=(0.9, 0.95),
                   devices=[Device("Limiter", "Limiter", [Param("Ceiling", -0.3, -24.0, 0.0, fmt=db)])])
    midi_fx = Track("MIDI only", midi=True, audio_out=False)
    return Song([drums, kick, snare, bass, midi_fx], [ret_a, ret_b], master)
