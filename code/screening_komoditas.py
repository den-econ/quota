"""
==============================================================================
screening_komoditas.py
==============================================================================
STUDI EKSPLORASI: KOMODITAS PANGAN/PAKAN MANA YANG ESENSIAL?

Tujuan
------
Menggantikan daftar komoditas ad-hoc dengan daftar hasil SARINGAN yang
dapat direproduksi. Dua lapis:

  LAPIS 1 (deskriptif) : untuk tiap produk kandidat, hitung
     - ketergantungan impor (IPR)
     - kedalaman hilir : pangsa biaya maksimum + industri mana
     - keluasan hilir  : jumlah industri pengguna material (>1%, >3%, >5%)
     - eksposur konsumen (proksi): pangsa permintaan akhir x IPR
  LAPIS 2 (brute force): jalankan simulasi disrupsi untuk SETIAP produk
     kandidat satu per satu (s = 0.5 dan 1.0), catat kerugian PDB,
     lonjakan harga, dan 3 industri paling terdampak.

Aturan seleksi -- SELURUHNYA BERBASIS DATA (Lapis 1 saja), TANPA memakai
hasil simulasi, agar daftar tidak bergantung pada parameter model yang
belum tervalidasi (sigma, epsilon, critshare). Lapis 2 (simulasi) hanya
dijalankan SETELAH seleksi, sebagai diagnostik, bukan kriteria:
  LOLOS bila ketergantungan impor >= AMBANG_IPR, DAN
        (risiko kuantitas : NTB industri pengguna material >= AMBANG_NTB
                            (% PDB; pengguna material = pangsa biaya >= 1%), ATAU
         risiko harga     : IPR >= AMBANG_IPR_HARGA (pasar domestik tipis =
                            potensi lonjakan kelangkaan, tanpa asumsi
                            elastisitas), ATAU
         risiko konsumen  : eksposur konsumen >= AMBANG_KONSUMEN)

Keluaran (data/interim/)
------------------------
  screening_komoditas.csv / .xlsx : tabel saringan lengkap + flag lolos
  screening_peta_eksposur.png     : peta kuadran (IPR vs kerugian PDB)
  klasifikasi_kandidat.csv        : daftar kandidat pangan/pakan --
                                    dibuat otomatis dgn kata kunci pada run
                                    pertama; SILAKAN EDIT manual (kolom
                                    is_kandidat 0/1) lalu jalankan ulang.

Cara pakai
----------
  python screening_komoditas.py          # run pertama: buat klasifikasi
  (edit klasifikasi_kandidat.csv bila perlu)
  python screening_komoditas.py          # run kedua: saringan penuh

Skrip ini MENGIMPOR mesin simulasi dari simulasi_disrupsi_impor.py --
letakkan keduanya di folder yang sama.
==============================================================================
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- impor mesin simulasi (data, kalibrasi, dan seluruh langkah model) -------
import simulasi_disrupsi_impor as sim
from simulasi_disrupsi_impor import INTERIM, LOG_DIR, N_SECTORS

# =============================================================================
# PARAMETER SARINGAN (dinyatakan eksplisit agar seleksi dapat direproduksi)
# =============================================================================

S_SCREEN = [0.50, 1.00]   # titik guncangan utk DIAGNOSTIK pasca-seleksi
EPS_SCREENING = 0.50      # elastisitas default utk diagnostik (bukan seleksi)
RUN_DIAGNOSTICS = True    # jalankan simulasi utk produk yang LOLOS saja

# ambang seleksi -- SEMUA berbasis data, lihat aturan di docstring
AMBANG_IPR       = 0.10   # gerbang: min. ketergantungan impor (pasokan antara)
AMBANG_NTB       = 1.00   # min. NTB pengguna material (% PDB); pengguna
                          # material = industri dgn pangsa biaya produk >= 1%
AMBANG_IPR_HARGA = 0.30   # IPR di atas ini = risiko harga kelangkaan
AMBANG_KONSUMEN  = 0.05   # min. eksposur konsumen (pangsa FD x IPR)

# --- kata kunci utk klasifikasi otomatis kandidat pangan/pakan ---------------
# hanya utk MEMBUAT draf klasifikasi_kandidat.csv; hasilnya bisa diedit manual
KEYWORDS_INCLUDE = [
    "padi", "beras", "jagung", "kedelai", "kacang", "ubi", "singkong",
    "sagu", "sayur", "buah", "kelapa", "sawit", "tebu", "gula", "kopi",
    "teh", "kakao", "coklat", "ternak", "sapi", "unggas", "ayam", "telur",
    "susu", "ikan", "udang", "perikanan", "daging", "garam", "tepung",
    "penggilingan", "roti", "mie", "makanan", "minuman", "pakan",
    "minyak makan", "minyak goreng", "rempah", "bumbu", "hortikultura",
]
KEYWORDS_EXCLUDE = [
    "minyak bumi", "gas", "batu bara", "kayu", "tembakau", "rokok",
    "tekstil", "kertas", "kimia", "karet",
]

# =============================================================================
# LOGGING (pola sama dgn skrip simulasi: layar + file di quota/log)
# =============================================================================

log = logging.getLogger("screening")
logfile = LOG_DIR / f"screening_{datetime.now():%Y%m%d_%H%M%S}.log"
log.setLevel(logging.INFO)
_fh = logging.FileHandler(logfile, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s",
                                   datefmt="%Y-%m-%d %H:%M:%S"))
_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(_fh)
log.addHandler(_ch)


# =============================================================================
# LAPIS 0 -- KLASIFIKASI KANDIDAT
# =============================================================================

def classify_candidates(sectors: pd.DataFrame) -> pd.DataFrame:
    """Baca klasifikasi_kandidat.csv bila ada; bila tidak, buat draf
    otomatis dari kata kunci lalu minta pengguna memeriksanya."""
    path = INTERIM / "klasifikasi_kandidat.csv"
    if path.exists():
        klas = pd.read_csv(path)
        log.info(f"Klasifikasi dibaca dari {path} "
                 f"({int(klas['is_kandidat'].sum())} kandidat).")
        return klas

    import re

    def guess(name: str) -> int:
        """Cocokkan kata kunci pada BATAS KATA (\\b), bukan substring --
        tanpa ini, 'ikan' cocok di dalam 'perbaIKANnya' sehingga Pesawat
        Terbang dan Kapal ikut menjadi kandidat pangan."""
        low = name.lower()
        if any(re.search(rf"\b{re.escape(k)}", low) for k in KEYWORDS_EXCLUDE):
            return 0
        return int(any(re.search(rf"\b{re.escape(k)}", low)
                       for k in KEYWORDS_INCLUDE))

    klas = sectors.copy()
    klas["is_kandidat"] = klas["sector_name"].map(guess)
    klas.to_csv(path, index=False)
    log.info(f"Draf klasifikasi dibuat: {path} "
             f"({int(klas['is_kandidat'].sum())} kandidat via kata kunci).")
    log.info("PERIKSA dan edit kolom is_kandidat (0/1) bila perlu, lalu "
             "jalankan ulang skrip ini.")
    return klas


# =============================================================================
# LAPIS 1 -- METRIK DESKRIPTIF
# =============================================================================

def layer1_metrics(d: dict) -> pd.DataFrame:
    """Metrik per produk, langsung dari matriks yang sudah terkalibrasi."""
    q, ZT, Zm, Atot = d["q"], d["ZT"], d["Zm"], d["Atot"]
    names = d["sectors"]["sector_name"].to_numpy()

    M_row = d["M_row"]                          # impor utk penggunaan antara
    supply = q + M_row
    ipr = np.where(supply > 0, M_row / supply, 0.0)

    # kedalaman: pangsa biaya maksimum di antara industri pengguna
    depth = Atot.max(axis=1)
    depth_at = Atot.argmax(axis=1)

    # keluasan: berapa industri yang memakai produk ini secara material
    breadth = {f"n_pengguna_{int(t*100)}pct": (Atot > t).sum(axis=1)
               for t in (0.01, 0.03, 0.05)}

    # eksposur konsumen (PROKSI): permintaan akhir = pasokan - penggunaan
    # antara (termasuk ekspor & investasi -- caveat), dikali IPR
    fd = np.clip(supply - ZT.sum(axis=1), 0.0, None)
    fd_share = np.where(supply > 0, fd / supply, 0.0)
    consumer_exposure = fd_share * ipr

    # risiko kuantitas (data-only): NTB industri yang MATERIAL bergantung
    # pada produk i (pangsa biaya >= 1%), sebagai % PDB
    material = Atot >= 0.01                        # (i,j) boolean
    ntb_pengguna = 100 * (material * d["va"][None, :]).sum(axis=1) / d["va"].sum()

    df = pd.DataFrame({
        "sector": d["sectors"]["sector"],
        "sector_name": names,
        "impor_antara_rp": M_row,
        "ipr": ipr,
        "ntb_pengguna_material_pct_pdb": ntb_pengguna,
        "kedalaman_maks": depth,
        "industri_terdalam": names[depth_at],
        **breadth,
        "pangsa_fd_proksi": fd_share,
        "eksposur_konsumen": consumer_exposure,
    })
    return df


# =============================================================================
# LAPIS 2 -- BRUTE FORCE: simulasi tiap kandidat satu per satu
# =============================================================================

def layer2_stress_test(d: dict, candidates: list[int]) -> pd.DataFrame:
    """Jalankan run_one utk tiap kandidat pada tiap s standar."""
    names = d["sectors"]["sector_name"].to_numpy()
    va_total = d["va"].sum()
    rows = []
    for n_done, code in enumerate(candidates, 1):
        i = code - 1
        if d["M_row"][i] <= 0:                  # tak ada impor: tak bisa dishock
            rows.append({"sector": code, "pct_pdb_s050": 0.0,
                         "pct_pdb_s100": 0.0, "harga_spike_s050_pct": 0.0,
                         "top3_industri_s050": "(tidak ada impor antara)"})
            continue
        rec = {"sector": code}
        for s in S_SCREEN:
            res = sim.run_one(d, [code], s)
            tag = f"s{int(100*s):03d}"
            rec[f"pct_pdb_{tag}"] = 100 * res["dva"].sum() / va_total
            rec[f"harga_spike_{tag}_pct"] = 100 * (np.exp(res["pi"][code]) - 1)
            if s == 0.50:
                top = np.argsort(res["dx_combined"])[::-1][:3]
                rec["top3_industri_s050"] = "; ".join(names[top])
        rows.append(rec)
        if n_done % 10 == 0:
            log.info(f"  ... {n_done}/{len(candidates)} kandidat selesai")
    return pd.DataFrame(rows)


# =============================================================================
# SELEKSI & KELUARAN
# =============================================================================

def apply_selection(df: pd.DataFrame) -> pd.DataFrame:
    """Aturan seleksi mekanis, SELURUHNYA dari metrik data (Lapis 1) --
    tidak ada keluaran simulasi di sini."""
    df["layak_kuantitas"] = df["ntb_pengguna_material_pct_pdb"] >= AMBANG_NTB
    df["layak_harga"]     = df["ipr"] >= AMBANG_IPR_HARGA
    df["layak_konsumen"]  = df["eksposur_konsumen"] >= AMBANG_KONSUMEN
    df["lolos_saringan"]  = (df["ipr"] >= AMBANG_IPR) & (
        df["layak_kuantitas"] | df["layak_harga"] | df["layak_konsumen"])
    return df


def exposure_map(df: pd.DataFrame):
    """Peta kuadran (data-only): IPR (x) vs NTB pengguna material (y, log),
    ukuran gelembung = eksposur konsumen."""
    fig, ax = plt.subplots(figsize=(10, 7))
    y = df["ntb_pengguna_material_pct_pdb"].clip(lower=1e-4)
    size = 40 + 3000 * df["eksposur_konsumen"]
    colors = np.where(df["lolos_saringan"], "firebrick", "grey")
    ax.scatter(df["ipr"], y, s=size, c=colors, alpha=0.6, edgecolor="k",
               linewidth=0.5)
    for _, r in df.iterrows():
        yv = max(r["ntb_pengguna_material_pct_pdb"], 1e-4)
        if r["lolos_saringan"] or yv > AMBANG_NTB:
            ax.annotate(f'{int(r["sector"])}', (r["ipr"], yv),
                        fontsize=7, ha="center", va="bottom")
    ax.axvline(AMBANG_IPR, ls="--", c="k", lw=0.8)
    ax.axvline(AMBANG_IPR_HARGA, ls=":", c="k", lw=0.8)
    ax.axhline(AMBANG_NTB, ls="--", c="k", lw=0.8)
    ax.set_yscale("log")
    ax.set_xlabel("Ketergantungan impor (IPR, pasokan antara)")
    ax.set_ylabel("NTB industri pengguna material (% PDB, skala log)")
    ax.set_title("Peta eksposur komoditas pangan/pakan\n"
                 "(merah = lolos saringan; ukuran = eksposur konsumen; "
                 "label = kode produk)")
    fig.tight_layout()
    fig.savefig(INTERIM / "screening_peta_eksposur.png", dpi=200)
    plt.close(fig)


def main():
    log.info(f"Log: {logfile}")
    log.info(f"Ambang seleksi (data-only): IPR>={AMBANG_IPR}, "
             f"NTB-pengguna>={AMBANG_NTB}% PDB, IPR-harga>={AMBANG_IPR_HARGA}, "
             f"konsumen>={AMBANG_KONSUMEN}; diagnostik={RUN_DIAGNOSTICS}")

    # --- data & kalibrasi: mesin yang sama dgn simulasi utama ---------------
    d = sim.calibrate(sim.load_all())
    # utk screening, isi elastisitas yang kosong dgn default (cukup utk ranking)
    d["eps"] = np.where(np.isnan(d["eps"]), EPS_SCREENING, d["eps"])

    # --- lapis 0: kandidat ----------------------------------------------------
    klas = classify_candidates(d["sectors"])
    candidates = klas.loc[klas["is_kandidat"] == 1, "sector"].astype(int).tolist()
    if not candidates:
        log.error("Tidak ada kandidat. Edit klasifikasi_kandidat.csv dulu.")
        return

    # --- lapis 1: metrik data + SELEKSI (tanpa simulasi) ---------------------
    log.info(f"Lapis 1: metrik deskriptif utk {N_SECTORS} produk ...")
    m1 = layer1_metrics(d)
    df = m1[m1["sector"].isin(candidates)].copy()
    df = apply_selection(df)

    # --- lapis 2: DIAGNOSTIK simulasi, hanya utk yang lolos ------------------
    passed = df.loc[df["lolos_saringan"], "sector"].astype(int).tolist()
    if RUN_DIAGNOSTICS and passed:
        log.info(f"Lapis 2 (diagnostik, BUKAN kriteria): simulasi "
                 f"{len(passed)} produk lolos x {len(S_SCREEN)} titik ...")
        m2 = layer2_stress_test(d, passed)
        m2 = m2.rename(columns={c: f"diag_{c}" for c in m2.columns
                                if c != "sector"})
        df = df.merge(m2, on="sector", how="left")
        sort_col = "diag_pct_pdb_s050"
    else:
        sort_col = "ntb_pengguna_material_pct_pdb"
    df = df.sort_values(sort_col, ascending=False, na_position="last")

    df.to_csv(INTERIM / "screening_komoditas.csv", index=False)
    with pd.ExcelWriter(INTERIM / "screening_komoditas.xlsx",
                        engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="saringan", index=False)
        df[df["lolos_saringan"]].to_excel(xw, sheet_name="lolos", index=False)
    exposure_map(df)

    lolos = df[df["lolos_saringan"]]
    log.info(f"\nHasil: {len(lolos)} dari {len(df)} kandidat lolos saringan:")
    for _, r in lolos.iterrows():
        alasan = [nm for nm, fl in [("kuantitas", r["layak_kuantitas"]),
                                    ("harga", r["layak_harga"]),
                                    ("konsumen", r["layak_konsumen"])] if fl]
        log.info(f"  {int(r['sector']):>3}  {r['sector_name'][:45]:<45} "
                 f"IPR={r['ipr']:.2f}  NTB-pengguna={r['ntb_pengguna_material_pct_pdb']:.2f}%  "
                 f"[{', '.join(alasan)}]")
    log.info("\nINGAT: saringan berbasis nilai TIDAK menangkap input "
             "murah-tapi-esensial (tipe karagenan). Lakukan tinjauan pakar "
             "atas daftar yang TIDAK lolos: 'adakah industri yang secara "
             "fisik tak bisa berproduksi tanpa produk ini?'")
    log.info(f"Keluaran di: {INTERIM}")


if __name__ == "__main__":
    main()
