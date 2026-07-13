"""
==============================================================================
simulasi_disrupsi_impor.py
==============================================================================
SIMULASI DAMPAK DISRUPSI IMPOR KOMODITAS PANGAN/PAKAN
(implementasi Python dari model v4 -- lihat dokumentasi teknis LaTeX)

Apa yang dilakukan skrip ini
----------------------------
Untuk setiap komoditas terdampak dan setiap besaran guncangan
s = 0.10, 0.20, ..., 1.00 (porsi pasokan impor yang hilang), skrip:

  1. KUANTITAS : menghitung kerugian output tiap 185 sektor melalui
                 (a) guncangan langsung dengan substitusi CES domestik-impor,
                 (b) kaskade kemacetan (bottleneck) ke hilir,
                 (c) efek permintaan hulu (indikatif);
  2. FAKTOR    : membagi kerugian nilai tambah menjadi kompensasi tenaga
                 kerja dan surplus usaha (closure B + labor hoarding);
  3. HARGA     : Tahap A -- lonjakan harga kelangkaan komoditas terdampak;
                 Tahap B -- rambatan biaya ke seluruh sektor
                 (batas bawah cost-push & batas atas scarcity).

Keluaran (di data/interim/)
---------------------------
  hasil_simulasi_grid.csv        : 1 baris per kombinasi (skenario x s)
  hasil_simulasi_detail.xlsx     : sheet "grid" + detail per-sektor
                                   untuk s terpilih (default 0.5 dan 1.0)
  dosis_respons_komoditas.png    : kurva kerugian PDB vs s per komoditas
  dosis_respons_bundel.png       : kurva untuk skenario bundel

Cara menjalankan
----------------
  python simulasi_disrupsi_impor.py

Kebutuhan paket: numpy, pandas, matplotlib, openpyxl
  pip install numpy pandas matplotlib openpyxl
==============================================================================
"""

from pathlib import Path
import logging
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")  # simpan grafik ke file tanpa membuka jendela
import matplotlib.pyplot as plt

# =============================================================================
# BAGIAN 0 -- PARAMETER (satu-satunya bagian yang perlu diedit sehari-hari)
# =============================================================================

# --- nama file data (format Stata .dta, hasil pipeline konversi IO 2020) ----
F_TOTAL = "io2020_total_hd_matrix.dta"   # matriks transaksi TOTAL (dom+impor)
F_DOM   = "io2020_domestik_matrix.dta"   # matriks transaksi DOMESTIK
F_PRIM  = "io2020_total_hd_primary.dta"  # blok input primer

# --- nama kolom di file input primer (sesuaikan bila berbeda) ---------------
COL_VA      = "tot_input_primer"    # nilai tambah bruto (NTB)
COL_TAX     = "pajak_subsidi_prod"  # pajak dikurangi subsidi atas produk
COL_ADJ     = "adj_if"              # adjustment i.f.
COL_TOTIN   = "tot_input"           # total input (baris 2100)
COL_KOMP    = "komp_tk"             # kompensasi tenaga kerja
COL_SURPLUS = "surplus_usaha"       # surplus usaha bruto

N_SECTORS = 185

# --- elastisitas substitusi CES domestik-impor per komoditas (sigma) --------
# Kasus batas: sigma besar (mis. 999) = substitusi sempurna;
#              sigma -> 0 = Leontief ketat; sigma = 1 = Cobb-Douglas.
# Nilai di bawah = ASUMSI (judgment, ~setengah Armington GTAP) -- lihat
# registri parameter pada dokumentasi teknis. Produk lain memakai default.
# DAFTAR PRODUK = hasil saringan data-only (screening_komoditas.py, Jul 2026).
SIGMA_DEFAULT = 2.0
SIGMA = {
    9:  1.2,   # Gandum (padi-padian lainnya): nyaris tanpa produksi domestik
               # -- mendekati esensial; IPR 0.99
    7:  1.3,   # Kedelai: kedelai lokal food-grade sangat terbatas; IPR 0.77
    65: 1.5,   # Gula: kapasitas rafinasi vs bahan baku
    61: 1.5,   # Tepung lainnya (hilir terigu)
    23: 2.0,   # Kakao: ada produksi domestik, substitusi parsial
    57: 2.0,   # Olahan buah/sayur
    50: 1.3,   # Garam industri: spesifikasi teknis ketat (klor-alkali/farmasi)
}

