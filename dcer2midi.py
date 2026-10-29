"""Convert Heartopia instrument recordings (record/**/*.bin, magic "DCER") to MIDI.

File layout, from AudioRecordComponent.GetUnCompressedRecordingData (XDTLevelAndEntity.dll):
    "DCER"  int16 version  int32 count
    count x {int32 seq, float32 time_s, int64 playerId, uint8 instrumentTypeId,
             bool isStart, int32 noteId, float32 distance}
    float32 recordedDuration

noteId -> pitch is inferred, not read from the game's Musicaudio table:
    10001-10022  the 22 white keys of a 3-octave keyboard, C3..C6
    10201-10215  the 15 black keys of the same keyboard
    11201-11206  instrument 6, six percussion pads, mapped to GM drums (guess)

Usage: python3 dcer2midi.py <out_dir>
"""

import struct
import sys
from pathlib import Path

RECORD_DIR = Path(
    "~/Library/Application Support/CrossOver/Bottles/Steam/drive_c/users/crossover"
    "/AppData/LocalLow/xd/Heartopia/record"
).expanduser()
TICKS_PER_BEAT = 480
TICKS_PER_SECOND = TICKS_PER_BEAT * 2  # tempo fixed at 120 bpm
DRUM_CHANNEL = 9
DRUM_NOTES = {11201: 36, 11202: 38, 11203: 42, 11204: 46, 11205: 45, 11206: 49}


def pitch(note_id: int) -> int | None:
    """Map a Heartopia noteId to a MIDI note number, or None if unknown."""
    if 10001 <= note_id <= 10022:
        k = note_id - 10001
        return 48 + 12 * (k // 7) + (0, 2, 4, 5, 7, 9, 11)[k % 7]
    if 10201 <= note_id <= 10215:
        k = note_id - 10201
        return 48 + 12 * (k // 5) + (1, 3, 6, 8, 10)[k % 5]
    return DRUM_NOTES.get(note_id)


def read_dcer(path: Path) -> tuple[list[tuple[float, int, int, bool, int]], float]:
    """Return (events, duration) where each event is (time, playerId, instrument, isStart, noteId)."""
    data = path.read_bytes()
    if data[:4] != b"DCER":
        raise ValueError(f"{path.name}: not a DCER file")
    (count,) = struct.unpack_from("<i", data, 6)
    events = []
    for i in range(count):
        _, t, player, inst, start, note, _ = struct.unpack_from("<ifqB?if", data, 10 + 26 * i)
        events.append((t, player, inst, start, note))
    (duration,) = struct.unpack_from("<f", data, 10 + 26 * count)
    return events, duration


def vlq(n: int) -> bytes:
    """Encode n as a MIDI variable-length quantity."""
    out = [n & 0x7F]
    while n := n >> 7:
        out.append(0x80 | (n & 0x7F))
    return bytes(reversed(out))


def track_chunk(name: str, timed: list[tuple[int, bytes]], end_tick: int) -> bytes:
    """Build one MTrk chunk from (tick, midi message) pairs."""
    body = bytearray(b"\x00\xff\x03" + vlq(len(name.encode())) + name.encode())
    last = 0
    for tick, msg in sorted(timed, key=lambda e: (e[0], e[1][0] & 0xF0 == 0x90)):
        body += vlq(tick - last) + msg
        last = tick
    body += vlq(max(end_tick - last, 0)) + b"\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(body)) + body


def to_midi(events: list[tuple[float, int, int, bool, int]], duration: float) -> bytes:
    """Render DCER events as a type-1 MIDI file, one track per (player, instrument)."""
    groups: dict[tuple[int, int], list[tuple[int, bytes]]] = {}
    channels: dict[tuple[int, int], int] = {}
    for t, player, inst, start, note in events:
        p = pitch(note)
        if p is None:
            continue
        key = (player, inst)
        if note in DRUM_NOTES:
            chan = DRUM_CHANNEL
        else:
            chan = channels.setdefault(key, len(channels) % 9)
        status = (0x90 if start else 0x80) | chan
        groups.setdefault(key, []).append((round(t * TICKS_PER_SECOND), bytes([status, p, 100 if start else 0])))

    end_tick = round(max([duration] + [e[0] for e in events]) * TICKS_PER_SECOND)
    tempo = b"\x00\xff\x51\x03" + (500_000).to_bytes(3, "big") + b"\x00\xff\x2f\x00"
    chunks = [b"MTrk" + struct.pack(">I", len(tempo)) + tempo]
    for (player, inst), timed in groups.items():
        chunks.append(track_chunk(f"player {player} instrument {inst}", timed, end_tick))
    return b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), TICKS_PER_BEAT) + b"".join(chunks)


def main(out: Path) -> None:
    """Convert every recording under RECORD_DIR into out/, mirroring subfolders."""
    files = sorted(RECORD_DIR.rglob("*.bin"))
    for src in files:
        dst = out / src.relative_to(RECORD_DIR).with_suffix(".mid")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(to_midi(*read_dcer(src)))
    print(f"{len(files)} recordings -> {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
