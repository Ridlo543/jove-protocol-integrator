# Riset Teknis Format JoVE & PubMed Central (PMC JATS XML)

Dokumen ini merangkum hasil verifikasi langsung dari sumber resmi **JoVE** dan **PubMed Central (NCBI/NLM)** pada `2026-11-23`.

---

## 1. Sumber Resmi yang Diverifikasi
1. **JoVE Standard Manuscript Template & Instructions for Authors:**
   - URL: `https://www.jove.com/files/Instructions_for_Authors.pdf`
2. **Contoh Artikel JoVE Terbit (dengan Persamaan Matematika & Protokol Bertingkat):**
   - URL: `https://www.jove.com/t/60874/calibration-vector-network-analyzer-for-measurements-radio-frequency`
3. **PubMed Central (PMC) Tagging Guidelines — Introduction & General Tagging Practice:**
   - URL: `https://pmc.ncbi.nlm.nih.gov/tagging-guidelines/article/style/`
   - URL: `https://pmc.ncbi.nlm.nih.gov/tagging-guidelines/article/genprac/`
4. **PMC Validation Tools & Style Checker:**
   - URL: `https://pmc.ncbi.nlm.nih.gov/pub/validation/`
   - URL: `https://pmc.ncbi.nlm.nih.gov/tools/stylechecker/` (web-based)
   - URL: `https://pmc.ncbi.nlm.nih.gov/pub/stylechecker-info/` (XSL stylesheets lokal)

---

## 2. Format Input Naskah JoVE (MS Word `.doc` / `.docx`)

Berdasarkan `Instructions_for_Authors.pdf`, naskah yang masuk dari penulis wajib berbentuk file Word yang dapat diedit (`.doc` atau `.docx`) dengan urutan bagian baku:

1. `TITLE` (maks 150 karakter, hindari singkatan)
2. `AUTHORS AND AFFILIATIONS` (afiliasi lengkap tanpa singkatan, email institusi, tanda `*` untuk equal contribution/footnote)
3. `SUMMARY` (10–50 kata)
4. `ABSTRACT` (150–300 kata)
5. `INTRODUCTION` (150–1.500 kata, min 2 paragraf)
6. `PROTOCOL` (1–10 halaman):
   - Dibagi menjadi bagian bernomor: `1. ...`, `2. ...`
   - Langkah bernomor bertingkat: `1.1`, `1.2`, sub-langkah `1.1.1`, dst. (nested ordered lists di HTML/XML)
   - Blok khusus: `NOTE:` dan `CAUTION:` (untuk bahan kimia berbahaya/toksik)
   - Aturan penulisan: satuan SI (`L`, `mL`, `µL`, `cm`, `kg`, `h`, `min`, `s`), spasi antara angka dan satuan (`50 mg`, `37 °C`), gaya sentrifugal dalam `x g` (bukan rpm), nama spesies dimiringkan setelah penyebutan pertama (*C. elegans*), tanpa simbol `™/®/©` di teks utama.
7. `REPRESENTATIVE RESULTS`
8. `FIGURES AND TABLES` (dikirim sebagai file terpisah, bukan tertanam di Word; penanda posisi di teks memakai `[Place Figure 1 here]`; gambar `.ai`, `.eps`, `.psd`, `.svg`, `.pdf`, atau `.tiff`/`.jpg` min 1440x480 px / 300 dpi; tabel dalam `.xls`/`.xlsx` tanpa pewarnaan)
9. `FIGURE AND TABLE LEGENDS` (judul singkat + deskripsi panel A, B, C)
10. `TABLE OF MATERIALS` (file terpisah, diurutkan alfabetis, tidak diberi nomor tabel)
11. `SUPPLEMENTARY FILES` (termasuk skrip/kode)
12. `DISCUSSION` (3–6 paragraf)
13. `ACKNOWLEDGMENTS` & `DISCLOSURES`
14. `REFERENCES` (min 10 referensi; format JoVE: `Last name, Initials. Title. Journal. Vol (Issue), pages (Year).`)

### Observasi dari Artikel Live JoVE (`jove.com/t/60874`)
- **Subscript/Superscript & Simbol:** Banyak notasi seperti $S_{11}$, $S_{21}$, `0 μsec`, `377 Ω`, `10 dB ± 0.5 dB`, `0.5 Ω`.
- **Persamaan Matematika:** Pada halaman web JoVE `60874`, persamaan display dirender sebagai gambar (`60874equ01.jpg`) dengan `alt` text deskriptif, sementara di teks menggunakan simbol Unicode/HTML entities.
- **Gambar:** Memiliki versi thumbnail/inline (`60874fig01.jpg`) dan versi resolusi besar (`60874fig01large.jpg`).

---

## 3. Format Output PubMed Central (NISO JATS / NLM XML)