# --- elastisitas permintaan jangka pendek per komoditas (epsilon) -----------
# Hanya dibutuhkan untuk komoditas yang dishock (Tahap A harga).
# Kisaran literatur permintaan pangan Indonesia; GANTI dgn estimasi Susenas.
EPSILON = {
    9:  0.35,  # gandum -> terigu -> mie/roti: permintaan pokok, inelastis
    7:  0.30,  # kedelai: episode tempe 2022 = jangkar kalibrasi
    65: 0.30,  # gula: pokok, inelastis
    61: 0.40,  # tepung lainnya
    23: 0.60,  # kakao: produk hilir (coklat) lebih elastis
    57: 0.50,  # olahan buah/sayur
    50: 0.30,  # garam industri: sangat inelastis
}

# --- parameter perilaku lainnya ----------------------------------------------
LAMBDA    = 1.00   # porsi kekurangan yang diselesaikan lewat harga (0..1)
PI_CAP    = 1.00   # plafon lonjakan harga, dalam log poin (1.0 ~ +172%)
PSI       = 0.70   # labor hoarding: L_new = L * r^psi (1 = proporsional murni)
# Ambang pangsa biaya: input i hanya bisa membatasi industri j (baik langsung
# maupun lewat kaskade) bila pangsanya dalam struktur input j melebihi ambang
# ini. Tanpa ambang (0), input bernilai remeh dapat "menghentikan" seluruh
# ekonomi -- hasil uji data riil menunjukkan itu artefak, bukan ekonomi.
# Jalankan sensitivitas pada {0.01, 0.03, 0.05}.
CRITSHARE = 0.01
# Mode kaskade (Langkah 2):
#   False (DEFAULT, "proporsional"): kendala dari pemasok i pada industri j
#         diredam pangsa biayanya: cap = 1 - a_ij*(1 - avail_i). Input 3%
#         biaya yang hilang 90% memotong output ~2,7%, bukan 90%.
#   True  ("strict"): ratio pemasok diteruskan penuh (min murni) -- batas
#         atas teoretis; pada data riil, sektor hub (perdagangan, listrik)
#         menularkan keruntuhan ke seluruh ekonomi. Hanya utk lampiran.
CASCADE_STRICT = False

# --- iterasi kaskade ----------------------------------------------------------
TOL      = 1e-9
MAX_ITER = 500

# --- pengecualian sel guncangan (kontaminasi agregasi produk) ----------------
# Produk IO bisa memuat lebih dari satu komoditas. Bila sebuah industri
# jelas membeli komponen NON-target dari produk agregat, sel itu
# dikecualikan dari guncangan. Format: {kode_produk: [kode_industri, ...]}.
# Kasus terdokumentasi: produk 9 ("padi-padian DAN BAHAN MAKANAN LAINNYA")
# dibeli besar oleh industri Minyak Nabati (58) dgn pangsa impor tinggi --
# itu bukan gandum; tanpa pengecualian, skenario gandum "menghantam"
# kelapa sawit lewat efek hulu. VERIFIKASI sel sebelum mengubah daftar ini.
SHOCK_EXEMPT = {
    9: [58],   # bahan makanan lainnya utk industri minyak != gandum
}

