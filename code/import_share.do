*==============================================================================
* Project : quota -- NTM / import disruption analysis (DEN)
* Do-file : import_share.do
* Purpose : Menghasilkan import_share.csv -- per industri j (kolom tabel IO):
*           input antara impor, input antara total, output bruto, dan
*           pangsa impor (dua penyebut).
* Inputs  : data/raw/io2020_total_hd_matrix.dta
*           data/raw/io2020_domestik_matrix.dta
* Output  : data/interim/import_share.csv
* Data    : Tabel IO BPS 2020, 185 produk, harga dasar (juta rupiah).
*           Impor = transaksi TOTAL dikurangi transaksi DOMESTIK (per sel);
*           identik dengan baris BPS 2000 (Total Konsumsi Antara Impor).
* Author  : Arya Swarnata
* Created : 2026-07
*==============================================================================

**# 0. Preambule ================================================================
version 16
clear all
macro drop _all
set more off
set varabbrev off
set linesize 120

* --- deteksi otomatis OS & username -> path root proyek ------------------------
if "`c(os)'" == "MacOSX" {
    global PROJ "/Users/`c(username)'/Documents/GitHub/quota"
}
else if "`c(os)'" == "Windows" {
    global PROJ "C:/Users/`c(username)'/Documents/GitHub/quota"
}
else {                                              // Unix/lainnya
    global PROJ "~/Documents/GitHub/quota"
}
global RAW     "$PROJ/data/raw"
global INTERIM "$PROJ/data/interim"
cap mkdir "$INTERIM"

* --- cek folder ada; berhenti dengan pesan jelas bila tidak ---------------------
cap confirm file "$RAW/io2020_total_hd_matrix.dta"
if _rc {
    di as error "File input tidak ditemukan di $RAW -- cek path proyek."
    exit 601
}

**# 1. Impor per sel: total dikurangi domestik ==================================
* Baris tabel IO = produk pemasok (i); kolom z1-z185 = industri pengguna (j).

use "$RAW/io2020_total_hd_matrix.dta", clear
keep sector z1-z185
rename z# zt#
tempfile total
save `total'

use "$RAW/io2020_domestik_matrix.dta", clear
keep sector z1-z185
rename z# zd#
merge 1:1 sector using `total', assert(3) nogen

* wide -> long: satu baris = satu sel (produk i, industri j)
rename sector product_i
reshape long zt zd, i(product_i) j(industry_j)
gen double use_imported = zt - zd

**# 2. Jumlahkan per industri (per kolom) =======================================
collapse (sum) interm_imported = use_imported ///
               interm_total    = zt, by(industry_j)

**# 3. Tambah nama sektor & output, hitung pangsa ===============================
rename industry_j sector
merge 1:1 sector using "$RAW/io2020_total_hd_matrix.dta", ///
      keepusing(sector_name output) assert(3) nogen
rename (sector sector_name output) (industry_j industry_name gross_output_q)

* dua penyebut:
*  (a) pangsa impor dari total input ANTARA industri j (= baris BPS 1900)
*  (b) pangsa impor dari TOTAL INPUT industri j (= output bruto, baris 2100;
*      penyebut ini juga memuat nilai tambah dan pajak-subsidi atas produk)
gen double imp_share_of_intermediates = interm_imported / interm_total ///
    if interm_total > 0
gen double imp_share_of_total_input   = interm_imported / gross_output_q

label var interm_imported            "Input antara impor industri j (= baris BPS 2000)"
label var interm_total               "Input antara total industri j (= baris BPS 1900)"
label var gross_output_q             "Output bruto = total input (baris BPS 2100)"
label var imp_share_of_intermediates "Impor / input antara total"
label var imp_share_of_total_input   "Impor / total input"

order industry_j industry_name interm_imported interm_total gross_output_q ///
      imp_share_of_intermediates imp_share_of_total_input
gsort -imp_share_of_total_input

export delimited using "$INTERIM/import_share.csv", replace
di as result _n "Selesai: $INTERIM/import_share.csv"
