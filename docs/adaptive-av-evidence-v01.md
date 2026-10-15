# Adaptive Music & Visual Evidence V0.1 — Stage 5.4.6.5C

Pipeline offline untuk pengukuran, kandidat temporal, dan enrichment Adaptive
Director Input V0.3. Pipeline tidak memilih shot/cut final, overlay, subtitle,
render, atau publish. Canonical dan speech artifacts tetap menjadi input baca.

## Runtime dan CLI

Python 3.14.2, NumPy 2.5.4 dan SciPy 1.18.1 dipasang dalam `.venv-av` dengan
persetujuan pengguna. Binary wheels digunakan; jsonschema 4.25.1 yang sudah ada
digunakan melalui `--system-site-packages`. Tidak ada model/dependensi ASR yang
dipasang atau diubah. Versi numerik dicatat di `requirements-av.txt` dan setiap
evidence. `.venv-av` diabaikan Git. FFmpeg/FFprobe 6.1.1 dan GNU timeout yang
sudah tersedia digunakan. CLI memilih `.venv-av/bin/python` jika tersedia.

```sh
python3 -B scripts/analyze_adaptive_av_evidence_v01.py generate \
  --video data/test-videos/cinematic-7693770515172887829.mp4 \
  --metadata data/analyses/universal/cinematic-7693770515172887829.media.json \
  --analysis data/analyses/universal/cinematic-universal-v02.canonical.json \
  --director-input data/analyses/director/adaptive-inputs/showcase.director-input-v03.json \
  --output-dir data/analyses/av-v01/showcase.final.v01

python3 -B scripts/analyze_adaptive_av_evidence_v01.py generate \
  --video data/test-videos/mandala-original.mp4 \
  --metadata data/analyses/universal/mandala-original.media.json \
  --analysis data/analyses/universal/pak-fuad-universal-v02.canonical.json \
  --director-input data/analyses/director/adaptive-inputs/pak-fuad.director-input-v03.json \
  --output-dir data/analyses/av-v01/pak-fuad.final.v01

python3 -B scripts/analyze_adaptive_av_evidence_v01.py validate \
  --bundle data/analyses/av-v01/showcase.final.v01

# Untuk enrichment terpisah: bundle harus lulus replay terlebih dahulu.
python3 -B scripts/analyze_adaptive_av_evidence_v01.py enrich \
  --bundle data/analyses/av-v01/showcase.final.v01 \
  --director-input data/analyses/director/adaptive-inputs/showcase.director-input-v03.json \
  --output data/analyses/director/adaptive-inputs/showcase.av-reviewed-run.v03.json
```

Output yang sudah ada selalu ditolak. Gunakan nama baru untuk run berikutnya.
`generate` tanpa `--director-input` membuat bundle evidence saja. `validate`
melakukan replay offline dari MP4, termasuk decode dan perhitungan ulang;
tidak melakukan ASR atau inference remote. Exit 0 menunjukkan penilaian selesai
dan validasi struktural/provenance lulus, bukan fakta audiovisual terverifikasi.

## Source dan kontrak

Utilitas Stage 5.4.6.4/5A/5B digunakan kembali untuk project-path checks,
JSON ketat, SHA-256, FFprobe metadata, canonical schema/semantic validation,
stream discovery, bounded subprocess, capture PCM, dan atomic exclusive writes.
Source ID, filename sidecar, SHA-256, duration, width/height/FPS harus cocok.
Metadata rounding mengikuti kontrak lama; bukan penambahan presisi palsu.

Bundle berisi `music-rhythm.v01.json`, `visual-timing.v01.json`,
`audiovisual-correlation.v01.json`, `validation.v01.json`, dan opsional
`director-input.enriched.v03.json`. Dua JSON schemas baru:

- `src/schemas/adaptive-av-evidence.v0.1.schema.json`: tiga jenis evidence,
  struktur pengukuran, kandidat, sumber, metode, provenance dan keterbatasan.
- `src/schemas/adaptive-av-validation.v0.1.schema.json`: checks, hash setiap
  artifact, eligibility terbatas, original/enriched Director references.

Setiap evidence merekam source hash lengkap, sidecar/canonical hash, hash kode
dan schemas/metode/dependency pins, versi alat/library, parameter, presisi,
event arrays, confidence, limitations dan `validation_status`.
`canonical_findings_status=unverified`, `verified_fact=false`,
`frame_verified=false` tetap eksplisit. Perubahan file bound membuat replay
gagal. Hash lokal tanpa tanda tangan tidak membuktikan autentikasi independen.

