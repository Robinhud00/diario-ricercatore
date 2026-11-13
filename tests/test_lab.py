import os, sys, tempfile, time, json, importlib.util
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load(tag):
    os.environ["HOME"] = tempfile.mkdtemp()
    spec = importlib.util.spec_from_file_location("dw_" + tag, os.path.join(here, "diario_web.py")); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.open_path = lambda p: opened.append(p); m.init_db(); return m
opened = []
drive = tempfile.mkdtemp()
# --- studente
st = load("stud")
c = st.load_cfg(); c["sync_dir"] = drive; c["owner_name"] = "Marco Rossi"; st.save_cfg(c)
con = st.db(); con.execute("INSERT INTO exp_groups(name) VALUES('NG012')"); gid = con.execute("SELECT max(id) FROM exp_groups").fetchone()[0]; con.commit(); con.close()
eid = st.api_new({})["id"]
st.api_save({"id": eid, "name": "Coupling FM13", "date": "12/11/2026", "project": "NG012", "obiettivo": "Alchilare", "procedura": "THF, 0 °C", "risultati": "", "note": "", "lang": ""})
con = st.db(); con.execute("UPDATE experiments SET group_id=? WHERE id=?", (gid, eid)); con.commit(); con.close()
st.sync_to_drive()
root = os.path.join(drive, st.DRIVE_SUBDIR)
S = json.load(open(os.path.join(root, "stato.json"), encoding="utf-8"))
assert S["owner"] == "Marco Rossi" and S["experiments"][0]["group"] == ["NG012"] and S["experiments"][0]["docx"].endswith(".docx"), S
assert os.path.isfile(os.path.join(root, "Documenti", *S["experiments"][0]["docx"].split("/")))
# --- supervisore (altro computer = altra HOME)
sup = load("sup")
try: sup.api_lab_add({"name": "Marco", "path": "/non/esiste"}); raise SystemExit("deve rifiutare")
except RuntimeError: pass
r = sup.api_lab_add({"name": "Marco", "path": drive}); assert r["found"], r          # accetta anche la cartella che contiene «Diario del Ricercatore»
g = sup.api_lab_get({}); m = g["members"][0]
assert m["ok"] and m["news"] == 1 and m["experiments"][0]["state"] == "new" and m["owner"] == "Marco Rossi", m
assert sup.lab_scan() == []                                                         # primo giro: nessuna notifica
d = sup.api_lab_exp({"member": m["id"], "exp": eid}); assert d["exp"]["sections"]["procedura"] == "THF, 0 °C"
assert sup.api_lab_get({})["members"][0]["news"] == 0
sup.api_lab_open({"member": m["id"], "exp": eid}); assert opened and opened[-1].endswith(".docx")
# lo studente modifica e aggiunge
time.sleep(1.1)
st.api_save({"id": eid, "name": "Coupling FM13", "date": "12/11/2026", "project": "NG012", "obiettivo": "Alchilare", "procedura": "THF, 0 °C, poi t.a.", "risultati": "Resa 71%", "note": "", "lang": ""})
e2 = st.api_new({})["id"]; st.sync_to_drive()
m = sup.api_lab_get({})["members"][0]; states = {e["id"]: e["state"] for e in m["experiments"]}
assert m["news"] == 2 and states[eid] == "changed" and states[e2] == "new", states
news = sup.lab_scan(); assert len(news) == 2 and {n[2] for n in news} == {True, False}, news
assert sup.lab_scan() == []
sup.api_lab_seen({"member": m["id"]}); assert sup.api_lab_get({})["members"][0]["news"] == 0
sup.api_lab_remove({"id": m["id"]}); assert sup.api_lab_get({})["members"] == []
print("TEST LABORATORIO OK")