# --- skenario: {nama: daftar kode produk terdampak} ---------------------------
# Tujuh komoditas hasil saringan data-only (screening_komoditas.py):
# lolos bila IPR >= 0.10 DAN (NTB pengguna material >= 1% PDB, ATAU
# IPR >= 0.30, ATAU eksposur konsumen >= 0.05). Lihat lampiran saringan
# pada dokumentasi teknis. Produk 73 (minuman beralkohol) dikeluarkan
# karena bukan komoditas ketahanan pangan.
SCENARIOS = {
    "Gandum (9)":              [9],
    "Kedelai (7)":             [7],
    "Gula (65)":               [65],
    "Tepung-terigu dst (61)":  [61],
    "Kakao (23)":              [23],
    "Olahan buah-sayur (57)":  [57],
    "Garam (50)":              [50],
    "BUNDEL hasil saringan":   [7, 9, 23, 50, 57, 61, 65],
}

# --- grid guncangan & titik detail ---------------------------------------------
S_GRID   = [round(0.1 * k, 2) for k in range(1, 11)]  # 0.10 ... 1.00
S_DETAIL = [0.50, 1.00]  # hanya s ini yang diekspor rinci per-sektor


# =============================================================================
# BAGIAN 1 -- DETEKSI LOKASI FOLDER (portabel antar komputer / username)
# =============================================================================

def find_repo_root() -> Path:
    """Temukan folder repo 'quota' tanpa hard-code username.

    Urutan pencarian:
      1. Naik dari lokasi skrip ini -- bekerja bila skrip disimpan di dalam
         repo (mis. quota/src/simulasi_disrupsi_impor.py).
      2. Lokasi standar: ~/Documents/GitHub/quota  (Path.home() otomatis
         menyesuaikan username di komputer mana pun).
    """
    # 1) cari ke atas dari file skrip
    try:
        here = Path(__file__).resolve()
        for parent in [here] + list(here.parents):
            if parent.name == "quota":
                return parent
    except NameError:
        pass  # __file__ tidak ada bila dijalankan interaktif -- lanjut ke (2)

    # 2) lokasi standar di home directory
    candidate = Path.home() / "Documents" / "GitHub" / "quota"
    if candidate.is_dir():
        return candidate

    raise FileNotFoundError(
        "Folder repo 'quota' tidak ditemukan. Simpan skrip ini di dalam repo, "
        "atau pastikan repo ada di ~/Documents/GitHub/quota."
    )


ROOT    = find_repo_root()
RAW     = ROOT / "data" / "raw" / "raw"
INTERIM = ROOT / "data" / "interim"
LOG_DIR = ROOT / "log"
INTERIM.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# --- logging: semua pesan tampil di layar DAN tersimpan di quota/log/ --------
log = logging.getLogger("simulasi")


def setup_logging() -> Path:
    """Siapkan log ke layar + file berstempel waktu; kembalikan path file."""
    logfile = LOG_DIR / f"simulasi_{datetime.now():%Y%m%d_%H%M%S}.log"
    log.setLevel(logging.INFO)
    fmt_file = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s",
                                 datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setFormatter(fmt_file)
    ch = logging.StreamHandler()                 # ke layar, tanpa stempel waktu
    ch.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(fh)
    log.addHandler(ch)
    return logfile


# =============================================================================
# BAGIAN 2 -- MUAT DATA & VALIDASI
# =============================================================================

def load_matrix(filename: str) -> tuple[np.ndarray, pd.DataFrame]:
    """Baca file .dta matriks IO -> (matriks Z 185x185, dataframe mentah).

    Konvensi: baris = produk penjual i, kolom z1..z185 = industri pembeli j.
    """
    path = RAW / filename
    if not path.exists():
        available = "\n  ".join(p.name for p in sorted(RAW.glob("*")))
        raise FileNotFoundError(
            f"{path} tidak ditemukan.\nFile yang ada di {RAW}:\n  {available}"
        )
    df = pd.read_stata(path).sort_values("sector").reset_index(drop=True)
    assert len(df) == N_SECTORS, f"{filename}: baris {len(df)} != {N_SECTORS}"
    z_cols = [f"z{i}" for i in range(1, N_SECTORS + 1)]
    return df[z_cols].to_numpy(dtype=float), df