## Audio: pengukuran dan estimasi

Hanya audio stream pertama yang diperiksa. PCM mono 16 kHz s16le dibuat dengan
capture helper Stage 5B dan dihapus setelah pengukuran. Fingerprint berlaku
untuk normalisasi ini saja; bukan bukti transkripsi atau akurasi semantik.
FFprobe memeriksa PTS tiap audio frame dan `nb_samples`. Waktu berasal dari
PTS awal dikurangi container presentation origin, lalu jumlah sampel.
Gap/discontinuity di atas tiga sampel ditolak; pipeline tidak menebak gap.
Durasi PCM harus cocok dengan coverage audio frames dalam 50 ms.
Window terakhir dibatasi pada durasi source.

Window nonoverlap 320 sampel/20 ms menghasilkan RMS, dBFS, spectral centroid
dan positive spectral flux. FFT SciPy menggunakan Hann window, tanpa zero
padding. Flux dinormalisasi terhadap jumlah magnitudo spektrum saat ini dan
sebelumnya. RMS dapat berubah karena speech, engine noise, efek, ataupun musik.
Centroid hanya ukuran spektrum, tidak mengklasifikasikan instrumen/suara.

Novelty = 0.6 × positive energy novelty + 0.4 × spectral flux. Energy novelty
membandingkan RMS dengan rata-rata lima window sebelumnya, dibagi RMS maksimum.
Ambang onset = max(0.06, median + 3 × MAD); SciPy `find_peaks` memakai jarak
minimum 100 ms. Energy peak memakai 45% peak RMS. Abrupt changes ≥8 dB,
intensity changes ≥10 dB dalam 0.5 s, dan quiet runs ≥0.2 s dicatat sebagai
kandidat. Quiet threshold = max(-45 dBFS dalam RMS, 4% peak RMS). Quiet berarti
relatif rendah menurut threshold, bukan keheningan absolut/batas kalimat.

Tempo hanya diuji pada wilayah yang canonical laporkan sebagai music-only,
tanpa speech/unknown/conflict atau kebutuhan speech review yang belum jelas.
Music/speech/unknown regions tetap disimpan terpisah dengan basis
`canonical_unverified`; klasifikasi ini bukan observasi akustik independen.
Segment gaps, overlap konflik dan uncertain speech tidak boleh menyediakan
jalan pintas untuk atribusi beat. Dialogue tanpa musik tidak diberi tempo.

Autocorrelation SciPy terhadap novelty menguji lag 13–50 window (0.26–1 s).
Estimasi membutuhkan ≥6 s, ≥8 onset, score ≥0.60, phase consistency ≥0.75,
≥6 siklus berbeda dan pengulangan pada kedua separuh wilayah. Tidak ada tempo
bila ambang gagal. Half/double tempo alternatives hanya dicatat bila lag
alternatif memang diuji dan mencapai correlation ≥0.60. Interpretasi musikal
tetap unverified. Candidate beat timestamps selalu menunjuk onset yang benar
diukur; tidak ada beat grid interpolasi atau timestamp hasil karangan.

## Visual: sampling dan kandidat

FFprobe mendapatkan presentation timestamps seluruh decoded video frames.
Indeks sampling memakai stride = ceil(frame count / (duration × 8)), minimum
1. FFmpeg memilih indeks tersebut sebelum downscale area ke RGB 64 × 64.
Tidak menggunakan fps filter yang membuat/interpolasi frame. Frame hanya
dipertahankan sementara untuk perbandingan berurutan; tidak ada frame dump.
Sampling biasanya sekitar 7.5 fps untuk sumber 30 fps. VFR bisa menghasilkan
gap yang berbeda: seluruh sampled PTS dan maximum observed gap direkam.

NumPy menghitung luminance, absolute difference, brightness-compensated
difference, dan histogram RGB empat bin per kanal. Candidate hard cuts
memerlukan centered difference ≥0.12 dan histogram difference ≥0.20. Large
structure change tanpa syarat histogram menjadi `visual_change_candidate`.
Uniform brightness change >0.12 tidak dianggap otomatis shot cut. Flash naik
lalu turun >0.18 menjadi `flash_candidate`; waktu kandidat menunjuk sampled
peak dan intervalnya mencakup frame sebelum/sesudah. Hard-cut inference pada
flash recovery ditahan. High-motion candidates ≥0.045, motion-change ≥0.08,
stable runs <0.018 selama ≥0.5 s dan monotonic fades ≥4 samples dengan perubahan
brightness ≥0.15 juga dicatat. Threshold adalah heuristik versi metode ini.

