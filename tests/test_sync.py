import os, sys, tempfile, json, sqlite3, threading, urllib.request, time
home = tempfile.mkdtemp(); os.environ["HOME"] = home
here = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.argv = [sys.argv[0], here]
sys.path.insert(0, here)
import importlib.util
spec = importlib.util.spec_from_file_location("dw", os.path.join(sys.argv[1], "diario_web.py")); dw = importlib.util.module_from_spec(spec); spec.loader.exec_module(dw)
dw.init_db()
# esperimento + allegato PNG finto
exp = dw.api_new({}); eid = exp.get("id") or exp.get("exp", {}).get("id")
dw.api_save({"id": eid, "name": "NG012 – step 3", "date": "2026-11-03", "project": "NG012", "obiettivo": "x", "procedura": "y", "risultati": "z", "note": ""})
# sincronizzazione senza cartella
try: dw.sync_to_drive(); raise SystemExit("deve fallire")
except RuntimeError as e: assert str(e) == "NODRIVE"
drive = os.path.join(home, "Library", "CloudStorage", "GoogleDrive-a@b.it", "Il mio Drive"); os.makedirs(drive)
assert dw.api_drive_find({})["found"] == [drive], dw.api_drive_find({})
for bad in ["/non/esiste", dw.APP_DIR]:
    try: dw.api_drive_set({"path": bad}); raise SystemExit("deve rifiutare " + bad)
    except RuntimeError: pass
assert dw.api_drive_set({"path": drive})["sync_dir"] == drive
# allegato
d = os.path.join(dw.ATT_DIR, str(eid)); os.makedirs(d, exist_ok=True)
png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")
p = os.path.join(d, "mol.png"); open(p, "wb").write(png)
con = dw.db(); con.execute("INSERT INTO attachments(exp_id,filename,path) VALUES(?,?,?)", (eid, "mol.png", p)); con.commit(); con.close()
r = dw.api_drive_sync({}); print(r)
root = os.path.join(drive, "Diario del Ricercatore")
dr = [os.path.join(a, f) for a, _, fs in os.walk(os.path.join(root, "Documenti")) for f in fs if f.endswith(".docx")]; assert len(dr) == 1, dr
assert os.path.exists(os.path.join(root, "Backup", "allegati", str(eid), "mol.png"))
bk = sqlite3.connect(os.path.join(root, "Backup", "diario.db")); assert bk.execute("SELECT count(*) FROM experiments").fetchone()[0] == 1; bk.close()
r2 = dw.api_drive_sync({}); assert r2["documenti"] == 0 and r2["allegati"] == 0, r2   # niente da rifare
# modifica -> nuovo Word
time.sleep(1.1); dw.api_save({"id": eid, "name": "NG012 – step 3", "date": "2026-11-03", "project": "NG012", "obiettivo": "x", "procedura": "cambiato", "risultati": "z", "note": ""})
r3 = dw.api_drive_sync({}); assert r3["documenti"] == 1, r3
# export copia su Drive
ex = dw.api_export({"id": eid}); assert ex["drive"] is True
st = dw.api_key_status({}); assert st["sync_dir"] == drive and st["sync_last"]
# rimozione
assert dw.api_drive_set({"path": ""})["sync_dir"] == ""
# jsme: URL e route statica
assert dw.jsme_url() == dw.JSME_CDN
os.makedirs(dw.JSME_DIR, exist_ok=True) if False else None
# server HTTP: pagina e blocco path traversal
from http.server import ThreadingHTTPServer
srv = ThreadingHTTPServer(("127.0.0.1", 0), dw.Handler); port = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()
html = urllib.request.urlopen("http://127.0.0.1:%d/" % port).read().decode()
assert 'JSME_URL = "https://jsme-editor.github.io' in html and "btnDraw" in html and "btnSync" in html
import urllib.error
for u in ["/jsme/../diario_web.py", "/jsme/nonesiste.js"]:
    try: urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, u)); raise SystemExit("deve dare errore " + u)
    except urllib.error.HTTPError as e: assert e.code in (403, 404)
srv.shutdown()
print("TUTTI I TEST DEL DIARIO LOCALE OK")