def load_all():
    """Muat ketiga file, jalankan validasi, kembalikan dict berisi data inti."""
    log.info(f"Membaca data dari: {RAW}")

    ZT, df_total = load_matrix(F_TOTAL)          # transaksi total
    ZD, _        = load_matrix(F_DOM)            # transaksi domestik

    prim = pd.read_stata(RAW / F_PRIM).sort_values("sector").reset_index(drop=True)
    assert len(prim) == N_SECTORS

    q     = df_total["output"].to_numpy(dtype=float)      # output bruto
    va    = prim[COL_VA].to_numpy(dtype=float)            # NTB
    tax   = prim[COL_TAX].to_numpy(dtype=float)
    adj   = prim[COL_ADJ].to_numpy(dtype=float)
    totin = prim[COL_TOTIN].to_numpy(dtype=float)
    Lcomp = prim[COL_KOMP].to_numpy(dtype=float)          # kompensasi TK
    Ksub  = prim[COL_SURPLUS].to_numpy(dtype=float)       # surplus usaha

    Zm = ZT - ZD                                          # penggunaan IMPOR

    # ---- tiga uji validasi: berhenti bila data salah susun ------------------
    assert Zm.min() >= -1e-6, f"VALIDASI GAGAL: Zm negatif (min={Zm.min():.4g})"
    balance = (ZT.sum(axis=0) + adj + tax + va) / q       # keseimbangan kolom
    dev = np.abs(balance - 1).max()
    assert dev < 1e-6, f"VALIDASI GAGAL: keseimbangan kolom, dev maks={dev:.3g}"
    assert np.abs(q - totin).max() < 1e-6 * q.max(), \
        "VALIDASI GAGAL: output != total input"
    log.info(f"Validasi OK  (min Zm = {Zm.min():.3g}; dev keseimbangan = {dev:.2e})")

    sectors = df_total[["sector", "sector_name"]].copy()
    return dict(ZT=ZT, ZD=ZD, Zm=Zm, q=q, va=va, Lcomp=Lcomp, Ksub=Ksub,
                sectors=sectors)


# =============================================================================
# BAGIAN 3 -- KALIBRASI (dihitung SEKALI, dipakai semua skenario)
# =============================================================================

def calibrate(d: dict) -> dict:
    """Hitung koefisien, pangsa impor, invers Leontief, dan vektor parameter."""
    q, ZT, ZD, Zm = d["q"], d["ZT"], d["ZD"], d["Zm"]
    n = N_SECTORS

    with np.errstate(divide="ignore", invalid="ignore"):
        Ad = np.where(q > 0, ZD / q, 0.0)     # koefisien domestik  (bagi per kolom)
        Am = np.where(q > 0, Zm / q, 0.0)     # koefisien impor
        wM = np.where(ZT > 0, Zm / ZT, 0.0)   # pangsa impor per sel (i,j)

    Atot = Ad + Am
    I    = np.eye(n)

    # dua inversi mahal, masing-masing sekali saja:
    L_inv   = np.linalg.inv(I - Ad)     # untuk efek hulu (Langkah 3)
    L_inv_T = np.linalg.inv(I - Ad.T)   # untuk harga batas bawah (Tahap B)

    # vektor sigma & epsilon sepanjang 185 (indeks 0..184 = produk 1..185)
    sigma = np.full(n, SIGMA_DEFAULT)
    for code, val in SIGMA.items():
        sigma[code - 1] = val
    eps = np.full(n, np.nan)                     # NaN = belum ditetapkan
    for code, val in EPSILON.items():
        eps[code - 1] = val

    M_row = Zm.sum(axis=1)   # impor antara per produk (utk ukuran kekurangan)

    d.update(Ad=Ad, Am=Am, Atot=Atot, wM=wM, L_inv=L_inv, L_inv_T=L_inv_T,
             sigma=sigma, eps=eps, M_row=M_row)
    return d


