"""
Oído analysis engine (no GUI).
Everything Oído measures, and how it interprets it, lives here; oido.py only displays it.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

from i18n import tr

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FFMPEG, FFPROBE = shutil.which("ffmpeg"), shutil.which("ffprobe")

AUDIO_EXT = {"mp3", "m4a", "aac", "flac", "wav", "ogg", "opus", "wma", "aif", "aiff", "alac", "ape",
             "wv", "mp4", "mkv", "webm", "mov"}
LOSSLESS = {"flac", "alac", "wavpack", "ape", "tta"} | {f"pcm_{x}" for x in
                                                        ("s16le", "s24le", "s32le", "f32le", "s16be", "s24be", "f64le", "u8")}
LOSSY = {"mp3", "aac", "opus", "vorbis", "wmav2", "wmav1", "ac3", "eac3", "mp2"}

# LAME lowpass table (CBR bitrate → cutoff in Hz), from optimum_bandwidth() in lame.c.
LAME_LOWPASS = [(96, 15100), (112, 15600), (128, 17000), (160, 17500), (192, 18600),
                (224, 19400), (256, 19700), (320, 20500)]
OPUS_TOP_BAND = (15600, 20000)  # last Opus/CELT energy band (eband5ms: 78–100 × 200 Hz)
SPOTIFY_LUFS = -14.0            # Spotify "Normal" mode (support.spotify.com, ITU-R BS.1770)

BANDS = [  # name, from, to, what it means musically
    ("Sub", 20, 60, "The hit you feel in your chest: sub-bass, electronic kicks, 808s. Small speakers barely reproduce it."),
    ("Bass", 60, 250, "The body: bass guitar, the kick's fundamental, low piano. It carries weight and warmth."),
    ("Low mids", 250, 800, "The 'wood' of guitars and voices. Too much and the mix turns muddy or boxy."),
    ("Mids", 800, 2500, "Where the message lives: vocals, guitars, snare. The ear is most sensitive here."),
    ("Presence", 2500, 6000, "Definition and attack: consonants, pick noise, the kick's click. Too much and it gets tiring."),
    ("Air", 6000, 20000, "Sparkle and space: cymbals, breaths, reverb tails. The first thing a bad MP3 throws away."),
]

NFFT = 4096          # linear spectrogram (fine resolution up high → quality checks)
NFFT_LOG = 16384     # log spectrogram (fine resolution down low → reading music)
COLS = 1200          # time columns
ROWS_LIN = 1024
ROWS_LOG = 900
F_MIN_LOG = 20.0
DB_MIN = -120.0
GOOD, OK, WARN, BAD, INFO = "good", "ok", "warn", "bad", "info"
LEVEL_RANK = {BAD: 0, WARN: 1, INFO: 2, OK: 3, GOOD: 4}


# ──────────────────────────────────────────────────────────────────────────────
#  FFmpeg input / output
# ──────────────────────────────────────────────────────────────────────────────
def probe(path: Path) -> dict:
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "stream=codec_name,sample_rate,channels,bit_rate,bits_per_raw_sample,bits_per_sample"
                        ":format=bit_rate,duration", "-of", "json", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    j = json.loads(r.stdout or "{}")
    if not j.get("streams"):
        raise RuntimeError(tr("No audio stream found in this file"))
    s, f = j["streams"][0], j.get("format", {})

    def num(*vals):
        for v in vals:
            try:
                if v not in (None, "", "N/A") and float(v) > 0:
                    return float(v)
            except (TypeError, ValueError):
                pass
        return 0.0
    return {"codec": s.get("codec_name", "?"), "sr": int(num(s.get("sample_rate"))) or 44100,
            "channels": int(num(s.get("channels"))) or 2,
            "bitrate": num(s.get("bit_rate"), f.get("bit_rate")) / 1000,
            "bits": int(num(s.get("bits_per_raw_sample"), s.get("bits_per_sample"))),
            "duration": num(f.get("duration"))}


def decode(path: Path, sr: int, ch: int, af: str | None = None) -> np.ndarray:
    cmd = [FFMPEG, "-v", "error", "-nostdin", "-i", str(path), "-map", "0:a:0"]
    if af:
        cmd += ["-af", af]
    cmd += ["-f", "f32le", "-acodec", "pcm_f32le", "-ac", str(ch), "-ar", str(sr), "-"]
    r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip()[-200:] or tr("FFmpeg could not decode the file"))
    return np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, ch)


_NUM = r"(-?[\d.]+|-?inf|nan)"


def loudness(path: Path) -> dict:
    """Integrated loudness, LRA and true peak, plus the loudness curve over time (every 100 ms), via ebur128."""
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-nostdin", "-v", "verbose", "-i", str(path),
                        "-map", "0:a:0", "-af", "ebur128=peak=true:framelog=verbose", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    err = r.stderr

    def f(v):
        try:
            x = float(v)
            return x if np.isfinite(x) else None
        except ValueError:
            return None
    t, m, s = [], [], []
    for mm in re.finditer(rf"t:\s*([\d.]+)\s+TARGET.*?M:\s*{_NUM}\s+S:\s*{_NUM}", err):
        t.append(float(mm.group(1)))
        m.append(f(mm.group(2)) or -120.0)
        s.append(f(mm.group(3)) or -120.0)
    out = {"I": None, "LRA": None, "TP": None,
           "curve_t": np.array(t, np.float32), "curve_m": np.array(m, np.float32), "curve_s": np.array(s, np.float32)}
    if (g := re.search(rf"Integrated loudness:\s*\n\s*I:\s*{_NUM}", err)):
        out["I"] = f(g.group(1))
    if (g := re.search(rf"Loudness range:\s*\n\s*LRA:\s*{_NUM}", err)):
        out["LRA"] = f(g.group(1))
    if (g := re.search(rf"True peak:\s*\n\s*Peak:\s*{_NUM}", err)):
        out["TP"] = f(g.group(1))
    if out["I"] is not None and out["I"] <= -69:
        out["I"] = None  # silence
    return out


# ──────────────────────────────────────────────────────────────────────────────
#  Analysis
# ──────────────────────────────────────────────────────────────────────────────
def to_level(db: np.ndarray) -> np.ndarray:
    return (np.clip((db - DB_MIN) / -DB_MIN, 0, 1) * 255).astype(np.uint8)


def smooth_rows(a: np.ndarray, k: int) -> np.ndarray:
    p = np.pad(a, ((0, 0), (k // 2, k - 1 - k // 2)), mode="edge")
    c = np.cumsum(p, axis=1, dtype=np.float64)
    c = np.concatenate([np.zeros((a.shape[0], 1)), c], axis=1)
    return ((c[:, k:] - c[:, :-k]) / k).astype(np.float32)


def bandwidth(freqs, mag_db, active, sr) -> dict:
    """
    Frequency ceiling, frame by frame. An encoder always cuts at the same place (ceilings stack up at one exact
    frequency and the drop is vertical); a natural recording varies and rolls off gradually.
    """
    nyq = sr / 2
    ref_sel = (freqs >= 500) & (freqs < 4000)
    fr_ref = mag_db[:, ref_sel].mean(axis=1)
    sm = smooth_rows(mag_db, 5)
    occ = (sm > fr_ref[:, None] - 65) & (sm > -110)
    rev = occ[:, ::-1]
    top = len(freqs) - 1 - rev.argmax(axis=1)
    top[~rev.any(axis=1)] = 0
    ceil = freqs[top]
    valid = active & (fr_ref > -75)
    if valid.sum() < 10:
        valid = active if active.sum() >= 10 else np.ones_like(active)
    c = ceil[valid]
    out = {"nyq": nyq, "median": float(np.median(c)), "p95": float(np.percentile(c, 95)),
           "wall": None, "sharp": 0.0, "eff": float(np.median(c)), "sporadic": None, "low_share": 0.0,
           "low_ceiling": None, "ceil_t": ceil.astype(np.float32), "valid": valid}
    # do the ceilings stack up at one exact frequency? (200 Hz histogram, Nyquist edge excluded)
    cand = c[(c >= 6000) & (c < nyq - 700)]
    if len(cand):
        edges = np.arange(6000, nyq, 200)
        h, _ = np.histogram(cand, bins=edges)
        k = int(h.argmax())
        frac = h[k] / len(c)
        near = cand[(cand >= edges[k] - 200) & (cand < edges[k + 1] + 200)]
        wall = float(np.median(near))
        sel = valid.copy()
        sel[valid] = np.abs(c - wall) <= 250
        if frac >= 0.2 and sel.sum() >= 5:
            p = 10 * np.log10(np.mean(10 ** (mag_db[sel] / 10), axis=0) + 1e-20)
            below = p[(freqs >= wall - 600) & (freqs < wall - 150)].mean()
            above = p[(freqs >= wall + 150) & (freqs < wall + 700)].mean()
            sharp = float(below - above)
            if sharp >= 20:
                out.update(wall=wall, sharp=sharp, eff=wall)
                hi = c > wall + 800
                if hi.mean() >= 0.03:
                    out["sporadic"] = float(np.median(c[hi]))
                lo = c < wall - 2500
                out["low_share"] = float(lo.mean())
                if lo.mean() >= 0.05:
                    out["low_ceiling"] = float(np.median(c[lo]))
    return out


def analyze(path: Path) -> dict:
    info = probe(path)
    sr = info["sr"]
    ch = 2 if info["channels"] >= 2 else 1
    x = decode(path, sr, ch)
    if len(x) < NFFT_LOG:
        x = np.pad(x, ((0, NFFT_LOG - len(x)), (0, 0)))
    n = len(x)
    L = x[:, 0]
    R = x[:, 1] if ch == 2 else x[:, 0]
    nyq = sr / 2

    # ── linear STFT: quality, frequency ceiling, bands ──
    win = np.hanning(NFFT).astype(np.float32)
    ref = win.sum() / 2
    starts = np.linspace(0, n - NFFT, COLS).astype(np.int64)
    idx = starts[:, None] + np.arange(NFFT)
    XL = np.fft.rfft(L[idx] * win, axis=1)
    XR = np.fft.rfft(R[idx] * win, axis=1) if ch == 2 else XL
    M = (XL + XR) / 2
    S = (XL - XR) / 2
    freqs = np.fft.rfftfreq(NFFT, 1 / sr)
    mag_db = (20 * np.log10(np.abs(M) / ref + 1e-12)).astype(np.float32)
    lv = to_level(mag_db).T[::-1]                         # rows: highs on top
    level_lin = lv[:ROWS_LIN * 2].reshape(ROWS_LIN, 2, COLS).max(axis=1) if lv.shape[0] >= ROWS_LIN * 2 else lv

    frame_rms = np.sqrt(np.mean(L[idx] ** 2, axis=1)) + 1e-12
    active = 20 * np.log10(frame_rms) > -60
    if active.sum() < 10:
        active[:] = True
    P = np.mean(np.abs(M[active]) ** 2, axis=0) / ref ** 2
    avg_db = 10 * np.log10(P + 1e-20)
    bw = bandwidth(freqs, mag_db, active, sr)

    # fake hi-res: a 44.1/48 kHz file 'stretched' upwards has a cliff right above 20–24 kHz
    hires_fake = None
    if sr > 48000:
        def band(a, b):
            s_ = (freqs >= a) & (freqs < b)
            return float(avg_db[s_].mean()) if s_.any() else None
        below, above = band(19000, 21000), band(26000, 30000)
        if below is not None and above is not None and below - above > 50:
            edge = np.where((freqs > 19000) & (avg_db > (below + above) / 2))[0]
            hires_fake = float(freqs[edge.max()]) if len(edge) else 22050.0
            bw["eff"] = min(bw["eff"], hires_fake)

    # ── long STFT for the log view (low-end resolution) ──
    mono = ((L + R) / 2).astype(np.float32)
    win16 = np.hanning(NFFT_LOG).astype(np.float32)
    ref16 = win16.sum() / 2
    rows_f = np.exp(np.linspace(np.log(nyq), np.log(F_MIN_LOG), ROWS_LOG))
    binf = rows_f / (sr / NFFT_LOG)
    b0 = np.clip(np.floor(binf).astype(np.int64), 0, NFFT_LOG // 2)
    b1 = np.clip(b0 + 1, 0, NFFT_LOG // 2)
    w1 = (binf - b0).astype(np.float32)
    starts16 = np.linspace(0, n - NFFT_LOG, COLS).astype(np.int64)
    level_log = np.empty((ROWS_LOG, COLS), np.uint8)
    for a in range(0, COLS, 100):
        st = starts16[a:a + 100]
        X = np.abs(np.fft.rfft(mono[st[:, None] + np.arange(NFFT_LOG)] * win16, axis=1)) / ref16
        db = 20 * np.log10(X + 1e-12)
        v = db[:, b0] * (1 - w1) + db[:, b1] * w1
        level_log[:, a:a + len(st)] = to_level(v).T

    # ── stereo ──
    l64, r64 = L.astype(np.float64), R.astype(np.float64)
    if ch == 2:
        den = np.sqrt(np.sum(l64 ** 2) * np.sum(r64 ** 2)) + 1e-20
        corr = float(np.sum(l64 * r64) / den)
        side_rms = float(np.sqrt(np.mean(((l64 - r64) / 2) ** 2)))
        mid_rms = float(np.sqrt(np.mean(((l64 + r64) / 2) ** 2))) + 1e-20
        width_db = 20 * np.log10(side_rms / mid_rms + 1e-12)
        dual_mono = side_rms / mid_rms < 1e-3
    else:
        corr, width_db, dual_mono = 1.0, -120.0, False
    rng = np.random.default_rng(0)
    loud = np.where(np.abs(mono) > 1e-3)[0]
    pick = rng.choice(loud, size=min(20000, len(loud)), replace=False) if len(loud) else np.array([], int)
    scope = np.stack([L[pick], R[pick]], axis=1).astype(np.float32)

    # ── bands: energy per octave, correlation and width per band ──
    bands = []
    for name, lo, hi, desc in BANDS:
        hi = min(hi, nyq)
        sel = (freqs >= lo) & (freqs < hi)
        if not sel.any() or hi <= lo:
            continue
        Ma, La, Ra, Sa = M[active][:, sel], XL[active][:, sel], XR[active][:, sel], S[active][:, sel]
        e = float(np.sum(np.abs(Ma) ** 2))
        cross = np.sum((La * np.conj(Ra)).real)
        el, er = np.sum(np.abs(La) ** 2), np.sum(np.abs(Ra) ** 2)
        bands.append({"name": name, "lo": lo, "hi": hi, "desc": desc,
                      "db": 10 * np.log10(e / np.log2(hi / lo) + 1e-20),
                      "corr": float(cross / (np.sqrt(el * er) + 1e-20)) if ch == 2 else 1.0,
                      "width": 10 * np.log10(float(np.sum(np.abs(Sa) ** 2)) / (e + 1e-20) + 1e-12)})
    if bands:
        avg = float(np.mean([b["db"] for b in bands]))
        for b in bands:
            b["rel"] = b["db"] - avg

    # ── peaks / clipping ──
    peak = float(np.max(np.abs(x)))
    flat_runs, overs = 0, 0
    if info["codec"] in LOSSLESS:
        # real clipping = the waveform goes FLAT at the ceiling: 3+ identical, loud samples
        for c_ in range(ch):
            a_ = x[:, c_]
            eq = (a_[1:] == a_[:-1]) & (np.abs(a_[1:]) > 0.5)
            if eq.any():
                e = np.diff(np.concatenate([[0], eq.view(np.int8), [0]]))
                st, en = np.where(e == 1)[0], np.where(e == -1)[0]
                flat_runs += int(np.sum((en - st) >= 2))
    else:
        overs = int(np.sum(np.abs(x) > 1.0))   # codec overshoots when decoding

    lu = loudness(path)
    return {"path": str(path), "info": info, "level_lin": np.ascontiguousarray(level_lin),
            "level_log": level_log, "bw": bw, "hires_fake": hires_fake, "nyq": nyq,
            "duration": n / sr, "corr": corr, "width_db": width_db, "dual_mono": dual_mono, "mono": ch == 1,
            "bands": bands, "peak_db": 20 * np.log10(peak + 1e-12), "flat_runs": flat_runs, "overs": overs,
            "scope": scope, **lu}


# ──────────────────────────────────────────────────────────────────────────────
#  Plain-language interpretation
# ──────────────────────────────────────────────────────────────────────────────
def khz(f):
    return f"{f / 1000:.1f} kHz"


def lame_equiv(freq: float) -> int:
    return min(LAME_LOWPASS, key=lambda p: abs(p[1] - freq))[0]


def youtube_profile(r: dict) -> bool:
    """Opus signature (YouTube's audio): 48 kHz and ceilings stacked at the edge of its top band (15.6 kHz)."""
    bw = r["bw"]
    if r["info"]["sr"] != 48000 or not bw["wall"]:
        return False
    lo, hi = OPUS_TOP_BAND
    near = lambda f: lo - 300 <= f <= lo + 800  # noqa: E731  (after re-encoding to MP3 the edge measures ~0.5 kHz higher)
    if near(bw["wall"]):
        return True
    return bw["low_ceiling"] is not None and near(bw["low_ceiling"]) and bw["wall"] >= hi - 800


def quality_report(r: dict) -> dict:
    info, bw = r["info"], r["bw"]
    f, nyq = bw["eff"], bw["nyq"]
    codec, br = info["codec"], info["bitrate"]
    lossless = codec in LOSSLESS
    yt = youtube_profile(r)
    items, flags = [], []

    if bw["wall"]:
        if f >= 20200:
            grade, lvl = tr("Excellent"), GOOD
        elif f >= 19300:
            grade, lvl = tr("Very good"), GOOD
        elif f >= 18300:
            grade, lvl = tr("Good"), OK
        elif f >= 16500:
            grade, lvl = tr("Fair"), WARN
        else:
            grade, lvl = tr("Poor"), BAD
        what = tr("The music reaches <b>{f}</b> and then hits a <b>wall</b>: for most of the track the content stops "
                  "at that exact frequency, dropping {drop} dB at once. Nature doesn't do that. It's the fingerprint "
                  "of a lossy encoder (MP3, AAC, Opus).", f=khz(f), drop=f"{bw['sharp']:.0f}")
        if bw["sporadic"]:
            what += "<br><br>" + tr("Above it you'll see <b>sporadic flashes up to {f}</b> (hits, cymbals): the encoder "
                                    "only spends data up there when the highs carry a lot of energy.",
                                    f=khz(bw["sporadic"]))
        if bw["low_ceiling"] and bw["low_share"] >= 0.05:
            what += "<br><br>" + tr("For <b>{pct}% of the track</b> the ceiling drops to ~{f} (darker sections, such as "
                                    "intros or breakdowns).", pct=f"{bw['low_share'] * 100:.0f}", f=khz(bw["low_ceiling"]))
        if yt:
            if f < 17000:
                grade, lvl = tr("Medium · YouTube profile"), WARN
            what += "<br><br>" + tr("<b>Opus signature</b>, YouTube's audio format. Opus splits the spectrum into bands, "
                                    "and the top one runs from 15.6 to 20 kHz. It only fills that band when the highs "
                                    "carry enough energy; otherwise it leaves it empty. That's the straight line you see "
                                    "at ~16 kHz.")
        else:
            what += "<br><br>" + tr("For reference, LAME cuts at ~{f} at {kbps} kbps CBR. Other encoders cut elsewhere, "
                                    "so treat this as a guide, not a verdict.",
                                    f=khz(dict(LAME_LOWPASS)[lame_equiv(f)]), kbps=lame_equiv(f))
    else:
        if f >= min(nyq - 1200, 20500) or r.get("hires_fake"):
            grade, lvl = tr("Excellent"), GOOD
            what = tr("No artificial wall: the ceiling moves with the arrangement and reaches <b>{f}</b> most of the "
                      "time. This is what a lossless file, or a very high-quality lossy one, looks like.", f=khz(f))
        else:
            grade, lvl = tr("Limited by the recording"), INFO
            what = tr("Most of the time the content reaches <b>~{f}</b>, but it <b>fades out gradually</b> and the "
                      "ceiling keeps moving: there's no artificial cut. That's usually natural (older recordings, tape, "
                      "instruments with little top end). It's not the file's fault.", f=khz(f))
    items.append({"title": tr("Real bandwidth"), "value": khz(f), "level": lvl, "pill": grade, "text": what,
                  "learn": tr("The dashed line on the spectrogram marks the typical ceiling; the dotted one, how far "
                              "the sporadic flashes go. Young ears hear up to roughly 16–20 kHz.")})

    if yt and not lossless:
        flags.append((tr("Likely source: YouTube"), WARN,
                      tr("48 kHz plus the Opus signature at 15.6 kHz. Saving it as {codec} at {kbps} kbps doesn't add "
                         "quality: YouTube set the ceiling. It's the best that source can give, but it's not the same "
                         "as a purchased or lossless file.", codec=codec.upper(), kbps=f"{br:.0f}")))
    elif bw["wall"] and br >= 250 and f < 19000 and not lossless:
        flags.append((tr("Upscaled file"), BAD,
                      tr("It says {kbps} kbps, but the content matches roughly {equiv} kbps. It was converted from a "
                         "worse file: the size went up, the quality didn't.", kbps=f"{br:.0f}", equiv=lame_equiv(f))))
    if lossless and bw["wall"] and f < 20800:
        flags.append((tr("Fake lossless"), BAD,
                      tr("It's {codec} (lossless), but it has a lossy encoder's wall at {f}. It was made from an "
                         "MP3/AAC: it takes the space of lossless and sounds like the compressed original.",
                         codec=codec.upper(), f=khz(f))))
    if r.get("hires_fake"):
        flags.append((tr("Fake hi-res"), WARN,
                      tr("It runs at {sr} kHz, but there's nothing above ~{f}. It's a CD-quality file that was "
                         "upsampled.", sr=f"{info['sr'] / 1000:g}", f=khz(r["hires_fake"]))))
        if lvl == GOOD:
            grade, lvl = tr("CD quality (not hi-res)"), OK
    if r["dual_mono"]:
        flags.append((tr("Mono dressed as stereo"), INFO,
                      tr("Both channels are identical. It may be an original mono recording (very common before 1967) "
                         "or a conversion mistake.")))

    tech = (f"{codec.upper()} · {br:.0f} kbps · {info['sr'] / 1000:g} kHz"
            + (f" · {info['bits']}-bit" if info["bits"] and lossless else "")
            + " · " + (tr("mono") if r["mono"] else tr("stereo")))
    items.append({"title": tr("What the file claims"), "value": tech, "level": INFO, "pill": tr("Label"),
                  "text": tr("This is what the file <i>declares</i>. Bitrate tells you how much data it uses per second, "
                             "not how much music is inside: a 320 made from a 128 still sounds like a 128."),
                  "learn": tr("Lossy (MP3, AAC, Opus, OGG) = throws information away. Lossless (FLAC, WAV, ALAC) = "
                              "exact copy, but only if the source was lossless too.")})
    overall = BAD if any(l_ == BAD for _, l_, _ in flags) else lvl
    if overall == BAD and flags and lvl != BAD:
        grade = tr("Upscaled / fake")
    return {"grade": grade, "level": overall, "items": items, "flags": flags, "youtube": yt}


def mix_report(r: dict) -> list[dict]:
    items = []
    I, TP, LRA = r["I"], r["TP"], r["LRA"]
    lossy = r["info"]["codec"] in LOSSY
    if I is not None:
        if I > -8:
            lv, pill, t = WARN, tr("Very loud"), tr("Pushed to the limit, deep in <i>loudness war</i> territory. It hits "
                                                    "hard at first listen, but usually loses punch and nuance.")
        elif I > -11:
            lv, pill, t = INFO, tr("Loud"), tr("Typical level for pop, rock and electronic music from the 2000s onward.")
        elif I > -15:
            lv, pill, t = GOOD, tr("Moderate"), tr("Balanced level, close to what streaming platforms play at.")
        else:
            lv, pill, t = GOOD, tr("Quiet / dynamic"), tr("A master with room to breathe: typical of jazz, classical, "
                                                          "audiophile releases or respectful remasters.")
        diff = I - SPOTIFY_LUFS
        if diff > 0.5:
            sp = tr("Spotify (Normal mode) plays everything at {ref} LUFS, so this track gets <b>turned down {d} dB</b>: "
                    "the extra loudness buys nothing there.", ref=f"{SPOTIFY_LUFS:.0f}", d=f"{diff:.1f}")
        elif diff > -0.5:
            sp = tr("Spotify (Normal mode) plays everything at {ref} LUFS, so this track stays practically the same.",
                    ref=f"{SPOTIFY_LUFS:.0f}")
        else:
            sp = tr("Spotify (Normal mode) plays everything at {ref} LUFS, so this track is {d} dB short of that level "
                    "(Spotify may turn it up, within limits).", ref=f"{SPOTIFY_LUFS:.0f}", d=f"{-diff:.1f}")
        items.append({"title": tr("Loudness (perceived volume)"), "value": f"{I:.1f} LUFS", "level": lv, "pill": pill,
                      "text": t + " " + sp,
                      "learn": tr("LUFS measures volume the way the ear perceives it (ITU-R BS.1770). Closer to 0 = "
                                  "louder. The curve under the spectrogram shows it across the track.")})
    if TP is not None:
        if TP > 0:
            lv, pill, t = BAD, tr("Above 0 dB"), tr("True peaks go over digital full scale.")
        elif TP > -1:
            lv, pill, t = WARN, tr("On the edge"), tr("Peaks sit right at the ceiling, with no headroom for MP3/AAC "
                                                      "conversion.")
        else:
            lv, pill, t = GOOD, tr("Headroom"), tr("There's a safety margin on the peaks.")
        if lossy and TP > -1:
            t += " " + tr("<b>Note:</b> in a lossy file this is almost always the codec: the original master was limited "
                          "near 0 dB, and compression makes the waveform overshoot the ceiling.")
        items.append({"title": tr("True peak"), "value": f"{TP:.1f} dBTP", "level": lv, "pill": pill,
                      "text": t + " " + tr("Spotify asks artists to keep true peak at -1 dBTP or lower."),
                      "learn": tr("True peak estimates the peak between samples (what actually leaves the converter), "
                                  "which can be higher than the sample peak an editor shows.")})
    if I is not None and TP is not None:
        plr = TP - I
        if plr < 8:
            lv, pill, t = WARN, tr("Heavily compressed"), tr("Barely any difference between the hits and the average: "
                                                             "the limiter flattened the transients.")
        elif plr < 12:
            lv, pill, t = INFO, tr("Modern compression"), tr("Compressed like most current commercial music. Energetic, "
                                                             "with some punch left.")
        elif plr < 16:
            lv, pill, t = GOOD, tr("Good dynamics"), tr("The hits stand well above the average: the drums breathe and "
                                                        "punch.")
        else:
            lv, pill, t = GOOD, tr("Very dynamic"), tr("Strong contrast between peaks and average, like an acoustic "
                                                       "recording or a carefully made master.")
        t += " <i>" + tr("(Rule-of-thumb ranges, not a standard.)") + "</i>"
        if lossy:
            t += " " + tr("In lossy files the peak is slightly inflated by the codec, so the master's real PLR is a "
                          "little lower.")
        items.append({"title": tr("Punch (PLR)"), "value": f"{plr:.1f} dB", "level": lv, "pill": pill, "text": t,
                      "learn": tr("PLR = true peak minus loudness: how much punch the mastering left. Fewer dB = more "
                                  "squashed.")})
    if LRA is not None:
        if LRA < 4:
            pill, t = tr("Very even"), tr("The level barely changes between sections: verse and chorus hit equally hard.")
        elif LRA <= 10:
            pill, t = tr("Normal"), tr("Sections differ without going to extremes, like most popular music.")
        else:
            pill, t = tr("Wide swings"), tr("It moves from soft passages to very loud ones: orchestral music, film "
                                            "scores, songs that build.")
        items.append({"title": tr("Loudness range (LRA)"), "value": f"{LRA:.1f} LU", "level": INFO, "pill": pill,
                      "text": t + " <i>" + tr("(Rule of thumb.)") + "</i>",
                      "learn": tr("LRA measures how much the level changes across the track (macro-dynamics). PLR "
                                  "measures micro-dynamics (hit by hit). On the loudness curve, it's how much the line "
                                  "rises and falls.")})
    if r["info"]["codec"] in LOSSLESS:
        n = r["flat_runs"]
        items.append({"title": tr("Clipping"), "value": tr("{n} runs", n=n) if n else tr("No clipping"),
                      "level": WARN if n > 50 else INFO if n else GOOD,
                      "pill": tr("Clipped peaks") if n else tr("Clean"),
                      "text": (tr("There are stretches where the waveform goes <b>flat</b> at the ceiling: clipped "
                                  "peaks. Common in very loud masters; overdone, it sounds like grit on the hits.") if n
                               else tr("No flat stretches at the ceiling: peaks are intact or handled by a limiter.")),
                      "learn": tr("Counts runs of 3+ identical, loud consecutive samples. Some engineers clip on "
                                  "purpose (soft clipping) to gain loudness.")})
    else:
        o = r["overs"]
        text = tr("In a lossy file the codec rebuilds the waveform and erases the original clipping's fingerprint, so "
                  "it can't be measured reliably.") + " "
        text += (tr("What you can see: {n} samples that exceed full scale when decoded. That's the codec overshooting "
                    "a very loud master; the player clips them.", n=f"{o:,}") if o
                 else tr("There are no decoding overs either."))
        items.append({"title": tr("Clipping"), "value": tr("Not measurable"), "level": INFO,
                      "pill": tr("{n} overs", n=f"{o:,}") if o else tr("No overs"), "text": text,
                      "learn": tr("To study a master's clipping you need the lossless file (FLAC/WAV).")})
    return items


def stereo_report(r: dict) -> list[dict]:
    items = []
    if r["mono"]:
        return [{"title": tr("Stereo image"), "value": tr("Mono"), "level": INFO, "pill": tr("1 channel"),
                 "text": tr("The file has a single channel."), "learn": ""}]
    c = r["corr"]
    if r["dual_mono"]:
        lv, pill, t = INFO, tr("Mono"), tr("Both channels are identical: everything sits in the center. The vectorscope "
                                           "shows a vertical line.")
    elif c > 0.95:
        lv, pill, t = INFO, tr("Nearly mono"), tr("Very little difference between left and right: a narrow, centered "
                                                  "image.")
    elif c >= 0.3:
        lv, pill, t = GOOD, tr("Healthy stereo"), tr("Good channel separation with a solid center.")
    elif c >= 0:
        lv, pill, t = WARN, tr("Very wide"), tr("A very wide image. Great on headphones, but check it in Mono (phones, "
                                                "Bluetooth speakers).")
    else:
        lv, pill, t = BAD, tr("Phase problems"), tr("The channels cancel each other out: in mono, instruments or the "
                                                    "bass disappear.")
    items.append({"title": tr("Stereo image"), "value": tr("correlation {c}", c=f"{c:+.2f}"), "level": lv, "pill": pill,
                  "text": t + " " + tr("What sits on the sides (Side) is {db} dB relative to the center (Mid).",
                                       db=f"{r['width_db']:.1f}"),
                  "learn": tr("Correlation +1 = mono, 0 = independent channels, negative = out of phase. Try the "
                              "player's 'Side' button to hear only what's on the sides.")})
    low = [b for b in r["bands"] if b["name"] in ("Sub", "Bass")]
    if low and not r["dual_mono"]:
        lc = min(b["corr"] for b in low)
        ok_ = lc >= 0.9
        items.append({"title": tr("Low end in mono"), "value": tr("correlation {c}", c=f"{lc:+.2f}"),
                      "level": GOOD if ok_ else WARN, "pill": tr("Centered") if ok_ else tr("Spread"),
                      "text": (tr("The low end sits in the center, as is standard in mastering: solid on any system.")
                               if ok_ else tr("Some low end is spread to the sides. It can be intentional (stereo "
                                              "synths, ambience), but in mono or with a single subwoofer it may lose "
                                              "power.")),
                      "learn": tr("Low frequencies are hard to localize, so they're usually mixed in mono. On vinyl it "
                                  "was mandatory: out-of-phase bass makes the stylus jump.")})
    widths = [(tr(b["name"]), b["width"]) for b in r["bands"]]
    if widths:
        widest = max(widths, key=lambda w: w[1])
        items.append({"title": tr("Where the width lives"), "value": widest[0], "level": INFO, "pill": tr("Widest band"),
                      "text": tr("Width per range (Side vs. Mid, in dB; higher = wider):") + " "
                              + " · ".join(f"{n_} {w_:+.0f}" for n_, w_ in widths) + ". "
                              + tr("Typically width grows toward the highs (reverbs, cymbals, backing vocals) while the "
                                   "low end stays centered."),
                      "learn": tr("Mix engineers open up the highs and keep the lows tight: the mix sounds big without "
                                  "losing weight.")})
    return items
