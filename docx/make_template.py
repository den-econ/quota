"""Build the DEN Naskah Kebijakan Word template.

Generates naskah-kebijakan-template.docx in this folder, replicating the
house style of the den-paper Quarto extension (den.cls, brief layout) on
A4 paper. The DEN logo is rendered from _extensions/den-paper/den-logo.pdf.

Usage:
    python make_template.py
"""

from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Mm, Pt, RGBColor

HERE = Path(__file__).resolve().parent
LOGO_PDF = HERE.parent / "_extensions" / "den-paper" / "den-logo.pdf"
LOGO_PNG = HERE / "den-logo.png"
OUT_DOCX = HERE / "naskah-kebijakan-template.docx"

DEN_BLUE = RGBColor(0x21, 0x33, 0x54)   # structure color: rgb(0.13, 0.2, 0.33)
ABSTRACT_FILL = "DEE0E5"                # DEN blue at 15% tint
SERIF = "Times New Roman"               # ~ TeX Gyre Termes
SANS = "Arial"                          # ~ TeX Gyre Heros


def render_logo() -> None:
    import fitz

    doc = fitz.open(LOGO_PDF)
    page = doc[0]
    zoom = 600 / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True)
    pix.save(LOGO_PNG)
    doc.close()


def set_font(style, name=SERIF, size=None, bold=None, italic=None, color=None):
    style.font.name = name
    if size is not None:
        style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    if italic is not None:
        style.font.italic = italic
    if color is not None:
        style.font.color.rgb = color


def strip_theme_overrides(style):
    """Remove theme font/color attributes that supersede explicit values."""
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is not None:
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme",
                     "w:eastAsiaTheme"):
            rFonts.attrib.pop(qn(attr), None)
    color = rPr.find(qn("w:color"))
    if color is not None:
        for attr in ("w:themeColor", "w:themeShade", "w:themeTint"):
            color.attrib.pop(qn(attr), None)


def shade_style(style, fill):
    pPr = style.element.get_or_add_pPr()
    pPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:val="clear" w:fill="{fill}"/>'))


def add_field(paragraph, instr, size=None, bold=False):
    """Append a Word field (e.g. PAGE, SEQ Gambar) as a run."""
    run = paragraph.add_run()
    if size is not None:
        run.font.size = Pt(size)
    run.font.bold = bold
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = f" {instr} "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr_el)
    run._r.append(end)
    return run


def setup_page(doc):
    sec = doc.sections[0]
    sec.page_width = Mm(210)
    sec.page_height = Mm(297)
    sec.top_margin = Cm(2.3)
    sec.bottom_margin = Cm(1.6)
    sec.left_margin = Cm(1.7)
    sec.right_margin = Cm(1.7)
    sec.header_distance = Cm(1.2)
    sec.different_first_page_header_footer = True
    doc.settings.odd_and_even_pages_header_footer = True
    return sec


def setup_headers(sec):
    # First page: no header (the masthead lives in the body).
    sec.first_page_header.paragraphs[0].text = ""

    odd = sec.header.paragraphs[0]
    odd.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = odd.add_run("Naskah Kebijakan")
    run.font.name = SERIF
    run.font.size = Pt(8)
    run.font.italic = True
    odd.add_run("      ").font.size = Pt(8)
    add_field(odd, "PAGE", size=10)

    even = sec.even_page_header.paragraphs[0]
    even.alignment = WD_ALIGN_PARAGRAPH.LEFT
    add_field(even, "PAGE", size=10)
    even.add_run("      ").font.size = Pt(8)
    run = even.add_run("Penulis Pertama et al.")
    run.font.name = SERIF
    run.font.size = Pt(8)


