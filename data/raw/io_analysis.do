*==============================================================================
* io_analysis.do
* Leontief analysis on BPS Indonesia IO tables (185 produk)
*   - io2016_total_matrix.dta    (Transaksi TOTAL, harga dasar, 2016)
*   - io2020_domestik_matrix.dta (Transaksi DOMESTIK, harga dasar, 2020)
*
* Produces, per table:
*   A matrix (technical coefficients), Leontief inverse L = inv(I-A),
*   output multipliers, backward/forward linkage indices (normalised),
*   saved to <table>_multipliers.dta
*
* NOTE ON CONCEPTS:
*   2020 domestik  -> Z contains DOMESTIC intermediates only. inv(I-Ad) gives
*                     domestic output multipliers (the standard policy object).
*   2016 total     -> Z includes IMPORTED intermediates. inv(I-A) overstates
*                     domestic impacts (assumes imports produced at home).
*                     Use for technology description, not domestic impact.
*==============================================================================
version 16
clear all
set more off

cd "`c(pwd)'"   // run from the folder containing the .dta files

local tables "io2016_total io2020_domestik io2020_total_hd io2020_total_hp"

foreach t of local tables {

    use "`t'_matrix.dta", clear
    quietly count
    local n = r(N)                      // 185
    assert `n' == 185

    *--- pull matrices into mata -------------------------------------------
    mkmat z1-z`n', matrix(Z)
    mkmat output, matrix(x)

    mata:
        Z = st_matrix("Z")
        x = st_matrix("x")
        n = rows(Z)

        // technical coefficients: A = Z * diag(1/x)  (guard zero-output)
        xinv = editvalue(1 :/ x', ., 0)
        A = Z :* xinv                    // broadcasts 1/x across columns

        // Leontief inverse
        L = luinv(I(n) - A)

        // output multipliers (column sums of L) = backward linkage (raw)
        m_backward = colsum(L)'          // n x 1

        // forward linkage via Ghosh: B = diag(1/x) * Z ; G = inv(I-B)
        B = editvalue(1 :/ x, ., 0) :* Z // broadcasts 1/x across rows
        G = luinv(I(n) - B)
        m_forward = rowsum(G)            // n x 1

        // Rasmussen normalised indices (mean = 1)
        bl_index = m_backward :/ mean(m_backward)
        fl_index = m_forward  :/ mean(m_forward)

        st_matrix("m_backward", m_backward)
        st_matrix("m_forward",  m_forward)
        st_matrix("bl_index",   bl_index)
        st_matrix("fl_index",   fl_index)
        st_matrix("L", L)
        st_matrix("A", A)
    end

    *--- attach results ------------------------------------------------------
    svmat double m_backward
    rename m_backward1 mult_output
    svmat double m_forward
    rename m_forward1 mult_forward
    svmat double bl_index
    rename bl_index1 backward_idx
    svmat double fl_index
    rename fl_index1 forward_idx

    label var mult_output  "Output multiplier (col sum Leontief inverse)"
    label var mult_forward "Forward multiplier (row sum Ghosh inverse)"
    label var backward_idx "Rasmussen backward linkage index (mean=1)"
    label var forward_idx  "Rasmussen forward linkage index (mean=1)"

    * key-sector classification
    gen byte key_sector = backward_idx > 1 & forward_idx > 1
    label var key_sector "Key sector (BL>1 & FL>1)"

    keep sector sector_name output mult_output mult_forward ///
         backward_idx forward_idx key_sector
    gsort -mult_output
    save "`t'_multipliers.dta", replace

    * export full Leontief inverse & A for downstream use (optional)
    preserve
        clear
        svmat double L, names(l)
        gen int sector = _n
        order sector
        save "`t'_leontief_inverse.dta", replace
    restore

    di as result _n "=== `t': top 10 output multipliers ==="
    list sector sector_name mult_output backward_idx forward_idx ///
        key_sector in 1/10, noobs sep(0)
}

*--- income & value-added multipliers (uses *_primary.dta) --------------------
foreach t of local tables {
    use "`t'_matrix.dta", clear
    mkmat z1-z185, matrix(Z)
    mkmat output, matrix(x)

    use "`t'_primary.dta", clear
    mkmat komp_tk,          matrix(w)     // labour compensation by sector
    mkmat tot_input_primer, matrix(va)    // gross value added by sector

    mata:
        Z = st_matrix("Z");  x = st_matrix("x")
        w = st_matrix("w");  va = st_matrix("va")
        n = rows(Z)
        A = Z :* editvalue(1 :/ x', ., 0)
        L = luinv(I(n) - A)
        wc  = editvalue(w  :/ x, ., 0)    // wage coefficient per unit output
        vac = editvalue(va :/ x, ., 0)    // VA coefficient per unit output
        m_income = (wc'  * L)'            // type-I income multiplier
        m_va     = (vac' * L)'            // type-I GDP multiplier
        st_matrix("m_income", m_income)
        st_matrix("m_va", m_va)
    end

    use "`t'_multipliers.dta", clear
    sort sector
    svmat double m_income
    rename m_income1 mult_income
    svmat double m_va
    rename m_va1 mult_va
    label var mult_income "Type-I income multiplier (wage per unit final demand)"
    label var mult_va     "Type-I GDP/VA multiplier (VA per unit final demand)"
    save "`t'_multipliers.dta", replace
}

di as result _n "Done. Outputs: *_multipliers.dta, *_leontief_inverse.dta"
