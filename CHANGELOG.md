# Changelog

All notable changes to Oído. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10-25

First public release.

### File quality
- Spectrogram with linear and logarithmic scales, time zoom, and frequency / time / level readout under the cursor.
- Frame-by-frame frequency ceiling that tells a codec "wall" apart from a recording's natural roll-off.
- Detection of upscaled files, fake lossless, fake hi-res, mono dressed as stereo and the YouTube (Opus) signature.

### Mix and master
- Integrated loudness and loudness curve over time, True Peak, PLR, LRA and comparison with Spotify's normalization.
- Real clipping detection on lossless files.
- Octave-band tonal balance.
- Stereo: correlation, mono bass, width per band and a live vectorscope.

### Listen and compare
- Player with Mono, Side, Only >16 kHz and Only <150 Hz modes.
- Loudness-matched A/B comparison and saved reference tracks.

### Workflow
- Sort by worst quality, CSV report and an "Analyze with Oído" Explorer context-menu entry.
- Single instance: files opened from Morph or Explorer join the window that's already open.
- Interface in English, Spanish and Russian.

### Distribution
- Windows installer that needs no admin rights, portable ZIP, FFmpeg bundled.