# =============================================================================
# BAGIAN 4 -- FUNGSI MODEL
# (setiap fungsi = satu langkah pada flowchart dokumentasi teknis)
# =============================================================================

def ces_factor(w_m: np.ndarray, s: float, sig: float) -> np.ndarray:
    """Faktor output langsung f(s) untuk SATU komoditas terdampak.

    f = [w_D + w_M * (1-s)^rho]^(1/rho),  rho = (sigma-1)/sigma
    w_m : vektor pangsa impor komoditas ini pada tiap industri pengguna.

    Kasus khusus:
      s = 1 dan sigma <= 1 -> input esensial: pengguna berhenti total (f=0)
      sigma = 1            -> Cobb-Douglas: f = (1-s)^w_M
    """
    w_d = 1.0 - w_m
    if s >= 1.0 and sig <= 1.0:
        return np.where(w_m > 0, 0.0, 1.0)
    if abs(sig - 1.0) < 1e-9:
        return (1.0 - s) ** w_m
    rho = (sig - 1.0) / sig
    return (w_d + w_m * (1.0 - s) ** rho) ** (1.0 / rho)


def step1_direct_shock(d: dict, shocked: list[int], s: float) -> np.ndarray:
    """LANGKAH 1: output layak tiap industri setelah guncangan langsung.

    Faktor CES hanya diterapkan pada industri yang PENGGUNAANNYA MATERIAL:
    pangsa input i dalam struktur biaya j harus > CRITSHARE. Tanpa saringan
    ini, input remeh (mis. garam 0,05% biaya sebuah sektor jasa) dapat
    "menghancurkan" penggunanya lewat eksponen CES -- artefak, bukan ekonomi.
    Bila beberapa komoditas terdampak sekaligus (bundel), yang paling
    mengikat menentukan (min antar komoditas) -- konsisten nest Leontief.
    """
    factor = np.ones(N_SECTORS)
    for code in shocked:
        i = code - 1
        f_i = ces_factor(d["wM"][i, :], s, d["sigma"][i])
        material = d["Atot"][i, :] > CRITSHARE   # pengguna yang material saja
        f_i = np.where(material, f_i, 1.0)
        for j_code in SHOCK_EXEMPT.get(code, []):  # sel terkontaminasi
            f_i[j_code - 1] = 1.0
        factor = np.minimum(factor, f_i)
    return d["q"] * factor


def step2_cascade(d: dict, q_hat1: np.ndarray) -> np.ndarray:
    """LANGKAH 2: kaskade kemacetan hilir (iterasi sampai konvergen).

    Tiap putaran, output industri j dibatasi oleh (a) batas Langkah-1-nya
    sendiri dan (b) kendala dari pemasok domestiknya (pangsa > CRITSHARE).

    Bentuk kendala pemasok (lihat saklar CASCADE_STRICT):
      proporsional : cap_ij = 1 - a_ij * (1 - avail_i)
                     -- kekurangan pemasok memotong output pelanggan
                        SEBANDING pangsa biayanya (gaya Hallegatte/ARIO);
                        pasangan yang benar-benar esensial kelak dikembalikan
                        ke aturan min lewat tabel kritikalitas.
      strict       : cap_ij = avail_i  (ratio diteruskan penuh; batas atas)
    """
    q, Ad = d["q"], d["Ad"]
    material = Ad > CRITSHARE                # matriks boolean (i,j), tetap

    x = q_hat1.copy()
    cap1 = q_hat1 / q                        # batas Langkah 1 (rasio)
    for _ in range(MAX_ITER):
        avail = x / q                        # rasio ketersediaan tiap produk
        if CASCADE_STRICT:
            caps = np.where(material, avail[:, None], 1.0)
        else:
            shortfall = (1.0 - avail)[:, None]           # (i,1)
            caps = np.where(material, 1.0 - Ad * shortfall, 1.0)
        cap2 = caps.min(axis=0)              # pemasok terketat tiap industri j
        x_new = q * np.minimum(cap1, cap2)
        if np.abs(x_new - x).max() < TOL * q.max():
            return x_new
        x = x_new
    log.warning("  kaskade mencapai MAX_ITER tanpa konvergen penuh")
    return x


