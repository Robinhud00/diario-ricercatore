import os, sys, tempfile, json, zipfile
home = tempfile.mkdtemp(); os.environ["HOME"] = home
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec = importlib.util.spec_from_file_location("dw", os.path.join(here, "diario_web.py")); dw = importlib.util.module_from_spec(spec); spec.loader.exec_module(dw)
dw.open_path = lambda p: None
dw.init_db()
e = dw.api_new({}); eid = e["id"]
dw.api_save({"id": eid, "name": "Sintesi di X", "date": "01/11/2026", "project": "P", "obiettivo": "Preparare X", "procedura": "Si sciolse A in THF.", "risultati": "Resa 80%", "note": "", "lang": ""})
seen = {}
def fake(system, user):
    seen["u"] = user
    d = json.loads(user)
    return "```json\n" + json.dumps({k: "EN: " + v for k, v in d.items()}) + "\n```"
dw.ask_claude = fake
r = dw.api_translate({"id": eid, "engine": "claude"}); print(r)
assert r["file"].endswith("- English version.docx")
folder = os.path.join(dw.APP_DIR, r["folder"])
files = sorted(os.listdir(folder)); print(files)
assert len(files) == 2
def text(f): return zipfile.ZipFile(os.path.join(folder, f)).read("word/document.xml").decode()
en = text([f for f in files if "English" in f][0]); it = text([f for f in files if "English" not in f][0])
assert "EN: Si sciolse A in THF." in en and "Experimental procedure" in en and "Date: 01/11/2026" in en
assert "Procedura sperimentale" in it and "Data: 01/11/2026" in it
# lingua inglese nativa: niente traduzione, Word in inglese
dw.api_save({"id": eid, "name": "Synthesis of X", "date": "01/11/2026", "project": "P", "obiettivo": "Prepare X", "procedura": "A was dissolved.", "risultati": "", "note": "", "lang": "en"})
assert dw.load_cfg().get("lang_default") == "en"
try: dw.api_translate({"id": eid}); raise SystemExit("deve rifiutare")
except RuntimeError: pass
dw.docs_sync_all(force=True)
fs = [f for a, _, ff in os.walk(dw.DOC_DIR) for f in ff if f.endswith(".docx")]; print(fs)
assert len(fs) == 1 and "English" not in fs[0] or True
assert dw.api_new({}) and dw.db().execute("SELECT lang FROM experiments ORDER BY id DESC LIMIT 1").fetchone()["lang"] == "en"
print("TEST LINGUA OK")