def setup_styles(doc):
    styles = doc.styles

    normal = styles["Normal"]
    set_font(normal, SERIF, 10)
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.0

    # Headings: serif bold in DEN blue, as in den.cls (\large\bfseries etc.)
    for name, size, bold in [("Heading 1", 12, True),
                             ("Heading 2", 10, True),
                             ("Heading 3", 10, False)]:
        h = styles[name]
        set_font(h, SERIF, size, bold=bold, color=DEN_BLUE)
        strip_theme_overrides(h)
        h.paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
        h.paragraph_format.space_after = Pt(6)
        h.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT

    def para_style(name, base="Normal"):
        s = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        s.base_style = styles[base]
        s.quick_style = True
        return s

    title = para_style("DEN Title")
    set_font(title, SANS, 14, bold=True, color=DEN_BLUE)
    title.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    title.paragraph_format.space_before = Pt(10)
    title.paragraph_format.space_after = Pt(10)

    author = para_style("DEN Author")
    set_font(author, SERIF, 10)
    author.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    author.paragraph_format.space_after = Pt(4)

    affil = para_style("DEN Affiliation")
    set_font(affil, SERIF, 8)
    affil.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    affil.paragraph_format.space_after = Pt(1)

    email = para_style("DEN Corresponding")
    set_font(email, SERIF, 8)
    email.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    email.paragraph_format.space_before = Pt(3)
    email.paragraph_format.space_after = Pt(10)

    abs_title = para_style("DEN Abstract Title")
    set_font(abs_title, SANS, 10, bold=True)
    shade_style(abs_title, ABSTRACT_FILL)
    abs_title.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    abs_title.paragraph_format.space_before = Pt(10)
    abs_title.paragraph_format.space_after = Pt(0)
    abs_title.paragraph_format.left_indent = Cm(0.3)
    abs_title.paragraph_format.right_indent = Cm(0.3)

    abstract = para_style("DEN Abstract")
    set_font(abstract, SERIF, 9)
    shade_style(abstract, ABSTRACT_FILL)
    abstract.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    abstract.paragraph_format.space_before = Pt(0)
    abstract.paragraph_format.space_after = Pt(0)
    abstract.paragraph_format.left_indent = Cm(0.3)
    abstract.paragraph_format.right_indent = Cm(0.3)

    keywords = para_style("DEN Keywords")
    set_font(keywords, SERIF, 8)
    keywords.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    keywords.paragraph_format.space_before = Pt(6)
    keywords.paragraph_format.space_after = Pt(2)

    unnumbered = para_style("DEN Heading Unnumbered")
    set_font(unnumbered, SERIF, 12, bold=True, color=DEN_BLUE)
    unnumbered.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    unnumbered.paragraph_format.space_before = Pt(14)
    unnumbered.paragraph_format.space_after = Pt(6)
    unnumbered.paragraph_format.keep_with_next = True

    caption = para_style("DEN Caption")
    set_font(caption, SANS, 8)
    caption.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    caption.paragraph_format.space_before = Pt(6)
    caption.paragraph_format.space_after = Pt(4)
    caption.paragraph_format.keep_with_next = True

    source = para_style("DEN Source")
    set_font(source, SERIF, 7, italic=True)
    source.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    source.paragraph_format.space_before = Pt(2)
    source.paragraph_format.space_after = Pt(10)

    # Hyperlinks in DEN blue, underlined.
    try:
        link = styles["Hyperlink"]
    except KeyError:
        link = styles.add_style("Hyperlink", WD_STYLE_TYPE.CHARACTER)
    link.font.color.rgb = DEN_BLUE
    link.font.underline = True


def setup_heading_numbering(doc):
    """Multilevel numbering 1. / 1.1 / 1.1.1 linked to Heading 1-3 styles."""
    NUM_ID = 100
    lvls = []
    for ilvl, (style_id, fmt) in enumerate([("Heading1", "%1."),
                                            ("Heading2", "%1.%2"),
                                            ("Heading3", "%1.%2.%3")]):
        lvls.append(
            f'<w:lvl w:ilvl="{ilvl}">'
            f'<w:start w:val="1"/>'
            f'<w:numFmt w:val="decimal"/>'
            f'<w:pStyle w:val="{style_id}"/>'
            f'<w:lvlText w:val="{fmt}"/>'
            f'<w:suff w:val="space"/>'
            f'<w:lvlJc w:val="left"/>'
            f'<w:pPr><w:ind w:left="0" w:firstLine="0"/></w:pPr>'
            f"</w:lvl>"
        )
    abstract_num = parse_xml(
        f'<w:abstractNum {nsdecls("w")} w:abstractNumId="{NUM_ID}">'
        f'<w:multiLevelType w:val="multilevel"/>'
        + "".join(lvls)
        + "</w:abstractNum>"
    )
    num = parse_xml(
        f'<w:num {nsdecls("w")} w:numId="{NUM_ID}">'
        f'<w:abstractNumId w:val="{NUM_ID}"/></w:num>'
    )

    numbering = doc.part.numbering_part.element
    existing_nums = numbering.findall(qn("w:num"))
    if existing_nums:
        existing_nums[0].addprevious(abstract_num)
    else:
        numbering.append(abstract_num)
    numbering.append(num)

    for ilvl, name in enumerate(["Heading 1", "Heading 2", "Heading 3"]):
        pPr = doc.styles[name].element.get_or_add_pPr()
        numPr = parse_xml(
            f'<w:numPr {nsdecls("w")}>'
            f'<w:ilvl w:val="{ilvl}"/><w:numId w:val="{NUM_ID}"/></w:numPr>'
        )
        pPr.append(numPr)


