import os, sys, tempfile, zipfile, json
home = tempfile.mkdtemp(); os.environ["HOME"] = home
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec = importlib.util.spec_from_file_location("dw", os.path.join(here, "diario_web.py")); dw = importlib.util.module_from_spec(spec); spec.loader.exec_module(dw)
dw.open_path = lambda p: None
dw.init_db()
con = dw.db()
con.execute("INSERT INTO exp_groups(name) VALUES('NG012')"); g1 = con.execute("SELECT max(id) FROM exp_groups").fetchone()[0]
con.execute("INSERT INTO exp_groups(name,parent_id) VALUES('Step 1',?)", (g1,)); g2 = con.execute("SELECT max(id) FROM exp_groups").fetchone()[0]
con.commit(); con.close()
png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")
ids = []
for i, (nm, dt, g) in enumerate([("Secondo", "05/11/2026", g2), ("Primo", "01/11/2026", g1), ("Altro progetto", "02/11/2026", None)]):
    eid = dw.api_new({})["id"]; ids.append(eid)
    dw.api_save({"id": eid, "name": nm, "date": dt, "project": "NG012" if g else "Altro", "obiettivo": "ob " + nm, "procedura": "- passo A\n- passo B", "risultati": "res " + nm, "note": "", "lang": ""})
    c = dw.db(); c.execute("UPDATE experiments SET group_id=? WHERE id=?", (g, eid)); c.commit(); c.close()
    d = os.path.join(dw.ATT_DIR, str(eid)); os.makedirs(d, exist_ok=True); p = os.path.join(d, "mol.png"); open(p, "wb").write(png)
    c = dw.db(); c.execute("INSERT INTO attachments(exp_id,filename,path) VALUES(?,?,?)", (eid, "mol.png", p)); c.commit(); c.close()
r = dw.api_merge({"group_id": g1}); print(r)
assert r["n"] == 2
path = os.path.join(dw.APP_DIR, r["folder"], r["file"])
x = zipfile.ZipFile(path).read("word/document.xml").decode()
assert x.index("Primo") < x.index("Secondo") and "Altro progetto" not in x and "Step 1" in x and "2 esperimenti" in x
assert x.count("pageBreakBefore") == 0 and x.count("ExpTitle") == 2
dw.api_merge({"project": "Altro"})
r2 = dw.api_merge({"group_id": g1, "english": True}); assert len(r2["senza_traduzione"]) == 2
dw.docs_sync_all()  # il riepilogo non viene toccato
assert os.path.exists(path)
import shutil; shutil.copy(path, os.path.join(os.environ.get("OUT", "/tmp"), "merge_test.docx"))
print("TEST UNIONE OK")
