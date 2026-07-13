"""
Convert BPS Indonesia Input-Output tables (185 produk) from CSV to Stata-ready .dta
Outputs per table:
  1. *_long.dta    : full table in long form (row_code, col_code, value)
  2. *_matrix.dta  : 185-row wide file (Z matrix z1-z185 + final demand + output)
  3. *_primary.dta : primary inputs / value added by sector (transposed VA rows)
"""
import pandas as pd
import numpy as np
import re, unicodedata

UP = "/mnt/user-data/uploads/"
OUT = "/home/claude/out/"
import os
os.makedirs(OUT, exist_ok=True)

FILES = {
    "io2016_total": {
        "path": UP + "Tabel_Input-Output_Indonesia_Transaksi_Total_Atas_Dasar_Harga_Dasar__185_Produk___2016___Juta_Rupiah_.csv",
        "code_row": 4, "label_row": 5, "data_row0": 6,
        "year": 2016, "concept": "Transaksi Total, harga dasar",
    },
    "io2020_domestik": {
        "path": UP + "Tabel_Input-Output_Indonesia_Transaksi_Domestik_Atas_Dasar_Harga_Dasar__185_Produk___2020__Juta_Rupiah_.csv",
        "code_row": 3, "label_row": 4, "data_row0": 5,
        "year": 2020, "concept": "Transaksi Domestik, harga dasar",
    },
    "io2020_total_hd": {
        "path": UP + "Tabel_Input-Output_Indonesia_Transaksi_Total_Atas_Dasar_Harga_Dasar__185_Produk___2020__Juta_Rupiah_.csv",
        "code_row": 3, "label_row": 4, "data_row0": 5,
        "year": 2020, "concept": "Transaksi Total, harga dasar",
    },
    "io2020_total_hp": {
        "path": UP + "Tabel_Input-Output_Indonesia_Transaksi_Total_Atas_Dasar_Harga_Pembeli__185_Produk___2020__Juta_Rupiah_.csv",
        "code_row": 3, "label_row": 4, "data_row0": 5,
        "year": 2020, "concept": "Transaksi Total, harga pembeli",
    },
}

# harmonised names for non-sector COLUMNS (both years' codes mapped to same var names)
COL_MAP = {
    "1800": ("tot_perm_antara",  "Total Permintaan Antara"),
    "3011": ("fd_rt",            "Konsumsi Rumah Tangga"),
    "3012": ("fd_lnprt",         "Konsumsi LNPRT"),
    "3020": ("fd_pemerintah",    "Konsumsi Pemerintah"),
    "3030": ("fd_pmtb",          "Pembentukan Modal Tetap Bruto"),
    "3040": ("fd_inventori",     "Perubahan Inventori"),
    "3050": ("fd_ekspor_brg",    "Ekspor Barang (fob)"),
    "3060": ("fd_ekspor_jasa",   "Ekspor Jasa"),
    "3090": ("tot_perm_akhir",   "Total Permintaan Akhir"),
    "3100": ("tot_permintaan",   "Total Permintaan / Use"),
    "4010": ("impor_brg",        "Impor Barang (cif)"),
    "4011": ("impor_brg",        "Impor Barang (cif)"),
    "4020": ("impor_jasa",       "Impor Jasa"),
    "4012": ("impor_jasa",       "Impor Jasa"),
    "4030": ("adj_if",           "Adjustment (i.f)"),
    "4013": ("adj_if",           "Adjustment (i.f)"),
    "4090": ("tot_impor",        "Total Impor"),
    "4019": ("tot_impor",        "Total Impor"),
    "5010": ("marjin_besar",     "Marjin Perdagangan Besar"),
    "5011": ("marjin_besar",     "Marjin Perdagangan Besar"),
    "5020": ("marjin_eceran",    "Marjin Perdagangan Eceran"),
    "5012": ("marjin_eceran",    "Marjin Perdagangan Eceran"),
    "5030": ("biaya_angkut",     "Biaya Pengangkutan"),
    "5013": ("biaya_angkut",     "Biaya Pengangkutan"),
    "5090": ("tot_marjin",       "Total Marjin & Biaya Angkut"),
    "5019": ("tot_marjin",       "Total Marjin & Biaya Angkut"),
    "6090": ("tot_pajak_subsidi","Total Pajak dikurang Subsidi atas Produk"),
    "7000": ("output",           "Output Domestik Harga Dasar"),
    "8000": ("tot_penyediaan",   "Total Penyediaan / Supply"),
}