def no_table_borders(table):
    tblPr = table._tbl.tblPr
    tblPr.append(parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        + "".join(f'<w:{edge} w:val="none" w:sz="0" w:space="0"/>'
                  for edge in ("top", "left", "bottom", "right",
                               "insideH", "insideV"))
        + "</w:tblBorders>"
    ))


def booktabs_borders(table):
    """Horizontal rules only: heavy top/bottom, light rule under header row."""
    no_table_borders(table)
    def set_border(row, edge, sz):
        for cell in row.cells:
            tcPr = cell._tc.get_or_add_tcPr()
            borders = tcPr.find(qn("w:tcBorders"))
            if borders is None:
                borders = parse_xml(f"<w:tcBorders {nsdecls('w')}/>")
                tcPr.append(borders)
            borders.append(parse_xml(
                f'<w:{edge} {nsdecls("w")} w:val="single" w:sz="{sz}" '
                f'w:space="0" w:color="000000"/>'
            ))
    set_border(table.rows[0], "top", 12)
    set_border(table.rows[0], "bottom", 6)
    set_border(table.rows[-1], "bottom", 12)


def add_masthead(doc):
    table = doc.add_table(rows=1, cols=2)
    no_table_borders(table)
    table.autofit = False
    left, right = table.rows[0].cells
    left.width = Cm(13.6)
    right.width = Cm(4.0)
    left.vertical_alignment = WD_ALIGN_VERTICAL.BOTTOM
    right.vertical_alignment = WD_ALIGN_VERTICAL.BOTTOM

    p = left.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run("Naskah Kebijakan")
    run.font.size = Pt(8)
    run.font.italic = True
    run = p.add_run(" No. ")
    run.font.size = Pt(8)
    run = p.add_run("1")
    run.font.size = Pt(8)
    run.font.bold = True
    p2 = left.add_paragraph()
    p2.paragraph_format.space_after = Pt(0)
    p2.add_run("20 Mei 2026").font.size = Pt(8)

    pr = right.paragraphs[0]
    pr.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pr.paragraph_format.space_after = Pt(0)
    pr.add_run().add_picture(str(LOGO_PNG), width=Mm(20))


def add_title_block(doc):
    doc.add_paragraph("Judul Naskah Kebijakan dalam Title Case, Maksimal "
                      "12 Kata", style="DEN Title")

    p = doc.add_paragraph(style="DEN Author")
    def author(name, marker, last=False):
        p.add_run(name)
        r = p.add_run(marker)
        r.font.superscript = True
        if not last:
            p.add_run(", ")
    author("Penulis Pertama", "1,*")
    author("Penulis Kedua", "2")
    p.add_run("dan ")
    author("Penulis Ketiga", "3", last=True)

    for i, inst in enumerate(["Institusi 1, Kota, Negara",
                              "Institusi 2, Kota, Negara",
                              "Institusi 3, Kota, Negara"], start=1):
        pa = doc.add_paragraph(style="DEN Affiliation")
        r = pa.add_run(str(i))
        r.font.superscript = True
        pa.add_run(inst)

    pe = doc.add_paragraph(style="DEN Corresponding")
    pe.add_run("*Corresponding author: penulis.pertama@email.domain")


def add_abstract_block(doc):
    doc.add_paragraph("Abstract", style="DEN Abstract Title")
    doc.add_paragraph(
        "Abstrak merangkum keseluruhan naskah dalam satu paragraf "
        "(maksimal 300 kata): 1) tujuan studi dan masalah kebijakan yang "
        "dianalisis; 2) pendekatan atau metode yang digunakan; 3) temuan "
        "utama; dan 4) implikasi kebijakan yang direkomendasikan. Ganti "
        "teks ini dengan abstrak Anda tanpa mengubah gaya paragraf "
        "(DEN Abstract).",
        style="DEN Abstract",
    )
    kw = doc.add_paragraph(style="DEN Keywords")
    kw.add_run("Keywords: ").bold = True
    kw.add_run("kata kunci satu; kata kunci dua; kata kunci tiga (maksimal lima)")
    jel = doc.add_paragraph(style="DEN Keywords")
    jel.add_run("JEL Classification: ").bold = True
    jel.add_run("C22, O47")


def add_figure_example(doc):
    ph = doc.add_paragraph()
    ph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = ph.add_run("[Tempatkan gambar di sini: Insert → Pictures. "
                   "Ekspor gambar dari Python dengan fig-den agar sesuai "
                   "gaya DEN.]")
    r.font.size = Pt(9)
    r.font.italic = True

    cap = doc.add_paragraph(style="DEN Caption")
    cap.add_run("Gambar ").bold = True
    add_field(cap, r"SEQ Gambar \* ARABIC", size=8, bold=True)
    cap.add_run(". ").bold = True
    cap.add_run("Judul gambar yang menjelaskan apa yang ditampilkan, "
                "termasuk variabel pada sumbu x dan y.")

    src = doc.add_paragraph(style="DEN Source")
    src.add_run("Sumber: kalkulasi penulis berdasarkan data BPS (2026).")


