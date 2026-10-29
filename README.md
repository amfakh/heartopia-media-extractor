# Heartopia Media Extractor (心动小镇相册与演奏提取)

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Extractor for your in-game **photo album** and **instrument recordings** from **Heartopia (心动小镇)**, pulled directly from the game's local cache.

This repository ships the extraction code only. Run it against your own local game install to decrypt the photos and convert the recordings; no keys, photos, or songs are included here.

---

## How to Extract from Game Files

If you have the game installed and have taken photos or recorded songs, you can extract everything directly from your local client.

### Prerequisites

- Python 3.10+ with [`uv`](https://docs.astral.sh/uv/) installed.
- Heartopia client installed (PC / Steam / CrossOver / Wine).

### Quick Start

1. **Clone repository:**
   ```bash
   git clone https://github.com/<your-username>/heartopia-media-extractor.git
   cd heartopia-media-extractor
   ```

2. **Decrypt your album and camera photos:**
   ```bash
   uv run decrypt_heartopia.py heartopia_photos
   ```
   Outputs your uploaded album photos into `heartopia_photos/album/` and every local camera photo (largest cached size) into `heartopia_photos/photos/`, named and timestamped by capture time.

3. **Decrypt the whole image cache:**
   ```bash
   uv run decrypt_heartopia.py heartopia_photos all
   ```
   Mirrors every file under `ScreenCapture/` (thumbnails, book pages, photo frames, record covers, announcements) into `heartopia_photos/all/`.

4. **Convert instrument recordings to MIDI:**
   ```bash
   python3 dcer2midi.py midi
   ```
   Writes one `.mid` per recording into `midi/`, with other players' shared songs under `midi/remote/`.

---

## Configuration

Both scripts default to the Windows client running in a CrossOver bottle named `Steam` on macOS. For another setup, edit the path constant at the top of each script to point at your `LocalLow\xd\Heartopia` folder (on Windows: `%USERPROFILE%\AppData\LocalLow\xd\Heartopia`):

| Script | Constant |
|---|---|
| `decrypt_heartopia.py` | `HEARTOPIA_DIR` |
| `dcer2midi.py` | `RECORD_DIR` |

---

## Reproducing After Game Updates

Nothing needs to change when the game updates. `decrypt_heartopia.py` reads the AES key and IV from your installed `DotnetAssemblies/XDTBaseService.dll` on every run, so a rotated key is picked up automatically. Rerun the commands above to export new photos and recordings.

---

## Technical Background

**Photos.** The game caches every image under `ScreenCapture/` with AES-256-CBC. The game's hot-update assemblies are wrapped in a light `XDENCODE0001` obfuscation; the script undoes it and reads the key and IV from the static initializer of `Client.BaseService.Utility.File.EncryptUtil`. See `xdencode_decode` and `cipher_params` in `decrypt_heartopia.py`.

File names in `ScreenCapture/Photo`:

| Pattern | Content |
|---|---|
| `normal+<uid>+Album+<ts>.png_<w>_<h>.jpg` | Photos uploaded to the in-game album |
| `<ts>_<w>_<h>.jpg` | Local camera photos, one file per cached size |
| `normal+<uid>+TakePhoto+<ts>...` | Thumbnails, mostly other players |
| `+Book+`, `+PhotoFrame+`, `+RecordCover+`, `+MicroHomeland+` | Images used by in-game objects |

`<ts>` is a Windows FILETIME (100 ns ticks since 1601).

**Recordings.** Songs live in `record/<uid>/*.bin` and are not encrypted. The `DCER` layout comes from `AudioRecordComponent.GetUnCompressedRecordingData` in `XDTLevelAndEntity.dll`, little-endian:

```
"DCER" | int16 version | int32 count
count x { int32 seq, float32 time_s, int64 playerId, uint8 instrumentTypeId,
          bool isStart, int32 noteId, float32 distance }
float32 recordedDuration
```

`noteId` to pitch is inferred from the data, not read from the game's `Musicaudio` table:

| noteId | Mapping | Confidence |
|---|---|---|
| 10001–10022 | 22 white keys of a 3-octave keyboard, C3–C6 | Order: high (median scale fit 0.92 over 40 songs vs 0.70 for a chromatic layout). Octave: guess |
| 10201–10215 | 15 black keys of the same keyboard | Same as above |
| 11201–11206 | Instrument 6, six pads mapped to GM drums | Guess |

Each (player, instrument) pair becomes one MIDI track at a fixed 120 bpm with the original timing. Velocity is a constant 100, since recordings carry none (`distance` is the distance to the recorder).

---

## Disclaimer

All game content, photos of in-game scenes, music, and trademarks belong to **XD Inc. (心动网络)**. This repository provides code for personal interoperability, research, and fan archival under fair use. Recordings and photos from other players stay their own; don't redistribute them.
