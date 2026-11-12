import os, sys, tempfile, time, json
home = tempfile.mkdtemp(); os.environ["HOME"] = home
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.argv = [sys.argv[0], here]
import importlib.util
spec = importlib.util.spec_from_file_location("dw", os.path.join(here, "diario_web.py")); dw = importlib.util.module_from_spec(spec); spec.loader.exec_module(dw)
dw.init_db()
con = dw.db()
con.execute("INSERT INTO exp_groups(name,parent_id) VALUES('Tesi',NULL)"); g1 = con.execute("SELECT max(id) FROM exp_groups").fetchone()[0]
con.execute("INSERT INTO exp_groups(name,parent_id) VALUES('Sintesi NG012',?)", (g1,)); g2 = con.execute("SELECT max(id) FROM exp_groups").fetchone()[0]
con.commit(); con.close()
e = dw.api_new({}); eid = e.get("id") or e["exp"]["id"]
dw.api_save({"id": eid, "name": "Step 1", "date": "2026-11-03", "project": "P", "obiettivo": "a", "procedura": "b", "risultati": "c", "note": ""})
con = dw.db(); con.execute("UPDATE experiments SET group_id=? WHERE id=?", (g2, eid)); con.commit(); con.close()
# allegato
d = os.path.join(dw.ATT_DIR, str(eid)); os.makedirs(d, exist_ok=True)
p = os.path.join(d, "nota.txt"); open(p, "w").write("ciao")
con = dw.db(); con.execute("INSERT INTO attachments(exp_id,filename,path) VALUES(?,?,?)", (eid, "nota.txt", p)); con.commit(); con.close()
# vecchio Word piatto
os.makedirs(dw.EXPORT_DIR, exist_ok=True); old = os.path.join(dw.EXPORT_DIR, "Step 1 (n.%d).docx" % eid); open(old, "wb").write(b"x")
r = dw.api_docs_reorganize({}); print(r)
base = os.path.join(dw.DOC_DIR, "Tesi", "Sintesi NG012", "Step 1 (n.%d)" % eid)
assert os.path.exists(os.path.join(base, "Step 1 (n.%d).docx" % eid)), os.listdir(dw.DOC_DIR)
assert open(os.path.join(base, "Allegati", "nota.txt")).read() == "ciao"
assert not os.path.exists(old) and os.path.exists(os.path.join(dw.EXPORT_DIR, "_gia_riordinati", os.path.basename(old)))
# rinomina sottogruppo e sposta di gruppo -> la cartella si sposta
con = dw.db(); con.execute("UPDATE exp_groups SET name='Sintesi B' WHERE id=?", (g2,)); con.commit(); con.close()
dw.docs_sync_all()
nb = os.path.join(dw.DOC_DIR, "Tesi", "Sintesi B", "Step 1 (n.%d)" % eid)
assert os.path.exists(os.path.join(nb, "Step 1 (n.%d).docx" % eid)) and not os.path.exists(base)
assert not os.path.isdir(os.path.join(dw.DOC_DIR, "Tesi", "Sintesi NG012"))
# rinomina esperimento
dw.api_save({"id": eid, "name": "Step uno", "date": "2026-11-03", "project": "P", "obiettivo": "a", "procedura": "b", "risultati": "c", "note": ""})
dw.docs_sync_all()
nb2 = os.path.join(dw.DOC_DIR, "Tesi", "Sintesi B", "Step uno (n.%d)" % eid)
assert os.path.exists(os.path.join(nb2, "Step uno (n.%d).docx" % eid)), os.listdir(os.path.dirname(nb2))
assert len(os.listdir(nb2)) == 2
# senza gruppo
con = dw.db(); con.execute("UPDATE experiments SET group_id=NULL WHERE id=?", (eid,)); con.commit(); con.close()
dw.docs_sync_all()
assert os.path.exists(os.path.join(dw.DOC_DIR, "Senza gruppo", "Step uno (n.%d)" % eid))
# eliminazione -> _Eliminati
con = dw.db(); con.execute("DELETE FROM experiments WHERE id=?", (eid,)); con.commit(); con.close()
dw.docs_sync_all()
assert os.path.isdir(os.path.join(dw.DOC_DIR, "_Eliminati")) and not os.path.isdir(os.path.join(dw.DOC_DIR, "Senza gruppo"))
print("TEST DOCUMENTI AD ALBERO OK")