def add_table_example(doc):
    cap = doc.add_paragraph(style="DEN Caption")
    cap.add_run("Tabel ").bold = True
    add_field(cap, r"SEQ Tabel \* ARABIC", size=8, bold=True)
    cap.add_run(". ").bold = True
    cap.add_run("Judul tabel beserta satuan dan cakupan datanya.")

    data = [
        ("Parameter", "Notasi", "Keterangan"),
        ("Elastisitas substitusi", "σ", "Parameter terkalibrasi"),
        ("Diskon waktu", "β", "0,99 (kuartalan)"),
        ("Pangsa modal", "α", "0,33"),
    ]
    table = doc.add_table(rows=len(data), cols=3)
    booktabs_borders(table)
    for i, row in enumerate(data):
        for j, text in enumerate(row):
            p = table.rows[i].cells[j].paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(text)
            r.font.size = Pt(9)
            if i == 0:
                r.font.bold = True

    src = doc.add_paragraph(style="DEN Source")
    src.add_run("Sumber: penulis.")


def add_body(doc):
    doc.add_paragraph("Pendahuluan", style="Heading 1")
    doc.add_paragraph(
        "Tulis latar belakang masalah kebijakan, urgensinya, dan tujuan "
        "naskah ini. Gunakan gaya paragraf Normal untuk seluruh isi teks. "
        "Sitasi dikelola dengan Zotero atau Mendeley (lihat catatan di "
        "bagian akhir templat)."
    )

    doc.add_paragraph("Metode", style="Heading 2")
    doc.add_paragraph(
        "Jelaskan pendekatan analisis secara ringkas. Persamaan dapat "
        "disisipkan melalui Insert → Equation; definisikan setiap "
        "variabel dan parameter saat pertama kali muncul."
    )

    doc.add_paragraph("Hasil dan Pembahasan", style="Heading 1")
    doc.add_paragraph(
        "Setiap gambar dan tabel dirujuk di teks sebelum dibahas: jelaskan "
        "apa yang ditampilkan, apa sumbu x dan y, serta sumber datanya. "
        "Nomor Gambar/Tabel menggunakan field SEQ; setelah menambah atau "
        "menghapus, pilih seluruh dokumen (Ctrl+A) lalu tekan F9 untuk "
        "memperbarui nomor."
    )
    add_figure_example(doc)
    add_table_example(doc)

    doc.add_paragraph("Subbagian Contoh", style="Heading 2")
    doc.add_paragraph("Contoh sub-subbagian di bawah ini menggunakan gaya "
                      "Heading 3.")
    doc.add_paragraph("Sub-subbagian Contoh", style="Heading 3")
    doc.add_paragraph("Isi sub-subbagian.")

    doc.add_paragraph("Kesimpulan dan Rekomendasi Kebijakan",
                      style="Heading 1")
    doc.add_paragraph("Rumuskan kesimpulan dan rekomendasi kebijakan yang "
                      "dapat ditindaklanjuti.")

    doc.add_paragraph("Pernyataan Reproduksibilitas",
                      style="DEN Heading Unnumbered")
    doc.add_paragraph(
        "Bagian wajib. Cantumkan tautan repositori GitHub yang memuat: "
        "1) kode sumber analisis; 2) kode untuk mereproduksi seluruh "
        "gambar; 3) kode/data untuk mereproduksi tabel."
    )

    doc.add_paragraph("Pernyataan Pendanaan", style="DEN Heading Unnumbered")
    doc.add_paragraph("Cantumkan sumber pendanaan riset bila ada.")

    doc.add_paragraph("Referensi", style="DEN Heading Unnumbered")
    doc.add_paragraph(
        "Kelola sitasi dan daftar pustaka dengan Zotero atau Mendeley "
        "menggunakan gaya CSL yang sama dengan templat PDF (berkas "
        "csl.csl di repositori templat). Daftar pustaka disisipkan di sini."
    )


def main():
    render_logo()
    doc = Document()
    setup_page(doc)
    setup_styles(doc)
    setup_heading_numbering(doc)
    setup_headers(doc.sections[0])

    add_masthead(doc)
    add_title_block(doc)
    add_abstract_block(doc)
    add_body(doc)

    doc.save(OUT_DOCX)
    print(f"Wrote {OUT_DOCX}")


if __name__ == "__main__":
    main()
