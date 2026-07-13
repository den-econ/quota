"""
==============================================================================
robustness_simulasi.py
==============================================================================
UJI KETAHANAN (ROBUSTNESS CHECK) SIMULASI DISRUPSI IMPOR

Tujuan
------
Mensubstansiasi dua klaim dokumentasi teknis:
  (1) BESARAN kerugian peka terhadap parameter -> karena itu dilaporkan
      sebagai kisaran; skrip ini menghitung kisarannya.
  (2) PERINGKAT kritikalitas antarkomoditas stabil -> skrip ini mengukur
      stabilitasnya (korelasi peringkat Spearman antar-varian).

Desain: one-at-a-time (OAT) -- setiap varian mengubah SATU parameter dari
baseline, sehingga kontribusi tiap asumsi terbaca terpisah:

  CRITSHARE      : 0.01* | 0.03 | 0.05
  skala SIGMA    : x0.5  | x1*  | x2   (elastisitas substitusi D-M)
  PSI (hoarding) : 0.5   | 0.7* | 1.0
  skala EPSILON  : x0.5  | x1*  | x1.5 (elastisitas permintaan, sisi harga)
  LAMBDA         : 0.5   | 1.0*
  + tiga varian khusus:
    "subst-sempurna" : sigma = 999 utk semua (spesifikasi awal pimpinan)
    "kaskade-ketat"  : CASCADE_STRICT = True (batas atas teoretis)
    "tanpa-exempt"   : SHOCK_EXEMPT = {} -- mengukur besarnya koreksi
                       dekontaminasi sel produk 9 -> Minyak Nabati
                                                   (* = baseline)
Kompatibel dgn simulasi_disrupsi_impor.py versi ber-SHOCK_EXEMPT;
baseline robustness otomatis memakai pengecualian yang aktif di skrip
utama.

Keluaran (data/interim/)
------------------------
  robustness_grid.csv / .xlsx  : kerugian PDB per komoditas per varian
                                 (pada s fokus), + korelasi peringkat
  robustness_tornado.png       : parameter mana yang paling menggerakkan
                                 hasil (kerugian PDB bundel, min-maks)
  robustness_ranking.png       : peringkat tiap komoditas antar-varian
  log berstempel waktu di quota/log/

Cara pakai:  python robustness_simulasi.py
(letakkan di folder yang sama dengan simulasi_disrupsi_impor.py)
==============================================================================
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import simulasi_disrupsi_impor as sim
from simulasi_disrupsi_impor import INTERIM, LOG_DIR

# =============================================================================
# PENGATURAN
# =============================================================================

S_FOKUS = 0.50          # titik guncangan utk perbandingan antar-varian
S_FOKUS_2 = 1.00        # titik kedua (dilaporkan di tabel, bukan grafik)

# definisi varian: (nama, {atribut modul: nilai}, skala_sigma, skala_eps)
BASELINE = ("baseline", {}, 1.0, 1.0)
VARIANTS = [
    BASELINE,
    ("critshare=0.03",   {"CRITSHARE": 0.03},      1.0, 1.0),
    ("critshare=0.05",   {"CRITSHARE": 0.05},      1.0, 1.0),
    ("sigma x0.5",       {},                        0.5, 1.0),
    ("sigma x2",         {},                        2.0, 1.0),
    ("psi=0.5",          {"PSI": 0.5},              1.0, 1.0),
    ("psi=1.0",          {"PSI": 1.0},              1.0, 1.0),
    ("epsilon x0.5",     {},                        1.0, 0.5),
    ("epsilon x1.5",     {},                        1.0, 1.5),
    ("lambda=0.5",       {"LAMBDA": 0.5},           1.0, 1.0),
    ("subst-sempurna",   {},                        np.inf, 1.0),  # sigma=999
    ("kaskade-ketat",    {"CASCADE_STRICT": True},  1.0, 1.0),
    ("tanpa-exempt",     {"SHOCK_EXEMPT": {}},      1.0, 1.0),
    #  ^ matikan pengecualian sel terkontaminasi (produk 9 -> Minyak
    #    Nabati): mengukur berapa besar koreksi dekontaminasi itu sendiri.
]

# parameter modul yang boleh diubah-ubah lalu dipulihkan
MODULE_PARAMS = ["CRITSHARE", "PSI", "LAMBDA", "PI_CAP",
                 "CASCADE_STRICT", "SHOCK_EXEMPT"]

# =============================================================================
# LOGGING
# =============================================================================

log = logging.getLogger("robustness")
logfile = LOG_DIR / f"robustness_{datetime.now():%Y%m%d_%H%M%S}.log"
log.setLevel(logging.INFO)
_fh = logging.FileHandler(logfile, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s",
                                   datefmt="%Y-%m-%d %H:%M:%S"))
_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(_fh)
log.addHandler(_ch)


# =============================================================================
# UTILITAS
# =============================================================================

def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Korelasi peringkat Spearman tanpa scipy (cukup utk n kecil)."""
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def run_variant(d_base: dict, name: str, overrides: dict,
                sigma_scale: float, eps_scale: float) -> list[dict]:
    """Jalankan seluruh skenario utk satu varian; kembalikan baris hasil."""
    # --- siapkan salinan data & parameter -----------------------------------
    d = dict(d_base)                              # salinan dangkal cukup:
    d["sigma"] = d_base["sigma"].copy()           # hanya vektor ini yang
    d["eps"]   = d_base["eps"].copy()             # dimodifikasi per varian
    if np.isinf(sigma_scale):
        d["sigma"][:] = 999.0                     # substitusi sempurna
    else:
        d["sigma"] = np.maximum(d["sigma"] * sigma_scale, 0.05)
    d["eps"] = d["eps"] * eps_scale

    saved = {p: getattr(sim, p) for p in MODULE_PARAMS}
    for p, v in overrides.items():
        setattr(sim, p, v)

    rows = []
    try:
        va_total = d["va"].sum()
        for scen_name, shocked in sim.SCENARIOS.items():
            for s in (S_FOKUS, S_FOKUS_2):
                res = sim.run_one(d, shocked, s)
                rows.append({
                    "varian": name,
                    "skenario": scen_name,
                    "s": s,
                    "pct_pdb": 100 * res["dva"].sum() / va_total,
                    "pct_komp_tk": 100 * res["dL"].sum() / d["Lcomp"].sum(),
                    "pi_maks_pct": 100 * (np.exp(max(res["pi"].values())) - 1),
                })
    finally:
        for p, v in saved.items():                # SELALU pulihkan parameter
            setattr(sim, p, v)
    return rows