def step3_upstream(d: dict, x_bot: np.ndarray) -> np.ndarray:
    """LANGKAH 3: efek permintaan hulu (indikatif).

    Industri yang outputnya turun membeli lebih sedikit dari pemasoknya;
    seluruh putaran dijumlahkan sekaligus oleh invers Leontief.
    """
    drop_purchases = d["Ad"] @ (d["q"] - x_bot)
    return d["L_inv"] @ drop_purchases


def step5_factors(d: dict, combined: np.ndarray) -> dict:
    """FAKTOR: bagi kerugian NTB menjadi kompensasi TK & surplus usaha.

    Closure B + hoarding: L_new = L * r^psi; surplus = klaim residual.
    """
    q, Lcomp, Ksub = d["q"], d["Lcomp"], d["Ksub"]
    r = np.clip(1.0 - combined / q, 0.0, 1.0)
    L_new = Lcomp * r ** PSI
    K_new = np.maximum(0.0, r * (Lcomp + Ksub) - L_new)
    return dict(r=r, dL=Lcomp - L_new, dK=Ksub - K_new)


def step6_scarcity_price(d: dict, shocked: list[int], s: float) -> dict:
    """HARGA TAHAP A: lonjakan kelangkaan tiap komoditas terdampak.

    d(ln p) = -lambda * d(ln pasokan_total) / epsilon, diplafon PI_CAP.
    Pasokan total = q_c + M_c (M = impor antara; lihat caveat dokumentasi).
    """
    pi = {}
    for code in shocked:
        i = code - 1
        e = d["eps"][i]
        if np.isnan(e):
            raise ValueError(
                f"Produk {code} dishock tetapi EPSILON belum ditetapkan -- "
                "tambahkan di BAGIAN 0 (disengaja agar tiap komoditas baru "
                "mendapat elastisitas eksplisit)."
            )
        M_eff = d["M_row"][i] - sum(d["Zm"][i, j_code - 1]
                                     for j_code in SHOCK_EXEMPT.get(code, []))
        M_eff = max(M_eff, 0.0)
        supply_old = d["q"][i] + M_eff
        supply_new = d["q"][i] + (1.0 - s) * M_eff
        dln_supply = np.log(max(supply_new, 1e-12) / supply_old)
        pi_c = -LAMBDA * dln_supply / e
        if pi_c > PI_CAP:
            log.warning(f"  pi produk {code} = {pi_c:.2f} > plafon "
                  f"{PI_CAP} -- dipangkas (sinyal pasar tipis)")
            pi_c = PI_CAP
        pi[code] = pi_c
    return pi


def step7_price_propagation(d: dict, pi: dict) -> tuple[np.ndarray, np.ndarray]:
    """HARGA TAHAP B: rambatan biaya -> (dp_lower, dp_upper), log poin.

    Batas BAWAH : hanya harga varietas IMPOR komoditas S yang naik;
                  185 harga domestik cost-determined.
    Batas ATAS  : KEDUA varietas komoditas S naik (harga S eksogen);
                  sektor lain N cost-determined -- model terpartisi.
    """
    n = N_SECTORS
    S = np.array([c - 1 for c in pi], dtype=int)
    pi_vec = np.array([pi[c] for c in pi])

    # --- batas bawah: dp = (I - Ad')^-1 Am' dpm ------------------------------
    dpm = np.zeros(n)
    dpm[S] = pi_vec
    dp_lower = d["L_inv_T"] @ (d["Am"].T @ dpm)

    # --- batas atas: partisi S (eksogen) vs N (endogen) ----------------------
    mask_N = np.ones(n, dtype=bool)
    mask_N[S] = False
    Ad_NN  = d["Ad"][np.ix_(mask_N, mask_N)]
    At_SN  = d["Atot"][np.ix_(S, mask_N)]
    dp_N   = np.linalg.solve(np.eye(mask_N.sum()) - Ad_NN.T, At_SN.T @ pi_vec)
    dp_upper = np.zeros(n)
    dp_upper[mask_N] = dp_N
    dp_upper[S] = pi_vec

    return dp_lower, dp_upper


