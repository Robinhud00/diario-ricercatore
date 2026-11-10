"""Prova: settori, tabelle di dati nel database e nel Word."""
import os, sys, tempfile, zipfile, importlib.util
home = tempfile.mkdtemp(); os.environ["HOME"] = home
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("dw", os.path.join(here, "diario_web.py")); dw = importlib.util.module_from_spec(spec); spec.loader.exec_module(dw)
dw.init_db()
exp = dw.api_new({})["id"]
# settori
assert dw.api_key_status({})["sectors"] is None
assert dw.api_sector_set({"sectors": ["farmaco", "inesistente", "biologia"]})["sectors"] == ["farmaco", "biologia"]
assert dw.api_key_status({})["sectors"] == ["farmaco", "biologia"] and "chimica" in dw.api_key_status({})["sector_names"]
# dati
pl = {"text": "1\t2", "summary": "IC50 = 1 uM\nR2 = 0.99", "table": [["x", "y"], ["1", "2"], ["3", "4"]]}
i = dw.api_ds_save({"exp": exp, "title": "Prova", "kind": "dr", "payload": pl})["id"]
assert dw.api_ds_list({"exp": exp})["datasets"][0]["payload"]["summary"].startswith("IC50")
dw.api_ds_save({"id": i, "exp": exp, "title": "Prova 2", "kind": "xy", "payload": pl})
assert dw.api_ds_list({"exp": exp})["datasets"][0]["title"] == "Prova 2"
try: dw.api_ds_save({"exp": exp, "payload": "no"}); raise SystemExit("doveva fallire")
except RuntimeError: pass
# Word
con = dw.db(); ds = dw.ds_for(con, exp); con.close()
data = dw.make_docx({"name": "T", "risultati": "ok"}, [], ds)
p = os.path.join(home, "d.docx"); open(p, "wb").write(data)
doc = zipfile.ZipFile(p).read("word/document.xml").decode()
assert "Dati e grafici" in doc and "<w:tbl>" in doc and "IC50 = 1 uM" in doc and "Prova 2" in doc
dw.api_ds_delete({"id": i}); assert dw.api_ds_list({"exp": exp})["datasets"] == []
# sezioni, Word e AI per settore
for sec in dw.SECTORS:
    dw.api_sector_set({"sectors": [sec]})
    assert dw.primary_sector() == sec and len(dw.sec_titles()) == 4 and dw.api_key_status({})["sections"]["procedura"][0]
    assert dw.SECTOR_AI[sec][0] in dw.base_rules()
dw.api_sector_set({"sectors": ["biologia", "chimica"]})
assert dw.sec_titles()[1][1] == "Materiali e metodi"
data = dw.make_docx({"name": "T", "procedura": "x"}, [], [])
open(os.path.join(home, "b.docx"), "wb").write(data)
assert "Materiali e metodi" in zipfile.ZipFile(os.path.join(home, "b.docx")).read("word/document.xml").decode()
dw.api_sector_set({"sectors": []}); assert dw.primary_sector() == "chimica"
print("TEST DATI OK")