PubMed Central menerima XML yang valid terhadap **NISO JATS Journal Publishing DTD** (v1.0, v1.1, v1.2, atau **v1.3**: `https://jats.nlm.nih.gov/publishing/1.3/JATS-journalpublishing1-3.dtd`) atau **NLM Journal Publishing DTD** (v2.3 / v3.0), dan **wajib lolos PMC Style Checker**.

### Aturan Teknis Kunci dari PMC Tagging Guidelines (`genprac`)

1. **Encoding & Karakter Khusus (Huruf Yunani, Simbol Sains):**
   - Gunakan **UTF-8** (atau ASCII dengan Unicode hex character entity seperti `&#x2203;` untuk `∃`, `&#x00B0;` untuk derajat `°`).
   - **Larangan aksesibilitas (JATS4R):** Jangan salah pakai karakter yang mirip secara visual (contoh: wajib `°` `&#x00B0;`, dilarang memakai modifier small O `&#x1D52;` atau masculine ordinal `&#x00BA;`).
   - Dilarang memakai `<private-char>` atau kode Unicode Private Use Area (`U+E000`–`U+F8FF`).

2. **Matematika (`<disp-formula>` dan `<inline-formula>`):**
   - Tag display formula dan inline formula (yang tidak bisa diwakili teks biasa + Unicode) dengan **MathML 2.0 / 3.0** (`<mml:math id="...">`).
   - Setiap `<disp-formula>` / `<inline-formula>` hanya boleh berisi **satu** representasi (plain markup, `<mml:math>`, atau `<graphic>`).
   - **Aturan LaTeX (`<tex-math>`):** Dilarang menaruh `<tex-math>` sendirian; `<tex-math>` **hanya boleh dipakai di dalam `<alternatives>`** bersama representasi MathML atau `<graphic>`.

3. **Tautan Internal & Eksternal:**
   - Tautan ke objek di dalam artikel (gambar, tabel, rumus, referensi) wajib memakai `<xref ref-type="fig|table|disp-formula|bibr" rid="...">`.
   - Tautan eksternal wajib memakai `<ext-link ext-link-type="uri" xlink:href="...">`.

4. **Pemformatan Teks (`<bold>`, `<italic>`, `<sc>`, `<sub>`, `<sup>`):**
   - Hanya dipakai untuk menandai bagian tertentu di dalam elemen (misal nama spesies `<italic>C. elegans</italic>` atau subscript `S<sub>11</sub>`).
   - Dilarang membungkus seluruh isi `<title>` atau `<label>` dengan `<bold>`.

5. **Elemen Kosong & Bahasa:**
   - Dilarang memakai elemen kosong untuk spasi/formatting.
   - Bahasa default adalah Inggris (`en`); bagian non-Inggris wajib diberi `@xml:lang` sesuai IETF RFC 5646.

---

## 4. Contoh Kerangka Minimal JATS 1.3 XML (Referensi Belajar / Uji Style Checker)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Publishing DTD v1.3 20210610//EN"
  "https://jats.nlm.nih.gov/publishing/1.3/JATS-journalpublishing1-3.dtd">
<article article-type="methods-article" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:mml="http://www.w3.org/1998/Math/MathML">
  <front>
    <journal-meta>
      <journal-id journal-id-type="nlm-ta">J Vis Exp</journal-id>
      <journal-title-group>
        <journal-title>Journal of Visualized Experiments</journal-title>
      </journal-title-group>
      <issn pub-type="epub">1940-087X</issn>
    </journal-meta>
    <article-meta>
      <article-id pub-id-type="doi">10.3791/00000</article-id>
      <title-group>
        <article-title>Sample Protocol Title</article-title>
      </title-group>
      <contrib-group>
        <contrib contrib-type="author">
          <name><surname>Doe</surname><given-names>Jane</given-names></name>
          <xref ref-type="aff" rid="aff1">1</xref>
        </contrib>
        <aff id="aff1"><label>1</label>Department of Engineering, Example University</aff>
      </contrib-group>
      <pub-date pub-type="epub"><day>23</day><month>11</month><year>2026</year></pub-date>
      <abstract><p>Sample abstract text.</p></abstract>
    </article-meta>
  </front>
  <body>
    <sec id="sec1">
      <title>Protocol</title>
      <list list-type="order">
        <list-item>
          <p>Set temperature to 37 &#x00B0;C and measure S<sub>11</sub> at 1.8 GHz (<xref ref-type="fig" rid="fig1">Figure 1</xref>).</p>
        </list-item>
      </list>
    </sec>
  </body>
</article>
```

*(Catatan: Sebelum dipakai sebagai sampel portofolio, file XML lengkap wajib diuji langsung di `https://pmc.ncbi.nlm.nih.gov/tools/stylechecker/` untuk memastikan 0 error DTD dan 0 error PMC Style Checker.)*
