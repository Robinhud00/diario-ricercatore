"""Prova delle parti dipendenti dal sistema operativo, simulando Windows (non serve Windows)."""
import os, sys, tempfile, types, importlib.util
home = tempfile.mkdtemp(); os.environ["HOME"] = home
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("dw", os.path.join(here, "diario_web.py")); dw = importlib.util.module_from_spec(spec); spec.loader.exec_module(dw)
calls = []
# --- apertura file / cartella su Windows
dw.IS_WIN, dw.IS_MAC = True, False
os.startfile = lambda p: calls.append(("startfile", p))
class P:  # finto Popen
    def __init__(self, cmd, *a, **k): calls.append(("popen", cmd))
dw.subprocess.Popen = P
dw.open_path("C:\\Users\\x\\a.docx"); dw.reveal_path("C:\\Users\\x\\a.docx")
assert calls[0] == ("startfile", "C:\\Users\\x\\a.docx"), calls
assert calls[1][1][0] == "explorer" and calls[1][1][1].startswith("/select,"), calls
# --- Mac e Linux
calls.clear(); dw.IS_WIN, dw.IS_MAC = False, True
dw.open_path("/x/a"); dw.reveal_path("/x/a")
assert calls == [("popen", ["open", "/x/a"]), ("popen", ["open", "-R", "/x/a"])], calls
calls.clear(); dw.IS_MAC = False
dw.open_path("/x/a"); assert calls == [("popen", ["xdg-open", "/x/a"])], calls
# --- ChemDraw su Windows: cerca ChemDraw.exe sotto Program Files
pf = os.path.join(home, "Program Files"); exe = os.path.join(pf, "PerkinElmerInformatics", "ChemOffice2020", "ChemDraw", "ChemDraw.exe")
os.makedirs(os.path.dirname(exe)); open(exe, "w").close()
exe2 = os.path.join(pf, "Revvity", "ChemOffice+ 23.1", "ChemDraw", "ChemDraw.exe"); os.makedirs(os.path.dirname(exe2)); open(exe2, "w").close()
os.utime(exe, (1, 1)); os.environ["ProgramFiles"] = pf; os.environ["ProgramFiles(x86)"] = os.path.join(home, "nonesiste"); os.environ["LOCALAPPDATA"] = os.path.join(home, "nonesiste2")
dw.IS_WIN = True
f = dw.find_chemdraw(); assert f == exe2, f      # sceglie l'installazione piu' recente
# --- curl: il percorso del file JSON deve usare / (i \ nel file di configurazione di curl sono escape)
seen = {}
def fake_run(cmd, input=None, **k):
    seen["input"] = input; seen["k"] = k
    return types.SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")
dw.subprocess.run = fake_run
orig = dw.tempfile.NamedTemporaryFile
class TF:
    def __init__(self, *a, **k): self.name = "C:\\Users\\x\\AppData\\Local\\Temp\\tmp1.json"; self._f = open(os.path.join(home, "t.json"), "w")
    def __enter__(self): return self
    def __exit__(self, *a): self._f.close()
    def write(self, t): self._f.write(t)
dw.tempfile.NamedTemporaryFile = TF
out = dw.curl_json("https://example.com/x", {"x-api-key": "k"}, body={"a": 1})
assert out == {"ok": True}
assert 'data-binary = "@C:/Users/x/AppData/Local/Temp/tmp1.json"' in seen["input"], seen["input"]
assert seen["k"].get("encoding") == "utf-8"
# --- Drive su Windows: usa la cartella impostata a mano con percorso di tipo Windows (qui simulato)
d = os.path.join(home, "G", "My Drive"); os.makedirs(d)
assert dw.check_sync_dir(d) == d
print("TUTTI I TEST WINDOWS OK")