# =============================================================================
# GRAFIK
# =============================================================================

def tornado_plot(grid: pd.DataFrame, bundle: str):
    """Rentang kerugian PDB bundel (s fokus) per kelompok parameter."""
    base_val = grid.query(
        "varian == 'baseline' and skenario == @bundle and s == @S_FOKUS"
    )["pct_pdb"].iloc[0]

    groups = {
        "critshare": ["critshare=0.03", "critshare=0.05"],
        "sigma":     ["sigma x0.5", "sigma x2", "subst-sempurna"],
        "psi":       ["psi=0.5", "psi=1.0"],
        "epsilon":   ["epsilon x0.5", "epsilon x1.5"],
        "lambda":    ["lambda=0.5"],
        "kaskade":   ["kaskade-ketat"],
        "exempt 9-58": ["tanpa-exempt"],
    }
    rows = []
    for gname, vnames in groups.items():
        vals = grid.query(
            "varian in @vnames and skenario == @bundle and s == @S_FOKUS"
        )["pct_pdb"]
        rows.append((gname, min(vals.min(), base_val),
                     max(vals.max(), base_val)))
    rows.sort(key=lambda r: r[2] - r[1])

    fig, ax = plt.subplots(figsize=(8, 5))
    ypos = np.arange(len(rows))
    for k, (gname, lo, hi) in enumerate(rows):
        ax.barh(k, hi - lo, left=lo, height=0.55, color="steelblue",
                alpha=0.8, edgecolor="k", linewidth=0.5)
    ax.axvline(base_val, color="firebrick", ls="--", lw=1.2,
               label=f"baseline = {base_val:.2f}%")
    ax.set_yticks(ypos)
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlabel(f"Kerugian PDB bundel pada s = {S_FOKUS} (%)")
    ax.set_title("Tornado: parameter mana yang paling menggerakkan hasil")
    ax.legend()
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(INTERIM / "robustness_tornado.png", dpi=200)
    plt.close(fig)