def run_one(d: dict, shocked: list[int], s: float) -> dict:
    """Jalankan SATU kombinasi (skenario, s) lengkap; kembalikan semua hasil."""
    q, va = d["q"], d["va"]

    # -- kuantitas -------------------------------------------------------------
    q_hat1   = step1_direct_shock(d, shocked, s)
    x_bot    = step2_cascade(d, q_hat1)
    dx_up    = step3_upstream(d, x_bot)
    dx_supply   = q - x_bot                       # = Langkah 1 + Langkah 2
    # konvensi konservatif (max), diplafon output sektor: kerugian sebuah
    # sektor tidak mungkin melebihi outputnya sendiri
    dx_combined = np.minimum(np.maximum(dx_supply, dx_up), q)
    va_coef  = np.where(q > 0, va / q, 0.0)
    dva      = va_coef * dx_combined              # kerugian NTB per sektor

    # -- faktor ------------------------------------------------------------------
    fac = step5_factors(d, dx_combined)

    # -- harga -------------------------------------------------------------------
    pi = step6_scarcity_price(d, shocked, s)
    dp_lower, dp_upper = step7_price_propagation(d, pi)

    return dict(q_hat1=q_hat1, x_bot=x_bot, dx_up=dx_up,
                dx_supply=dx_supply, dx_combined=dx_combined, dva=dva,
                dL=fac["dL"], dK=fac["dK"], r=fac["r"],
                pi=pi, dp_lower=dp_lower, dp_upper=dp_upper)


# =============================================================================
# BAGIAN 5 -- LOOP GRID & AGREGASI
# =============================================================================

def aggregate_row(d: dict, res: dict, name: str, shocked, s: float) -> dict:
    """Ringkas satu run menjadi satu baris dataset grid."""
    q, va, Lcomp, Ksub = d["q"], d["va"], d["Lcomp"], d["Ksub"]
    w_out = q / q.sum()   # bobot output utk indeks harga (proksi PPI)
    return {
        "skenario": name,
        "produk": " ".join(map(str, shocked)),
        "s": s,
        "kerugian_output_rp": res["dx_combined"].sum(),
        "pct_output": 100 * res["dx_combined"].sum() / q.sum(),
        "kerugian_ntb_rp": res["dva"].sum(),
        "pct_pdb": 100 * res["dva"].sum() / va.sum(),
        "kerugian_komp_tk_rp": res["dL"].sum(),
        "pct_komp_tk": 100 * res["dL"].sum() / Lcomp.sum(),
        "kerugian_surplus_rp": res["dK"].sum(),
        "pct_surplus": 100 * res["dK"].sum() / Ksub.sum(),
        "pi_maks_pct": 100 * (np.exp(max(res["pi"].values())) - 1),
        "indeks_harga_bawah_pct": 100 * (w_out @ res["dp_lower"]),
        "indeks_harga_atas_pct": 100 * (w_out @ res["dp_upper"]),
    }


def detail_table(d: dict, res: dict) -> pd.DataFrame:
    """Tabel rinci 185 sektor untuk satu run (diurut kerugian terbesar)."""
    df = d["sectors"].copy()
    df["kerugian_langsung"]   = d["q"] - res["q_hat1"]          # Delta(1)
    df["kerugian_kaskade"]    = res["q_hat1"] - res["x_bot"]    # Delta(2)
    df["kerugian_hulu_indik"] = res["dx_up"]
    df["kerugian_gabungan"]   = res["dx_combined"]
    df["kerugian_ntb"]        = res["dva"]
    df["kerugian_komp_tk"]    = res["dL"]
    df["kerugian_surplus"]    = res["dK"]
    df["dp_bawah_pct"] = 100 * (np.exp(res["dp_lower"]) - 1)
    df["dp_atas_pct"]  = 100 * (np.exp(res["dp_upper"]) - 1)
    return df.sort_values("kerugian_gabungan", ascending=False)