# harmonised names for non-sector ROWS (primary inputs)
ROW_MAP = {
    "i.f":  ("adj_if",            "Adjustment (i.f)"),
    "i.f.": ("adj_if",            "Adjustment (i.f)"),
    "1900": ("tot_input_antara",  "Total Input/Konsumsi Antara"),
    "1950": ("pajak_subsidi_prod","Pajak dikurang Subsidi atas Produk"),
    "2000": ("konsumsi_impor",    "Total Konsumsi Antara Impor"),
    "2010": ("komp_tk",           "Kompensasi Tenaga Kerja"),
    "2020": ("surplus_usaha",     "Surplus Usaha Bruto"),
    "2030": ("pajak_lain_prod",   "Pajak dikurang Subsidi Lainnya atas Produksi"),
    "2090": ("tot_input_primer",  "Total Input Primer"),
    "2100": ("tot_input",         "Total Input"),
}

def clean_num(s):
    if not isinstance(s, str):
        return np.nan if pd.isna(s) else float(s)
    s = s.strip()
    if s in ("", "-"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return np.nan
    return -v if neg else v

def clean_label(s):
    if pd.isna(s):
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    return re.sub(r"\s+", " ", s).strip()

for key, meta in FILES.items():
    raw = pd.read_csv(meta["path"], header=None, dtype=str)
    cr, lr, dr = meta["code_row"], meta["label_row"], meta["data_row0"]

    # ---- columns ----
    col_codes, col_labels, col_idx = [], [], []
    for c in range(3, raw.shape[1]):
        code = raw.iloc[cr, c]
        if pd.isna(code) or str(code).strip() == "":
            continue
        code = str(code).strip()
        col_codes.append(code)
        col_labels.append(clean_label(raw.iloc[lr, c]))
        col_idx.append(c)

    # ---- rows ----
    row_codes, row_labels, row_idx = [], [], []
    for r in range(dr, raw.shape[0]):
        code = raw.iloc[r, 1]
        if pd.isna(code) or str(code).strip() == "":
            continue
        code = str(code).strip()
        row_codes.append(code)
        row_labels.append(clean_label(raw.iloc[r, 2]))
        row_idx.append(r)

    # numeric block
    block = raw.iloc[row_idx, col_idx].map(clean_num).to_numpy()

    n_sec = 185
    sec_col_pos = [i for i, cc in enumerate(col_codes) if cc.isdigit() and 1 <= int(cc) <= 185]
    sec_row_pos = [i for i, rc in enumerate(row_codes) if rc.isdigit() and 1 <= int(rc) <= 185]
    assert len(sec_col_pos) == n_sec and len(sec_row_pos) == n_sec, (key, len(sec_col_pos), len(sec_row_pos))

    sec_names = [row_labels[i] for i in sec_row_pos]  # use row labels as canonical

    # =========== 1. LONG FILE ===========
    recs = []
    for ri, rpos in enumerate(row_idx):
        rc, rl = row_codes[ri], row_labels[ri]
        for ci, cpos in enumerate(col_idx):
            cc, cl = col_codes[ci], col_labels[ci]
            recs.append((rc, rl, cc, cl, block[ri, ci]))
    long = pd.DataFrame(recs, columns=["row_code", "row_label", "col_code", "col_label", "value"])
    long["year"] = meta["year"]
    long["tabel"] = meta["concept"]
    # numeric sector ids where applicable (0 = non-sector row/col)
    long["row_sec"] = pd.to_numeric(long["row_code"], errors="coerce")
    long.loc[~long["row_sec"].between(1, 185), "row_sec"] = 0
    long["col_sec"] = pd.to_numeric(long["col_code"], errors="coerce")
    long.loc[~long["col_sec"].between(1, 185), "col_sec"] = 0
    long["row_sec"] = long["row_sec"].fillna(0).astype(np.int16)
    long["col_sec"] = long["col_sec"].fillna(0).astype(np.int16)
    long.to_stata(
        OUT + f"{key}_long.dta", write_index=False, version=118,
        variable_labels={
            "row_code": "Kode baris (BPS)", "row_label": "Label baris",
            "col_code": "Kode kolom (BPS)", "col_label": "Label kolom",
            "value": "Nilai (juta rupiah)", "year": "Tahun tabel IO",
            "tabel": "Konsep transaksi", "row_sec": "Sektor baris 1-185 (0=bukan sektor)",
            "col_sec": "Sektor kolom 1-185 (0=bukan sektor)",
        },
    )

    # =========== 2. MATRIX FILE (185 rows) ===========
    Z = block[np.ix_(sec_row_pos, sec_col_pos)]
    mat = pd.DataFrame({"sector": np.arange(1, 186, dtype=np.int16),
                        "sector_name": sec_names})
    for j in range(n_sec):
        mat[f"z{j+1}"] = Z[:, j]
    varlabs = {"sector": "Kode sektor (1-185)", "sector_name": "Nama produk/sektor"}
    for j in range(n_sec):
        varlabs[f"z{j+1}"] = f"Ke sektor {j+1}: {sec_names[j]}"[:80]
    # append non-sector columns (final demand, totals, imports, margins)
    seen = set()
    for i, cc in enumerate(col_codes):
        if i in sec_col_pos:
            continue
        vname, vlab = COL_MAP.get(cc, (f"c{cc}", col_labels[i]))
        if vname in seen:
            continue
        seen.add(vname)
        mat[vname] = block[sec_row_pos, i]
        varlabs[vname] = vlab[:80]
    mat.to_stata(OUT + f"{key}_matrix.dta", write_index=False, version=118,
                 variable_labels=varlabs)

    # =========== 3. PRIMARY INPUTS FILE (transpose VA rows) ===========
    prim = pd.DataFrame({"sector": np.arange(1, 186, dtype=np.int16),
                         "sector_name": sec_names})
    pvarlabs = {"sector": "Kode sektor (1-185)", "sector_name": "Nama produk/sektor"}
    seenr = set()
    for i, rc in enumerate(row_codes):
        if i in sec_row_pos:
            continue
        vname, vlab = ROW_MAP.get(rc, (f"r{rc}", row_labels[i]))
        if vname in seenr:
            continue
        seenr.add(vname)
        prim[vname] = block[i, sec_col_pos]
        pvarlabs[vname] = vlab[:80]
    prim.to_stata(OUT + f"{key}_primary.dta", write_index=False, version=118,
                  variable_labels=pvarlabs)

    # =========== validation ===========
    x_col = mat["output"].to_numpy() if "output" in mat else None
    ti = prim["tot_input"].to_numpy()
    print(f"[{key}] Z shape {Z.shape}, sum Z = {Z.sum():,.0f}")
    if x_col is not None:
        diff = np.abs(x_col - ti)
        print(f"  output(7000) vs total input(2100): max abs diff = {diff.max():,.0f} "
              f"(rel {np.nanmax(diff/np.where(ti==0,np.nan,ti)):.2e})")
    # row identity: intermediate + final demand
    chk = Z.sum(axis=1) - mat["tot_perm_antara"].to_numpy()
    print(f"  rowsum(Z) vs 1800: max abs diff = {np.abs(chk).max():,.0f}")
    print(f"  GDP check (sum tot_input_primer) = {prim['tot_input_primer'].sum():,.0f} juta")

print("done")