def ranking_plot(grid: pd.DataFrame, commodities: list[str]):
    """Peringkat tiap komoditas (1 = kerugian terbesar) antar-varian."""
    sub = grid.query("skenario in @commodities and s == @S_FOKUS")
    piv = sub.pivot(index="skenario", columns="varian", values="pct_pdb")
    ranks = piv.rank(ascending=False, axis=0)
    variants = [v[0] for v in VARIANTS]           # jaga urutan
    ranks = ranks[variants]

    fig, ax = plt.subplots(figsize=(11, 5))
    im = ax.imshow(ranks.to_numpy(), cmap="YlOrRd_r", aspect="auto",
                   vmin=1, vmax=len(commodities))
    ax.set_xticks(range(len(variants)))
    ax.set_xticklabels(variants, rotation=40, ha="right", fontsize=8)
    ax.set_yticks(range(len(ranks.index)))
    ax.set_yticklabels(ranks.index, fontsize=9)
    for i in range(ranks.shape[0]):
        for j in range(ranks.shape[1]):
            ax.text(j, i, int(ranks.iloc[i, j]), ha="center", va="center",
                    fontsize=8)
    ax.set_title(f"Peringkat kerugian PDB per varian (s = {S_FOKUS}; "
                 "1 = paling merusak)")
    fig.colorbar(im, ax=ax, shrink=0.8, label="peringkat")
    fig.tight_layout()
    fig.savefig(INTERIM / "robustness_ranking.png", dpi=200)
    plt.close(fig)


# =============================================================================
# UTAMA
# =============================================================================

def main():
    log.info(f"Log: {logfile}")
    log.info(f"Varian: {[v[0] for v in VARIANTS]}")

    d = sim.calibrate(sim.load_all())

    rows = []
    for name, overrides, sscale, escale in VARIANTS:
        log.info(f"Varian: {name} ...")
        rows.extend(run_variant(d, name, overrides, sscale, escale))
    grid = pd.DataFrame(rows)

    # --- stabilitas peringkat --------------------------------------------------
    bundle = [n for n in sim.SCENARIOS if "BUNDEL" in n.upper()][0]
    commodities = [n for n in sim.SCENARIOS if n != bundle]
    base = grid.query(
        "varian == 'baseline' and skenario in @commodities and s == @S_FOKUS"
    ).set_index("skenario")["pct_pdb"]

    corr_rows = []
    for name, *_ in VARIANTS:
        v = grid.query(
            "varian == @name and skenario in @commodities and s == @S_FOKUS"
        ).set_index("skenario")["pct_pdb"].reindex(base.index)
        corr_rows.append({"varian": name,
                          "spearman_vs_baseline": spearman(base.values,
                                                           v.values)})
    corr = pd.DataFrame(corr_rows)

    # --- keluaran ---------------------------------------------------------------
    grid.to_csv(INTERIM / "robustness_grid.csv", index=False)
    wide = grid.query("s == @S_FOKUS").pivot(index="skenario",
                                             columns="varian",
                                             values="pct_pdb")
    with pd.ExcelWriter(INTERIM / "robustness_grid.xlsx",
                        engine="openpyxl") as xw:
        grid.to_excel(xw, sheet_name="panjang", index=False)
        wide.to_excel(xw, sheet_name=f"pdb_s{int(100*S_FOKUS)}")
        corr.to_excel(xw, sheet_name="korelasi_peringkat", index=False)

    tornado_plot(grid, bundle)
    ranking_plot(grid, commodities)

    # --- ringkasan di log --------------------------------------------------------
    log.info("\n=== RINGKASAN ===")
    b = grid.query("skenario == @bundle and s == @S_FOKUS")
    base_val = b.loc[b["varian"] == "baseline", "pct_pdb"].iloc[0]
    log.info(f"Kerugian PDB bundel (s={S_FOKUS}): "
             f"min {b['pct_pdb'].min():.2f}% | "
             f"baseline {base_val:.2f}% | "
             f"maks {b['pct_pdb'].max():.2f}%")
    worst = corr["spearman_vs_baseline"].min()
    log.info(f"Stabilitas peringkat: Spearman minimum antar-varian = "
             f"{worst:.3f} " + ("(SANGAT STABIL)" if worst >= 0.9 else
                                "(STABIL)" if worst >= 0.7 else
                                "(PERIKSA -- peringkat bergeser material)"))
    for _, r in corr.iterrows():
        log.info(f"  {r['varian']:<18} Spearman = "
                 f"{r['spearman_vs_baseline']:.3f}")
    log.info(f"Keluaran di: {INTERIM}")


if __name__ == "__main__":
    main()
