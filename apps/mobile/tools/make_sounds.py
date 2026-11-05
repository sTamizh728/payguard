"""
Generate PayGuard's sound effects as small WAV files (no third-party audio,
no copyright). Run from apps/mobile:  python tools/make_sounds.py

Each sound has a different shape so it can be recognised without looking:
  payment_sent    two notes going UP        money left your wallet
  money_received  three bright notes UP     money came in / refund done
  request_sent    one soft short note       a request is waiting
  warning         two low notes going DOWN  scam warning / something failed
  confirm_needed  two gentle taps           please confirm
  listening       quick rising blip         microphone on
  stopped         quick falling blip        microphone off
  unlocked        soft major chord          app unlocked
"""
import math
import struct
import wave
from pathlib import Path

RATE = 44100
OUT = Path(__file__).resolve().parents[1] / "android/app/src/main/res/raw"


def note(freq, length, volume=0.5, decay=6.0, attack=0.008, end_freq=None):
    """A soft bell-like tone: sine + gentle overtones, quick attack, smooth fade."""
    samples = []
    count = int(RATE * length)
    phase = 0.0
    for i in range(count):
        t = i / RATE
        f = freq if end_freq is None else freq + (end_freq - freq) * (i / count)
        phase += 2 * math.pi * f / RATE
        value = (
            math.sin(phase)
            + 0.35 * math.sin(2 * phase)
            + 0.12 * math.sin(3 * phase)
        ) / 1.47
        envelope = min(1.0, t / attack) * math.exp(-decay * t)
        # fade the last 10 ms to avoid a click
        tail = min(1.0, (count - i) / (RATE * 0.01))
        samples.append(value * envelope * tail * volume)
    return samples


def silence(length):
    return [0.0] * int(RATE * length)


def mix(*parts_with_offsets):
    """Overlap notes: each item is (start_seconds, samples)."""
    end = max(int(start * RATE) + len(s) for start, s in parts_with_offsets)
    out = [0.0] * end
    for start, s in parts_with_offsets:
        offset = int(start * RATE)
        for i, v in enumerate(s):
            out[offset + i] += v
    peak = max(1e-9, max(abs(v) for v in out))
    if peak > 0.9:
        out = [v * 0.9 / peak for v in out]
    return out


def save(name, samples):
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / f"pg_{name}.wav"), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(b"".join(
            struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767)) for v in samples
        ))


E5, A5, C6, E6, G6 = 659.25, 880.0, 1046.5, 1318.5, 1568.0
A3, E3, C5, G5, E4 = 220.0, 164.8, 523.25, 783.99, 329.6

SOUNDS = {
    "payment_sent": mix((0.0, note(E5, 0.35)), (0.12, note(A5, 0.5))),
    "money_received": mix(
        (0.0, note(C6, 0.3, 0.45)), (0.09, note(E6, 0.3, 0.45)), (0.18, note(G6, 0.55, 0.45))
    ),
    "request_sent": note(G5, 0.28, 0.45, decay=10),
    "warning": mix(
        (0.0, note(A3, 0.35, 0.6, decay=4)), (0.2, note(E3, 0.5, 0.6, decay=4))
    ),
    "confirm_needed": mix((0.0, note(C5, 0.16, 0.45, decay=14)), (0.17, note(C5, 0.2, 0.45, decay=12))),
    "listening": note(600, 0.14, 0.4, decay=8, end_freq=1000),
    "stopped": note(1000, 0.14, 0.4, decay=8, end_freq=600),
    "unlocked": mix((0.0, note(C5, 0.6, 0.3, decay=4)), (0.0, note(E4 * 2, 0.6, 0.25, decay=4)), (0.0, note(G5, 0.6, 0.25, decay=4))),
}

if __name__ == "__main__":
    for name, samples in SOUNDS.items():
        save(name, samples)
        print(f"pg_{name}.wav  {len(samples) / RATE:.2f}s")
