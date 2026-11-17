# Lo stesso Diario su due computer (ufficio e casa) che condividono la stessa cartella Google Drive.
import os, sys, tempfile, json, importlib.util, time, sqlite3, shutil
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load(tag, name, base):
    os.environ["HOME"] = tempfile.mkdtemp(prefix=tag + "-")
    spec = importlib.util.spec_from_file_location("dw_" + tag, os.path.join(here, "diario_web.py")); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.open_path = lambda p: None; m.init_db()
    c = m.load_cfg(); c["owner_name"] = name
    if base: c["sync_dir"] = base
    m.save_cfg(c); return m
def save(m, eid, **kw):
    r = m.db().execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
    d = {k: r[k] for k in ("name", "date", "project", "obiettivo", "procedura", "risultati", "note")}; d.update(kw); d["id"] = eid; d["lang"] = ""
    return m.api_save(d)
def snap(m):
    con = m.db(); out = {}
    for r in con.execute("SELECT * FROM experiments ORDER BY id"):
        g = con.execute("SELECT name FROM exp_groups WHERE id=?", (r["group_id"],)).fetchone() if r["group_id"] else None
        atts = sorted((a["filename"], open(a["path"], "rb").read()) for a in con.execute("SELECT * FROM attachments WHERE exp_id=?", (r["id"],)))
        dss = [(x["title"], x["payload"]) for x in con.execute("SELECT * FROM datasets WHERE exp_id=? ORDER BY id", (r["id"],))]
        tr = con.execute("SELECT procedura FROM translations WHERE exp_id=?", (r["id"],)).fetchone()
        out[r["id"]] = (r["uid"], r["name"], r["procedura"], g["name"] if g else None, atts, dss, tr["procedura"] if tr else None)
    con.close(); return out
def docs(m): return sorted(os.path.relpath(os.path.join(a, f), m.DOC_DIR) for a, _, fs in os.walk(m.DOC_DIR) for f in fs if f.endswith(".docx"))
def both(): A.sync_to_drive(); B.sync_to_drive(); A.sync_to_drive(); B.sync_to_drive()

