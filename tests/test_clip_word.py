"""Prova: incolla dagli appunti (grabber simulato) e documento Word (giustificato, immagini, piè di pagina)."""
import os, sys, tempfile, zipfile, struct, zlib, importlib.util, re
home = tempfile.mkdtemp(); os.environ["HOME"] = home
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("dw", os.path.join(here, "diario_web.py")); dw = importlib.util.module_from_spec(spec); spec.loader.exec_module(dw)
dw.init_db()

def png(w, h, dpi=None):
    raw = b"".join(b"\x00" + b"\xff\x80\x00" * w for _ in range(h))
    def ch(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    out = b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    if dpi:
        p = int(dpi / 0.0254); out += ch(b"pHYs", struct.pack(">IIB", p, p, 1))
    return out + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")

# dpi nel PNG
d = dw.png_set_dpi(png(100, 50), 288); i = dw.img_info(d); assert i[:2] == (100, 50) and abs(i[2] - 288) < 1, i
d = dw.png_set_dpi(png(100, 50, 72), 288); assert abs(dw.img_info(d)[2] - 288) < 1
# dimensioni: 4x di 200x100pt a 288dpi = 800x400px -> 7.05cm; molecola minuscola viene ingrandita; schema enorme ridotto
cw, ch = dw.fit_cm(800, 400, 288); assert 7 < cw < 7.1, cw
cw, ch = dw.fit_cm(100, 60, 288); assert cw >= 2.9, cw
cw, ch = dw.fit_cm(6000, 3000, 300); assert cw <= 16.01 and ch <= 9.01, (cw, ch)

# incolla (Mac simulato)
con = dw.db(); con.execute("INSERT INTO experiments(name) VALUES('Prova')") if False else None; con.close()
r = dw.api_new({}) if hasattr(dw, "api_new") else None
exp_id = (r or {}).get("id") or 1
dw.read_system_clipboard = lambda tmp: {"png": png(800, 400), "cdx": b"VjCD0100", "dpi": 288, "types": ["com.adobe.pdf"], "how": "pdf"}
res = dw.api_clip_paste({"exp": exp_id}); assert len(res["saved"]) == 2 and res["saved"][0].endswith(".png") and res["saved"][1].endswith(".cdx"), res
dw.read_system_clipboard = lambda tmp: {"png": None, "cdx": None, "dpi": 0, "types": ["public.utf8-plain-text"], "how": ""}
try: dw.api_clip_paste({"exp": exp_id}); raise SystemExit("doveva fallire")
except RuntimeError as e: assert "public.utf8-plain-text" in str(e)

# Word
atts = []
con = dw.db()
for row in con.execute("SELECT filename,path FROM attachments WHERE exp_id=?", (exp_id,)).fetchall(): atts.append({"filename": row["filename"], "path": row["path"]})
extra = os.path.join(home, "schema.png"); open(extra, "wb").write(png(1200, 500, 96)); atts.append({"filename": "schema.png", "path": extra})
exp = {"name": "Sintesi di prova", "date": "2026-11-06", "project": "NG012",
       "obiettivo": "Testo lungo " * 40, "procedura": "Si scioglie il reagente.\n\n- prima voce\n- seconda voce\n1) uno\n2. due\nFine.", "risultati": "", "note": ""}
data = dw.make_docx(exp, atts)
out = os.environ.get("OUT_DOCX") or os.path.join(home, "t.docx"); open(out, "wb").write(data)
z = zipfile.ZipFile(out); doc = z.read("word/document.xml").decode()
assert 'w:jc w:val="both"' in doc and "Figura 1" in doc and "Figura 2. schema" in doc and "footerReference" in doc
assert "word/footer1.xml" in z.namelist() and 'ListLine' in doc
print("OK", out)