def main():
    logfile = setup_logging()
    log.info(f"Log tersimpan di: {logfile}")
    # catat parameter run agar setiap log bisa direproduksi
    log.info(f"Parameter: CRITSHARE={CRITSHARE}, CASCADE_STRICT={CASCADE_STRICT}, PSI={PSI}, LAMBDA={LAMBDA}, "
             f"PI_CAP={PI_CAP}, SIGMA_DEFAULT={SIGMA_DEFAULT}")
    log.info(f"SIGMA khusus: {SIGMA}")
    log.info(f"EPSILON: {EPSILON}")

    d = calibrate(load_all())

    grid_rows = []
    detail_sheets = {}   # {nama_sheet: DataFrame}

    for k, (name, shocked) in enumerate(SCENARIOS.items(), start=1):
        log.info(f"\n=== Skenario {k}/{len(SCENARIOS)}: {name} ===")
        for s in S_GRID:
            res = run_one(d, shocked, s)
            row = aggregate_row(d, res, name, shocked, s)
            grid_rows.append(row)
            log.info(f"  s={s:.2f}: output -{row['pct_output']:.2f}% | "
                  f"PDB -{row['pct_pdb']:.2f}% | "
                  f"harga (bawah-atas) {row['indeks_harga_bawah_pct']:.2f}"
                  f"-{row['indeks_harga_atas_pct']:.2f}%")
            if s in S_DETAIL:
                sheet = f"sc{k}_s{int(100 * s)}"     # mis. sc1_s50, sc1_s100
                detail_sheets[sheet] = detail_table(d, res)

    grid = pd.DataFrame(grid_rows)

    # ---- simpan keluaran ------------------------------------------------------
    csv_path = INTERIM / "hasil_simulasi_grid.csv"
    grid.to_csv(csv_path, index=False)

    xlsx_path = INTERIM / "hasil_simulasi_detail.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as xw:
        grid.to_excel(xw, sheet_name="grid", index=False)
        for sheet, df in detail_sheets.items():
            df.to_excel(xw, sheet_name=sheet[:31], index=False)

    make_plots(grid)
    log.info(f"\nSelesai. Keluaran di: {INTERIM}")


# =============================================================================
# BAGIAN 6 -- GRAFIK DOSIS-RESPONS
# =============================================================================

def make_plots(grid: pd.DataFrame):
    """Dua PNG: (1) 10 komoditas individual, (2) skenario bundel."""
    bundle_name = [n for n in SCENARIOS if "BUNDEL" in n.upper()][0]

    fig, ax = plt.subplots(figsize=(9, 6))
    for name in SCENARIOS:
        if name == bundle_name:
            continue
        sub = grid[grid["skenario"] == name]
        ax.plot(sub["s"], sub["pct_pdb"], marker="o", ms=3, label=name)
    ax.set_xlabel("Porsi pasokan impor hilang (s)")
    ax.set_ylabel("Kerugian NTB (% PDB)")
    ax.set_title("Kurva dosis-respons disrupsi impor per komoditas")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(INTERIM / "dosis_respons_komoditas.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 5))
    sub = grid[grid["skenario"] == bundle_name]
    ax.plot(sub["s"], sub["pct_pdb"], marker="o", color="firebrick", lw=2)
    ax.set_xlabel("Porsi pasokan impor hilang (s)")
    ax.set_ylabel("Kerugian NTB (% PDB)")
    ax.set_title("Dosis-respons: bundel seluruh komoditas pangan/pakan")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(INTERIM / "dosis_respons_bundel.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