Perubahan lighting, exposure, pan, neon, kendaraan bergerak dan shake masih
bisa menghasilkan kandidat palsu. Camera motion/object motion tidak dibedakan,
dan kamera tidak diklasifikasikan sebagai pan/dolly/tilt. PTS sampel berasal
dari decoded frames, tetapi event di antara sampel tetap `signal_estimated`,
bukan `frame_verified`. Kandidat cut mencakup bracket waktu dua sampel.

Visual events/stable regions memperoleh references ke canonical segments dan
visual/audiovisual events yang intervalnya overlap. Semantics, reveal, vehicle
identity dan model descriptions tetap berada di canonical; asosiasi hanya
`approximate_model_context`, dengan `independently_verified=false`.

## Korelasi dan enrichment

Setiap kandidat visual diskret mencari generic onset/change audio terdekat.
Match hanya dibuat jika absolute offset ≤0.25 s. Report memuat signed offset,
event IDs, tolerance, dan jumlah uncertainty audio+visual. Confidence low,
`relation_status=uncertain`, `intentional_sync_verified=false`. Fades/stable
runs tidak diperlakukan sebagai satu titik sync; stable regions hanya punya
asosiasi canonical, termasuk konteks dialogue. Musik absent/unknown tidak
mengubah generic acoustic onset menjadi musical beat. Tanpa audio, matches
kosong. Efek yang sudah ada bukan rekomendasi menambah efek lain.

Director V0.3 schema lama tetap utuh. Source dan canonical reference harus
cocok. Transcript/speech_alignment references, source dan seluruh editorial
policy dipertahankan persis. Existing AV slots tidak ditimpa. Renderer harus
unknown dengan operations kosong; jika input mengklaim verified, enrichment
ditolak sampai tersedia kontrak verifikasi yang sesuai. Render/publish tetap
false. Visual evidence yang lulus structural/source checks boleh attached
dengan `signal_estimated`. Music slot hanya attached jika estimasi regional
lulus; unavailable/uncertain membuat null. Correlation tidak menambah slot
di schema lama: tersedia melalui bundle/validation report.

## Batas resource dan publikasi artifact

Source envelope: ≤180 s, nominal FPS ≤120, ≤25,000 decoded frames, ≤1,500
sampled frames. Probe/decode timeout 60 s; stdout JSON ≤8 MiB, PCM ≤6.4 MB,
RGB ≤18.432 MB, stderr DEVNULL. Worker CLI dibatasi address space 1 GiB,
CPU 180 s; BLAS/OMP threads=1. GNU timeout memberikan wall deadline 240 s
untuk process group, TERM lalu KILL setelah 2 s. TERM handler worker melepas
existing bounded subprocess finally blocks, kill/wait/reap anak FFmpeg.
Controller memiliki batas luar 245 s dan output ≤8 MiB. API Python langsung
tetap memakai batas per-decode dan ukuran input; gunakan CLI untuk batas total.

JSON duplicate keys/nonfinite, traversal dan resolved symlink escapes ditolak.
Input hashes dicek lagi sebelum output. Directory dibuat eksklusif setelah
analisis berhasil; file dipublikasikan dengan atomic no-clobber helper.
Validation report ditulis terakhir. Kegagalan publikasi membersihkan hanya
file yang dibuat run tersebut. Forced SIGKILL bisa menyisakan bundle parsial;
tanpa validation report bundle tidak dapat diterima. Concurrent replacement
oleh proses lokal yang memodifikasi filesystem tetap di luar autentikasi ini;
consumer harus revalidate sebelum menggunakan evidence.

## Tes offline

```sh
OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv-av/bin/python -B \
  -m unittest discover -s tests -p 'test_adaptive_av_evidence_v01.py' -v

OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv-av/bin/python -B \
  -m unittest discover -s tests -p 'test_*.py' -v
```

Tes sintetis memeriksa periodic/irregular/speech-like signals, spectral change
tanpa RMS jump, silence, hard cuts, pan, lighting, flashes, fades, decoded PTS,
cross-source contamination, path safety, artifact replay, preservation policy,
eligibility, output/temp cleanup dan process-group termination. Synthetic
FFmpeg fixture benar-benar di-decode; mock fixtures tidak diklaim sebagai
media nyata. Hasil real video dan angka regresi disimpan dalam laporan Stage 5C.