drive = tempfile.mkdtemp(prefix="drive-")          # «Il mio Drive»: lo stesso account sui due computer
# ---- 1) ufficio: un diario con gruppi, allegati, tabelle, traduzione
A = load("ufficio", "Tiziano", drive)
con = A.db(); con.execute("INSERT INTO exp_groups(name,uid) VALUES('NG012','gA')"); g1 = con.execute("SELECT max(id) FROM exp_groups").fetchone()[0]
con.execute("INSERT INTO exp_groups(name,parent_id,uid) VALUES('Step 1',?,'gB')", (g1,)); g2 = con.execute("SELECT max(id) FROM exp_groups").fetchone()[0]; con.commit(); con.close()
e1 = A.api_new({"group_id": g2})["id"]; save(A, e1, name="Coupling FM13", procedura="THF, 0 °C")
A.add_attachment(e1, "spettro.png", b"\x89PNG-fake-1")
A.api_ds_save({"exp": e1, "title": "Resa", "kind": "table", "payload": {"rows": [[1, 2]]}})
con = A.db(); con.execute("INSERT INTO translations(exp_id,name,obiettivo,procedura,risultati,note,updated) VALUES(?,?,?,?,?,?,?)", (e1, "Coupling", "", "THF, 0 °C (EN)", "", "", A.now())); con.commit(); con.close()
e2 = A.api_new({})["id"]; save(A, e2, name="Debenzilazione", procedura="H2, Pd/C")
A.sync_to_drive()
assert os.listdir(drive) == ["Diario del Ricercatore - Tiziano"], os.listdir(drive)
# ---- 2) casa: un computer nuovo, con un esperimento di prova suo, si collega al Diario dell'ufficio
B = load("casa", "", None)
eb = B.api_new({})["id"]; save(B, eb, name="Prova di casa", procedura="niente")
r = B.api_link_diary({"path": drive}); print("collegato:", r)
assert os.listdir(drive) == ["Diario del Ricercatore - Tiziano"], "non deve creare una seconda cartella"
assert B.owner_name() == "Tiziano" and B.diary_id() == A.diary_id()
both()
sa, sb = snap(A), snap(B)
assert sa == sb, (sa, sb)
assert {v[1] for v in sa.values()} == {"Coupling FM13", "Debenzilazione", "Prova di casa"}
assert [v for v in sa.values() if v[1] == "Coupling FM13"][0][3:] == ("Step 1", [("spettro.png", b"\x89PNG-fake-1")], [("Resa", json.dumps({"rows": [[1, 2]]}))], "THF, 0 °C (EN)")
assert docs(A) == docs(B), (docs(A), docs(B))
print("numeri:", {k: v[1] for k, v in sa.items()})
# ---- 3) a casa modifico, aggiungo un allegato, creo un gruppo e un esperimento; in ufficio arriva tutto
idc = [k for k, v in snap(B).items() if v[1] == "Coupling FM13"][0]
save(B, idc, procedura="THF, 0 °C, poi t.a. 2 h")
B.add_attachment(idc, "tlc.png", b"TLC-casa")
gnew = B.api_group_new({"name": "Saggi"})["id"]
en = B.api_new({"group_id": gnew})["id"]; save(B, en, name="Saggio IC50")
both()
assert snap(A) == snap(B)
ca = [v for v in snap(A).values() if v[1] == "Coupling FM13"][0]
assert ca[2] == "THF, 0 °C, poi t.a. 2 h" and ("tlc.png", b"TLC-casa") in ca[4]
assert [v for v in snap(A).values() if v[1] == "Saggio IC50"][0][3] == "Saggi"
# ---- 4) i due computer creano un esperimento ciascuno senza essersi sincronizzati: stesso numero
xa = A.api_new({})["id"]; save(A, xa, name="Nuovo in ufficio")
xb = B.api_new({})["id"]; save(B, xb, name="Nuovo a casa")
assert xa == xb, "devono avere lo stesso numero per provare la collisione"
both(); both()
sa, sb = snap(A), snap(B)
assert sa == sb, (sa, sb)
names = [v[1] for v in sa.values()]
assert names.count("Nuovo in ufficio") == 1 and names.count("Nuovo a casa") == 1 and len(set(sa)) == len(sa)
assert docs(A) == docs(B)
# ---- 5) stesso esperimento modificato sui due computer prima di sincronizzarsi: nessuna perdita
k = [k for k, v in snap(A).items() if v[1] == "Debenzilazione"][0]
save(A, k, procedura="versione UFFICIO")
save(B, k, procedura="versione CASA")
both()
sa, sb = snap(A), snap(B)
assert sa == sb, ("\n".join(map(str, sorted(sa.items()))), "\n".join(map(str, sorted(sb.items()))))
procs = sorted(v[2] for v in sa.values() if v[1].startswith("Debenzilazione"))
assert procs == ["versione CASA", "versione UFFICIO"], procs
assert any("versione dall'altro computer" in v[1] for v in sa.values())
# ---- 6) cancello a casa -> sparisce anche in ufficio (il Word va in _Eliminati)
kk = [k for k, v in snap(B).items() if v[1] == "Prova di casa"][0]
B.api_delete({"id": kk}); both()
assert "Prova di casa" not in [v[1] for v in snap(A).values()] and snap(A) == snap(B)
# ---- 7) mentre in ufficio sto scrivendo arriva la versione di casa: tengo la mia e conservo l'altra come copia
k = [k for k, v in snap(A).items() if v[1] == "Saggio IC50"][0]
base = A.api_get({"id": k})["exp"]["updated"]
time.sleep(1.1)
save(B, k, risultati="IC50 da casa"); B.sync_to_drive(); A.sync_to_drive()       # arriva in ufficio
r = A.api_save({"id": k, "uid": A.api_get({"id": k})["exp"]["uid"], "base": base, "name": "Saggio IC50", "date": "", "project": "", "obiettivo": "", "procedura": "scritto in ufficio", "risultati": "", "note": "", "lang": ""})
assert r["conflict_copy"], r
both()
sa = snap(A); assert sa == snap(B)
assert sorted((v[2], v[1].endswith("(versione dall'altro computer)")) for v in sa.values() if v[1].startswith("Saggio IC50")) == [("", True), ("scritto in ufficio", False)], [v for v in sa.values() if v[1].startswith("Saggio")]
# ---- 8) messaggi dello studente scritti da due computer: tutti e due «miei»
root = A.drive_root()
A.api_msg_send({"exp": None, "text": "dall'ufficio"}); B.api_msg_send({"exp": None, "text": "da casa"})
assert sorted((m["text"], m["mine"]) for m in A.api_msg_thread({"exp": None})["messages"]) == [("da casa", True), ("dall'ufficio", True)]
# ---- 9) gli studenti seguiti (supervisore) sono gli stessi sui due computer, anche quando ne togli uno
sdrive = tempfile.mkdtemp(prefix="stud-")
S = load("studente", "Federico", sdrive); S.api_new({}); S.sync_to_drive()
link = os.path.join(drive, "Diario del Ricercatore - Federico")                  # la scorciatoia nel Drive del supervisore
os.symlink(S.drive_root(), link)
A.api_lab_add({"name": "Federico", "path": link}); both()
assert [m["name"] for m in B.api_lab_get({})["members"]] == ["Federico"] and B.api_lab_get({})["members"][0]["ok"]
mid = B.api_lab_get({})["members"][0]["id"]; B.api_lab_remove({"id": mid}); both()
assert A.api_lab_get({})["members"] == [] and B.api_lab_get({})["members"] == []
time.sleep(1.1); A.api_lab_add({"name": "Federico di nuovo", "path": link}); both()
assert [m["name"] for m in B.api_lab_get({})["members"]] == ["Federico di nuovo"]
assert os.listdir(S.drive_root()) and not any(f.startswith("Diario") for f in os.listdir(S.drive_root()))
# il Diario del supervisore non ha toccato la cartella dello studente
assert json.load(open(os.path.join(S.drive_root(), "stato.json"), encoding="utf-8"))["owner"] == "Federico"
# ---- 10) recupero: l'unico computer e' rotto, nella cartella c'e' solo la copia di sicurezza di una versione vecchia
old = tempfile.mkdtemp(prefix="vecchio-"); dfold = os.path.join(old, "Diario del Ricercatore - Sara"); os.makedirs(os.path.join(dfold, "Backup", "allegati", "7"))
db = sqlite3.connect(os.path.join(dfold, "Backup", "diario.db"))
db.executescript("CREATE TABLE experiments(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, date TEXT, project TEXT, obiettivo TEXT, procedura TEXT, risultati TEXT, note TEXT, updated TEXT, group_id INTEGER, lang TEXT);"
                 "CREATE TABLE attachments(id INTEGER PRIMARY KEY AUTOINCREMENT, exp_id INTEGER, filename TEXT, path TEXT);"
                 "INSERT INTO experiments(id,name,procedura,updated) VALUES(7,'Esperimento salvato','procedura vecchia','2026-10-01T10:00:00');"
                 "INSERT INTO attachments(exp_id,filename,path) VALUES(7,'nmr.png','C:\\Users\\sara\\DiarioRicercatore\\allegati\\7\\nmr.png');")
db.commit(); db.close()
open(os.path.join(dfold, "Backup", "allegati", "7", "nmr.png"), "wb").write(b"NMR")
json.dump({"install_id": "aaaa", "diary_id": "aaaa", "owner": "Sara"}, open(os.path.join(dfold, ".diario_proprietario.json"), "w"))
N = load("nuovo", "", None)
r = N.api_link_diary({"path": dfold}); assert r["restored"], r
sn = snap(N); assert [(v[1], v[2], v[4]) for v in sn.values()] == [("Esperimento salvato", "procedura vecchia", [("nmr.png", b"NMR")])], sn
assert os.path.isdir(os.path.join(dfold, "Dati", "esperimenti")) and len(os.listdir(os.path.join(dfold, "Dati", "esperimenti"))) == 1
print("TEST PIU' COMPUTER OK")
