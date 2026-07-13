# BPS Indonesia IO Tables (185 Produk) — Stata-ready conversion

Source: BPS CSV exports (all juta rupiah)
- `io2016_total_*`     : Transaksi **Total**, harga dasar, **2016**
- `io2020_domestik_*`  : Transaksi **Domestik**, harga dasar, **2020**
- `io2020_total_hd_*`  : Transaksi **Total**, harga dasar, **2020**
- `io2020_total_hp_*`  : Transaksi **Total**, harga pembeli, **2020**

All .dta files are Stata format 118 (Stata 14+). Values in **juta rupiah**.
Zeros in the source ("-") are stored as 0, not missing.

## Files (three per table, using the prefixes above)

| File | Rows | Contents |
|---|---|---|
| `*_long.dta` | ~40k | Full table in long form: `row_code`, `row_label`, `col_code`, `col_label`, `value`, plus `row_sec`/`col_sec` (numeric 1–185, 0 = non-sector row/col such as final demand, VA, totals). Best for merging/reshaping. |
| `*_matrix.dta` | 185 | One row per origin sector. `z1`–`z185` = intermediate deliveries to destination sectors (the Z matrix); then harmonised final-demand and supply-side columns: `fd_rt fd_lnprt fd_pemerintah fd_pmtb fd_inventori fd_ekspor_brg fd_ekspor_jasa tot_perm_antara tot_perm_akhir tot_permintaan impor_brg impor_jasa adj_if tot_impor marjin_besar marjin_eceran biaya_angkut tot_marjin tot_pajak_subsidi output tot_penyediaan`. Ready for `mkmat`. |
| `*_primary.dta` | 185 | Primary inputs by (column) sector: `adj_if tot_input_antara pajak_subsidi_prod konsumsi_impor komp_tk surplus_usaha pajak_lain_prod tot_input_primer tot_input`. |

Column codes were harmonised across years (BPS used 4010/5010-style codes in
2016 and 4011/5011-style in 2020 for the same concepts).

## Analysis do-file: `io_analysis.do`

Run it from the folder containing the .dta files. For each table it:
1. Builds A = Z·diag(1/x) with x = `output` (col 7000; verified ≡ row 2100).
2. Computes the Leontief inverse L = (I−A)⁻¹ via `mata luinv()`.
3. Output multipliers (column sums of L), forward multipliers (Ghosh row sums),
   Rasmussen backward/forward linkage indices (mean-normalised), key-sector flag.
4. Type-I income and GDP/VA multipliers using `komp_tk` and `tot_input_primer`.

Outputs: `*_multipliers.dta` (185 sectors, sorted by output multiplier) and
`*_leontief_inverse.dta` (full 185×185 L, vars `l1`–`l185`).

## Validation performed
- `output` (7000) == `tot_input` (2100) exactly, all 185 sectors, both years.
- Row sums of Z == `tot_perm_antara` (1800) exactly.
- Implied GDP: 2016 ≈ Rp 12,171 T; 2020 ≈ Rp 15,049 T (matches BPS national accounts at basic prices).
- No zero-output sectors (no division-by-zero in A).

## Which table for which purpose
- **io2020_domestik** (harga dasar): Z = domestic intermediates only.
  inv(I−A_d) gives *domestic* output multipliers — the standard object for
  impact/policy analysis. Use this one for multiplier and shock work.
- **io2020_total_hd** (harga dasar): Z includes imported intermediates.
  Describes the full input *technology*; its Leontief inverse overstates
  domestic impacts (VA multipliers ≈ 1 by construction).
- **Import-use matrix**: M = Z(total_hd) − Z(domestik). Verified exact:
  column sums of M equal the domestik table's row 2000 (Total Konsumsi
  Antara Impor) to the rupiah. Use M/x for import coefficients — useful for
  import-dependence / NTM exposure analysis by sector.
- **io2020_total_hp** (harga pembeli): same total concept but valued at
  purchaser prices (margins & product taxes folded into cells). Not standard
  for Leontief analysis; useful for expenditure-side description and for
  deriving margin/tax layers by comparing against the harga dasar table.
- **io2016_total**: total concept only — 2016 vs 2020 multipliers are NOT
  directly comparable unless you also obtain the 2016 domestik table.
Cross-table consistency (2020): GDP identical across all three tables
(Rp 15,049,221,956 juta); Z(total_hd) − Z(domestik) ≥ 0 elementwise.
