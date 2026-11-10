#!/usr/bin/env python3
"""
Diario del Ricercatore - versione browser (nessuna libreria da installare)
- Esperimenti con nome, data, progetto e sezioni di testo
- Allegati ChemDraw (.cdx, .cdxml, .cd) e qualsiasi altro file
- Assistente AI (Claude) per stilare / correggere / tradurre il testo
Dati in ~/DiarioRicercatore (stesso archivio della versione con finestra nativa).
Il server ascolta solo su 127.0.0.1 (il tuo computer), non e' raggiungibile da altri.
"""
import os
import sys
import json
import shutil
import sqlite3
import secrets
import tempfile
import threading
import subprocess
import datetime
import webbrowser
import re
import io
import struct
import zipfile
import urllib.parse
import mimetypes
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"

# Su Windows il terminale puo' non supportare le emoji: non deve mai bloccare l'avvio
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

APP_DIR = os.path.expanduser("~/DiarioRicercatore")
ATT_DIR = os.path.join(APP_DIR, "allegati")
DB_PATH = os.path.join(APP_DIR, "diario.db")
CFG_PATH = os.path.join(APP_DIR, "config.json")
MODEL = "claude-sonnet-5-5"
TOKEN = secrets.token_urlsafe(24)

os.makedirs(ATT_DIR, exist_ok=True)

# ---------------- AI ----------------
BASE_RULES = (
    "Sei un assistente per chimici di laboratorio che scrivono il quaderno di laboratorio. "
    "Non inventare MAI dati: conserva esattamente quantita', unita', rese, temperature, tempi, "
    "nomi di reagenti/solventi, numeri di composto e sigle (es. NG012, FM03). "
    "Se manca un'informazione importante, segnalala tra parentesi quadre come [da completare: ...]. "
    "Rispondi SOLO con il testo risultante, senza commenti, senza virgolette, senza markdown."
)
MODES = {
    "stila": (
        "Riscrivi il testo come sezione sperimentale professionale in stile articolo scientifico "
        "(ACS): forma impersonale/passato, frasi chiare, ordine cronologico, quantita' con unita' "
        "e mmol/equivalenti se presenti nel testo, work-up e purificazione ben distinti. "
        "Mantieni la lingua del testo originale."
    ),
    "correggi": (
        "Correggi solo ortografia, grammatica e punteggiatura, senza cambiare lo stile ne' il "
        "contenuto. Mantieni la lingua del testo originale."
    ),
    "inglese": "Traduci in inglese scientifico, stile sezione sperimentale (past tense, impersonal).",
    "titolo": (
        "Proponi UN titolo breve e descrittivo (max 10 parole) per questo esperimento, "
        "nella lingua del testo. Solo il titolo."
    ),
}


def load_cfg():
    try:
        with open(CFG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    with open(CFG_PATH, "w") as f:
        json.dump(cfg, f)
    os.chmod(CFG_PATH, 0o600)


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_gemini_model_cache = {}


def get_api_key():
    return (os.environ.get("ANTHROPIC_API_KEY") or load_cfg().get("api_key", "")).strip()


def get_gemini_key():
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            or load_cfg().get("gemini_key", "")).strip()


def check_key_chars(key):
    if any(c in key for c in '"\\\n\r \t'):
        raise RuntimeError("La chiave API contiene caratteri non validi (spazi o a capo): reinseriscila.")


def curl_json(url, headers, body=None, timeout=150, who="il servizio AI"):
    """Chiamata HTTP con curl (gia' presente su macOS e su Windows 10/11, usa i certificati di sistema).
    La chiave e i dati non finiscono mai nella riga di comando."""
    for v in [url] + list(headers.values()):
        if any(c in v for c in '"\\\n\r'):
            raise RuntimeError("Valore non valido nella richiesta (caratteri speciali nella chiave?).")
    tmp = None
    try:
        lines = ['url = "%s"' % url] + ['header = "%s: %s"' % kv for kv in headers.items()]
        lines += ["silent", "show-error", "max-time = %d" % timeout]
        if body is not None:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
                tf.write(json.dumps(body))
                tmp = tf.name
            lines.append('data-binary = "@%s"' % tmp.replace("\\", "/"))
        p = subprocess.run(["curl", "-K", "-"], input="\n".join(lines), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout + 20)
    except FileNotFoundError:
        raise RuntimeError("curl non trovato sul sistema (su Windows serve Windows 10 o 11 aggiornato).")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Timeout: %s non ha risposto in tempo." % who)
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    if p.returncode != 0:
        raise RuntimeError("Connessione a %s fallita: %s" % (who, p.stderr.strip() or "errore di rete"))
    try:
        return json.loads(p.stdout)
    except Exception:
        raise RuntimeError("Risposta non valida da %s: %s" % (who, p.stdout[:200]))


def ask_claude(system, user):
    key = get_api_key()
    if not key:
        raise RuntimeError("NOKEY:claude")
    check_key_chars(key)
    out = curl_json(
        ANTHROPIC_URL,
        {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        {"model": MODEL, "max_tokens": 3000, "system": system,
         "messages": [{"role": "user", "content": user}]},
        who="Claude")
    if out.get("type") == "error":
        raise RuntimeError("Errore API Claude: " + (out.get("error") or {}).get("message", "errore API"))
    text = "".join(b.get("text", "") for b in out.get("content", []) if isinstance(b, dict)).strip()
    if not text:
        raise RuntimeError("Claude ha restituito una risposta vuota.")
    return text


def gemini_pick_model(names):
    """Sceglie il modello Gemini di testo piu' adatto fra quelli disponibili per la chiave:
    preferisce i modelli stabili, poi la famiglia 'flash' (veloce, di solito inclusa nel piano gratuito),
    poi la versione piu' recente."""
    best, best_key = None, None
    for n in names:
        m = re.match(r"^models/(gemini-(\d+(?:\.\d+)*)-(flash-lite|flash|pro)(?:-(.+))?)$", n)
        if not m:
            continue
        full, ver, kind, rest = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        if re.search(r"image|tts|live|audio|embed|vision|computer|robot|native|customtools|thinking|learnlm", rest):
            continue
        stable = 0 if re.search(r"preview|exp", rest) else 1
        key = (stable, {"flash": 3, "flash-lite": 2, "pro": 1}[kind],
               tuple(int(x) for x in ver.split(".")), -len(rest))
        if best_key is None or key > best_key:
            best, best_key = full, key
    return best


def gemini_error(out, key):
    err = out.get("error") or {}
    msg = s(err.get("message")) or "errore sconosciuto"
    code, status = err.get("code"), s(err.get("status"))
    blob = json.dumps(err)
    if (code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED")
            or "ACCESS_TOKEN_TYPE_UNSUPPORTED" in blob or "API key not valid" in msg):
        hint = "Google ha rifiutato la chiave. "
        if key.startswith("AQ."):
            hint += ("Le chiavi che iniziano con «AQ.» (il nuovo formato di AI Studio) non sono ancora accettate "
                     "da tutte le connessioni. Prova a creare una chiave classica (inizia con «AIza») da Google Cloud "
                     "Console → API e servizi → Credenziali → Crea credenziali → Chiave API, con l'API "
                     "«Generative Language» abilitata; oppure usa Claude. ")
        else:
            hint += "Controlla di averla copiata per intero e che l'API Gemini sia abilitata per il progetto. "
        return RuntimeError(hint + "(Dettaglio Google: " + msg + ")")
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return RuntimeError("Gemini: limite di richieste o quota esaurita. Riprova fra poco. (" + msg + ")")
    return RuntimeError("Errore Gemini: " + msg)


def gemini_model(key):
    fixed = s(load_cfg().get("gemini_model")).strip()
    if fixed:
        return fixed
    if _gemini_model_cache.get("m"):
        return _gemini_model_cache["m"]
    out = curl_json(GEMINI_BASE + "/models?pageSize=200", {"x-goog-api-key": key}, who="Gemini")
    if out.get("error"):
        raise gemini_error(out, key)
    names = [m.get("name", "") for m in out.get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    pick = gemini_pick_model(names)
    if not pick:
        raise RuntimeError("Nessun modello Gemini di testo disponibile per questa chiave. "
                           "Puoi scrivere a mano il nome del modello in «Chiavi API e impostazioni».")
    _gemini_model_cache["m"] = pick
    return pick


def ask_gemini(system, user):
    key = get_gemini_key()
    if not key:
        raise RuntimeError("NOKEY:gemini")
    check_key_chars(key)
    model = gemini_model(key)
    out = curl_json(
        "%s/models/%s:generateContent" % (GEMINI_BASE, model),
        {"x-goog-api-key": key, "content-type": "application/json"},
        {"systemInstruction": {"parts": [{"text": system}]},
         "contents": [{"role": "user", "parts": [{"text": user}]}],
         "generationConfig": {"temperature": 0.3}},
        who="Gemini")
    if out.get("error"):
        if (out["error"].get("code") == 404 or out["error"].get("status") == "NOT_FOUND"):
            _gemini_model_cache.clear()   # il modello scelto automaticamente non esiste piu': si riscegliera'
        raise gemini_error(out, key)
    blocked = (out.get("promptFeedback") or {}).get("blockReason")
    if blocked:
        raise RuntimeError("Gemini ha bloccato la richiesta (%s). Riprova con un testo diverso o usa Claude." % blocked)
    cands = out.get("candidates") or []
    parts = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought")).strip()
    if not text:
        fr = cands[0].get("finishReason") if cands else ""
        raise RuntimeError("Gemini ha restituito una risposta vuota" + (" (%s)" % fr if fr else "") + ".")
    return text


# ---------------- DB ----------------
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS experiments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, date TEXT, project TEXT,
            obiettivo TEXT DEFAULT '', procedura TEXT DEFAULT '',
            risultati TEXT DEFAULT '', note TEXT DEFAULT '',
            updated TEXT
        );
        CREATE TABLE IF NOT EXISTS attachments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exp_id INTEGER, filename TEXT, path TEXT
        );
        CREATE TABLE IF NOT EXISTS datasets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exp_id INTEGER, title TEXT, kind TEXT, payload TEXT, updated TEXT
        );
        CREATE TABLE IF NOT EXISTS exp_groups(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, parent_id INTEGER, color TEXT,
            collapsed INTEGER DEFAULT 0, archived INTEGER DEFAULT 0
        );
        """
    )
    # migrazione: i database creati dalle versioni precedenti non hanno la colonna group_id
    cols = [r["name"] for r in con.execute("PRAGMA table_info(experiments)")]
    if "group_id" not in cols:
        con.execute("ALTER TABLE experiments ADD COLUMN group_id INTEGER")
    con.commit()
    con.close()


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def s(v):
    return "" if v is None else str(v)


# ---------------- API ----------------
def api_list(d):
    q = "%" + s(d.get("q")).strip() + "%"
    con = db()
    rows = con.execute(
        "SELECT id,name,date,project FROM experiments "
        "WHERE name LIKE ? OR project LIKE ? OR obiettivo LIKE ? OR procedura LIKE ? "
        "ORDER BY updated DESC, id DESC",
        (q, q, q, q),
    ).fetchall()
    con.close()
    return {"items": [dict(r) for r in rows]}


def api_get(d):
    con = db()
    row = con.execute("SELECT * FROM experiments WHERE id=?", (int(d["id"]),)).fetchone()
    if not row:
        con.close()
        raise RuntimeError("Esperimento non trovato.")
    atts = con.execute("SELECT id,filename FROM attachments WHERE exp_id=? ORDER BY id", (row["id"],)).fetchall()
    con.close()
    return {"exp": dict(row), "attachments": [dict(a) for a in atts]}


def api_new(d):
    con = db()
    gid = d.get("group_id")
    if gid is not None:
        gid = int(gid)
        if not con.execute("SELECT 1 FROM exp_groups WHERE id=?", (gid,)).fetchone():
            gid = None
        else:
            con.execute("UPDATE exp_groups SET collapsed=0 WHERE id=?", (gid,))
    cur = con.execute(
        "INSERT INTO experiments(name,date,project,updated,group_id) VALUES(?,?,?,?,?)",
        ("Nuovo esperimento", datetime.date.today().strftime("%d/%m/%Y"), "", now(), gid),
    )
    con.commit()
    new_id = cur.lastrowid
    con.close()
    return {"id": new_id}


def api_save(d):
    con = db()
    con.execute(
        "UPDATE experiments SET name=?,date=?,project=?,obiettivo=?,procedura=?,risultati=?,note=?,updated=? WHERE id=?",
        (s(d.get("name")).strip(), s(d.get("date")).strip(), s(d.get("project")).strip(),
         s(d.get("obiettivo")), s(d.get("procedura")), s(d.get("risultati")), s(d.get("note")),
         now(), int(d["id"])),
    )
    con.commit()
    con.close()
    return {}


def api_delete(d):
    exp_id = int(d["id"])
    con = db()
    con.execute("DELETE FROM attachments WHERE exp_id=?", (exp_id,))
    con.execute("DELETE FROM experiments WHERE id=?", (exp_id,))
    con.commit()
    nxt = con.execute("SELECT id FROM experiments ORDER BY updated DESC, id DESC LIMIT 1").fetchone()
    con.close()
    shutil.rmtree(os.path.join(ATT_DIR, str(exp_id)), ignore_errors=True)
    return {"next": nxt["id"] if nxt else None}


PALETTE = ["#EC4899", "#EA580C", "#B45309", "#059669", "#2563EB", "#0D9488", "#DC2626", "#64748B"]


def api_tree(d):
    q = s(d.get("q")).strip()
    con = db()
    groups = [dict(r) for r in con.execute(
        "SELECT id,name,parent_id,color,collapsed,archived FROM exp_groups ORDER BY id")]
    cols = "id,name,date,project,group_id"
    if q:
        like = "%" + q + "%"
        rows = con.execute(
            "SELECT " + cols + " FROM experiments WHERE name LIKE ? OR project LIKE ? OR obiettivo LIKE ? "
            "OR procedura LIKE ? OR risultati LIKE ? OR note LIKE ? ORDER BY id DESC", (like,) * 6).fetchall()
    else:
        rows = con.execute("SELECT " + cols + " FROM experiments ORDER BY id DESC").fetchall()
    con.close()
    return {"groups": groups, "exps": [dict(r) for r in rows]}


def group_descendants(con, gid):
    out, stack = set(), [gid]
    while stack:
        cur = stack.pop()
        for r in con.execute("SELECT id FROM exp_groups WHERE parent_id=?", (cur,)):
            if r["id"] not in out:
                out.add(r["id"])
                stack.append(r["id"])
    return out


def group_exists(con, gid):
    return con.execute("SELECT 1 FROM exp_groups WHERE id=?", (gid,)).fetchone() is not None


def api_group_new(d):
    name = s(d.get("name")).strip()[:80] or "Nuovo gruppo"
    parent = d.get("parent_id")
    con = db()
    if parent is not None:
        parent = int(parent)
        if not group_exists(con, parent):
            con.close()
            raise RuntimeError("Gruppo superiore non trovato.")
        con.execute("UPDATE exp_groups SET collapsed=0 WHERE id=?", (parent,))
    n = con.execute("SELECT COUNT(*) AS c FROM exp_groups").fetchone()["c"]
    cur = con.execute("INSERT INTO exp_groups(name,parent_id,color,collapsed,archived) VALUES(?,?,?,0,0)",
                      (name, parent, PALETTE[n % len(PALETTE)]))
    con.commit()
    new_id = cur.lastrowid
    con.close()
    return {"id": new_id}


def api_group_update(d):
    gid = int(d["id"])
    sets, vals = [], []
    if "name" in d:
        name = s(d["name"]).strip()
        if not name:
            raise RuntimeError("Il nome del gruppo non puo' essere vuoto.")
        sets.append("name=?")
        vals.append(name[:80])
    if "color" in d:
        c = s(d["color"])
        if not re.match(r"^#[0-9A-Fa-f]{6}$", c):
            raise RuntimeError("Colore non valido.")
        sets.append("color=?")
        vals.append(c)
    if "collapsed" in d:
        sets.append("collapsed=?")
        vals.append(1 if d["collapsed"] else 0)
    if "archived" in d:
        sets.append("archived=?")
        vals.append(1 if d["archived"] else 0)
    if not sets:
        return {}
    con = db()
    con.execute("UPDATE exp_groups SET " + ",".join(sets) + " WHERE id=?", vals + [gid])
    con.commit()
    con.close()
    return {}


def api_group_move(d):
    gid = int(d["id"])
    parent = d.get("parent_id")
    con = db()
    if parent is not None:
        parent = int(parent)
        if not group_exists(con, parent):
            con.close()
            raise RuntimeError("Gruppo di destinazione non trovato.")
        if parent == gid or parent in group_descendants(con, gid):
            con.close()
            raise RuntimeError("Non puoi spostare un gruppo dentro se stesso o in un suo sottogruppo.")
    con.execute("UPDATE exp_groups SET parent_id=? WHERE id=?", (parent, gid))
    con.commit()
    con.close()
    return {}


def api_group_delete(d):
    """Elimina solo il contenitore: sottogruppi ed esperimenti passano al gruppo superiore."""
    gid = int(d["id"])
    con = db()
    row = con.execute("SELECT parent_id FROM exp_groups WHERE id=?", (gid,)).fetchone()
    if row:
        parent = row["parent_id"]
        con.execute("UPDATE exp_groups SET parent_id=? WHERE parent_id=?", (parent, gid))
        con.execute("UPDATE experiments SET group_id=? WHERE group_id=?", (parent, gid))
        con.execute("DELETE FROM exp_groups WHERE id=?", (gid,))
        con.commit()
    con.close()
    return {}


def api_exp_move(d):
    gid = d.get("group_id")
    con = db()
    if gid is not None:
        gid = int(gid)
        if not group_exists(con, gid):
            con.close()
            raise RuntimeError("Gruppo non trovato.")
    con.execute("UPDATE experiments SET group_id=? WHERE id=?", (gid, int(d["id"])))
    con.commit()
    con.close()
    return {}


def att_path(att_id):
    con = db()
    row = con.execute("SELECT path FROM attachments WHERE id=?", (int(att_id),)).fetchone()
    con.close()
    if not row:
        raise RuntimeError("Allegato non trovato.")
    real = os.path.realpath(row["path"])
    if not real.startswith(os.path.realpath(ATT_DIR) + os.sep):
        raise RuntimeError("Percorso non valido.")
    if not os.path.exists(real):
        raise RuntimeError("Il file non esiste piu' sul disco.")
    return real


def open_path(path):
    """Apre un file o un'app con il programma predefinito (macOS, Windows, Linux)."""
    if IS_WIN:
        os.startfile(path)
    elif IS_MAC:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def reveal_path(path):
    """Mostra il file nella sua cartella (Finder / Esplora risorse)."""
    if IS_WIN:
        subprocess.Popen(["explorer", "/select," + os.path.normpath(path)])
    elif IS_MAC:
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


# ---------------- Appunti (ChemDraw -> Diario) ----------------
JXA_CLIP = r"""
ObjC.import('AppKit');
ObjC.import('Foundation');
function run(argv) {
  var dir = argv[0];
  var pb = $.NSPasteboard.generalPasteboard;
  var types = ObjC.deepUnwrap(pb.types) || [];
  var out = {types: types, png: null, cdx: null, dpi: 0, how: ""};
  function save(data, name) {
    var path = dir + "/" + name;
    data.writeToFileAtomically(path, true);
    return path;
  }
  function has(t) { return types.indexOf(t) >= 0; }
  // 1) l'originale ChemDraw (formato CDX), se presente
  for (var i = 0; i < types.length; i++) {
    var low = String(types[i]).toLowerCase();
    if (low.indexOf("cdx") >= 0 || (low.indexOf("chemdraw") >= 0 && low.indexOf("interchange") >= 0)) {
      var dd = pb.dataForType(types[i]);
      if (dd && dd.length > 0) { out.cdx = save(dd, "clip.cdx"); break; }
    }
  }
  // 2) immagine: PDF vettoriale (nitido) > PNG > TIFF
  var pdf = has("com.adobe.pdf") ? pb.dataForType("com.adobe.pdf") : null;
  if (pdf && pdf.length > 0) {
    try {
      var img = $.NSImage.alloc.initWithData(pdf);
      var sz = img.size;
      var k = 4;
      var w = Math.max(1, Math.ceil(sz.width * k)), h = Math.max(1, Math.ceil(sz.height * k));
      var rep = $.NSBitmapImageRep.alloc.initWithBitmapDataPlanesPixelsWidePixelsHighBitsPerSampleSamplesPerPixelHasAlphaIsPlanarColorSpaceNameBytesPerRowBitsPerPixel(
        null, w, h, 8, 4, true, false, $.NSDeviceRGBColorSpace, 0, 0);
      $.NSGraphicsContext.saveGraphicsState;
      $.NSGraphicsContext.setCurrentContext($.NSGraphicsContext.graphicsContextWithBitmapImageRep(rep));
      $.NSColor.whiteColor.set;
      $.NSRectFill($.NSMakeRect(0, 0, w, h));
      img.drawInRectFromRectOperationFraction($.NSMakeRect(0, 0, w, h), $.NSZeroRect, 2, 1.0);
      $.NSGraphicsContext.restoreGraphicsState;
      var png = rep.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $());
      out.png = save(png, "clip.png");
      out.dpi = 72 * k;
      out.how = "pdf";
    } catch (e) { out.how = "pdf-fallito: " + e; out.png = null; }
  }
  if (!out.png && has("public.png")) {
    var d = pb.dataForType("public.png");
    if (d && d.length > 0) { out.png = save(d, "clip.png"); out.how = "png"; }
  }
  if (!out.png && has("public.tiff")) {
    var d2 = pb.dataForType("public.tiff");
    if (d2 && d2.length > 0) {
      var rep2 = $.NSBitmapImageRep.imageRepWithData(d2);
      var p2 = rep2.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $());
      out.png = save(p2, "clip.png"); out.how = "tiff";
    }
  }
  return JSON.stringify(out);
}
"""

PS_CLIP = (
    "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
    "$i=[System.Windows.Forms.Clipboard]::GetImage(); "
    "if($i){$i.Save($args[0],[System.Drawing.Imaging.ImageFormat]::Png); Write-Output 'ok'}"
)


def png_set_dpi(data, dpi):
    """Scrive (o sostituisce) la risoluzione di un PNG, cosi' il Word lo dimensiona bene."""
    import zlib
    if data[:8] != b"\x89PNG\r\n\x1a\n" or not dpi:
        return data
    ppm = int(round(dpi / 0.0254))
    chunk = struct.pack(">IIB", ppm, ppm, 1)
    crc = zlib.crc32(b"pHYs" + chunk) & 0xffffffff
    new = struct.pack(">I", 9) + b"pHYs" + chunk + struct.pack(">I", crc)
    out, pos, done = [data[:8]], 8, False
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        end = pos + 12 + length
        if ctype == b"pHYs":
            if not done:
                out.append(new)
                done = True
        else:
            if ctype == b"IDAT" and not done:
                out.append(new)
                done = True
            out.append(data[pos:end])
        pos = end
    return b"".join(out)


def read_system_clipboard(tmpdir):
    """Legge l'immagine dagli appunti del sistema. Ritorna dict(png=bytes|None, cdx=bytes|None, dpi, types, how)."""
    res = {"png": None, "cdx": None, "dpi": 0, "types": [], "how": ""}
    if IS_MAC:
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", JXA_CLIP, tmpdir],
                           capture_output=True, text=True, timeout=40)
        if r.returncode != 0:
            raise RuntimeError("Non riesco a leggere gli appunti: " + (r.stderr or "").strip()[:300])
        info = json.loads((r.stdout or "").strip().splitlines()[-1])
        res["types"], res["dpi"], res["how"] = info.get("types") or [], info.get("dpi") or 0, info.get("how") or ""
        for key in ("png", "cdx"):
            if info.get(key) and os.path.exists(info[key]):
                with open(info[key], "rb") as f:
                    res[key] = f.read()
    elif IS_WIN:
        out = os.path.join(tmpdir, "clip.png")
        r = subprocess.run(["powershell", "-STA", "-NoProfile", "-Command", PS_CLIP, out],
                           capture_output=True, text=True, timeout=40)
        if os.path.exists(out):
            with open(out, "rb") as f:
                res["png"] = f.read()
            res["how"] = "windows"
        elif r.returncode != 0:
            raise RuntimeError("Non riesco a leggere gli appunti: " + (r.stderr or "").strip()[:300])
    else:
        raise RuntimeError("L'incolla dagli appunti di sistema e' disponibile solo su Mac e Windows.")
    return res


def add_attachment(exp_id, name, data):
    dest_dir = os.path.join(ATT_DIR, str(exp_id))
    os.makedirs(dest_dir, exist_ok=True)
    base, ext = os.path.splitext(name)
    dest, k = os.path.join(dest_dir, name), 1
    while os.path.exists(dest):
        dest = os.path.join(dest_dir, "%s_%d%s" % (base, k, ext))
        k += 1
    with open(dest, "wb") as f:
        f.write(data)
    con = db()
    con.execute("INSERT INTO attachments(exp_id,filename,path) VALUES(?,?,?)", (exp_id, os.path.basename(dest), dest))
    con.commit()
    con.close()
    return os.path.basename(dest)


def api_clip_paste(d):
    exp_id = int(d["exp"])
    tmp = tempfile.mkdtemp(prefix="diario-clip-")
    try:
        res = read_system_clipboard(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not res["png"] and not res["cdx"]:
        t = ", ".join(res["types"][:12]) if res["types"] else "nessuno"
        raise RuntimeError("Negli appunti non c'e' nessuna immagine ChemDraw. Formati presenti: %s. "
                           "In ChemDraw seleziona la struttura e premi Cmd+C (Ctrl+C su Windows)." % t)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = "chemdraw-" + stamp
    saved = []
    if res["png"]:
        png = png_set_dpi(res["png"], res["dpi"]) if res["dpi"] else res["png"]
        saved.append(add_attachment(exp_id, stem + ".png", png))
    if res["cdx"]:
        saved.append(add_attachment(exp_id, stem + ".cdx", res["cdx"]))
    return {"saved": saved, "how": res["how"]}


def api_att_open(d):
    open_path(att_path(d["id"]))
    return {}


def api_att_reveal(d):
    reveal_path(att_path(d["id"]))
    return {}


def api_att_delete(d):
    con = db()
    row = con.execute("SELECT path FROM attachments WHERE id=?", (int(d["id"]),)).fetchone()
    con.execute("DELETE FROM attachments WHERE id=?", (int(d["id"]),))
    con.commit()
    con.close()
    if row:
        try:
            os.remove(row["path"])
        except OSError:
            pass
    return {}


SECTOR_AI = {
    "chimica": ("chimici di laboratorio", "Riscrivi il testo come sezione sperimentale professionale in stile articolo scientifico (ACS): forma impersonale/passato, ordine cronologico, quantita' con unita' e mmol/equivalenti se presenti nel testo, work-up e purificazione ben distinti."),
    "farmaco": ("farmacologi e biochimici", "Riscrivi il testo come sezione Materials and Methods di un articolo di farmacologia/biochimica: forma impersonale/passato, bersaglio, composti, concentrazioni, tampone, incubazione, rivelazione, controlli e analisi dei dati (fit, IC50) ben distinti."),
    "biologia": ("biologi molecolari e cellulari", "Riscrivi il testo come sezione Materials and Methods di un articolo di biologia molecolare/cellulare: forma impersonale/passato, linee cellulari (passaggio), terreni, trattamenti, anticorpi con diluizioni, kit, repliche e analisi statistica ben distinti."),
    "micro": ("microbiologi", "Riscrivi il testo come sezione Materials and Methods di un articolo di microbiologia: forma impersonale/passato, ceppi, terreni, condizioni di crescita, inoculo, metodo (CFU, MIC, curve di crescita) e standard di riferimento ben distinti."),
    "materiali": ("ricercatori di materiali, fisica e ingegneria", "Riscrivi il testo come sezione sperimentale di un articolo di materiali/fisica/ingegneria: forma impersonale/passato, materiali e lotti, parametri di processo, strumenti e modelli, condizioni di misura e calibrazione ben distinti."),
    "dati": ("ricercatori di informatica e data science", "Riscrivi il testo come sezione di metodo di un articolo di informatica/data science: forma impersonale/passato, dati, versioni, iperparametri, seed, hardware, metriche e procedura di valutazione ben distinti."),
}


def primary_sector():
    sel = load_cfg().get("sectors") or []
    return sel[0] if sel and sel[0] in SECTOR_AI else "chimica"


def base_rules():
    who = SECTOR_AI[primary_sector()][0]
    return (
        "Sei un assistente per %s che scrivono il quaderno di laboratorio. "
        "Non inventare MAI dati: conserva esattamente quantita', unita', valori, rese, temperature, tempi, "
        "nomi di reagenti, campioni, ceppi, linee cellulari, parametri e sigle (es. NG012, FM03). "
        "Se manca un'informazione importante, segnalala tra parentesi quadre come [da completare: ...]. "
        "Rispondi SOLO con il testo risultante, senza commenti, senza virgolette, senza markdown." % who)


def api_ai(d):
    mode = s(d.get("mode"))
    text = s(d.get("text"))
    if not text.strip():
        raise RuntimeError("Testo vuoto.")
    if mode == "libera":
        instr = s(d.get("instr")).strip()
        if not instr:
            raise RuntimeError("Istruzione mancante.")
        system = base_rules() + " Istruzione dell'utente: " + instr
    elif mode in MODES:
        body = MODES[mode]
        if mode == "stila":
            body = SECTOR_AI[primary_sector()][1] + " Mantieni la lingua del testo originale."
        system = base_rules() + " " + body
    else:
        raise RuntimeError("Modalita' sconosciuta.")
    engine = s(d.get("engine") or "claude")
    fn = {"claude": ask_claude, "gemini": ask_gemini}.get(engine)
    if not fn:
        raise RuntimeError("Motore AI sconosciuto.")
    return {"result": fn(system, text), "engine": engine}


EXPORT_DIR = os.path.join(APP_DIR, "esportazioni")
_OB = ("🎯 Obiettivo", "Qual è lo scopo dell'esperimento?")
_NO = ("📝 Note e prossimi passi", "")
SECTION_SETS = {
    "chimica": {"obiettivo": _OB, "procedura": ("🧪 Procedura sperimentale", "Scrivi qui appunti e procedura, anche in modo disordinato: l'AI li metterà in forma."),
                "risultati": ("📊 Risultati e osservazioni", "Rese, aspetto, TLC, NMR, osservazioni…"), "note": _NO},
    "farmaco": {"obiettivo": ("🎯 Obiettivo e ipotesi", "Bersaglio, composti, domanda a cui risponde il saggio."), "procedura": ("🧫 Saggio e condizioni", "Bersaglio/enzima, composti e concentrazioni, tampone, incubazione, rivelazione, controlli…"),
                "risultati": ("📊 Risultati (IC50, Ki, inibizione)", "Valori ottenuti, confronto con i riferimenti, osservazioni…"), "note": _NO},
    "biologia": {"obiettivo": ("🎯 Obiettivo e ipotesi", "Domanda biologica e ipotesi da verificare."), "procedura": ("🧬 Materiali e metodi", "Linee cellulari e passaggio, trattamenti, anticorpi (diluizioni, lotti), kit, protocollo…"),
                 "risultati": ("📊 Risultati e osservazioni", "Espressione, bande, immagini, repliche, osservazioni…"), "note": _NO},
    "micro": {"obiettivo": ("🎯 Obiettivo e ipotesi", "Ceppi, composti e domanda a cui risponde l'esperimento."), "procedura": ("🦠 Materiali e metodi", "Ceppi, terreni, condizioni di crescita, inoculo, metodo (CFU, MIC, curve), controlli…"),
              "risultati": ("📊 Risultati (conte, MIC, crescita)", "Conte, MIC, tempi di raddoppio, osservazioni…"), "note": _NO},
    "materiali": {"obiettivo": _OB, "procedura": ("🔧 Preparazione e condizioni di misura", "Materiale e lotto, processo, parametri, strumento e calibrazione, condizioni ambientali…"),
                  "risultati": ("📊 Misure e risultati", "Valori misurati, incertezze, confronto con le attese…"), "note": _NO},
    "dati": {"obiettivo": ("🎯 Obiettivo e ipotesi", "Domanda di ricerca, ipotesi, metrica di successo."), "procedura": ("💻 Metodo e configurazione", "Dati e versione, modello, iperparametri, seed, hardware, comando eseguito…"),
             "risultati": ("📊 Risultati e metriche", "Metriche, confronti con la baseline, osservazioni…"), "note": _NO},
}


def sec_titles():
    st = SECTION_SETS[primary_sector()]
    return [(k, re.sub(r"^[^\w]+", "", st[k][0]).strip()) for k in ("obiettivo", "procedura", "risultati", "note")]
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def xml_esc(t):
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t).replace("\t", "    ")
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def w_par(text="", style=None, italic=False, color=None, size=None, jc=None, ind=None):
    inner = ""
    if style:
        inner += '<w:pStyle w:val="%s"/>' % style
    if ind:
        inner += '<w:ind w:left="%d" w:hanging="%d"/>' % ind
    if jc:
        inner += '<w:jc w:val="%s"/>' % jc
    ppr = "<w:pPr>%s</w:pPr>" % inner if inner else ""
    rpr = ""
    if italic:
        rpr += "<w:i/>"
    if color:
        rpr += '<w:color w:val="%s"/>' % color
    if size:
        rpr += '<w:sz w:val="%d"/>' % size
    if rpr:
        rpr = "<w:rPr>%s</w:rPr>" % rpr
    if text == "":
        return "<w:p>%s</w:p>" % ppr
    return '<w:p>%s<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (ppr, rpr, xml_esc(text))


IMG_EXT = {".png": ("png", "image/png"), ".jpg": ("jpeg", "image/jpeg"), ".jpeg": ("jpeg", "image/jpeg")}
CHEM_EXT = (".cdx", ".cdxml", ".cd", ".c3xml")


def is_image(name):
    return os.path.splitext(name.lower())[1] in IMG_EXT


def img_info(data):
    """Ritorna (larghezza_px, altezza_px, dpi o None) per PNG/JPEG, altrimenti None."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", data[16:24])
            dpi, pos = None, 8
            while pos + 8 <= len(data):
                length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
                if ctype == b"pHYs":
                    ppux, _ppuy, unit = struct.unpack(">IIB", data[pos + 8:pos + 17])
                    if unit == 1 and ppux:
                        dpi = ppux * 0.0254
                    break
                if ctype in (b"IDAT", b"IEND"):
                    break
                pos += 12 + length
            return w, h, dpi
        if data[:2] == b"\xff\xd8":
            pos, dpi = 2, None
            while pos + 4 <= len(data):
                if data[pos] != 0xFF:
                    pos += 1
                    continue
                marker = data[pos + 1]
                if marker == 0xFF:
                    pos += 1
                    continue
                pos += 2
                if marker == 0xD8 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
                    continue
                seglen = struct.unpack(">H", data[pos:pos + 2])[0]
                if marker == 0xE0 and data[pos + 2:pos + 7] == b"JFIF\x00":
                    units = data[pos + 9]
                    xd = struct.unpack(">H", data[pos + 10:pos + 12])[0]
                    if units == 1 and xd:
                        dpi = float(xd)
                    elif units == 2 and xd:
                        dpi = xd * 2.54
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[pos + 3:pos + 7])
                    return w, h, dpi
                pos += seglen
    except Exception:
        return None
    return None


def fit_cm(w, h, dpi, max_w=16.0, max_h=9.0, min_w=3.0):
    """Dimensione in cm per il Word: grandezza naturale (se manca la risoluzione si assume uno
    schermo Retina, 144 dpi), ridotta per stare nella pagina e ingrandita se troppo piccola."""
    d = dpi if dpi and 30 <= dpi <= 1200 else 144.0
    cw, ch = w / d * 2.54, h / d * 2.54
    if cw < min_w and w >= 60:
        k = min(min_w / cw, max_h / ch)
        cw, ch = cw * k, ch * k
    k = min(1.0, max_w / cw, max_h / ch)
    return cw * k, ch * k


def w_image(rid, idx, cx, cy, descr):
    d = xml_esc(descr).replace('"', "&quot;")
    return (
        '<w:p><w:pPr><w:keepNext/><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
        '<wp:inline distT="0" distB="0" distL="0" distR="0">'
        '<wp:extent cx="%d" cy="%d"/><wp:docPr id="%d" name="Immagine %d" descr="%s"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic><pic:nvPicPr><pic:cNvPr id="%d" name="%s"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
    ) % (cx, cy, idx, idx, d, idx, d, rid, cx, cy)


def w_table(rows):
    """Tabella Word semplice (prima riga = intestazione), colonne di larghezza uguale."""
    rows = [[s(c) for c in r] for r in rows if r]
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    width = 9638 // ncol
    out = ['<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:jc w:val="center"/><w:tblBorders>'
           + "".join('<w:%s w:val="single" w:sz="4" w:space="0" w:color="C4B5FD"/>' % b
                     for b in ("top", "left", "bottom", "right", "insideH", "insideV"))
           + '</w:tblBorders><w:tblLayout w:type="fixed"/><w:tblCellMar><w:left w:w="80" w:type="dxa"/>'
           '<w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>'
           + "".join('<w:gridCol w:w="%d"/>' % width for _ in range(ncol)) + "</w:tblGrid>"]
    for ri, r in enumerate(rows):
        out.append("<w:tr>" + ("<w:trPr><w:cantSplit/><w:tblHeader/></w:trPr>" if ri == 0 else "<w:trPr><w:cantSplit/></w:trPr>"))
        for ci in range(ncol):
            txt = r[ci] if ci < len(r) else ""
            shade = '<w:shd w:val="clear" w:color="auto" w:fill="EDE9FE"/>' if ri == 0 else ""
            rpr = "<w:rPr><w:b/><w:sz w:val=\"20\"/></w:rPr>" if ri == 0 else '<w:rPr><w:sz w:val="20"/></w:rPr>'
            out.append('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/>%s</w:tcPr><w:p><w:pPr><w:spacing w:after="20"/>'
                       '<w:jc w:val="center"/></w:pPr><w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p></w:tc>'
                       % (width, shade, rpr, xml_esc(txt)))
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def make_docx(exp, atts, datasets=None):
    """Crea un file .docx (Word) con la sola libreria standard."""
    body = [w_par(exp.get("name") or "Esperimento senza nome", style="Title")]
    media, media_rels, images = [], [], []
    for a in atts:
        if not (is_image(a["filename"]) and a.get("path") and os.path.exists(a["path"])):
            continue
        try:
            with open(a["path"], "rb") as f:
                data = f.read()
        except OSError:
            continue
        info = img_info(data)
        if info:
            images.append({"att": a, "data": data, "info": info,
                           "ext": IMG_EXT[os.path.splitext(a["filename"].lower())[1]][0]})
    meta = []
    if s(exp.get("date")).strip():
        meta.append("Data: " + s(exp["date"]).strip())
    if s(exp.get("project")).strip():
        meta.append("Progetto: " + s(exp["project"]).strip())
    if meta:
        body.append(w_par("   ·   ".join(meta), color="6B7280"))
    chart_images = [im for im in images if im["att"]["filename"].lower().startswith("grafico-")]
    images = [im for im in images if im not in chart_images]

    def emit_images(lst):
        for im in lst:
            n = len(media) + 1
            name = "image%d.%s" % (n, im["ext"])
            media.append((name, im["data"]))
            media_rels.append(
                '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/%s"/>'
                % (n + 1, name))
            fname = im["att"]["filename"]
            if fname.lower().startswith("grafico-"):
                cw, ch = fit_cm(im["info"][0], im["info"][1], 200.0, max_h=10.5)
            else:
                cw, ch = fit_cm(*im["info"])
            body.append(w_image("rId%d" % (n + 1), n, int(cw * 360000), int(ch * 360000), fname))
            base = os.path.splitext(fname)[0]
            base = re.sub(r"-\d{8}-\d{6}$", "", base)
            base = re.sub(r"^(grafico|molecola)-", "", base)
            auto = base.lower() in ("incollata", "chemdraw", "molecola", "grafico")
            cap = "Figura %d" % n + ("" if auto else ". " + base.replace("_", " "))
            body.append(
                '<w:p><w:pPr><w:spacing w:after="240"/><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:i/><w:color w:val="6B7280"/>'
                '<w:sz w:val="18"/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % xml_esc(cap))

    for key, title in sec_titles():
        if key == "procedura" and images:
            body.append(w_par("Schema di reazione e strutture", style="Heading1"))
            emit_images(images)
        txt = s(exp.get(key)).strip()
        if txt:
            body.append(w_par(title, style="Heading1"))
            for line in txt.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                line = line.rstrip()
                if not line.strip():
                    continue
                m = re.match(r"^\s*([-*\u2022\u2013]|\d+[.)])\s+(.*)$", line)
                if m:
                    mark = "\u2022" if m.group(1) in "-*\u2022\u2013" else m.group(1)
                    body.append(w_par(mark + "\t" + m.group(2), jc="both", ind=(567, 283), style="ListLine"))
                else:
                    body.append(w_par(line.strip(), jc="both"))
        if key == "risultati" and (datasets or chart_images):
            body.append(w_par("Dati e grafici", style="Heading1"))
            for ds in datasets or []:
                pl = ds.get("payload") or {}
                body.append(w_par(s(ds.get("title")) or "Dati", style="Heading2"))
                if s(pl.get("summary")).strip():
                    for ln in s(pl["summary"]).split("\n"):
                        if ln.strip():
                            body.append(w_par(ln.strip(), jc="both"))
                if pl.get("table"):
                    body.append(w_table(pl["table"]))
                    body.append(w_par(""))
            emit_images(chart_images)
    if atts:
        body.append(w_par("Allegati", style="Heading1"))
        in_doc = set(im["att"]["filename"] for im in images)
        img_stems = set(os.path.splitext(f)[0].lower() for f in in_doc)
        for a in atts:
            fn = a["filename"]
            note = ""
            if fn in in_doc:
                note = "  (immagine inserita nel documento)"
            elif fn.lower().endswith(CHEM_EXT):
                if os.path.splitext(fn)[0].lower() in img_stems:
                    note = "  (originale ChemDraw, schema inserito nel documento)"
                else:
                    note = "  (originale ChemDraw: nessuna immagine associata, non visibile nel documento)"
            body.append(w_par("•  " + fn + note))
    body.append(w_par(""))
    body.append(w_par("Esportato dal Diario del Ricercatore il " +
                      datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                      italic=True, color="9CA3AF", size=18))

    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    document = (
        head + '<w:document xmlns:w="%s" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>' % W_NS + "".join(body) +
        '<w:sectPr><w:footerReference w:type="default" r:id="rId900"/><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
        'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>'
    )
    styles = (
        head + '<w:styles xmlns:w="%s">' % W_NS +
        '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
        '<w:sz w:val="22"/><w:lang w:val="it-IT"/></w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
        '<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="80"/></w:pPr>'
        '<w:rPr><w:b/><w:color w:val="5B21B6"/><w:sz w:val="44"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
        '<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="280" w:after="100"/>'
        '<w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:color w:val="7C3AED"/><w:sz w:val="28"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>'
        '<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/>'
        '<w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:color w:val="5B21B6"/><w:sz w:val="24"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="ListLine"><w:name w:val="List Line"/><w:basedOn w:val="Normal"/>'
        '<w:pPr><w:tabs><w:tab w:val="left" w:pos="567"/></w:tabs><w:spacing w:after="60"/></w:pPr></w:style>'
        "</w:styles>"
    )
    footer = (
        head + '<w:ftr xmlns:w="%s"><w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
        '<w:r><w:rPr><w:color w:val="9CA3AF"/><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:rPr><w:color w:val="9CA3AF"/><w:sz w:val="18"/></w:rPr><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        '<w:r><w:rPr><w:color w:val="9CA3AF"/><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r><w:rPr><w:color w:val="9CA3AF"/><w:sz w:val="18"/></w:rPr><w:t>1</w:t></w:r>'
        '<w:r><w:rPr><w:color w:val="9CA3AF"/><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>'
        "</w:p></w:ftr>" % W_NS
    )
    content_types = (
        head + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Default Extension="jpeg" ContentType="image/jpeg"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
        "</Types>"
    )
    rels = (
        head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rId900" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
        "@@MEDIA@@</Relationships>"
    )
    doc_rels = doc_rels.replace("@@MEDIA@@", "".join(media_rels))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/footer1.xml", footer)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        for name, data in media:
            z.writestr("word/media/" + name, data)
    return buf.getvalue()


def safe_name(t):
    t = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", s(t)).strip().strip(".")
    return t[:80] or "esperimento"


def api_export(d):
    exp_id = int(d["id"])
    con = db()
    row = con.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
    atts = con.execute("SELECT filename,path FROM attachments WHERE exp_id=? ORDER BY id", (exp_id,)).fetchall()
    dsets = ds_for(con, exp_id)
    con.close()
    if not row:
        raise RuntimeError("Esperimento non trovato.")
    os.makedirs(EXPORT_DIR, exist_ok=True)
    path = os.path.join(EXPORT_DIR, "%s (n.%d).docx" % (safe_name(row["name"]), exp_id))
    with open(path, "wb") as f:
        f.write(make_docx(dict(row), [dict(a) for a in atts], dsets))
    drive = False
    base = sync_base()
    if base:
        try:
            dest = os.path.join(base, DRIVE_SUBDIR, "Esperimenti")
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(path, os.path.join(dest, os.path.basename(path)))
            drive = True
        except OSError:
            drive = False
    try:
        open_path(path)
    except OSError:
        pass
    return {"file": os.path.basename(path), "folder": os.path.join("~", "DiarioRicercatore", "esportazioni"), "drive": drive}


def find_chemdraw():
    """Cerca ChemDraw (macOS: ChemDraw*.app; Windows: ChemDraw.exe sotto Program Files)."""
    found = []
    if IS_WIN:
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")]

        def scan_win(base, depth):
            try:
                entries = os.listdir(base)
            except OSError:
                return
            for name in entries:
                full, low = os.path.join(base, name), name.lower()
                if low == "chemdraw.exe":
                    found.append(full)
                elif (depth > 0 and os.path.isdir(full)
                      and re.match(r"(chemdraw|chemoffice|perkinelmer|revvity|cambridgesoft)", low)):
                    scan_win(full, depth - 1)

        for base in roots:
            if base:
                scan_win(base, 4)
    else:
        def scan(base, depth):
            try:
                entries = os.listdir(base)
            except OSError:
                return
            for name in entries:
                full, low = os.path.join(base, name), name.lower()
                if low.endswith(".app") and low.startswith("chemdraw"):
                    found.append(full)
                elif (depth > 0 and not low.endswith(".app") and os.path.isdir(full)
                      and re.match(r"(chemdraw|chemoffice|perkinelmer|revvity|cambridgesoft)", low)):
                    scan(full, depth - 1)

        for base in ("/Applications", os.path.expanduser("~/Applications")):
            scan(base, 2)
        if not found and IS_MAC:
            try:
                p = subprocess.run(["mdfind", "kMDItemKind == 'Application' && kMDItemFSName == 'ChemDraw*'"],
                                   capture_output=True, text=True, timeout=8)
                found = [ln for ln in p.stdout.splitlines() if ln.endswith(".app")]
            except (OSError, subprocess.SubprocessError):
                pass
    if not found:
        return None
    if IS_WIN:   # i nomi delle cartelle (ChemOffice2020, 23.1…) non sono confrontabili: vale l'installazione piu' recente
        found.sort(key=lambda p: (os.path.getmtime(p), p))
    else:
        found.sort(key=lambda p: ([int(x) for x in re.findall(r"\d+", p)], p))
    return found[-1]


def api_chemdraw_open(d):
    target = s(load_cfg().get("chemdraw_app")).strip() or find_chemdraw()
    if not target:
        raise RuntimeError("NOCHEMDRAW")
    try:
        if IS_WIN:
            if os.path.exists(target):
                os.startfile(target)
            else:   # solo il nome del programma
                p = subprocess.run(["cmd", "/c", "start", "", target], capture_output=True, timeout=25)
                if p.returncode != 0:
                    raise RuntimeError("NOCHEMDRAW")
        elif IS_MAC:
            cmd = ["open", target] if (os.sep in target or target.endswith(".app")) else ["open", "-a", target]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            if p.returncode != 0:
                raise RuntimeError("NOCHEMDRAW")
        else:
            raise RuntimeError("NOCHEMDRAW")
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("NOCHEMDRAW")
    return {"app": os.path.basename(target)}


def api_chemdraw_set(d):
    v = s(d.get("app")).strip().strip("'\"")
    if not IS_WIN:
        v = v.replace("\\ ", " ")
    cfg = load_cfg()
    if v:
        cfg["chemdraw_app"] = v
    else:
        cfg.pop("chemdraw_app", None)
    save_cfg(cfg)
    return {}


# ---------------- Cartella Google Drive (sincronizzazione e backup) ----------------
DRIVE_SUBDIR = "Diario del Ricercatore"
_sync_lock = threading.Lock()
_sync_state = {"time": "", "error": "", "last_ts": 0.0}


def drive_candidates():
    """Cartelle di Google Drive per desktop trovate sul computer (le propone, non le sceglie da sole)."""
    home = os.path.expanduser("~")
    out = []
    base = os.path.join(home, "Library", "CloudStorage")
    try:
        for name in sorted(os.listdir(base)):
            if name.startswith("GoogleDrive"):
                acc = os.path.join(base, name)
                for sub in ("Il mio Drive", "My Drive", "Mio Drive"):
                    if os.path.isdir(os.path.join(acc, sub)):
                        out.append(os.path.join(acc, sub))
    except OSError:
        pass
    for extra in ("Google Drive/Il mio Drive", "Google Drive/My Drive", "Google Drive", "My Drive"):
        full = os.path.join(home, extra)
        if os.path.isdir(full) and full not in out:
            out.append(full)
    if IS_WIN:   # Google Drive per desktop monta un'unita' (di solito G:) con «Il mio Drive» o «My Drive»
        for letter in "GHIJKLMNOPQRSTUVWXYZDEF":
            for sub in ("Il mio Drive", "My Drive", "Mio Drive"):
                full = "%s:\\%s" % (letter, sub)
                if os.path.isdir(full) and full not in out:
                    out.append(full)
    return out


def sync_base():
    v = s(load_cfg().get("sync_dir")).strip()
    if not v:
        return None
    v = os.path.expanduser(v)
    return v if os.path.isdir(v) else None


def check_sync_dir(v):
    v = s(v).strip().strip("'\"")
    if not IS_WIN:
        v = v.replace("\\ ", " ")
    v = os.path.expanduser(v)
    if not os.path.isdir(v):
        raise RuntimeError("Quella cartella non esiste. Controlla il percorso (Mac: Finder, seleziona la cartella e premi ⌥⌘C · Windows: tasto destro sulla cartella → Copia come percorso).")
    real = os.path.realpath(v)
    app_real = os.path.realpath(APP_DIR)
    if real == app_real or real.startswith(app_real + os.sep):
        raise RuntimeError("Scegli una cartella diversa da quella dei dati del Diario.")
    probe = os.path.join(v, ".diario_prova_%d" % os.getpid())
    try:
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except OSError:
        raise RuntimeError("Non riesco a scrivere in quella cartella: controlla i permessi.")
    return v


def api_drive_find(d):
    return {"found": drive_candidates(), "current": s(load_cfg().get("sync_dir"))}


def api_drive_set(d):
    cfg = load_cfg()
    v = s(d.get("path")).strip()
    if v:
        cfg["sync_dir"] = check_sync_dir(v)
    else:
        cfg.pop("sync_dir", None)
    save_cfg(cfg)
    return {"sync_dir": s(cfg.get("sync_dir"))}


def _copy_if_changed(src, dst):
    try:
        st = os.stat(src)
        if os.path.exists(dst):
            dt = os.stat(dst)
            if dt.st_size == st.st_size and dt.st_mtime >= st.st_mtime:
                return False
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except OSError:
        return False


def sync_to_drive():
    """Copia nella cartella Drive: un Word per ogni esperimento + copia di sicurezza di database e allegati."""
    base = sync_base()
    if not base:
        raise RuntimeError("NODRIVE")
    if not _sync_lock.acquire(blocking=False):
        raise RuntimeError("Una sincronizzazione e' gia' in corso.")
    try:
        root = os.path.join(base, DRIVE_SUBDIR)
        dir_exp = os.path.join(root, "Esperimenti")
        dir_bak = os.path.join(root, "Backup")
        os.makedirs(dir_exp, exist_ok=True)
        os.makedirs(dir_bak, exist_ok=True)
        # 1) copia coerente del database (anche mentre il Diario e' in uso)
        tmp = os.path.join(dir_bak, "diario.db.tmp")
        src = db()
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        os.replace(tmp, os.path.join(dir_bak, "diario.db"))
        # 2) allegati
        n_att = 0
        for r, _dirs, files in os.walk(ATT_DIR):
            for fn in files:
                sp = os.path.join(r, fn)
                if _copy_if_changed(sp, os.path.join(dir_bak, "allegati", os.path.relpath(sp, ATT_DIR))):
                    n_att += 1
        # 3) un Word per esperimento (solo quelli nuovi o modificati)
        n_doc = 0
        con = db()
        rows = con.execute("SELECT * FROM experiments ORDER BY id").fetchall()
        for row in rows:
            atts = con.execute("SELECT filename,path FROM attachments WHERE exp_id=? ORDER BY id", (row["id"],)).fetchall()
            path = os.path.join(dir_exp, "%s (n.%d).docx" % (safe_name(row["name"]), row["id"]))
            try:
                upd = datetime.datetime.fromisoformat(s(row["updated"])).timestamp()
            except ValueError:
                upd = time.time()
            for a in atts:
                try:
                    upd = max(upd, os.path.getmtime(a["path"]))
                except OSError:
                    pass
            dsets = ds_for(con, row["id"])
            for ds in dsets:
                try:
                    upd = max(upd, datetime.datetime.fromisoformat(s(ds["updated"])).timestamp())
                except ValueError:
                    pass
            if os.path.exists(path) and os.path.getmtime(path) >= upd:
                continue
            with open(path, "wb") as f:
                f.write(make_docx(dict(row), [dict(a) for a in atts], dsets))
            n_doc += 1
        con.close()
        _sync_state.update({"time": now(), "error": "", "last_ts": time.time()})
        return {"documenti": n_doc, "allegati": n_att, "esperimenti": len(rows), "cartella": root}
    except Exception as ex:
        _sync_state["error"] = str(ex)
        raise
    finally:
        _sync_lock.release()


def api_drive_sync(d):
    try:
        return sync_to_drive()
    except RuntimeError as ex:
        raise
    except OSError as ex:
        raise RuntimeError("Sincronizzazione non riuscita: %s" % ex)


def auto_sync_loop():
    """Ogni 5 minuti, se la cartella Drive e' impostata e ci sono modifiche, sincronizza da sola."""
    while True:
        time.sleep(300)
        try:
            if sync_base() and os.path.getmtime(DB_PATH) > _sync_state["last_ts"]:
                sync_to_drive()
        except Exception:
            pass


# ---------------- Editor di strutture (JSME) ----------------
JSME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jsme")
JSME_CDN = "https://jsme-editor.github.io/dist/jsme/jsme.nocache.js"


def jsme_url():
    """Se accanto a diario_web.py c'e' la cartella «jsme» (scaricata), l'editor funziona anche senza internet."""
    if os.path.isfile(os.path.join(JSME_DIR, "jsme.nocache.js")):
        return "/jsme/jsme.nocache.js"
    return JSME_CDN


SECTORS = {
    "chimica": "Chimica (sintesi)", "farmaco": "Farmacologia / biochimica",
    "biologia": "Biologia molecolare e cellulare", "micro": "Microbiologia",
    "materiali": "Materiali / fisica / ingegneria", "dati": "Informatica e dati",
}


def api_sector_set(d):
    sel = [x for x in (d.get("sectors") or []) if x in SECTORS]
    cfg = load_cfg()
    cfg["sectors"] = sel
    save_cfg(cfg)
    return {"sectors": sel}


def ds_row(r):
    try:
        payload = json.loads(r["payload"] or "{}")
    except ValueError:
        payload = {}
    return {"id": r["id"], "exp_id": r["exp_id"], "title": r["title"], "kind": r["kind"],
            "payload": payload, "updated": r["updated"]}


def ds_for(con, exp_id):
    return [ds_row(r) for r in con.execute("SELECT * FROM datasets WHERE exp_id=? ORDER BY id", (exp_id,)).fetchall()]


def api_ds_list(d):
    con = db()
    res = ds_for(con, int(d["exp"]))
    con.close()
    return {"datasets": res}


def api_ds_save(d):
    payload = d.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("Dati non validi.")
    blob = json.dumps(payload, ensure_ascii=False)
    if len(blob) > 2000000:
        raise RuntimeError("Tabella troppo grande.")
    title = s(d.get("title")).strip()[:120] or "Dati senza titolo"
    kind = s(d.get("kind"))[:20]
    con = db()
    if d.get("id"):
        con.execute("UPDATE datasets SET title=?,kind=?,payload=?,updated=? WHERE id=? AND exp_id=?",
                    (title, kind, blob, now(), int(d["id"]), int(d["exp"])))
        new_id = int(d["id"])
    else:
        cur = con.execute("INSERT INTO datasets(exp_id,title,kind,payload,updated) VALUES(?,?,?,?,?)",
                          (int(d["exp"]), title, kind, blob, now()))
        new_id = cur.lastrowid
    con.commit()
    con.close()
    return {"id": new_id}


def api_ds_delete(d):
    con = db()
    con.execute("DELETE FROM datasets WHERE id=?", (int(d["id"]),))
    con.commit()
    con.close()
    return {}


def api_key_status(d):
    cfg = load_cfg()
    return {"sectors": cfg.get("sectors"), "sector_names": SECTORS, "sections": SECTION_SETS[primary_sector()], "claude": bool(get_api_key()), "gemini": bool(get_gemini_key()),
            "gemini_model": s(cfg.get("gemini_model")), "chemdraw": s(cfg.get("chemdraw_app")),
            "sync_dir": s(cfg.get("sync_dir")), "sync_last": _sync_state["time"], "sync_error": _sync_state["error"]}


def api_set_keys(d):
    cfg = load_cfg()
    for field, cfg_key in (("claude", "api_key"), ("gemini", "gemini_key")):
        v = s(d.get(field)).strip()
        if v:                       # campo vuoto = non cambiare la chiave gia' salvata
            check_key_chars(v)
            cfg[cfg_key] = v
    for who in (d.get("remove") or []):
        if who == "claude":
            cfg.pop("api_key", None)
        elif who == "gemini":
            cfg.pop("gemini_key", None)
    if "gemini_model" in d:
        m = s(d["gemini_model"]).strip()
        if m.startswith("models/"):
            m = m[len("models/"):]
        if m and not re.match(r"^[A-Za-z0-9._-]+$", m):
            raise RuntimeError("Nome del modello non valido.")
        if m:
            cfg["gemini_model"] = m
        else:
            cfg.pop("gemini_model", None)
    save_cfg(cfg)
    _gemini_model_cache.clear()
    return {}


ROUTES = {
    "/api/list": api_list, "/api/get": api_get, "/api/new": api_new, "/api/save": api_save,
    "/api/delete": api_delete, "/api/att_open": api_att_open, "/api/att_reveal": api_att_reveal,
    "/api/att_delete": api_att_delete, "/api/clip_paste": api_clip_paste, "/api/sector_set": api_sector_set,
    "/api/ds_list": api_ds_list, "/api/ds_save": api_ds_save, "/api/ds_delete": api_ds_delete, "/api/ai": api_ai, "/api/key_status": api_key_status,
    "/api/set_keys": api_set_keys, "/api/export": api_export,
    "/api/chemdraw_open": api_chemdraw_open, "/api/chemdraw_set": api_chemdraw_set,
    "/api/drive_find": api_drive_find, "/api/drive_set": api_drive_set, "/api/drive_sync": api_drive_sync,
    "/api/tree": api_tree, "/api/group_new": api_group_new, "/api/group_update": api_group_update,
    "/api/group_move": api_group_move, "/api/group_delete": api_group_delete, "/api/exp_move": api_exp_move,
}


# ---------------- HTTP ----------------
class Handler(BaseHTTPRequestHandler):
    server_version = "Diario/1.0"

    def log_message(self, *a):
        pass

    def host_ok(self):
        host = self.headers.get("Host") or ""
        port = self.server.server_port
        return host in ("127.0.0.1:%d" % port, "localhost:%d" % port)

    def send_json(self, obj, code=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.host_ok():
            return self.send_error(403)
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/att":
            return self.serve_attachment(parsed.query)
        if path.startswith("/jsme/"):
            return self.serve_jsme(path[len("/jsme/"):])
        if path != "/":
            return self.send_error(404)
        data = PAGE.replace("__TOKEN__", TOKEN).replace("__JSME__", jsme_url()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def serve_jsme(self, rel):
        """File dell'editor JSME scaricato in locale (solo dalla cartella «jsme»)."""
        real = os.path.realpath(os.path.join(JSME_DIR, urllib.parse.unquote(rel)))
        if not real.startswith(os.path.realpath(JSME_DIR) + os.sep) or not os.path.isfile(real):
            return self.send_error(404)
        ctype = mimetypes.guess_type(real)[0] or "application/octet-stream"
        if real.endswith(".js"):
            ctype = "application/javascript"
        with open(real, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_attachment(self, query):
        """Serve un'immagine allegata (solo PNG/JPG) per le anteprime nella pagina."""
        qs = urllib.parse.parse_qs(query)
        tok = (qs.get("t") or [""])[0]
        if not secrets.compare_digest(tok.encode("utf-8"), TOKEN.encode("utf-8")):
            return self.send_error(403)
        try:
            p = att_path(int((qs.get("id") or ["0"])[0]))
        except Exception:
            return self.send_error(404)
        ext = os.path.splitext(p)[1].lower()
        if ext not in IMG_EXT:
            return self.send_error(404)
        with open(p, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", IMG_EXT[ext][1])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def handle_upload(self, query, n):
        qs = urllib.parse.parse_qs(query)
        exp_id = int(qs["exp"][0])
        name = os.path.basename(qs.get("name", ["file"])[0]).strip() or "file"
        dest_dir = os.path.join(ATT_DIR, str(exp_id))
        os.makedirs(dest_dir, exist_ok=True)
        base, ext = os.path.splitext(name)
        dest = os.path.join(dest_dir, name)
        k = 1
        while os.path.exists(dest):
            dest = os.path.join(dest_dir, "%s_%d%s" % (base, k, ext))
            k += 1
        remaining = n
        with open(dest, "wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        con = db()
        con.execute("INSERT INTO attachments(exp_id,filename,path) VALUES(?,?,?)",
                    (exp_id, os.path.basename(dest), dest))
        con.commit()
        con.close()
        return {}

    def do_POST(self):
        if not self.host_ok() or not secrets.compare_digest(self.headers.get("X-Token") or "", TOKEN):
            return self.send_json({"error": "non autorizzato"}, 403)
        parsed = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            if parsed.path == "/api/upload":
                res = self.handle_upload(parsed.query, n)
            else:
                fn = ROUTES.get(parsed.path)
                raw = self.rfile.read(n) if n else b"{}"
                if not fn:
                    return self.send_json({"error": "rotta sconosciuta"}, 404)
                res = fn(json.loads(raw.decode("utf-8") or "{}"))
            self.send_json(res)
        except RuntimeError as ex:
            self.send_json({"error": str(ex)}, 400)
        except Exception as ex:
            self.send_json({"error": "Errore interno: %s" % ex}, 500)


# ---------------- Pagina ----------------
PAGE = r"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🔬 Diario del Ricercatore</title>
<style>
:root{--v:#7C3AED;--vd:#5B21B6;--vl:#EDE9FE;--g:#10B981;--b:#3B82F6;--o:#F59E0B;--r:#EC4899;--bg:#F8F7FF}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;background:var(--bg);color:#1F2937}
.app{display:flex;height:100vh}
aside{width:300px;flex:none;background:linear-gradient(180deg,#7C3AED,#5B21B6);color:#fff;padding:20px 16px;display:flex;flex-direction:column;gap:10px}
.logo{font-size:26px;font-weight:800;line-height:1.1;margin:4px 4px 8px}
#search{width:100%;border:0;border-radius:10px;padding:10px 12px;font:inherit;outline:none;background:#fff;color:#1F2937;-webkit-text-fill-color:#1F2937;caret-color:#5B21B6}
#search::placeholder{color:#6B7280;-webkit-text-fill-color:#6B7280;opacity:1}
#list{flex:1;overflow:auto;background:rgba(0,0,0,.18);border-radius:14px;padding:6px}
.item{display:flex;flex-direction:column;width:100%;text-align:left;background:transparent;color:#fff;border:0;border-radius:10px;padding:9px 12px;margin-bottom:3px;cursor:pointer;font:inherit}
.item:hover{background:rgba(255,255,255,.14)}
.item.sel{background:var(--vl);color:var(--vd)}
.it-name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.it-date{font-size:12px;opacity:.75;padding-left:22px}
main{flex:1;overflow:auto;padding:22px 26px 60px}
.card{background:#fff;border-radius:16px;box-shadow:0 2px 10px rgba(91,33,182,.08);padding:16px 18px;margin-bottom:14px;border:2px solid transparent}
.card.active{border-color:#C4B5FD}
input,textarea{font:inherit;color:inherit}
input.title{width:100%;font-size:24px;font-weight:700;border:0;background:var(--vl);border-radius:12px;padding:12px 14px;outline:none}
.row{display:flex;gap:8px;margin-top:10px;align-items:center}
.row input{border:1px solid #DDD6FE;border-radius:10px;padding:9px 12px;outline:none}
#date{width:130px;flex:none}
#project{flex:1;min-width:120px}
.row{flex-wrap:wrap}
.row .btn{white-space:nowrap;flex:none}
textarea{width:100%;border:1px solid #DDD6FE;border-radius:12px;padding:11px 13px;background:#FAFAFF;resize:vertical;line-height:1.5;outline:none;min-height:70px;font-size:15px}
textarea:focus,.row input:focus{border-color:var(--v)}
.btn{border:0;border-radius:10px;padding:9px 14px;color:#fff;font:inherit;font-weight:600;cursor:pointer}
.btn:hover{filter:brightness(.92)}
.btn:disabled{opacity:.5;cursor:wait}
.violet{background:var(--v)}.green{background:var(--g)}.blue{background:var(--b)}.orange{background:var(--o)}.pink{background:var(--r)}.red{background:#EF4444}.grey{background:#9CA3AF}
.ghost{background:transparent;border:1px solid rgba(255,255,255,.75)}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.ailabel{font-weight:700;color:var(--v);margin-right:6px}
.keyrow{display:flex;justify-content:space-between;align-items:center;margin-top:6px}
.modal .hint{font-size:13px;color:#6B7280}
#status{color:#6B7280;margin-left:auto;font-size:14px}
.h2{font-weight:700;color:var(--vd);font-size:17px;margin:0 0 8px}
.att{display:flex;align-items:center;gap:8px;background:var(--vl);border-radius:10px;padding:7px 12px;margin-top:6px}
.att .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.small{padding:5px 11px;font-size:13px}
select{font:inherit;border:1px solid #DDD6FE;border-radius:10px;padding:8px 10px;background:#fff;max-width:420px;outline:none}
.sbrow{display:flex;gap:8px}
.sbrow .btn{padding:9px 8px;white-space:nowrap;font-size:14px;min-width:0}
.sbnote{color:rgba(255,255,255,.85);font-size:13px;padding:8px 10px}
.grp{margin-bottom:5px}
.ghead{position:relative;display:flex;align-items:center;gap:6px;border-radius:9px;padding:6px 8px;color:#fff;cursor:pointer;user-select:none;-webkit-user-select:none;text-shadow:0 1px 1px rgba(0,0,0,.25)}
.ghead.dropover{outline:3px solid #fff}
.garrow{width:14px;text-align:center;font-size:12px}
.gname{flex:1;min-width:0;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gcount{font-size:12px;background:rgba(0,0,0,.22);border-radius:10px;padding:1px 8px}
.gmore{border:0;background:rgba(255,255,255,.3);color:#fff;border-radius:6px;padding:0 8px;cursor:pointer;font-size:16px;font-weight:700;line-height:20px}
.gmore:hover{background:rgba(255,255,255,.55)}
.gmenu{position:fixed;z-index:30;background:#fff;color:#1F2937;border-radius:12px;box-shadow:0 8px 28px rgba(30,20,60,.35);padding:6px;min-width:250px;display:flex;flex-direction:column}
.gmenu button{border:0;background:transparent;text-align:left;padding:9px 12px;border-radius:8px;font:inherit;cursor:pointer}
.gmenu button:hover{background:var(--vl)}
.gmenu button.danger{color:#DC2626}
.gcolors{display:flex;gap:6px;padding:8px 12px 6px;align-items:center}
.gcolors span{font-size:13px;color:#6B7280;margin-right:4px}
.gcolors .sw{width:20px;height:20px;border-radius:50%;padding:0;border:2px solid #fff;box-shadow:0 0 0 1px #D1D5DB}
.gcolors .sw.cur{box-shadow:0 0 0 2px #1F2937}
.gbody{margin:3px 0 0 9px;padding-left:6px;border-left:3px solid}
.thumb{max-height:110px;max-width:260px;border-radius:8px;background:#fff;border:1px solid #DDD6FE}
.warn{color:#B45309;font-size:12px;white-space:normal;margin-top:2px}
.muted{color:#9CA3AF}
.drop{border:2px dashed #C4B5FD;border-radius:12px;padding:12px;margin-top:8px}
.drop.over{background:var(--vl)}
.topline{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px}
.secgrid{display:grid;grid-template-columns:1fr 1fr;gap:6px 14px}
.secopt{display:flex;align-items:center;gap:6px;padding:8px 10px;border:1px solid #DDD6FE;border-radius:10px;cursor:pointer}
.modal.wide{width:min(1180px,96vw)}
.dsgrid{display:flex;gap:16px;flex-wrap:wrap;overflow:auto;min-height:0}
.dsleft{flex:1 1 360px;display:flex;flex-direction:column;gap:8px;min-width:300px}
.dsright{flex:1.4 1 460px;display:flex;flex-direction:column;gap:8px;min-width:320px}
.dsopt{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.dsopt input[type=text],.dsopt select{flex:1;min-width:120px}
.dsopt select,.dsleft select{border:1px solid #DDD6FE;border-radius:10px;padding:9px 10px;background:#fff;font:inherit}
.dstext{min-height:240px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;white-space:pre}
.dsprev{border:1px solid #E5E7EB;border-radius:12px;background:#fff;padding:4px}
.dsprev svg{width:100%;height:auto;display:block}
.dssum{white-space:pre-wrap;font-size:13px;color:#374151;background:#F5F3FF;border-radius:10px;padding:8px 10px}
.dssum:empty{display:none}
table.grid{border-collapse:collapse;width:100%;font-size:13px}
table.grid th{background:#EDE9FE;color:#5B21B6;font-weight:600;padding:5px 6px;text-align:left;white-space:nowrap}
table.grid td{padding:2px;border-bottom:1px solid #F3F4F6}
table.grid input,table.grid select{width:100%;border:1px solid #E5E7EB;border-radius:6px;padding:5px 6px;font:inherit;font-size:13px;background:#fff}
table.grid .gcomp{display:block;padding:5px 6px;color:#5B21B6;font-weight:600;white-space:nowrap}
.gdel{border:0;background:transparent;color:#EF4444;cursor:pointer;font-size:14px}
.gridwrap{display:flex;flex-direction:column;gap:8px;align-items:flex-start;max-width:100%;overflow:auto}
.platebox{overflow:auto;max-width:100%}
table.plate{border-collapse:collapse;font-size:11px}
table.plate th{color:#6B7280;font-weight:600;padding:2px 4px}
table.plate td{padding:1px}
table.plate input{width:46px;border:1px solid #E5E7EB;border-radius:5px;padding:4px;font:inherit;font-size:11px;text-align:center;background:#fff}
.modal-bg{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(30,20,60,.45);display:flex;align-items:center;justify-content:center;z-index:10}
.modal{background:#fff;border-radius:18px;padding:20px;width:min(760px,92vw);max-height:90vh;display:flex;flex-direction:column;gap:10px}
.modal textarea{min-height:300px}
.modal input{border:1px solid #DDD6FE;border-radius:10px;padding:10px 12px;outline:none}
.modal .btns{display:flex;gap:8px;justify-content:flex-end}
</style>
</head>
<body>
<div class="app">
  <aside>
    <div class="logo">🔬 Diario del<br>Ricercatore</div>
    <div class="sbrow">
      <button class="btn orange" id="btnNew" style="flex:1.25" title="Nuovo esperimento">＋ Esperimento</button>
      <button class="btn ghost" id="btnNewGroup" style="flex:1" title="Crea un gruppo per raggruppare gli esperimenti">📁＋ Gruppo</button>
    </div>
    <input id="search" placeholder="🔍 Cerca esperimento…">
    <div id="list"></div>
    <button class="btn ghost" id="btnSector">🧭 Settore</button>
    <button class="btn ghost" id="btnArchive">📦 Archivio</button>
    <button class="btn ghost" id="btnSync" title="Salva Word e copia di sicurezza nella cartella di Google Drive">☁️ Sincronizza con Drive</button>
    <button class="btn ghost" id="btnKey">🔑 Chiavi API e impostazioni</button>
  </aside>
  <main>
    <div class="card">
      <input id="name" class="title" placeholder="Nome dell'esperimento (es. NG012 – step 3)">
      <div class="row">
        <input id="date" placeholder="Data">
        <input id="project" placeholder="Progetto / molecola target">
        <button class="btn green" id="btnSave">💾 Salva</button>
        <button class="btn orange" id="btnChem" title="Apre l'app ChemDraw">⚗️ ChemDraw</button>
        <button class="btn blue" id="btnExport" title="Crea un documento Word di questo esperimento">📄 Esporta in Word</button>
        <button class="btn red" id="btnDel" title="Elimina esperimento">🗑</button>
      </div>
      <div class="row">
        <span class="muted">📁 Gruppo:</span>
        <select id="groupsel"></select>
      </div>
    </div>
    <div class="card bar" id="aibar"><span class="ailabel" id="ailabel"></span>
      <select id="engine" title="Quale intelligenza artificiale usare">
        <option value="claude">🟣 Claude</option>
        <option value="gemini">🔵 Gemini</option>
      </select>
    </div>
    <div id="sections"></div>
    <div class="card">
      <div class="topline">
        <div class="h2" style="margin:0">📈 Dati e grafici</div>
      </div>
      <div id="dsquick" class="dsopt" style="margin-top:8px"></div>
      <div id="dslist" style="margin-top:8px"></div>
    </div>
    <div class="card">
      <div class="topline">
        <div class="h2" style="margin:0">📎 Allegati (ChemDraw e altri file)</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn orange" id="btnPasteChem" title="Incolla nell'esperimento la struttura copiata da ChemDraw (Cmd+C / Ctrl+C in ChemDraw)">📋 Incolla da ChemDraw</button>
          <button class="btn violet" id="btnDraw" title="Disegna una molecola o uno schema e allegalo all'esperimento">🧪 Disegna molecola</button>
          <button class="btn blue" id="btnAdd">＋ Aggiungi file</button>
        </div>
      </div>
      <input type="file" id="filepick" multiple style="display:none">
      <div class="drop" id="drop">
        <div id="attlist"></div>
        <div class="muted" style="margin-top:8px;font-size:13px">💡 <b>Per vedere gli schemi nel Word:</b> in ChemDraw seleziona la struttura, premi ⌘C e poi ⌘V su questa pagina (oppure salva lo schema come PNG e trascinalo qui). Il file .cdx/.cdxml resta allegato come originale modificabile. Le immagini PNG/JPG compaiono nel documento Word.</div>
      </div>
    </div>
  </main>
</div>
<script>
const TOKEN = "__TOKEN__";
const JSME_URL = "__JSME__";
let SECTIONS = [
  ["obiettivo", "🎯 Obiettivo", "Qual è lo scopo dell'esperimento?", 3],
  ["procedura", "🧪 Procedura sperimentale", "Scrivi qui appunti e procedura, anche in modo disordinato: l'AI li metterà in forma.", 10],
  ["risultati", "📊 Risultati e osservazioni", "Rese, aspetto, TLC, NMR, osservazioni…", 5],
  ["note", "📝 Note e prossimi passi", "", 4]
];
const AIBTNS = [
  ["✨ Stila", "violet", "stila"],
  ["🔤 Correggi", "green", "correggi"],
  ["🌍 In inglese", "blue", "inglese"],
  ["💡 Suggerisci titolo", "orange", "titolo"],
  ["🪄 Istruzione libera", "pink", "libera"]
];
let curId = null, active = "procedura", saveTimer = null, dirty = false, searchTimer = null;
let TREE = { groups: [], exps: [] }, archiveMode = false, curGroup = null;
const PALETTE = ["#EC4899", "#EA580C", "#B45309", "#059669", "#2563EB", "#0D9488", "#DC2626", "#64748B"];
const $ = id => document.getElementById(id);

function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const k in (props || {})) {
    if (k === "class") e.className = props[k];
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), props[k]);
    else e.setAttribute(k, props[k]);
  }
  for (const c of kids.flat()) {
    if (c == null) continue;
    e.append(c);
  }
  return e;
}

async function api(route, body) {
  const r = await fetch("/api/" + route, {
    method: "POST",
    headers: { "X-Token": TOKEN, "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  });
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (r.status === 403) throw new Error("Sessione scaduta: chiudi questa scheda e riapri il Diario dal file «Avvia Diario.command».");
  if (!r.ok || data.error) throw new Error(data.error || ("Errore " + r.status));
  return data;
}

let statusTimer = null;
function status(msg, ms) {
  $("status") && ($("status").textContent = msg);
  clearTimeout(statusTimer);
  if (ms) statusTimer = setTimeout(() => { $("status").textContent = ""; }, ms);
}
function fail(e) { status(""); alert(e.message || String(e)); }

function autosize(t) {
  t.style.height = "auto";
  t.style.height = Math.max(t.scrollHeight + 2, 70) + "px";
}

function collect() {
  const o = { id: curId, name: $("name").value, date: $("date").value, project: $("project").value };
  SECTIONS.forEach(s => { o[s[0]] = $("sec_" + s[0]).value; });
  return o;
}

async function saveNow() {
  clearTimeout(saveTimer);
  if (curId == null) return;
  await api("save", collect());
  dirty = false;
  status("✅ Salvato", 2000);
  await loadList();
}

function scheduleSave() {
  dirty = true;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => saveNow().catch(() => {}), 1500);
}

// ---------- gruppi (stile tracce di gruppo di Ableton) ----------
const gById = id => TREE.groups.find(g => g.id === id);
function inArchive(gid) {            // vero se il gruppo o un suo antenato è archiviato
  let g = gid == null ? null : gById(gid), n = 0;
  while (g && n++ < 100) { if (g.archived) return true; g = g.parent_id == null ? null : gById(g.parent_id); }
  return false;
}
function isUnder(gid, ancestorId) {  // vero se gid è dentro ancestorId (a qualsiasi livello)
  let g = gid == null ? null : gById(gid), n = 0;
  while (g && n++ < 100) { if (g.id === ancestorId) return true; g = g.parent_id == null ? null : gById(g.parent_id); }
  return false;
}
function groupPath(gid) {
  const p = []; let g = gid == null ? null : gById(gid), n = 0;
  while (g && n++ < 100) { p.unshift(g.name); g = g.parent_id == null ? null : gById(g.parent_id); }
  return p.join(" › ");
}
function countExps(gid) {
  let n = TREE.exps.filter(e => e.group_id === gid).length;
  TREE.groups.filter(g => g.parent_id === gid).forEach(g => { n += countExps(g.id); });
  return n;
}
const isArchiveRoot = g => g.archived && (g.parent_id == null || !inArchive(g.parent_id));
function orderedGroups(parent, depth, out) {
  TREE.groups.filter(g => g.parent_id === parent).forEach(g => { out.push([g, depth]); orderedGroups(g.id, depth + 1, out); });
  return out;
}

async function loadList() {
  const d = await api("tree", { q: $("search").value.trim() });
  TREE = { groups: d.groups, exps: d.exps };
  const ids = new Set(TREE.groups.map(g => g.id));
  TREE.groups.forEach(g => { if (g.parent_id != null && !ids.has(g.parent_id)) g.parent_id = null; });
  TREE.exps.forEach(e => { if (e.group_id != null && !ids.has(e.group_id)) e.group_id = null; });
  renderList();
  fillGroupSelect();
}

function fillGroupSelect() {
  const sel = $("groupsel");
  sel.innerHTML = "";
  sel.append(h("option", { value: "" }, "— nessun gruppo —"));
  orderedGroups(null, 0, []).forEach(([g, depth]) => {
    if (inArchive(g.id) && g.id !== curGroup) return;
    sel.append(h("option", { value: String(g.id) },
      "  ".repeat(depth) + "📁 " + g.name + (inArchive(g.id) ? " (archiviato)" : "")));
  });
  sel.value = curGroup == null ? "" : String(curGroup);
}

function renderExp(e, showPath, draggable) {
  const full = (e.name || "Senza nome") + (e.date ? "  ·  " + e.date : "") +
    (e.group_id != null ? "\n📁 " + groupPath(e.group_id) : "");
  const el = h("div", { class: "item" + (e.id === curId ? " sel" : ""), title: full, onclick: () => switchTo(e.id).catch(fail) },
    h("span", { class: "it-name" }, "🧪 " + (e.name || "Senza nome")),
    h("span", { class: "it-date" }, (showPath && e.group_id != null ? groupPath(e.group_id) + " · " : "") + (e.date || "")));
  if (draggable) {
    el.setAttribute("draggable", "true");
    el.addEventListener("dragstart", ev => {
      ev.stopPropagation();
      ev.dataTransfer.setData("text/plain", "exp:" + e.id);
      ev.dataTransfer.effectAllowed = "move";
    });
  }
  return el;
}

function renderGroup(g, arch) {
  const wrap = h("div", { class: "grp" });
  const ctl = h("span", { class: "gctl" });
  let items = null;
  if (!arch) {
    items = [
      ["🧪  Nuovo esperimento in questo gruppo", () => newExp(g.id)],
      ["📁  Nuovo sottogruppo", () => newGroup(g.id)],
      ["✎  Rinomina", () => renameGroup(g)],
      ["📦  Archivia (scompare dall'elenco)", () => archiveGroup(g)],
      ["🗑  Elimina il gruppo…", () => deleteGroup(g), true]];
  } else if (isArchiveRoot(g)) {
    items = [
      ["↩  Ripristina nell'elenco", () => restoreGroup(g)],
      ["🗑  Elimina il gruppo…", () => deleteGroup(g), true]];
  }
  if (items) ctl.append(h("button", { class: "gmore", title: "Azioni del gruppo", onclick: ev => openGroupMenu(ev, items, arch ? null : g) }, "⋯"));
  const head = h("div", { class: "ghead", title: groupPath(g.id), style: "background:" + g.color, onclick: () => toggleGroup(g) },
    h("span", { class: "garrow" }, g.collapsed ? "▸" : "▾"),
    h("span", { class: "gname", title: g.name }, "📁 " + g.name),
    h("span", { class: "gcount" }, String(countExps(g.id))),
    ctl);
  wrap.append(head);
  if (!g.collapsed) {
    const body = h("div", { class: "gbody", style: "border-left-color:" + g.color });
    TREE.groups.filter(x => x.parent_id === g.id && (arch || !x.archived)).forEach(x => body.append(renderGroup(x, arch)));
    TREE.exps.filter(e => e.group_id === g.id).forEach(e => body.append(renderExp(e, false, !arch)));
    if (!body.childNodes.length) body.append(h("div", { class: "sbnote" }, "Vuoto: trascina qui degli esperimenti"));
    wrap.append(body);
  }
  if (!arch) {
    head.setAttribute("draggable", "true");
    head.addEventListener("dragstart", ev => {
      ev.stopPropagation();
      ev.dataTransfer.setData("text/plain", "grp:" + g.id);
      ev.dataTransfer.effectAllowed = "move";
    });
    wrap.addEventListener("dragover", ev => { ev.preventDefault(); ev.stopPropagation(); head.classList.add("dropover"); });
    wrap.addEventListener("dragleave", ev => { if (!wrap.contains(ev.relatedTarget)) head.classList.remove("dropover"); });
    wrap.addEventListener("drop", ev => {
      ev.preventDefault(); ev.stopPropagation(); head.classList.remove("dropover");
      handleDrop(ev.dataTransfer.getData("text/plain"), g.id);
    });
  }
  return wrap;
}

function renderList() {
  const box = $("list");
  box.innerHTML = "";
  const q = $("search").value.trim();
  const roots = TREE.groups.filter(isArchiveRoot);
  $("btnArchive").textContent = archiveMode ? "← Torna ai miei esperimenti" : "📦 Archivio" + (roots.length ? " (" + roots.length + ")" : "");
  if (archiveMode) box.append(h("div", { class: "sbnote" }, "📦 Archivio: qui ci sono i gruppi archiviati. Per rimetterne uno nell'elenco clicca ⋯ → Ripristina."));
  if (q) {
    const found = TREE.exps.filter(e => archiveMode ? (e.group_id != null && inArchive(e.group_id)) : !inArchive(e.group_id));
    if (!found.length) box.append(h("div", { class: "sbnote" }, "Nessun risultato"));
    found.forEach(e => box.append(renderExp(e, true, false)));
    return;
  }
  if (archiveMode) {
    if (!roots.length) box.append(h("div", { class: "sbnote" }, "Nessun gruppo archiviato."));
    roots.forEach(g => box.append(renderGroup(g, true)));
    return;
  }
  TREE.groups.filter(g => g.parent_id == null && !g.archived).forEach(g => box.append(renderGroup(g, false)));
  TREE.exps.filter(e => e.group_id == null).forEach(e => box.append(renderExp(e, false, true)));
  if (!box.childNodes.length) box.append(h("div", { class: "sbnote" }, "Nessun esperimento."));
}

async function handleDrop(payload, gid) {
  const m = /^(exp|grp):(\d+)$/.exec(payload || "");
  if (!m) return;
  const id = Number(m[2]);
  try {
    if (m[1] === "exp") {
      await api("exp_move", { id, group_id: gid });
      if (id === curId) curGroup = gid;
    } else {
      if (gid === id || isUnder(gid, id)) return;      // non si può spostare un gruppo dentro se stesso
      await api("group_move", { id, parent_id: gid });
    }
    if (gid != null) { const t = gById(gid); if (t && t.collapsed) await api("group_update", { id: gid, collapsed: 0 }); }
    await loadList();
  } catch (e) { fail(e); }
}

function closeMenu() { document.querySelectorAll(".gmenu").forEach(m => m.remove()); }
function openGroupMenu(ev, items, colorGroup) {
  ev.stopPropagation();
  closeMenu();
  const r = ev.currentTarget.getBoundingClientRect();
  const m = h("div", { class: "gmenu" });
  if (colorGroup) {
    const row = h("div", { class: "gcolors" }, h("span", null, "Colore"));
    PALETTE.forEach(c => row.append(h("button", {
      class: "sw" + (c === colorGroup.color ? " cur" : ""), style: "background:" + c, title: c,
      onclick: e => { e.stopPropagation(); closeMenu(); setColor(colorGroup, c).catch(fail); }
    })));
    m.append(row);
  }
  items.forEach(([label, fn, danger]) => m.append(h("button", {
    class: danger ? "danger" : "",
    onclick: e => { e.stopPropagation(); closeMenu(); Promise.resolve(fn()).catch(fail); }
  }, label)));
  document.body.append(m);
  const mw = m.offsetWidth, mh = m.offsetHeight;
  m.style.left = Math.max(8, Math.min(r.right - mw, window.innerWidth - mw - 8)) + "px";
  m.style.top = (r.bottom + mh + 8 > window.innerHeight ? Math.max(8, r.top - mh - 4) : r.bottom + 4) + "px";
}

function toggleGroup(g) {
  g.collapsed = g.collapsed ? 0 : 1;
  renderList();
  api("group_update", { id: g.id, collapsed: g.collapsed }).catch(() => {});
}
async function newGroup(parentId) {
  const name = prompt(parentId == null ? "Nome del nuovo gruppo (es. Progetto NG012):" : "Nome del sottogruppo:");
  if (name === null) return;
  await api("group_new", { name: name.trim(), parent_id: parentId });
  await loadList();
}
async function renameGroup(g) {
  const n = prompt("Nome del gruppo:", g.name);
  if (n === null || !n.trim()) return;
  await api("group_update", { id: g.id, name: n.trim() });
  await loadList();
}
async function setColor(g, c) {
  await api("group_update", { id: g.id, color: c });
  await loadList();
}
async function archiveGroup(g) {
  await api("group_update", { id: g.id, archived: 1 });
  await loadList();
  status("📦 «" + g.name + "» archiviato: lo trovi in 📦 Archivio", 7000);
}
async function restoreGroup(g) {
  await api("group_update", { id: g.id, archived: 0 });
  await loadList();
  status("✅ «" + g.name + "» ripristinato", 4000);
}
async function deleteGroup(g) {
  if (!confirm("Eliminare il gruppo «" + g.name + "»?\n\nGli esperimenti NON vengono cancellati: passano al gruppo superiore (o all'elenco principale).")) return;
  await api("group_delete", { id: g.id });
  await loadList();
}

async function switchTo(id) {
  if (id === curId) return;
  await saveNow();
  await openExp(id);
}

async function openExp(id) {
  const d = await api("get", { id });
  curId = id;
  const e = d.exp;
  curGroup = e.group_id == null ? null : e.group_id;
  $("name").value = e.name || "";
  $("date").value = e.date || "";
  $("project").value = e.project || "";
  SECTIONS.forEach(s => { const t = $("sec_" + s[0]); t.value = e[s[0]] || ""; autosize(t); });
  renderAtt(d.attachments);
  refreshDs().catch(() => {});
  dirty = false;
  await loadList();
}

async function newExp(gid) {
  await saveNow();
  const d = await api("new", { group_id: gid == null ? null : gid });
  await openExp(d.id);
  $("name").focus();
  $("name").select();
}

async function deleteExp() {
  if (curId == null) return;
  if (!confirm("Eliminare questo esperimento e i suoi allegati?")) return;
  clearTimeout(saveTimer);
  const d = await api("delete", { id: curId });
  curId = null;
  dirty = false;
  if (d.next) await openExp(d.next); else await newExp();
}

function setActive(k) {
  active = k;
  SECTIONS.forEach(s => $("card_" + s[0]).classList.toggle("active", s[0] === k));
  const sec = SECTIONS.find(s => s[0] === k);
  $("ailabel").textContent = "✨ AI su: " + sec[1].split(" ").slice(1).join(" ");
}

// ---------- allegati ----------
function renderAtt(list) {
  const box = $("attlist");
  box.innerHTML = "";
  if (!list.length) {
    box.append(h("div", { class: "muted" }, "Nessun allegato. Aggiungi o trascina qui i tuoi schemi ChemDraw."));
    return;
  }
  const imgStems = new Set(list.filter(x => /\.(png|jpe?g)$/i.test(x.filename))
    .map(x => x.filename.replace(/\.[^.]*$/, "").toLowerCase()));
  list.forEach(a => {
    const chem = /\.(cdx|cdxml|cd|c3xml)$/i.test(a.filename);
    const isImg = /\.(png|jpe?g)$/i.test(a.filename);
    const stem = a.filename.replace(/\.[^.]*$/, "").toLowerCase();
    const noImg = chem && !imgStems.has(stem);
    box.append(h("div", { class: "att" },
      isImg ? h("img", { class: "thumb", src: "/att?id=" + a.id + "&t=" + TOKEN, alt: a.filename })
            : h("span", null, chem ? "⚗️" : "📄"),
      h("span", { class: "nm" }, a.filename,
        noImg ? h("div", { class: "warn" }, "⚠️ Nessuna immagine associata: nel Word comparirà solo il nome. Incolla lo schema da ChemDraw (⌘C → ⌘V qui) o aggiungi un PNG con lo stesso nome.") : null),
      h("button", { class: "btn violet small", onclick: () => api("att_open", { id: a.id }).catch(fail) }, "Apri"),
      h("button", { class: "btn blue small", onclick: () => api("att_reveal", { id: a.id }).catch(fail) }, "Cartella"),
      h("button", { class: "btn red small", onclick: () => delAtt(a.id) }, "✕")));
  });
}

async function delAtt(id) {
  if (!confirm("Rimuovere l'allegato?")) return;
  await api("att_delete", { id });
  const d = await api("get", { id: curId });
  renderAtt(d.attachments);
}

async function pasteChem(silent) {
  if (curId == null) return;
  status("📋 Leggo gli appunti…");
  try {
    if (dirty) await saveNow();
    const r = await api("clip_paste", { exp: curId });
    status("✅ Struttura incollata: " + r.saved.join(", "), 3000);
    const d = await api("get", { id: curId });
    renderAtt(d.attachments);
  } catch (ex) {
    status("");
    if (!silent) throw ex;
    status("Negli appunti non c'e' nessuna struttura (usa il pulsante 📋 Incolla da ChemDraw per i dettagli)", 4000);
  }
}

async function uploadFiles(files) {
  if (curId == null) return;
  for (const f of files) {
    status("⬆️ Carico " + f.name + "…");
    const r = await fetch("/api/upload?exp=" + curId + "&name=" + encodeURIComponent(f.name),
      { method: "POST", headers: { "X-Token": TOKEN }, body: f });
    if (!r.ok) {
      let m = "";
      try { m = (await r.json()).error; } catch (e) {}
      alert("Errore nel caricamento di " + f.name + ": " + m);
    }
  }
  status("✅ Allegati caricati", 2000);
  const d = await api("get", { id: curId });
  renderAtt(d.attachments);
}

// ---------- AI ----------
const engineName = () => ($("engine").value === "gemini" ? "Gemini" : "Claude");
function setBusy(b) {
  document.querySelectorAll(".aibtn").forEach(x => { x.disabled = b; });
  status(b ? "✨ " + engineName() + " sta lavorando…" : "");
}

async function runAI(mode) {
  let text, target, instr = "";
  if (mode === "titolo") {
    text = SECTIONS.map(s => s[1] + ":\n" + $("sec_" + s[0]).value).join("\n\n");
    target = "name";
  } else {
    text = $("sec_" + active).value;
    target = active;
  }
  if (!text.replace(/[^\p{L}\p{N}]/gu, "")) { alert("Scrivi prima qualcosa nella sezione selezionata."); return; }
  if (mode === "libera") {
    instr = prompt("Cosa vuoi che faccia " + engineName() + " con questo testo?\n(es. riassumi in 3 righe, aggiungi una tabella delle rese)");
    if (!instr) return;
  }
  const engine = $("engine").value, name = engineName();
  setBusy(true);
  try {
    const d = await api("ai", { mode, text, instr, engine });
    showPreview(d.result, target, name);
  } catch (e) {
    if ((e.message || "").startsWith("NOKEY")) openKey("Manca la chiave API di " + name + ": incollala qui sotto.");
    else alert(e.message);
  } finally {
    setBusy(false);
  }
}

function modal(children) {
  const bg = h("div", { class: "modal-bg" }, h("div", { class: "modal" }, children));
  document.body.append(bg);
  return bg;
}

function showPreview(result, target, who) {
  const ta = h("textarea", null);
  ta.value = result;
  const close = () => bg.remove();
  const apply = append => {
    const v = ta.value;
    if (target === "name") {
      $("name").value = v.trim();
    } else {
      const box = $("sec_" + target);
      box.value = append ? (box.value + "\n\n" + v) : v;
      autosize(box);
    }
    close();
    saveNow().catch(fail);
  };
  const btns = [h("button", { class: "btn green", onclick: () => apply(false) }, "✅ Sostituisci")];
  if (target !== "name") btns.push(h("button", { class: "btn blue", onclick: () => apply(true) }, "➕ Aggiungi sotto"));
  btns.push(h("button", { class: "btn grey", onclick: () => close() }, "Annulla"));
  const bg = modal([
    h("div", { class: "h2", style: "margin:0" }, "✨ Proposta di " + (who || "Claude") + " — controlla e modifica prima di applicare"),
    ta,
    h("div", { class: "btns" }, btns)
  ]);
}

async function openKey(hint) {
  let st = { claude: false, gemini: false, gemini_model: "", chemdraw: "", sync_dir: "" };
  try { st = await api("key_status"); } catch (e) {}
  const done = "✅ già salvata (lascia vuoto per non cambiarla)";
  const cin = h("input", { type: "password", autocomplete: "off", placeholder: st.claude ? done : "sk-ant-…" });
  const gin = h("input", { type: "password", autocomplete: "off", placeholder: st.gemini ? done : "incolla la chiave Gemini" });
  const gm = h("input", { type: "text", autocomplete: "off", placeholder: "lascia vuoto: scelta automatica" });
  gm.value = st.gemini_model || "";
  const chem = h("input", { type: "text", autocomplete: "off", placeholder: "lascia vuoto: ricerca automatica" });
  chem.value = st.chemdraw || "";
  const drv = h("input", { type: "text", autocomplete: "off", placeholder: "es. ~/Library/CloudStorage/GoogleDrive-…/Il mio Drive  oppure  G:\\Il mio Drive" });
  drv.value = st.sync_dir || "";
  const drvFound = h("div", { class: "hint" }, "");
  const findDrive = async () => {
    try {
      const r = await api("drive_find");
      drvFound.innerHTML = "";
      if (!r.found.length) { drvFound.textContent = "Non ho trovato Google Drive per desktop su questo computer: installalo da google.com/drive/download oppure scrivi tu il percorso della cartella."; return; }
      drvFound.append("Trovata: ");
      r.found.forEach(p => drvFound.append(h("a", { href: "#", onclick: ev => { ev.preventDefault(); drv.value = p; } }, p), " "));
      drvFound.append(" (clicca per usarla)");
    } catch (e) { fail(e); }
  };
  const close = () => bg.remove();
  const rm = who => h("button", { class: "btn grey small", onclick: async () => {
    try { await api("set_keys", { remove: [who] }); close(); status("✅ Chiave rimossa", 2500); } catch (e) { fail(e); }
  } }, "Rimuovi");
  const bg = modal([
    h("div", { class: "h2", style: "margin:0" }, "🔑 Chiavi API e impostazioni"),
    hint ? h("div", { class: "warn", style: "font-size:14px" }, hint) : null,
    h("div", { class: "keyrow" }, h("b", null, "🟣 Claude (Anthropic)"), st.claude ? rm("claude") : null),
    h("div", { class: "hint" }, "Creala su ",
      h("a", { href: "https://console.anthropic.com", target: "_blank" }, "console.anthropic.com"), " → API keys."),
    cin,
    h("div", { class: "keyrow" }, h("b", null, "🔵 Gemini (Google)"), st.gemini ? rm("gemini") : null),
    h("div", { class: "hint" }, "Creala su ",
      h("a", { href: "https://aistudio.google.com/apikey", target: "_blank" }, "aistudio.google.com/apikey"), "."),
    gin,
    h("div", { class: "hint" }, "Modello Gemini (facoltativo, es. gemini-2.5-flash):"),
    gm,
    h("div", { class: "keyrow" }, h("b", null, "⚗️ App ChemDraw")),
    h("div", { class: "hint" }, "Di solito si trova da sola. Se serve, scrivi il nome (es. ChemDraw 23.1) o il percorso dell'app."),
    chem,
    h("div", { class: "keyrow" }, h("b", null, "☁️ Cartella di Google Drive (facoltativa)")),
    h("div", { class: "hint" }, "Il Word di ogni esperimento e una copia di sicurezza (database e allegati) vengono salvati qui, in «Diario del Ricercatore». Serve l'app Google Drive per desktop, che poi sincronizza online da sola. Si aggiorna da sola ogni 5 minuti se hai fatto modifiche, oppure con «☁️ Sincronizza con Drive»."),
    drv,
    h("div", { class: "row" }, h("button", { class: "btn blue small", onclick: () => findDrive() }, "🔎 Cerca Google Drive"),
      st.sync_last ? h("span", { class: "hint" }, "Ultima sincronizzazione: " + st.sync_last.replace("T", " ")) : null),
    drvFound,
    st.sync_error ? h("div", { class: "warn", style: "font-size:13px" }, "Ultimo errore di sincronizzazione: " + st.sync_error) : null,
    h("div", { class: "hint" }, "Le chiavi vengono salvate solo sul tuo computer, in ~/DiarioRicercatore/config.json."),
    h("div", { class: "btns" },
      h("button", { class: "btn green", onclick: async () => {
        try {
          await api("set_keys", { claude: cin.value, gemini: gin.value, gemini_model: gm.value });
          if (chem.value.trim() !== (st.chemdraw || "")) await api("chemdraw_set", { app: chem.value });
          if (drv.value.trim() !== (st.sync_dir || "")) await api("drive_set", { path: drv.value });
          close(); status("✅ Impostazioni salvate", 2500);
        } catch (e) { fail(e); }
      } }, "Salva"),
      h("button", { class: "btn grey", onclick: () => close() }, "Annulla"))
  ]);
  (hint ? (/Gemini/.test(hint) ? gin : cin) : cin).focus();
}

async function openChemDraw() {
  try {
    status("⚗️ Apro ChemDraw…");
    await api("chemdraw_open");
    status("✅ ChemDraw aperto", 3000);
  } catch (e) {
    status("");
    if (e.message !== "NOCHEMDRAW") return fail(e);
    const v = prompt("Non ho trovato ChemDraw tra le applicazioni.\nScrivi il nome dell'app (es. ChemDraw 23.1) oppure incolla il suo percorso completo (Mac: Finder, seleziona l'app e premi ⌥⌘C · Windows: il percorso di ChemDraw.exe).");
    if (!v || !v.trim()) return;
    await api("chemdraw_set", { app: v });
    try {
      await api("chemdraw_open");
      status("✅ ChemDraw aperto", 3000);
    } catch (e2) {
      await api("chemdraw_set", { app: "" });
      alert("Non riesco ad aprire «" + v.trim() + "». Controlla il nome o il percorso e riprova.");
    }
  }
}

// ---------- Disegno di molecole (JSME) ----------
let jsmeLoading = null;
function loadJsme() {
  if (window.JSApplet && window.JSApplet.JSME) return Promise.resolve();
  if (!jsmeLoading) {
    jsmeLoading = new Promise((res, rej) => {
      const sc = document.createElement("script");
      sc.src = JSME_URL; sc.async = true;
      const fail2 = m => { jsmeLoading = null; rej(new Error(m)); };
      sc.onerror = () => fail2("Non riesco a caricare l'editor di strutture. Serve la connessione a internet (oppure scarica JSME e mettilo nella cartella «jsme» accanto a diario_web.py).");
      document.head.append(sc);
      const t0 = Date.now();
      const iv = setInterval(() => {
        if (window.JSApplet && window.JSApplet.JSME) { clearInterval(iv); res(); }
        else if (Date.now() - t0 > 20000) { clearInterval(iv); fail2("L'editor di strutture non risponde."); }
      }, 200);
    });
  }
  return jsmeLoading;
}

function svgToPng(svg) {
  return new Promise((resolve, reject) => {
    let w = 0, h0 = 0;
    const vb = svg.match(/viewBox\s*=\s*"([\d.\-eE+ ,]+)"/i);
    if (vb) { const p = vb[1].trim().split(/[\s,]+/).map(Number); w = p[2]; h0 = p[3]; }
    const mw = svg.match(/<svg[^>]*\swidth\s*=\s*"([\d.]+)/i), mh = svg.match(/<svg[^>]*\sheight\s*=\s*"([\d.]+)/i);
    if (mw && mh) { w = parseFloat(mw[1]); h0 = parseFloat(mh[1]); }
    if (!(w > 0 && h0 > 0)) { w = 700; h0 = 400; }
    if (!/<svg[^>]*\sxmlns=/i.test(svg)) svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
    if (!/<svg[^>]*\swidth=/i.test(svg)) svg = svg.replace("<svg", '<svg width="' + w + '" height="' + h0 + '"');
    const scale = Math.min(3, 1600 / w);
    const img = new Image();
    img.onload = () => {
      const cv = document.createElement("canvas");
      cv.width = Math.round(w * scale); cv.height = Math.round(h0 * scale);
      const cx = cv.getContext("2d");
      cx.fillStyle = "#fff"; cx.fillRect(0, 0, cv.width, cv.height);
      cx.drawImage(img, 0, 0, cv.width, cv.height);
      cv.toBlob(b => b ? resolve(b) : reject(new Error("Immagine non creata.")), "image/png");
    };
    img.onerror = () => reject(new Error("Non riesco a convertire il disegno in immagine."));
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  });
}

async function molImage(applet, box) {
  let svg = null;
  try { if (applet.getMolecularAreaGraphicsString) svg = applet.getMolecularAreaGraphicsString(); } catch (e) {}
  if (svg && /<svg/i.test(svg)) return svgToPng(svg);
  const cv = box.querySelector("canvas");
  if (cv) {
    return new Promise((res, rej) => {
      const out = document.createElement("canvas");
      out.width = cv.width; out.height = cv.height;
      const cx = out.getContext("2d");
      cx.fillStyle = "#fff"; cx.fillRect(0, 0, out.width, out.height);
      cx.drawImage(cv, 0, 0);
      out.toBlob(b => b ? res(b) : rej(new Error("Immagine non creata.")), "image/png");
    });
  }
  throw new Error("Questa versione dell'editor non permette di ottenere l'immagine del disegno. Disegna in ChemDraw e incolla lo schema (⌘C → ⌘V).");
}

async function openMolEditor() {
  if (curId == null) return;
  await saveNow();
  const holder = h("div", { id: "jsmebox", style: "min-height:380px;overflow:auto" }, h("div", { class: "muted" }, "Carico l'editor di strutture…"));
  const nm = h("input", { type: "text", placeholder: "Nome della molecola (es. NG012)", maxlength: "60" });
  const smi = h("div", { class: "hint" }, "");
  let applet = null;
  const close = () => bg.remove();
  const add = h("button", { class: "btn green", onclick: async () => {
    try {
      if (!applet) return;
      if (!(applet.smiles() || "").trim()) { alert("Disegna prima almeno una molecola."); return; }
      status("🧪 Creo l'immagine…");
      const png = await molImage(applet, holder);
      const mol = applet.molFile();
      const pad = n => String(n).padStart(2, "0");
      const dt = new Date();
      const stamp = dt.getFullYear() + pad(dt.getMonth() + 1) + pad(dt.getDate()) + "-" + pad(dt.getHours()) + pad(dt.getMinutes()) + pad(dt.getSeconds());
      const base = (nm.value.trim().replace(/[^\w.\- ]+/g, "").replace(/\s+/g, "_") || "molecola") + "-" + stamp;
      const files = [new File([png], base + ".png", { type: "image/png" })];
      if (mol && mol.trim()) files.push(new File([mol], base + ".mol", { type: "chemical/x-mdl-molfile" }));
      close();
      await uploadFiles(files);
    } catch (e) { fail(e); }
  } }, "Aggiungi all'esperimento");
  const bg = modal([
    h("div", { class: "h2", style: "margin:0" }, "🧪 Disegna una molecola"),
    h("div", { class: "hint" }, "Disegna la struttura o lo schema. Verrà allegata come immagine (compare nel Word) insieme al file .mol modificabile, che si apre anche con ChemDraw."),
    holder, nm, smi,
    h("div", { class: "btns" }, add, h("button", { class: "btn grey", onclick: () => close() }, "Annulla"))
  ]);
  try {
    await loadJsme();
    holder.innerHTML = "";
    const w = Math.max(320, Math.min(700, Math.floor(window.innerWidth * 0.8)));
    applet = new window.JSApplet.JSME("jsmebox", w + "px", "380px");
    applet.setCallBack("AfterStructureModified", ev => { try { smi.textContent = "SMILES: " + (ev.src.smiles() || ""); } catch (e) {} });
  } catch (e) { holder.textContent = e.message; }
}

// ---------- Cartella Google Drive ----------
async function syncDrive(silent) {
  let st = {};
  try { st = await api("key_status"); } catch (e) {}
  if (!st.sync_dir) { if (!silent) openKey("Scegli prima la cartella di Google Drive qui sotto."); return; }
  try {
    status("☁️ Sincronizzo con Drive…");
    const r = await api("drive_sync");
    status("✅ Drive aggiornato: " + r.documenti + " Word nuovi/aggiornati, " + r.allegati + " allegati copiati (" + r.esperimenti + " esperimenti)", 9000);
  } catch (e) { fail(e); }
}

// ---------- Settori di ricerca ----------
let SECTORS_SEL = null, SECTOR_NAMES = {};
const CHEM_SECTORS = ["chimica", "farmaco"];
function sectorHas(k) { return !SECTORS_SEL || !SECTORS_SEL.length || SECTORS_SEL.indexOf(k) >= 0; }
function applySections(map) {
  if (!map) return;
  SECTIONS.forEach(s => {
    const m = map[s[0]]; if (!m) return;
    s[1] = m[0]; if (m[1] !== undefined) s[2] = m[1];
    const card = $("card_" + s[0]); if (!card) return;
    card.querySelector(".h2").textContent = s[1];
    $("sec_" + s[0]).placeholder = s[2];
  });
  if (typeof active === "string" && $("ailabel")) setActive(active);
}
function applySectors() {
  const chem = !SECTORS_SEL || !SECTORS_SEL.length || SECTORS_SEL.some(s => CHEM_SECTORS.indexOf(s) >= 0);
  ["btnChem", "btnPasteChem", "btnDraw"].forEach(id => { const b = $(id); if (b) b.style.display = chem ? "" : "none"; });
  const names = (SECTORS_SEL || []).map(k => SECTOR_NAMES[k]).filter(Boolean);
  $("btnSector").textContent = "🧭 Settore: " + (names.length ? (names.length > 1 ? names.length + " settori" : names[0]) : "tutti");
  $("btnSector").title = names.length ? names.join(", ") : "Scegli il tuo settore di ricerca";
  renderQuick();
}
async function loadSectors() {
  const st = await api("key_status");
  SECTOR_NAMES = st.sector_names || {};
  SECTORS_SEL = st.sectors == null ? null : st.sectors;
  applySectors();
  applySections(st.sections);
  return st.sectors == null;
}
function openSectors(first) {
  const boxes = {};
  const rows = Object.keys(SECTOR_NAMES).map(k => {
    const cb = h("input", { type: "checkbox" });
    cb.checked = (SECTORS_SEL || []).indexOf(k) >= 0;
    boxes[k] = cb;
    return h("label", { class: "secopt" }, cb, " " + SECTOR_NAMES[k]);
  });
  const close = () => bg.remove();
  const save = async () => {
    const sel = Object.keys(boxes).filter(k => boxes[k].checked);
    try { await api("sector_set", { sectors: sel }); } catch (e) { fail(e); return; }
    SECTORS_SEL = sel; applySectors(); close();
    try { applySections((await api("key_status")).sections); } catch (e) {}
  };
  const bg = modal([
    h("div", { class: "h2", style: "margin:0" }, "🧭 In che settore lavori?"),
    h("div", { class: "hint" }, "Puoi sceglierne più di uno. Il Diario mostra gli strumenti del tuo settore (per esempio il disegno delle molecole per chi fa chimica o farmacologia). Si può cambiare in qualsiasi momento."),
    h("div", { class: "secgrid" }, rows),
    h("div", { class: "btns" }, h("button", { class: "btn green", onclick: save }, "Conferma"),
      first ? null : h("button", { class: "btn grey", onclick: close }, "Annulla"))
  ]);
}

// ---------- Matematica e statistica ----------
const mean = a => a.reduce((s, x) => s + x, 0) / a.length;
const sdev = a => { if (a.length < 2) return NaN; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1)); };
function fmt(v, sig) {
  sig = sig || 3;
  if (v == null || !isFinite(v)) return "–";
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e5 || a < 1e-3) return v.toExponential(sig - 1).replace("e+", "e");
  return String(parseFloat(v.toPrecision(sig)));
}
function lgam(x) {
  const c = [76.18009172947146, -86.50532032941677, 24.01409824083091, -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5];
  let y = x, t = x + 5.5; t -= (x + 0.5) * Math.log(t);
  let s = 1.000000000190015; for (const cc of c) { y += 1; s += cc / y; }
  return -t + Math.log(2.5066282746310005 * s / x);
}
function betacf(a, b, x) {
  const FP = 1e-300; const qab = a + b, qap = a + 1, qam = a - 1;
  let c = 1, d = 1 - qab * x / qap; if (Math.abs(d) < FP) d = FP; d = 1 / d; let hh = d;
  for (let m = 1; m <= 300; m++) {
    const m2 = 2 * m; let aa = m * (b - m) * x / ((qam + m2) * (a + m2));
    d = 1 + aa * d; if (Math.abs(d) < FP) d = FP; c = 1 + aa / c; if (Math.abs(c) < FP) c = FP; d = 1 / d; hh *= d * c;
    aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
    d = 1 + aa * d; if (Math.abs(d) < FP) d = FP; c = 1 + aa / c; if (Math.abs(c) < FP) c = FP; d = 1 / d;
    const del = d * c; hh *= del; if (Math.abs(del - 1) < 3e-12) break;
  }
  return hh;
}
function incbeta(x, a, b) {
  if (x <= 0) return 0; if (x >= 1) return 1;
  const bt = Math.exp(lgam(a + b) - lgam(a) - lgam(b) + a * Math.log(x) + b * Math.log(1 - x));
  return x < (a + 1) / (a + b + 2) ? bt * betacf(a, b, x) / a : 1 - bt * betacf(b, a, 1 - x) / b;
}
const T975 = [0, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042];
function tcrit(df) { if (df < 1) return NaN; if (df <= 30) return T975[Math.round(df)]; if (df <= 60) return 2.0 - (df - 30) * 0.00133; if (df <= 120) return 2.0 - 0.04 - (df - 60) * 0.0003; return 1.96; }
function pStars(p) { return p < 0.001 ? "***" : p < 0.01 ? "**" : p < 0.05 ? "*" : "ns"; }
function fmtP(p) { return p < 0.0001 ? "p < 0.0001" : "p = " + p.toFixed(4).replace(/0+$/, "").replace(/\.$/, ""); }
function welch(a, b) {
  const n1 = a.length, n2 = b.length; if (n1 < 2 || n2 < 2) return null;
  const v1 = sdev(a) ** 2 / n1, v2 = sdev(b) ** 2 / n2; if (v1 + v2 === 0) return null;
  const t = (mean(a) - mean(b)) / Math.sqrt(v1 + v2);
  const df = (v1 + v2) ** 2 / (v1 * v1 / (n1 - 1) + v2 * v2 / (n2 - 1));
  return { t, df, p: incbeta(df / (df + t * t), df / 2, 0.5) };
}
function anova1(groups) {
  const k = groups.length, all = [].concat(...groups), N = all.length; if (k < 2 || N - k < 1) return null;
  const gm = mean(all); let ssb = 0, ssw = 0;
  groups.forEach(g => { const m = mean(g); ssb += g.length * (m - gm) ** 2; g.forEach(v => { ssw += (v - m) ** 2; }); });
  if (ssw === 0) return null;
  const d1 = k - 1, d2 = N - k, F = (ssb / d1) / (ssw / d2);
  return { F, d1, d2, p: incbeta(d2 / (d2 + d1 * F), d2 / 2, d1 / 2) };
}
function solveLin(A, b) {
  const n = b.length, M = A.map((r, i) => r.concat([b[i]]));
  for (let i = 0; i < n; i++) {
    let p = i; for (let r = i + 1; r < n; r++) if (Math.abs(M[r][i]) > Math.abs(M[p][i])) p = r;
    if (Math.abs(M[p][i]) < 1e-300) return null;
    const tmp = M[i]; M[i] = M[p]; M[p] = tmp;
    for (let r = 0; r < n; r++) { if (r === i) continue; const f = M[r][i] / M[i][i]; for (let c = i; c <= n; c++) M[r][c] -= f * M[i][c]; }
  }
  return M.map((r, i) => r[n] / r[i]);
}
function invMat(A) {
  const n = A.length, cols = [];
  for (let j = 0; j < n; j++) { const e = Array(n).fill(0); e[j] = 1; const s = solveLin(A, e); if (!s) return null; cols.push(s); }
  return A.map((_, i) => cols.map(c => c[i]));
}
// minimi quadrati non lineari (Levenberg-Marquardt) su model(x, p); free = indici dei parametri liberi
function lsq(model, xs, ys, p0, free) {
  let p = p0.slice(), lam = 1e-2;
  const sse = pp => { let s = 0; for (let i = 0; i < xs.length; i++) { const r = ys[i] - model(xs[i], pp); s += r * r; } return s; };
  const jac = pp => xs.map(x => free.map(k => {
    const hh = 1e-6 * Math.max(Math.abs(pp[k]), 1e-3), q = pp.slice(), q2 = pp.slice(); q[k] += hh; q2[k] -= hh;
    return (model(x, q) - model(x, q2)) / (2 * hh);
  }));
  const normal = pp => {
    const J = jac(pp), k = free.length, A = Array.from({ length: k }, () => Array(k).fill(0)), g = Array(k).fill(0);
    for (let i = 0; i < xs.length; i++) { const r = ys[i] - model(xs[i], pp); for (let a = 0; a < k; a++) { g[a] += J[i][a] * r; for (let b = 0; b < k; b++) A[a][b] += J[i][a] * J[i][b]; } }
    return { A, g };
  };
  let cost = sse(p);
  if (!isFinite(cost)) return null;
  for (let it = 0; it < 300; it++) {
    const { A, g } = normal(p); let improved = false, tiny = false;
    for (let tr = 0; tr < 14; tr++) {
      const B = A.map((row, a) => row.map((v, b) => a === b ? v * (1 + lam) + 1e-12 : v));
      const d = solveLin(B, g); if (!d) { lam *= 10; continue; }
      const q = p.slice(); free.forEach((kk, a) => { q[kk] += d[a]; });
      const c = sse(q);
      if (isFinite(c) && c < cost) { tiny = (cost - c) / (cost + 1e-30) < 1e-13; p = q; cost = c; lam = Math.max(lam / 5, 1e-9); improved = true; break; }
      lam *= 5;
    }
    if (!improved || tiny) break;
  }
  const { A } = normal(p), inv = invMat(A), df = xs.length - free.length;
  const se = Array(p.length).fill(NaN);
  if (inv && df > 0) { const s2 = cost / df; free.forEach((k, a) => { se[k] = Math.sqrt(Math.max(0, s2 * inv[a][a])); }); }
  return { p, sse: cost, df, se };
}
function r2of(ys, sse) { const m = mean(ys); const sst = ys.reduce((s, y) => s + (y - m) ** 2, 0); return sst > 0 ? 1 - sse / sst : NaN; }

// curva dose-risposta a 4 parametri: y = bottom + (top-bottom) / (1 + 10^((logEC50 - logx) * hill))
const model4 = (x, p) => p[0] + (p[1] - p[0]) / (1 + Math.pow(10, Math.max(-300, Math.min(300, (p[2] - x) * p[3]))));
function fit4PL(pts, fix) {
  const lx = pts.map(q => Math.log10(q.x)), ys = pts.map(q => q.y);
  const ux = Array.from(new Set(lx)).sort((a, b) => a - b);
  if (ux.length < (fix ? 3 : 4) || pts.length < (fix ? 3 : 5)) return null;
  const mu = ux.map(u => mean(ys.filter((_, i) => lx[i] === u)));
  const lo = Math.min.apply(null, mu), hi = Math.max.apply(null, mu), dec = mu[0] > mu[mu.length - 1];
  const mid = (lo + hi) / 2; let c0 = ux[Math.floor(ux.length / 2)];
  for (let i = 0; i < ux.length - 1; i++) if ((mu[i] - mid) * (mu[i + 1] - mid) <= 0) { c0 = (ux[i] + ux[i + 1]) / 2; break; }
  const free = fix ? [2, 3] : [0, 1, 2, 3]; let best = null;
  for (const hh of [1, 0.6, 2]) for (const dc of [0, -0.5, 0.5, 1, -1]) {
    const r = lsq(model4, lx, ys, [fix ? fix[0] : lo, fix ? fix[1] : hi, c0 + dc, dec ? -hh : hh], free);
    if (r && (!best || r.sse < best.sse)) best = r;
  }
  if (!best) return null;
  const p = best.p, t = tcrit(best.df), c = p[2], se = best.se[2];
  const out = { bottom: p[0], top: p[1], logc: c, hill: p[3], ec50: Math.pow(10, c), sse: best.sse, df: best.df, r2: r2of(ys, best.sse), n: pts.length, se: best.se, dec };
  if (isFinite(se) && isFinite(t)) out.ci = [Math.pow(10, c - t * se), Math.pow(10, c + t * se)];
  out.curve = [];
  const a = ux[0] - 0.4, b = ux[ux.length - 1] + 0.4;
  for (let i = 0; i <= 120; i++) { const x = a + (b - a) * i / 120; out.curve.push([Math.pow(10, x), model4(x, p)]); }
  return out;
}
function fitLinear(pts) {
  const n = pts.length; if (n < 3) return null;
  const mx = mean(pts.map(q => q.x)), my = mean(pts.map(q => q.y));
  let sxx = 0, sxy = 0; pts.forEach(q => { sxx += (q.x - mx) ** 2; sxy += (q.x - mx) * (q.y - my); });
  if (sxx === 0) return null;
  const m = sxy / sxx, q0 = my - m * mx; let sse = 0; pts.forEach(q => { sse += (q.y - (q0 + m * q.x)) ** 2; });
  const s2 = sse / (n - 2), sem = Math.sqrt(s2 / sxx), seq = Math.sqrt(s2 * (1 / n + mx * mx / sxx));
  const xs = pts.map(q => q.x), a = Math.min.apply(null, xs), b = Math.max.apply(null, xs);
  return { slope: m, intercept: q0, se_slope: sem, se_int: seq, r2: r2of(pts.map(q => q.y), sse), n, curve: [[a, q0 + m * a], [b, q0 + m * b]] };
}
function fitMM(pts) {
  const xs = pts.map(q => q.x), ys = pts.map(q => q.y); if (new Set(xs).size < 3 || pts.length < 4) return null;
  const model = (x, p) => p[0] * x / (p[1] + x), vmax = Math.max.apply(null, ys), sx = xs.slice().sort((a, b) => a - b);
  let best = null;
  for (const f of [1, 0.3, 3]) { const r = lsq(model, xs, ys, [vmax * 1.1, Math.max(1e-12, sx[Math.floor(sx.length / 2)]) * f], [0, 1]); if (r && (!best || r.sse < best.sse)) best = r; }
  if (!best) return null;
  const hi = sx[sx.length - 1], curve = [];
  for (let i = 0; i <= 100; i++) { const x = hi * 1.05 * i / 100; curve.push([x, model(x, best.p)]); }
  return { vmax: best.p[0], km: best.p[1], se: best.se, r2: r2of(ys, best.sse), n: pts.length, curve };
}

function fitPoly2(pts) {
  const n = pts.length; if (n < 4) return null;
  const S = k => pts.reduce((s, q) => s + Math.pow(q.x, k), 0), T = k => pts.reduce((s, q) => s + q.y * Math.pow(q.x, k), 0);
  const c = solveLin([[n, S(1), S(2)], [S(1), S(2), S(3)], [S(2), S(3), S(4)]], [T(0), T(1), T(2)]); if (!c) return null;
  let sse = 0; pts.forEach(q => { sse += (q.y - (c[0] + c[1] * q.x + c[2] * q.x * q.x)) ** 2; });
  const xs = pts.map(q => q.x), a = Math.min.apply(null, xs), b = Math.max.apply(null, xs), curve = [];
  for (let i = 0; i <= 100; i++) { const x = a + (b - a) * i / 100; curve.push([x, c[0] + c[1] * x + c[2] * x * x]); }
  return { c, r2: r2of(pts.map(q => q.y), sse), n, curve };
}
function fitExp(pts) {
  const p = pts.filter(q => q.y > 0); if (p.length < 3) return null;
  const lin = fitLinear(p.map(q => ({ x: q.x, y: Math.log(q.y) }))); if (!lin) return null;
  const model = (x, q) => q[0] * Math.exp(Math.max(-700, Math.min(700, q[1] * x)));
  const r = lsq(model, p.map(q => q.x), p.map(q => q.y), [Math.exp(lin.intercept), lin.slope], [0, 1]); if (!r) return null;
  const xs = p.map(q => q.x), a = Math.min.apply(null, xs), b = Math.max.apply(null, xs), curve = [];
  for (let i = 0; i <= 100; i++) { const x = a + (b - a) * i / 100; curve.push([x, model(x, r.p)]); }
  return { a: r.p[0], k: r.p[1], se: r.se, r2: r2of(p.map(q => q.y), r.sse), n: p.length, curve };
}
function fitPower(pts) {
  const p = pts.filter(q => q.y > 0 && q.x > 0); if (p.length < 3) return null;
  const lin = fitLinear(p.map(q => ({ x: Math.log(q.x), y: Math.log(q.y) }))); if (!lin) return null;
  const model = (x, q) => q[0] * Math.pow(x, q[1]);
  const r = lsq(model, p.map(q => q.x), p.map(q => q.y), [Math.exp(lin.intercept), lin.slope], [0, 1]); if (!r) return null;
  const xs = p.map(q => q.x), a = Math.min.apply(null, xs), b = Math.max.apply(null, xs), curve = [];
  for (let i = 0; i <= 100; i++) { const x = a + (b - a) * i / 100; curve.push([x, model(x, r.p)]); }
  return { a: r.p[0], b: r.p[1], se: r.se, r2: r2of(p.map(q => q.y), r.sse), n: p.length, curve };
}

// ---------- Lettura della tabella incollata ----------
function splitLine(l) { if (l.indexOf("\t") >= 0) return l.split("\t"); if (l.indexOf(";") >= 0) return l.split(";"); return l.trim().split(/\s+/); }
function num(c) {
  if (c == null) return NaN; c = String(c).trim().replace(",", ".");
  return /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(c) ? parseFloat(c) : NaN;
}
function parseSeries(text, kind) {
  const series = []; let cur = null;
  for (const raw of String(text).replace(/\r/g, "").split("\n")) {
    const line = raw.trim(); if (!line) continue;
    if (line[0] === "#") { cur = { name: line.slice(1).trim() || ("Serie " + (series.length + 1)), rows: [] }; series.push(cur); continue; }
    if (!cur) { cur = { name: "", rows: [] }; series.push(cur); }
    const cells = splitLine(line).map(c => c.trim());
    if (kind === "bars") {
      const ys = cells.slice(1).map(num).filter(isFinite);
      if (cells[0] && ys.length) cur.rows.push({ label: cells[0], ys });
    } else {
      const x = num(cells[0]); if (!isFinite(x)) continue;
      const ys = cells.slice(1).map(num).filter(isFinite);
      if (ys.length) cur.rows.push({ x, ys });
    }
  }
  return series.filter(s => s.rows.length);
}

// ---------- Analisi: ritorna grafico, riassunto e tabella ----------
const TEXT_KINDS = { dr: "Dose-risposta (IC50 / EC50)", xy: "Grafico x-y (con fit)", bars: "Barre: gruppi, media ± DS e test", table: "Tabella libera con grafico" };
const DS_KINDS = Object.assign({}, TEXT_KINDS);
const DS_EXAMPLES = {
  dr: "# Composto A\n0.001\t98\t101\t97\n0.01\t95\t93\t96\n0.1\t80\t84\t78\n1\t48\t52\t50\n10\t15\t18\t12\n100\t4\t6\t3\n# Composto B\n0.001\t100\t99\t102\n0.01\t99\t97\t100\n0.1\t92\t90\t94\n1\t75\t72\t78\n10\t40\t38\t45\n100\t12\t10\t14",
  xy: "0\t0.1\t0.2\t0.1\n10\t0.9\t1.0\t0.8\n20\t1.8\t1.7\t1.9\n30\t2.6\t2.7\t2.5\n40\t3.6\t3.5\t3.7\n50\t4.4\t4.5\t4.3",
  bars: "Controllo\t100\t96\t104\t99\nTrattato 1\t72\t68\t75\t70\nTrattato 2\t45\t50\t41\t47",
  table: "Prova\tLearning rate\tEpoche\tAccuratezza\nrun1\t0.01\t20\t0.81\nrun2\t0.001\t20\t0.86\nrun3\t0.001\t50\t0.89\nrun4\t0.0001\t50\t0.84"
};
function analyzeTable(spec) {
  const o = spec.opts || {}, warns = [];
  const rows = String(spec.text).replace(/\r/g, "").split("\n").filter(l => l.trim()).map(l => splitLine(l).map(c => c.trim()));
  const chart = { kind: "bars", title: spec.title || "", xlabel: spec.xlabel || "", ylabel: spec.ylabel || "", series: [], bars: [] };
  if (rows.length < 2) return { chart, summary: "", table: [], warns: ["Scrivi la riga di intestazione e almeno una riga di dati."] };
  const head = rows[0], body = rows.slice(1).map(r => head.map((_, i) => r[i] || ""));
  const table = [head].concat(body);
  const ci = Math.min(Math.max(parseInt(o.col, 10) || (head.length - 1), 1), head.length - 1);
  const vals = body.map(r => num(r[ci])), ok = vals.filter(isFinite);
  let summary = "";
  if (head.length < 2) { warns.push("Servono almeno due colonne."); return { chart, summary, table, warns }; }
  if (ok.length) summary = "Colonna «" + head[ci] + "»: n = " + ok.length + ", media = " + fmt(mean(ok), 4) + (ok.length > 1 ? ", DS = " + fmt(sdev(ok), 3) : "") + ", min = " + fmt(Math.min.apply(null, ok), 4) + ", max = " + fmt(Math.max.apply(null, ok), 4) + ".";
  else warns.push("La colonna scelta per il grafico non contiene numeri.");
  const xs = body.map(r => num(r[0]));
  if (ok.length && xs.every(isFinite) && body.length >= 2) {
    const sub = analyze({ kind: "xy", title: spec.title, unit: spec.unit, xlabel: spec.xlabel || head[0], ylabel: spec.ylabel || head[ci], opts: o,
      text: body.map((r, i) => isFinite(vals[i]) ? xs[i] + "\t" + vals[i] : "").filter(Boolean).join("\n") });
    return { chart: sub.chart, summary: [summary, sub.summary].filter(Boolean).join("\n"), table, warns: warns.concat(sub.warns) };
  }
  chart.bars = body.map((r, i) => isFinite(vals[i]) ? { label: r[0] || ("riga " + (i + 1)), ys: [vals[i]], mean: vals[i], sd: NaN, n: 1 } : null).filter(Boolean);
  chart.xlabel = spec.xlabel || ""; chart.ylabel = spec.ylabel || head[ci];
  return { chart, summary, table, warns };
}
function analyze(spec) {
  if (spec.kind === "table") return analyzeTable(spec);
  const kind = spec.kind, o = spec.opts || {}, unit = spec.unit || "";
  const raw = parseSeries(spec.text, kind), lines = [], warns = [];
  const chart = { kind, title: spec.title || "", xlabel: spec.xlabel || "", ylabel: spec.ylabel || "", logx: kind === "dr" || !!o.logx, logy: kind === "xy" && !!o.logy, series: [], bars: [] };
  let table = [];
  if (!raw.length) return { chart, summary: "", table, warns: ["Inserisci i dati nella tabella."] };
  if (kind === "bars") {
    const rows = [].concat(...raw.map(s => s.rows));
    chart.bars = rows.map(r => ({ label: r.label, ys: r.ys, mean: mean(r.ys), sd: sdev(r.ys), n: r.ys.length }));
    table = [["Gruppo", "Media", "DS", "SEM", "n"]].concat(chart.bars.map(b => [b.label, fmt(b.mean, 4), fmt(b.sd, 3), fmt(b.sd / Math.sqrt(b.n), 3), String(b.n)]));
    const groups = rows.map(r => r.ys);
    if (groups.length === 2) {
      const w = welch(groups[0], groups[1]);
      if (w) { lines.push("Test t di Welch (" + rows[0].label + " vs " + rows[1].label + "): t = " + fmt(w.t, 3) + ", gdl = " + fmt(w.df, 3) + ", " + fmtP(w.p) + " (" + pStars(w.p) + ")."); chart.note = fmtP(w.p) + " (" + pStars(w.p) + ", Welch)"; }
      else warns.push("Per il test servono almeno 2 valori per gruppo.");
    } else if (groups.length > 2) {
      const a = anova1(groups);
      if (a) { lines.push("ANOVA a una via: F(" + a.d1 + ", " + a.d2 + ") = " + fmt(a.F, 3) + ", " + fmtP(a.p) + " (" + pStars(a.p) + ")."); chart.note = "ANOVA " + fmtP(a.p) + " (" + pStars(a.p) + ")"; }
      else warns.push("Per l'ANOVA servono almeno 2 valori per gruppo.");
    }
    if (groups.some(g => g.length < 3)) warns.push("Alcuni gruppi hanno meno di 3 repliche: le statistiche sono poco affidabili.");
    return { chart, summary: lines.join("\n"), table, warns };
  }
  const lab = n => (o.label && o.label !== "auto") ? o.label : (n ? "IC50" : "EC50");
  raw.forEach((s, si) => {
    const name = s.name || spec.title || "Dati";
    const color = CHART_COLORS[si % CHART_COLORS.length], pts = [], flat = [];
    s.rows.forEach(r => {
      if (kind === "dr" && r.x <= 0) { warns.push("Concentrazione ≤ 0 (" + r.x + ") non inclusa nel grafico e nel fit."); return; }
      if (kind === "xy" && o.logx && r.x <= 0) { warns.push("Valori di x ≤ 0 non inclusi (asse logaritmico)."); return; }
      if (kind === "xy" && o.logy && r.ys.some(v => v <= 0)) { warns.push("Valori di y ≤ 0 non inclusi (asse y logaritmico)."); r = { x: r.x, ys: r.ys.filter(v => v > 0) }; if (!r.ys.length) return; }
      pts.push({ x: r.x, ys: r.ys, mean: mean(r.ys), sd: sdev(r.ys), n: r.ys.length });
      r.ys.forEach(y => flat.push({ x: r.x, y }));
    });
    const ser = { name, color, pts, curve: null };
    if (kind === "dr") {
      const f = fit4PL(flat, o.fixTB ? [0, 100] : null);
      if (!f) { warns.push(name + ": servono almeno 5 punti su 4 concentrazioni diverse per il fit (3 con estremi fissi)."); }
      else {
        ser.curve = f.curve; ser.fit = f;
        const L = lab(f.dec), u = unit ? " " + unit : "";
        let s1 = name + ": " + L + " = " + fmt(f.ec50, 3) + u;
        if (f.ci) s1 += " (IC 95%: " + fmt(f.ci[0], 3) + " – " + fmt(f.ci[1], 3) + ")"; else warns.push(name + ": intervallo di confidenza non calcolabile (pochi punti).");
        s1 += "; pendenza (Hill) = " + fmt(f.hill, 3) + "; top = " + fmt(f.top, 3) + "; bottom = " + fmt(f.bottom, 3) + "; R² = " + fmt(f.r2, 4) + "; n = " + f.n + " (gdl " + f.df + ").";
        lines.push(s1);
        ser.legend = name + "  " + L + " " + fmt(f.ec50, 3) + u;
        if (f.r2 < 0.9) warns.push(name + ": R² basso (" + fmt(f.r2, 3) + "): controlla i dati o prova gli estremi fissi.");
        if (f.ec50 < Math.min.apply(null, flat.map(q => q.x)) || f.ec50 > Math.max.apply(null, flat.map(q => q.x))) warns.push(name + ": " + L + " fuori dall'intervallo di concentrazioni misurato, il valore è un'estrapolazione.");
      }
    } else if (o.fit === "lineare") {
      const f = fitLinear(flat);
      if (f) { ser.curve = f.curve; lines.push(name + ": y = " + fmt(f.slope, 4) + " · x " + (f.intercept < 0 ? "− " : "+ ") + fmt(Math.abs(f.intercept), 4) + "; pendenza ± ES = " + fmt(f.slope, 4) + " ± " + fmt(f.se_slope, 2) + "; R² = " + fmt(f.r2, 4) + "; n = " + f.n + "."); ser.legend = name + "  R² " + fmt(f.r2, 3); }
      else warns.push(name + ": servono almeno 3 punti per la retta.");
    } else if (o.fit === "poly2") {
      const f = fitPoly2(flat);
      if (f) { ser.curve = f.curve; lines.push(name + ": y = " + fmt(f.c[2], 4) + " · x² " + (f.c[1] < 0 ? "− " : "+ ") + fmt(Math.abs(f.c[1]), 4) + " · x " + (f.c[0] < 0 ? "− " : "+ ") + fmt(Math.abs(f.c[0]), 4) + "; R² = " + fmt(f.r2, 4) + "; n = " + f.n + "."); ser.legend = name + "  R² " + fmt(f.r2, 3); }
      else warns.push(name + ": servono almeno 4 punti per il polinomio di 2° grado.");
    } else if (o.fit === "exp") {
      const f = fitExp(flat);
      if (f) {
        ser.curve = f.curve;
        const t2 = f.k > 0 ? "tempo di raddoppio = " + fmt(Math.LN2 / f.k, 3) : "emivita = " + fmt(Math.LN2 / Math.abs(f.k), 3);
        lines.push(name + ": y = " + fmt(f.a, 4) + " · exp(" + fmt(f.k, 4) + " · x); k = " + fmt(f.k, 4) + " ± " + fmt(f.se[1], 2) + "; " + t2 + (unit ? " " + unit : "") + "; R² = " + fmt(f.r2, 4) + "; n = " + f.n + ".");
        ser.legend = name + "  k " + fmt(f.k, 3);
      } else warns.push(name + ": servono almeno 3 punti con y > 0 per l'esponenziale.");
    } else if (o.fit === "power") {
      const f = fitPower(flat);
      if (f) { ser.curve = f.curve; lines.push(name + ": y = " + fmt(f.a, 4) + " · x^" + fmt(f.b, 4) + "; esponente = " + fmt(f.b, 4) + " ± " + fmt(f.se[1], 2) + "; R² = " + fmt(f.r2, 4) + "; n = " + f.n + "."); ser.legend = name + "  esp. " + fmt(f.b, 3); }
      else warns.push(name + ": servono almeno 3 punti con x > 0 e y > 0 per la legge di potenza.");
    } else if (o.fit === "mm") {
      const f = fitMM(flat);
      if (f) { ser.curve = f.curve; lines.push(name + ": Vmax = " + fmt(f.vmax, 3) + " ± " + fmt(f.se[0], 2) + "; Km = " + fmt(f.km, 3) + " ± " + fmt(f.se[1], 2) + (unit ? " " + unit : "") + "; R² = " + fmt(f.r2, 4) + "; n = " + f.n + "."); ser.legend = name + "  Km " + fmt(f.km, 3); }
      else warns.push(name + ": servono almeno 4 punti su 3 valori di x diversi per Michaelis-Menten.");
    }
    if (pts.some(q => q.n < 2)) warns.push(name + ": alcuni punti hanno una sola replica (niente barre di errore).");
    chart.series.push(ser);
  });
  // tabella: x e, per ogni serie, media ± DS (n)
  const xs = Array.from(new Set([].concat(...chart.series.map(s => s.pts.map(q => q.x))))).sort((a, b) => a - b);
  table = [[(spec.xlabel || "x") + (unit && kind === "dr" ? " (" + unit + ")" : "")].concat(chart.series.map(s => (chart.series.length > 1 ? s.name + ": " : "") + "media ± DS (n)"))];
  xs.forEach(x => table.push([fmt(x, 4)].concat(chart.series.map(s => { const q = s.pts.find(p => p.x === x); return q ? fmt(q.mean, 4) + (isFinite(q.sd) ? " ± " + fmt(q.sd, 2) : "") + " (" + q.n + ")" : "–"; }))));
  return { chart, summary: lines.join("\n"), table, warns: Array.from(new Set(warns)) };
}

// ---------- Disegno del grafico (SVG) ----------
const CHART_COLORS = ["#2563EB", "#DC2626", "#059669", "#D97706", "#7C3AED", "#DB2777", "#0891B2", "#65A30D"];
const xesc = t => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
function niceTicks(lo, hi, n) {
  n = n || 6; if (!(hi > lo)) { lo -= 1; hi += 1; }
  const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag;
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag, s = Math.floor(lo / step + 1e-9) * step, e = Math.ceil(hi / step - 1e-9) * step, t = [];
  for (let v = s; v <= e + step * 1e-6; v += step) t.push(parseFloat(v.toPrecision(12)));
  return t;
}
function chartSVG(c) {
  const W = 680, H = 440, many = c.kind !== "bars" && c.series.length > 1;
  const L = 74, R = many ? 20 : 24, T = c.title ? 44 : 22, B = 64, pw = W - L - R, ph = H - T - B;
  let xmin, xmax, ymin = Infinity, ymax = -Infinity, cats = [];
  const ylog = !!c.logy && c.kind !== "bars";
  const upd = v => { if (isFinite(v) && (!ylog || v > 0)) { ymin = Math.min(ymin, v); ymax = Math.max(ymax, v); } };
  if (c.kind === "bars") {
    cats = c.bars; c.bars.forEach(b => { upd(b.mean + (isFinite(b.sd) ? b.sd : 0)); upd(b.mean - (isFinite(b.sd) ? b.sd : 0)); b.ys.forEach(upd); });
    ymin = Math.min(0, ymin);
  } else {
    xmin = Infinity; xmax = -Infinity;
    c.series.forEach(s => {
      s.pts.forEach(q => { xmin = Math.min(xmin, q.x); xmax = Math.max(xmax, q.x); q.ys.forEach(upd); upd(q.mean - (isFinite(q.sd) ? q.sd : 0)); upd(q.mean + (isFinite(q.sd) ? q.sd : 0)); });
      if (s.curve) s.curve.forEach(pt => { xmin = Math.min(xmin, pt[0]); xmax = Math.max(xmax, pt[0]); upd(pt[1]); });
    });
    if (!isFinite(xmin)) return '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H + '"><rect width="100%" height="100%" fill="#fff"/></svg>';
  }
  if (!isFinite(ymin)) { ymin = 0; ymax = 1; }
  let yt, y0, y1, sy;
  if (ylog) {
    const a = Math.floor(Math.log10(ymin) - 1e-9), b0 = Math.ceil(Math.log10(ymax) + 1e-9), b = b0 === a ? b0 + 1 : b0;
    yt = []; for (let e = a; e <= b; e++) yt.push(Math.pow(10, e));
    y0 = Math.pow(10, a); y1 = Math.pow(10, b);
    sy = v => T + ph - (Math.log10(Math.max(v, y0)) - a) / (b - a) * ph;
  } else {
    yt = niceTicks(ymin - (c.kind === "bars" ? 0 : (ymax - ymin) * 0.04), ymax + (ymax - ymin) * 0.06, 6); y0 = yt[0]; y1 = yt[yt.length - 1];
    sy = v => T + ph - (v - y0) / (y1 - y0) * ph;
  }
  let sx, xticks = [], out = [];
  if (c.kind === "bars") { sx = i => L + pw * (i + 0.5) / cats.length; }
  else if (c.logx) {
    const a = Math.floor(Math.log10(xmin) - 1e-9), b = Math.ceil(Math.log10(xmax) + 1e-9), bb = b === a ? b + 1 : b;
    sx = v => L + (Math.log10(v) - a) / (bb - a) * pw;
    for (let e = a; e <= bb; e++) xticks.push([e, "10"]);
  } else {
    const xt = niceTicks(xmin, xmax, 6), a = xt[0], b = xt[xt.length - 1];
    sx = v => L + (v - a) / (b - a) * pw; xt.forEach(v => xticks.push([v, null]));
  }
  out.push('<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H + '" font-family="Arial, Helvetica, sans-serif">');
  out.push('<rect width="100%" height="100%" fill="#ffffff"/>');
  if (c.title) out.push('<text x="' + W / 2 + '" y="26" text-anchor="middle" font-size="16" font-weight="bold" fill="#111827">' + xesc(c.title) + "</text>");
  yt.forEach(v => {
    out.push('<line x1="' + L + '" x2="' + (L + pw) + '" y1="' + sy(v) + '" y2="' + sy(v) + '" stroke="#E5E7EB" stroke-width="1"/>');
    out.push(ylog ? '<text x="' + (L - 8) + '" y="' + (sy(v) + 4) + '" text-anchor="end" font-size="12" fill="#374151">10<tspan dy="-5" font-size="9">' + Math.round(Math.log10(v)) + "</tspan></text>"
      : '<text x="' + (L - 8) + '" y="' + (sy(v) + 4) + '" text-anchor="end" font-size="12" fill="#374151">' + fmt(v, 4) + "</text>");
  });
  if (c.kind !== "bars") xticks.forEach(([v, tag]) => {
    const x = tag ? sx(Math.pow(10, v)) : sx(v);
    out.push('<line x1="' + x + '" x2="' + x + '" y1="' + (T + ph) + '" y2="' + (T + ph + 5) + '" stroke="#374151"/>');
    out.push(tag ? '<text x="' + x + '" y="' + (T + ph + 20) + '" text-anchor="middle" font-size="12" fill="#374151">10<tspan dy="-5" font-size="9">' + v + "</tspan></text>"
      : '<text x="' + x + '" y="' + (T + ph + 20) + '" text-anchor="middle" font-size="12" fill="#374151">' + fmt(v, 4) + "</text>");
  });
  out.push('<line x1="' + L + '" x2="' + L + '" y1="' + T + '" y2="' + (T + ph) + '" stroke="#374151" stroke-width="1.4"/>');
  out.push('<line x1="' + L + '" x2="' + (L + pw) + '" y1="' + (T + ph) + '" y2="' + (T + ph) + '" stroke="#374151" stroke-width="1.4"/>');
  if (c.kind === "bars") {
    const bw = Math.min(90, pw / cats.length * 0.6);
    cats.forEach((b, i) => {
      const x = sx(i), col = CHART_COLORS[i % CHART_COLORS.length], top = sy(Math.max(b.mean, 0)), base = sy(0);
      out.push('<rect x="' + (x - bw / 2) + '" y="' + Math.min(top, base) + '" width="' + bw + '" height="' + Math.abs(base - top) + '" fill="' + col + '" fill-opacity="0.75" stroke="' + col + '"/>');
      if (isFinite(b.sd)) {
        const a = sy(b.mean - b.sd), z = sy(b.mean + b.sd);
        out.push('<path d="M' + x + " " + a + "V" + z + "M" + (x - 8) + " " + a + "H" + (x + 8) + "M" + (x - 8) + " " + z + "H" + (x + 8) + '" stroke="#111827" stroke-width="1.6" fill="none"/>');
      }
      b.ys.forEach((v, j) => { const jx = x + (b.ys.length > 1 ? (j / (b.ys.length - 1) - 0.5) * bw * 0.5 : 0); out.push('<circle cx="' + jx + '" cy="' + sy(v) + '" r="3.2" fill="#fff" stroke="#111827" stroke-width="1"/>'); });
      out.push('<text x="' + x + '" y="' + (T + ph + 20) + '" text-anchor="middle" font-size="12" fill="#374151">' + xesc(b.label.length > 18 ? b.label.slice(0, 17) + "…" : b.label) + "</text>");
    });
    if (c.note) out.push('<text x="' + (L + pw) + '" y="' + (T + 14) + '" text-anchor="end" font-size="12" fill="#374151">' + xesc(c.note) + "</text>");
  } else {
    c.series.forEach(s => {
      if (s.curve) out.push('<polyline fill="none" stroke="' + s.color + '" stroke-width="2.2" points="' + s.curve.filter(p => (!c.logx || p[0] > 0) && (!ylog || p[1] > 0)).map(p => sx(p[0]).toFixed(1) + "," + sy(p[1]).toFixed(1)).join(" ") + '"/>');
      s.pts.forEach(q => {
        const x = sx(q.x);
        if (ylog && !(q.mean > 0)) return;
        if (isFinite(q.sd) && q.n > 1) { const a = sy(q.mean - q.sd), z = sy(q.mean + q.sd); out.push('<path d="M' + x + " " + a + "V" + z + "M" + (x - 4) + " " + a + "H" + (x + 4) + "M" + (x - 4) + " " + z + "H" + (x + 4) + '" stroke="' + s.color + '" stroke-width="1.4" fill="none"/>'); }
        out.push('<circle cx="' + x + '" cy="' + sy(q.mean) + '" r="4.6" fill="' + s.color + '" stroke="#fff" stroke-width="1"/>');
      });
    });
    const leg = c.series.map(s => s.legend || s.name).filter(Boolean);
    if (leg.length && (many || c.series.some(s => s.legend))) {
      const lw = Math.min(330, Math.max.apply(null, leg.map(t => t.length)) * 6.6 + 34), lx = L + pw - lw - 6, ly = T + 8;
      out.push('<rect x="' + lx + '" y="' + ly + '" width="' + lw + '" height="' + (leg.length * 18 + 8) + '" fill="#fff" fill-opacity="0.9" stroke="#D1D5DB"/>');
      c.series.forEach((s, i) => {
        const yy = ly + 8 + i * 18 + 8;
        out.push('<line x1="' + (lx + 8) + '" x2="' + (lx + 24) + '" y1="' + yy + '" y2="' + yy + '" stroke="' + s.color + '" stroke-width="2.4"/><circle cx="' + (lx + 16) + '" cy="' + yy + '" r="3.6" fill="' + s.color + '"/>');
        out.push('<text x="' + (lx + 30) + '" y="' + (yy + 4) + '" font-size="12" fill="#111827">' + xesc(s.legend || s.name) + "</text>");
      });
    }
  }
  if (c.xlabel) out.push('<text x="' + (L + pw / 2) + '" y="' + (H - 14) + '" text-anchor="middle" font-size="13" fill="#111827">' + xesc(c.xlabel) + "</text>");
  if (c.ylabel) out.push('<text transform="translate(18 ' + (T + ph / 2) + ') rotate(-90)" text-anchor="middle" font-size="13" fill="#111827">' + xesc(c.ylabel) + "</text>");
  out.push("</svg>");
  return out.join("");
}

// ---------- Finestra "Dati e grafici" ----------
function defaultKind() {
  const s = SECTORS_SEL || [];
  if (!s.length || s.indexOf("farmaco") >= 0) return "dr";
  if (s.indexOf("biologia") >= 0) return "bars";
  return "xy";
}
function openAny(d) { if (STRUCT_KINDS[d.kind]) openStructured(d, d.kind); else openDataset(d); }
function openDataset(ds, preset) {
  if (curId == null) return;
  const tool = preset && preset.tool ? TOOLS[preset.tool] : null;
  const pl = ds ? ds.payload : {};
  const kindSel = h("select", null, Object.keys(TEXT_KINDS).map(k => h("option", { value: k }, TEXT_KINDS[k])));
  kindSel.value = (ds && ds.kind) || (tool && tool.text) || defaultKind();
  const title = h("input", { type: "text", placeholder: "Titolo (es. Inibizione di NLRP3 – composti A e B)", maxlength: "120" }); title.value = ds ? ds.title : (tool ? tool.label : "");
  const unitSel = h("select", null, ["", "M", "mM", "µM", "nM", "pM", "µg/mL", "mg/mL", "mg/kg", "s", "min", "h", "°C", "V", "mV", "nm", "mm"].map(u => h("option", { value: u }, u || "(unità)")));
  unitSel.value = pl.unit != null ? pl.unit : (tool && tool.unit ? tool.unit : "µM");
  const xl = h("input", { type: "text", placeholder: "Etichetta asse x" }), yl = h("input", { type: "text", placeholder: "Etichetta asse y" });
  xl.value = pl.xlabel || (tool && tool.xl) || ""; yl.value = pl.ylabel || (tool && tool.yl) || "";
  const o0 = pl.opts || (tool && tool.opts) || {};
  const fixTB = h("input", { type: "checkbox" }); fixTB.checked = !!o0.fixTB;
  const logx = h("input", { type: "checkbox" }); logx.checked = !!o0.logx;
  const logy = h("input", { type: "checkbox" }); logy.checked = !!o0.logy;
  const labSel = h("select", null, [["auto", "IC50/EC50 automatico"], ["IC50", "IC50"], ["EC50", "EC50"]].map(a => h("option", { value: a[0] }, a[1])));
  labSel.value = o0.label || "auto";
  const fitSel = h("select", null, [["none", "nessun fit"], ["lineare", "retta (regressione lineare)"], ["poly2", "polinomio di 2° grado"], ["exp", "esponenziale (k, raddoppio / emivita)"], ["power", "legge di potenza"], ["mm", "Michaelis-Menten (Vmax, Km)"]].map(a => h("option", { value: a[0] }, a[1])));
  fitSel.value = o0.fit || "none";
  const colSel = h("select", null);
  const ta = h("textarea", { class: "dstext", spellcheck: "false", placeholder: "Incolla qui da Excel…" });
  ta.value = pl.text || "";
  const hint = h("div", { class: "hint" }), preview = h("div", { class: "dsprev" }), summ = h("div", { class: "dssum" }), warnBox = h("div", { class: "warn", style: "font-size:13px" });
  const optDr = h("div", { class: "dsopt" }, h("label", null, fixTB, " estremi fissi (top 100, bottom 0)"), labSel);
  const optXy = h("div", { class: "dsopt" }, h("label", null, logx, " x logaritmico"), h("label", null, logy, " y logaritmico"), fitSel);
  const optTb = h("div", { class: "dsopt" }, h("span", { class: "muted" }, "Colonna da rappresentare:"), colSel);
  let timer = null, last = null, lastHead = "";
  const fillCols = () => {
    const first = ta.value.replace(/\r/g, "").split("\n").find(l => l.trim()) || "";
    if (first === lastHead) return; lastHead = first;
    const cur = colSel.value, head = first ? splitLine(first).map(c => c.trim()) : [];
    colSel.innerHTML = "";
    head.forEach((c, i) => { if (i > 0) colSel.append(h("option", { value: String(i) }, c || ("colonna " + (i + 1)))); });
    colSel.value = (o0.col && !cur) ? String(o0.col) : (cur || String(Math.max(head.length - 1, 1)));
    if (!colSel.value && colSel.options.length) colSel.selectedIndex = colSel.options.length - 1;
  };
  const spec = () => {
    const k = kindSel.value;
    return { kind: k, title: title.value.trim(), unit: k === "bars" || k === "table" && !fitSel.value ? "" : unitSel.value,
      xlabel: xl.value.trim() || (k === "dr" ? "Concentrazione" + (unitSel.value ? " (" + unitSel.value + ")" : "") : ""),
      ylabel: yl.value.trim() || (k === "dr" ? "Risposta (%)" : ""), text: ta.value,
      opts: { fixTB: fixTB.checked, logx: logx.checked, logy: logy.checked, label: labSel.value, fit: (k === "xy" || k === "table") ? fitSel.value : "none", col: colSel.value } };
  };
  const refresh = () => {
    const k = kindSel.value;
    hint.textContent = k === "bars"
      ? "Una riga per gruppo: nome, poi i valori delle repliche (separati da tab, «;» o spazio). Con 2 gruppi fa il test t di Welch, con 3 o più l'ANOVA."
      : k === "dr" ? "Una riga per concentrazione: concentrazione, poi le repliche della risposta. Più composti: separali con una riga «# Nome». Il fit è a 4 parametri."
        : k === "table" ? "La prima riga è l'intestazione, poi una riga per prova. Se la prima colonna è numerica fa un grafico x-y (con fit a scelta), altrimenti un grafico a barre."
          : "Una riga per punto: x, poi le repliche di y. Più serie: separale con una riga «# Nome».";
    optDr.style.display = k === "dr" ? "" : "none"; optXy.style.display = (k === "xy" || k === "table") ? "" : "none"; optTb.style.display = k === "table" ? "" : "none";
    unitSel.style.display = (k === "bars") ? "none" : "";
    if (k === "table") fillCols();
    try {
      last = analyze(spec());
      preview.innerHTML = chartSVG(last.chart);
      summ.textContent = last.summary;
      warnBox.textContent = last.warns.length ? "⚠️ " + last.warns.join(" · ") : "";
    } catch (e) { preview.textContent = "Errore nel calcolo: " + e.message; }
  };
  const sched = () => { clearTimeout(timer); timer = setTimeout(refresh, 250); };
  [kindSel, unitSel, fixTB, logx, logy, labSel, fitSel, colSel].forEach(el => el.addEventListener("change", refresh));
  [title, xl, yl, ta].forEach(el => el.addEventListener("input", sched));
  const close = () => bg.remove();
  const persist = async () => {
    if (!ta.value.trim()) { alert("Inserisci prima i dati."); return null; }
    const sp = spec(), a = analyze(sp);
    const pl2 = { kind: sp.kind, title: sp.title, text: sp.text, unit: sp.unit, xlabel: xl.value.trim(), ylabel: yl.value.trim(), opts: sp.opts, summary: a.summary, table: a.table };
    const r = await api("ds_save", { id: ds ? ds.id : null, exp: curId, title: title.value.trim() || DS_KINDS[kindSel.value], kind: kindSel.value, payload: pl2 });
    if (ds) ds.id = r.id; else ds = { id: r.id };
    return r.id;
  };
  const save = h("button", { class: "btn green", onclick: async () => { try { if (await persist() == null) return; close(); await refreshDs(); status("✅ Dati salvati", 2500); } catch (e) { fail(e); } } }, "💾 Salva i dati");
  const attach = h("button", { class: "btn violet", onclick: async () => {
    try {
      if (await persist() == null) return;
      status("🖼️ Creo l'immagine del grafico…");
      const png = await svgToPng(chartSVG(analyze(spec()).chart));
      const pad = n => String(n).padStart(2, "0"), dt = new Date();
      const stamp = dt.getFullYear() + pad(dt.getMonth() + 1) + pad(dt.getDate()) + "-" + pad(dt.getHours()) + pad(dt.getMinutes()) + pad(dt.getSeconds());
      const nm = (title.value.trim().replace(/[^\w.\- ]+/g, "").replace(/\s+/g, "_").slice(0, 50) || "grafico");
      close();
      await uploadFiles([new File([png], "grafico-" + (nm === "grafico" ? "" : nm + "-") + stamp + ".png", { type: "image/png" })]);
      await refreshDs();
    } catch (e) { fail(e); }
  } }, "🖼️ Salva e allega il grafico");
  const example = h("button", { class: "btn grey small", onclick: () => { ta.value = DS_EXAMPLES[kindSel.value] || ""; if (!title.value) title.value = "Esempio"; lastHead = "\u0000"; refresh(); } }, "Esempio");
  const bg = modal([
    h("div", { class: "h2", style: "margin:0" }, "📈 Dati e grafici"),
    h("div", { class: "dsgrid" },
      h("div", { class: "dsleft" }, title, h("div", { class: "dsopt" }, kindSel, unitSel), hint,
        h("div", { class: "keyrow" }, h("span", { class: "muted" }, "Tabella dei dati (puoi incollare da Excel)"), example), ta, optDr, optXy, optTb,
        h("div", { class: "dsopt" }, xl, yl)),
      h("div", { class: "dsright" }, preview, warnBox, summ)),
    h("div", { class: "btns" }, save, attach, h("button", { class: "btn grey", onclick: close }, "Chiudi"))
  ]);
  bg.querySelector(".modal").classList.add("wide");
  refresh();
}

// ---------- Strumenti per settore ----------
// preset = tipo di tabella di testo con le opzioni gia' pronte; kind = finestra strutturata
const TOOLS = {
  reag:      { label: "Reagenti e rese", icon: "⚗️", sectors: ["chimica"], kind: "reag" },
  char:      { label: "Caratterizzazione", icon: "🔬", sectors: ["chimica"], kind: "char" },
  dr:        { label: "Dose-risposta (IC50)", icon: "📈", sectors: ["farmaco"], text: "dr" },
  mm:        { label: "Cinetica enzimatica (Km, Vmax)", icon: "🧪", sectors: ["farmaco"], text: "xy", opts: { fit: "mm" }, unit: "µM" },
  assay:     { label: "Scheda del saggio", icon: "🧫", sectors: ["farmaco"], kind: "assay" },
  plate:     { label: "Piastra a 96 pozzetti", icon: "🔳", sectors: ["biologia"], kind: "plate" },
  qpcr:      { label: "qPCR (ΔΔCt)", icon: "🧬", sectors: ["biologia"], kind: "qpcr" },
  samples:   { label: "Campioni e reagenti", icon: "🧫", sectors: ["biologia"], kind: "samples" },
  cfu:       { label: "Conte CFU", icon: "🦠", sectors: ["micro"], kind: "cfu" },
  mic:       { label: "MIC", icon: "💊", sectors: ["micro"], kind: "mic" },
  growth:    { label: "Curva di crescita", icon: "📈", sectors: ["micro"], text: "xy", opts: { fit: "exp", logy: true }, unit: "h", xl: "Tempo (h)", yl: "OD600 / CFU" },
  strain:    { label: "Ceppo e condizioni", icon: "🧫", sectors: ["micro"], kind: "strain" },
  xy:        { label: "Misure x-y con fit", icon: "📉", sectors: ["materiali", "dati", "farmaco", "biologia", "micro", "chimica"], text: "xy" },
  table:     { label: "Tabella con grafico", icon: "📋", sectors: ["materiali", "dati"], text: "table" },
  bars:      { label: "Gruppi: media ± DS e test", icon: "📊", sectors: ["biologia", "farmaco", "micro", "materiali", "dati", "chimica"], text: "bars" },
  materials: { label: "Materiale e condizioni di misura", icon: "🔧", sectors: ["materiali"], kind: "materials" },
  env:       { label: "Ambiente e riproducibilità", icon: "💻", sectors: ["dati"], kind: "env" },
};
const SECTOR_TOOLS = {
  chimica: ["reag", "char", "bars", "xy"],
  farmaco: ["dr", "mm", "assay", "bars"],
  biologia: ["plate", "qpcr", "samples", "bars"],
  micro: ["cfu", "mic", "growth", "strain"],
  materiali: ["xy", "table", "materials", "bars"],
  dati: ["table", "bars", "xy", "env"]
};
const CARD_TEMPLATES = {
  char: ["Aspetto", "Resa", "Punto di fusione", "Rf (eluente)", "1H NMR", "13C NMR", "MS (ESI / HRMS)", "HPLC (purezza, tR)", "IR", "[α]D"],
  assay: ["Bersaglio / enzima", "Composto (lotto)", "Substrato / ligando e concentrazione", "Tampone e pH", "Temperatura e tempo di incubazione", "Metodo di rivelazione", "Controlli (positivo, negativo, veicolo)", "Concentrazione di DMSO"],
  samples: ["Linea cellulare (passaggio)", "Terreno e siero", "Densità di semina", "Trattamento (concentrazione, tempo)", "Anticorpi primari (diluizione, lotto)", "Anticorpi secondari", "Kit / reagenti (lotto)", "Repliche biologiche / tecniche"],
  strain: ["Ceppo (codice)", "Terreno", "Temperatura e atmosfera", "Inoculo (CFU/mL o OD)", "Tempo di incubazione", "Composto / antibiotico (lotto)", "Standard di riferimento (CLSI, EUCAST)"],
  materials: ["Materiale e lotto", "Sintesi / processo (parametri)", "Strumento e modello", "Condizioni ambientali (T, umidità)", "Calibrazione", "Preparazione del campione", "Norma di riferimento"],
  env: ["Repository e commit", "Versione software e librerie", "Seed casuale", "Hardware", "Dataset (versione)", "Comando eseguito", "Tempo di calcolo"]
};
const STRUCT_KINDS = { reag: "Reagenti e rese", char: "Caratterizzazione", assay: "Scheda del saggio", plate: "Piastra a 96 pozzetti", qpcr: "qPCR (ΔΔCt)", samples: "Campioni e reagenti", cfu: "Conte CFU", mic: "MIC", strain: "Ceppo e condizioni", materials: "Materiale e condizioni di misura", env: "Ambiente e riproducibilità" };
Object.assign(DS_KINDS, STRUCT_KINDS);

function toolsForSectors() {
  const sel = (SECTORS_SEL && SECTORS_SEL.length) ? SECTORS_SEL : ["chimica"];
  const out = [];
  sel.forEach(s => (SECTOR_TOOLS[s] || []).forEach(k => { if (out.indexOf(k) < 0) out.push(k); }));
  return out;
}
function startTool(k) {
  const t = TOOLS[k];
  if (t.kind) openStructured(null, t.kind); else openDataset(null, { tool: k });
}
function renderQuick() {
  const box = $("dsquick"); if (!box) return;
  box.innerHTML = "";
  toolsForSectors().forEach(k => box.append(h("button", { class: "btn blue small", title: TOOLS[k].label, onclick: () => startTool(k) }, TOOLS[k].icon + " " + TOOLS[k].label)));
  box.append(h("button", { class: "btn grey small", onclick: openToolChooser }, "＋ Altri strumenti…"));
}
function openToolChooser() {
  const close = () => bg.remove(), parts = [];
  Object.keys(SECTOR_NAMES).forEach(s => {
    parts.push(h("div", { class: "h2", style: "margin:8px 0 2px" }, SECTOR_NAMES[s]));
    parts.push(h("div", { class: "dsopt" }, (SECTOR_TOOLS[s] || []).map(k => h("button", { class: "btn violet small", onclick: () => { close(); startTool(k); } }, TOOLS[k].icon + " " + TOOLS[k].label))));
  });
  const bg = modal([h("div", { class: "h2", style: "margin:0" }, "＋ Scegli lo strumento")].concat(parts, [h("div", { class: "btns" }, h("button", { class: "btn grey", onclick: close }, "Chiudi"))]));
}

// ---------- Editor a griglia ----------
function gridEditor(cols, rows, onChange) {
  const table = h("table", { class: "grid" }), tbody = h("tbody");
  table.append(h("thead", null, h("tr", null, cols.map(c => h("th", { style: c.w ? "min-width:" + c.w + "px" : "" }, c.label)).concat([h("th", null, "")]))), tbody);
  let data = rows.map(r => Object.assign({}, r));
  const cellEls = [];
  const readonlyCols = cols.filter(c => c.computed);
  const fire = () => onChange && onChange(data);
  function build() {
    tbody.innerHTML = ""; cellEls.length = 0;
    data.forEach((row, ri) => {
      const tr = h("tr"), els = {};
      cols.forEach((c, ci) => {
        let el;
        if (c.computed) { el = h("span", { class: "gcomp" }, ""); }
        else if (c.type === "select") {
          el = h("select", null, (c.opts || []).map(o => h("option", { value: o }, o || "–")));
          el.value = row[c.key] != null ? row[c.key] : (c.opts || [""])[0];
          row[c.key] = el.value;
          el.addEventListener("change", () => { row[c.key] = el.value; fire(); });
        } else {
          el = h("input", { type: "text", autocomplete: "off", placeholder: c.ph || "" });
          el.value = row[c.key] != null ? row[c.key] : "";
          el.addEventListener("input", () => { row[c.key] = el.value; fire(); });
          el.addEventListener("paste", ev => {
            const txt = (ev.clipboardData || window.clipboardData).getData("text");
            if (txt.indexOf("\t") < 0 && txt.indexOf("\n") < 0) return;
            ev.preventDefault();
            const lines = txt.replace(/\r/g, "").split("\n").filter((l, i, a) => l !== "" || i < a.length - 1);
            const editable = cols.filter(x => !x.computed && x.type !== "select");
            const start = editable.indexOf(c);
            lines.forEach((ln, li) => {
              const rr = ri + li; while (data.length <= rr) data.push({});
              ln.split("\t").forEach((v, k) => { const cc = editable[start + k]; if (cc) data[rr][cc.key] = v.trim(); });
            });
            build(); fire();
          });
        }
        els[c.key] = el; tr.append(h("td", null, el));
      });
      tr.append(h("td", null, h("button", { class: "gdel", title: "Elimina la riga", onclick: () => { data.splice(ri, 1); if (!data.length) data.push({}); build(); fire(); } }, "✕")));
      cellEls.push(els); tbody.append(tr);
    });
  }
  build();
  const add = h("button", { class: "btn grey small", onclick: () => { data.push({}); build(); fire(); } }, "＋ Aggiungi riga");
  return {
    el: h("div", { class: "gridwrap" }, table, add),
    rows: () => data,
    setComputed: (key, arr) => { cellEls.forEach((els, i) => { if (els[key]) els[key].textContent = arr[i] == null ? "" : arr[i]; }); }
  };
}
const nz = v => { const x = num(v); return isFinite(x) ? x : NaN; };

// ---------- Definizione dei tipi strutturati ----------
function cardKind(id) {
  return {
    hint: "Compila i campi che servono (puoi aggiungere altre righe). I campi vuoti non compaiono nel Word.",
    init: () => ({ rows: CARD_TEMPLATES[id].map(k => ({ k, v: "" })) }),
    build: (st, on) => {
      const g = gridEditor([{ key: "k", label: "Campo", w: 200 }, { key: "v", label: "Valore", w: 320 }], st.rows, rows => { st.rows = rows; on(); });
      return { el: g.el, sync: () => { st.rows = g.rows(); } };
    },
    analyze: st => {
      const rows = st.rows.filter(r => (r.v || "").trim());
      return { chart: null, summary: "", table: rows.length ? [["Campo", "Valore"]].concat(rows.map(r => [r.k || "", r.v])) : [], warns: rows.length ? [] : ["Compila almeno un campo."] };
    }
  };
}
const KIND_DEFS = {};
["char", "assay", "samples", "strain", "materials", "env"].forEach(k => { KIND_DEFS[k] = cardKind(k); });

// --- Reagenti e rese
KIND_DEFS.reag = {
  hint: "Per ogni riga indica PM e una tra massa, mmol oppure volume + densità. La resa si calcola sul reagente limitante (il primo reagente, o quello segnato «limitante»). Stechiometria 1:1 col prodotto.",
  init: () => ({ rows: [{ role: "Reagente" }, { role: "Reagente" }, { role: "Solvente" }, { role: "Prodotto" }] }),
  build: (st, on) => {
    const cols = [{ key: "role", label: "Ruolo", type: "select", opts: ["Reagente", "Catalizzatore / additivo", "Solvente", "Prodotto"] }, { key: "name", label: "Nome", w: 150 },
      { key: "mw", label: "PM", w: 60 }, { key: "mass", label: "Massa (mg)", w: 70 }, { key: "vol", label: "Vol. (mL)", w: 60 }, { key: "dens", label: "Dens.", w: 55 }, { key: "mmol", label: "mmol", w: 60 },
      { key: "lim", label: "Limitante", type: "select", opts: ["", "limitante"] }, { key: "c_mmol", label: "mmol", computed: true }, { key: "c_eq", label: "Equiv. / resa", computed: true }];
    const g = gridEditor(cols, st.rows, rows => { st.rows = rows; on(); });
    return { el: g.el, sync: () => { st.rows = g.rows(); }, after: () => { const a = reagCalc(st.rows); g.setComputed("c_mmol", a.rows.map(r => r.mmol == null ? "" : fmt(r.mmol, 4))); g.setComputed("c_eq", a.rows.map(r => r.txt)); } };
  },
  analyze: st => {
    const a = reagCalc(st.rows), warns = a.warns;
    const table = [["Ruolo", "Nome", "PM", "Massa (mg)", "Vol. (mL)", "mmol", "Equiv. / resa"]].concat(a.rows.filter(r => r.src.name || r.mmol != null || r.vol).map(r => [r.src.role || "", r.src.name || "", r.src.mw || "", r.src.mass || "", r.src.vol || "", r.mmol == null ? "" : fmt(r.mmol, 4), r.txt]));
    return { chart: null, summary: a.summary, table: table.length > 1 ? table : [], warns };
  }
};
function reagCalc(rows) {
  const warns = [], out = rows.map(src => {
    const mw = nz(src.mw), mass = nz(src.mass), vol = nz(src.vol), dens = nz(src.dens), mm = nz(src.mmol);
    let mmol = null;
    if (isFinite(mm)) mmol = mm; else if (isFinite(mass) && mw > 0) mmol = mass / mw; else if (isFinite(vol) && isFinite(dens) && mw > 0 && src.role !== "Solvente") mmol = vol * dens * 1000 / mw;
    return { src, mmol, mw, txt: "" };
  });
  let lim = out.find(r => r.src.lim === "limitante" && r.mmol != null) || out.find(r => r.src.role === "Reagente" && r.mmol != null);
  const sum = [];
  if (lim) {
    sum.push("Reagente limitante: " + (lim.src.name || "(senza nome)") + ", " + fmt(lim.mmol, 4) + " mmol.");
    out.forEach(r => {
      if (r.mmol == null) return;
      if (r.src.role === "Prodotto") {
        const y = r.mmol / lim.mmol * 100; r.txt = "resa " + fmt(y, 3) + " %";
        sum.push("Prodotto " + (r.src.name || "") + ": " + (isFinite(nz(r.src.mass)) ? fmt(nz(r.src.mass), 4) + " mg, " : "") + fmt(r.mmol, 4) + " mmol, resa " + fmt(y, 3) + " %." + (isFinite(r.mw) ? " Massa teorica: " + fmt(lim.mmol * r.mw, 4) + " mg." : ""));
        if (y > 105) warns.push("Resa superiore al 100%: controlla PM e quantità (" + (r.src.name || "prodotto") + ").");
      } else r.txt = r === lim ? "1.00 (limitante)" : fmt(r.mmol / lim.mmol, 3) + " equiv.";
    });
    const vs = out.filter(r => r.src.role === "Solvente").reduce((s, r) => s + (isFinite(nz(r.src.vol)) ? nz(r.src.vol) : 0), 0);
    if (vs > 0) sum.push("Concentrazione del limitante: " + fmt(lim.mmol / vs, 3) + " M (" + fmt(vs, 3) + " mL di solvente).");
  } else if (rows.some(r => r.name || r.mass || r.mmol)) warns.push("Inserisci PM e massa (o mmol) di almeno un reagente per calcolare equivalenti e resa.");
  out.forEach(r => { if (r.src.role !== "Solvente" && r.src.name && r.mmol == null && (r.src.mass || r.src.vol)) warns.push("«" + r.src.name + "»: manca il PM (o la densità per un volume)."); });
  return { rows: out, summary: sum.join("\n"), warns: Array.from(new Set(warns)) };
}

// --- Conte CFU
function parseDil(v) {
  v = String(v == null ? "" : v).trim().replace(",", "."); if (!v) return NaN;
  let m;
  if ((m = v.match(/^10\^?\s*\(?(-?\d+)\)?$/))) return Math.pow(10, +m[1]);
  if ((m = v.match(/^1\s*[:/]\s*(\d+(\.\d+)?)$/))) return 1 / +m[1];
  if (/^-\d+$/.test(v)) return Math.pow(10, +v);
  const x = Number(v); return isFinite(x) && x > 0 ? x : NaN;
}
KIND_DEFS.cfu = {
  hint: "Per ogni diluizione scrivi le colonie contate sulle piastre. Diluizione: -6, 10^-6, 1e-6 o 1:1000000. Contano le piastre con 30-300 colonie. Volume piastrato in mL (di solito 0.1).",
  init: () => ({ rows: [{ vol: "0.1" }, { vol: "0.1" }, { vol: "0.1" }] }),
  build: (st, on) => {
    const g = gridEditor([{ key: "s", label: "Campione", w: 130 }, { key: "d", label: "Diluizione", w: 80 }, { key: "c1", label: "Piastra 1", w: 60 }, { key: "c2", label: "Piastra 2", w: 60 }, { key: "c3", label: "Piastra 3", w: 60 }, { key: "vol", label: "Vol. (mL)", w: 60 }, { key: "cc", label: "CFU/mL", computed: true }], st.rows, rows => { st.rows = rows; on(); });
    return { el: g.el, sync: () => { st.rows = g.rows(); }, after: () => { g.setComputed("cc", cfuCalc(st.rows).rowTxt); } };
  },
  analyze: st => {
    const a = cfuCalc(st.rows);
    return { chart: a.chart, summary: a.summary, table: a.table, warns: a.warns };
  }
};
function cfuCalc(rows) {
  const warns = [], per = {}, rowTxt = [];
  rows.forEach(r => {
    const dil = parseDil(r.d), vol = isFinite(nz(r.vol)) ? nz(r.vol) : 0.1, cs = [r.c1, r.c2, r.c3].map(nz).filter(isFinite);
    if (!(r.s || "").trim() || !isFinite(dil) || !cs.length) { rowTxt.push(""); return; }
    const valid = cs.filter(c => c >= 30 && c <= 300);
    if (!valid.length) { rowTxt.push("fuori 30-300"); warns.push((r.s) + " (diluizione " + r.d + "): nessuna piastra tra 30 e 300 colonie, riga esclusa."); return; }
    if (valid.length < cs.length) warns.push(r.s + " (diluizione " + r.d + "): alcune piastre fuori dall'intervallo 30-300 sono state escluse.");
    const cfu = mean(valid) / (dil * vol); rowTxt.push(fmt(cfu, 3));
    (per[r.s.trim()] = per[r.s.trim()] || []).push(cfu);
  });
  const names = Object.keys(per), chart = { kind: "bars", title: "", xlabel: "", ylabel: "log10 CFU/mL", series: [], bars: [] };
  const table = names.length ? [["Campione", "CFU/mL (media)", "log10 CFU/mL", "n diluizioni"]] : [];
  names.forEach(n => {
    const v = per[n], m = mean(v), lg = v.map(x => Math.log10(x));
    chart.bars.push({ label: n, ys: lg, mean: mean(lg), sd: sdev(lg), n: v.length });
    table.push([n, m.toExponential(2).replace("e+", "e"), fmt(Math.log10(m), 4), String(v.length)]);
  });
  const summary = names.map(n => n + ": " + mean(per[n]).toExponential(2).replace("e+", "e") + " CFU/mL (log10 = " + fmt(Math.log10(mean(per[n])), 4) + ").").join("\n");
  return { rowTxt, chart: names.length ? chart : null, summary, table, warns: Array.from(new Set(warns)) };
}

// --- MIC
KIND_DEFS.mic = {
  hint: "Una riga per ogni concentrazione provata: composto, ceppo, concentrazione e se c'è crescita. La MIC è la concentrazione più bassa senza crescita.",
  init: () => ({ rows: [2, 4, 8, 16, 32, 64].map(c => ({ conc: String(c), g: "crescita" })) }),
  build: (st, on) => {
    const g = gridEditor([{ key: "s", label: "Composto", w: 130 }, { key: "strain", label: "Ceppo", w: 130 }, { key: "conc", label: "Conc. (µg/mL)", w: 90 }, { key: "g", label: "Crescita", type: "select", opts: ["crescita", "no crescita"] }], st.rows, rows => { st.rows = rows; on(); });
    return { el: g.el, sync: () => { st.rows = g.rows(); } };
  },
  analyze: st => {
    const groups = {}, warns = [];
    st.rows.forEach(r => { const c = nz(r.conc); if (!isFinite(c)) return; const key = (r.s || "").trim() + "\u0001" + (r.strain || "").trim(); (groups[key] = groups[key] || []).push({ c, no: r.g === "no crescita" }); });
    const keys = Object.keys(groups), table = keys.length ? [["Composto", "Ceppo", "MIC (µg/mL)"]] : [], chart = { kind: "bars", title: "", xlabel: "", ylabel: "MIC (µg/mL)", series: [], bars: [] }, lines = [];
    keys.forEach(k => {
      const [s, strain] = k.split("\u0001"), list = groups[k].sort((a, b) => a.c - b.c);
      let mic = null;
      for (let i = 0; i < list.length; i++) if (list[i].no && list.slice(i).every(x => x.no)) { mic = list[i].c; break; }
      if (mic == null && list.some(x => x.no)) warns.push((s || "composto") + " / " + (strain || "ceppo") + ": risultati non monotoni (crescita a concentrazioni più alte di una senza crescita): controlla.");
      const txt = mic != null ? String(mic) : "> " + list[list.length - 1].c;
      table.push([s, strain, txt]); lines.push((s || "–") + " su " + (strain || "–") + ": MIC = " + txt + " µg/mL.");
      if (mic != null) chart.bars.push({ label: ((s || "") + " " + (strain || "")).trim(), ys: [mic], mean: mic, sd: NaN, n: 1 });
    });
    if (!keys.length) warns.push("Inserisci almeno una concentrazione.");
    return { chart: chart.bars.length ? chart : null, summary: lines.join("\n"), table, warns };
  }
};

// --- qPCR
KIND_DEFS.qpcr = {
  hint: "Una riga per gruppo e gene con i Ct delle repliche. Indica il gene di riferimento e il gruppo di controllo qui sopra: il Diario calcola ΔCt, ΔΔCt e fold change (2^-ΔΔCt).",
  init: () => ({ ref: "GAPDH", ctrl: "Controllo", rows: [{ g: "Controllo", gene: "GAPDH" }, { g: "Controllo", gene: "Gene X" }, { g: "Trattato", gene: "GAPDH" }, { g: "Trattato", gene: "Gene X" }] }),
  build: (st, on) => {
    const ref = h("input", { type: "text", placeholder: "Gene di riferimento" }), ctrl = h("input", { type: "text", placeholder: "Gruppo di controllo" });
    ref.value = st.ref || ""; ctrl.value = st.ctrl || "";
    ref.addEventListener("input", () => { st.ref = ref.value; on(); }); ctrl.addEventListener("input", () => { st.ctrl = ctrl.value; on(); });
    const g = gridEditor([{ key: "g", label: "Gruppo", w: 120 }, { key: "gene", label: "Gene", w: 110 }, { key: "c1", label: "Ct 1", w: 60 }, { key: "c2", label: "Ct 2", w: 60 }, { key: "c3", label: "Ct 3", w: 60 }], st.rows, rows => { st.rows = rows; on(); });
    return { el: h("div", null, h("div", { class: "dsopt" }, ref, ctrl), g.el), sync: () => { st.rows = g.rows(); } };
  },
  analyze: st => {
    const warns = [], cell = {};
    st.rows.forEach(r => { const cs = [r.c1, r.c2, r.c3].map(nz).filter(isFinite); if (!(r.g || "").trim() || !(r.gene || "").trim() || !cs.length) return; (cell[r.g.trim() + "\u0001" + r.gene.trim()] = cell[r.g.trim() + "\u0001" + r.gene.trim()] || []).push(...cs); if (cs.some(c => c > 35)) warns.push("Ct > 35 (" + r.g + ", " + r.gene + "): segnale molto debole."); });
    const groups = Array.from(new Set(Object.keys(cell).map(k => k.split("\u0001")[0]))), genes = Array.from(new Set(Object.keys(cell).map(k => k.split("\u0001")[1])));
    const ref = (st.ref || "").trim(), ctrl = (st.ctrl || "").trim(), chart = { kind: "bars", title: "", xlabel: "", ylabel: "Espressione relativa (2^-ΔΔCt)", series: [], bars: [] }, table = [], lines = [];
    if (!groups.length) return { chart: null, summary: "", table, warns: ["Inserisci i valori di Ct."] };
    if (genes.indexOf(ref) < 0) return { chart: null, summary: "", table, warns: ["Il gene di riferimento «" + ref + "» non compare nella tabella."] };
    if (groups.indexOf(ctrl) < 0) return { chart: null, summary: "", table, warns: ["Il gruppo di controllo «" + ctrl + "» non compare nella tabella."] };
    table.push(["Gene", "Gruppo", "Ct medio", "ΔCt", "ΔΔCt", "Fold change (intervallo)"]);
    genes.filter(x => x !== ref).forEach(gene => {
      const dct = {};
      groups.forEach(G => {
        const t = cell[G + "\u0001" + gene], r = cell[G + "\u0001" + ref];
        if (!t || !r) { warns.push(gene + " / " + G + ": manca il gene o il riferimento."); return; }
        dct[G] = { d: mean(t) - mean(r), sd: Math.sqrt((isFinite(sdev(t)) ? sdev(t) ** 2 : 0) + (isFinite(sdev(r)) ? sdev(r) ** 2 : 0)), ct: mean(t) };
      });
      if (!dct[ctrl]) return;
      groups.forEach(G => {
        if (!dct[G]) return;
        const dd = dct[G].d - dct[ctrl].d, fold = Math.pow(2, -dd), lo = Math.pow(2, -(dd + dct[G].sd)), hi = Math.pow(2, -(dd - dct[G].sd));
        table.push([gene, G, fmt(dct[G].ct, 4), fmt(dct[G].d, 4), fmt(dd, 4), fmt(fold, 3) + " (" + fmt(lo, 3) + " – " + fmt(hi, 3) + ")"]);
        lines.push(gene + " – " + G + ": fold change = " + fmt(fold, 3) + " (" + fmt(lo, 3) + " – " + fmt(hi, 3) + ").");
        chart.bars.push({ label: gene + " " + G, ys: [fold], mean: fold, sd: (hi - lo) / 2, n: 2 });
      });
    });
    if (!chart.bars.length) warns.push("Servono almeno un gene bersaglio oltre al riferimento.");
    return { chart: chart.bars.length ? chart : null, summary: lines.join("\n"), table: chart.bars.length ? table : [], warns: Array.from(new Set(warns)) };
  }
};

// --- Piastra a 96 pozzetti
const PLATE_ROWS = "ABCDEFGH".split("");
KIND_DEFS.plate = {
  hint: "Compila il layout (nome del gruppo in ogni pozzetto, es. Blank, Controllo, Comp-A 10 µM) e i valori letti (assorbanza, fluorescenza…). Puoi incollare un blocco 8×12 da Excel in ciascuna griglia. Pozzetti vuoti ignorati.",
  init: () => ({ layout: PLATE_ROWS.map(() => Array(12).fill("")), vals: PLATE_ROWS.map(() => Array(12).fill("")), blank: "Blank", ctrl: "Controllo", subBlank: true, norm: true }),
  build: (st, on) => {
    const mk = (key, title) => {
      const tbl = h("table", { class: "plate" }), body = h("tbody");
      tbl.append(h("thead", null, h("tr", null, [h("th", null, "")].concat(Array.from({ length: 12 }, (_, i) => h("th", null, String(i + 1)))))), body);
      PLATE_ROWS.forEach((L, r) => {
        const tr = h("tr", null, h("th", null, L));
        for (let c = 0; c < 12; c++) {
          const inp = h("input", { type: "text", autocomplete: "off" }); inp.value = st[key][r][c] || "";
          inp.addEventListener("input", () => { st[key][r][c] = inp.value; on(); });
          inp.addEventListener("paste", ev => {
            const txt = (ev.clipboardData || window.clipboardData).getData("text");
            if (txt.indexOf("\t") < 0 && txt.indexOf("\n") < 0) return;
            ev.preventDefault();
            txt.replace(/\r/g, "").split("\n").forEach((ln, li) => { if (!ln && li > 0) return; ln.split("\t").forEach((v, k) => { if (r + li < 8 && c + k < 12) st[key][r + li][c + k] = v.trim(); }); });
            const holder = tbl.parentNode; holder.replaceWith(mk(key, title)); on();
          });
          tr.append(h("td", null, inp));
        }
        body.append(tr);
      });
      return h("div", { class: "platebox" }, h("div", { class: "keyrow" }, h("b", null, title)), tbl);
    };
    const blank = h("input", { type: "text", placeholder: "Nome del bianco" }), ctrl = h("input", { type: "text", placeholder: "Nome del controllo" });
    blank.value = st.blank || ""; ctrl.value = st.ctrl || "";
    blank.addEventListener("input", () => { st.blank = blank.value; on(); }); ctrl.addEventListener("input", () => { st.ctrl = ctrl.value; on(); });
    const sb = h("input", { type: "checkbox" }), nm = h("input", { type: "checkbox" }); sb.checked = !!st.subBlank; nm.checked = !!st.norm;
    sb.addEventListener("change", () => { st.subBlank = sb.checked; on(); }); nm.addEventListener("change", () => { st.norm = nm.checked; on(); });
    return { el: h("div", null, h("div", { class: "dsopt" }, blank, ctrl), h("div", { class: "dsopt" }, h("label", null, sb, " sottrai il bianco"), h("label", null, nm, " normalizza sul controllo (= 100 %)")), mk("layout", "Layout (nome del gruppo)"), mk("vals", "Valori letti")), sync: () => {} };
  },
  analyze: st => {
    const warns = [], wells = [];
    for (let r = 0; r < 8; r++) for (let c = 0; c < 12; c++) {
      const lab = (st.layout[r][c] || "").trim(), v = nz(st.vals[r][c]);
      if (lab && isFinite(v)) wells.push({ lab, v });
      else if (lab && (st.vals[r][c] || "").trim()) warns.push("Valore non numerico in " + PLATE_ROWS[r] + (c + 1) + ".");
      else if (isFinite(v) && !lab) warns.push("Pozzetto " + PLATE_ROWS[r] + (c + 1) + " con valore ma senza nome nel layout: ignorato.");
    }
    const isB = l => l.toLowerCase() === (st.blank || "").trim().toLowerCase(), isC = l => l.toLowerCase() === (st.ctrl || "").trim().toLowerCase();
    let bl = 0;
    if (st.subBlank) { const b = wells.filter(w => isB(w.lab)).map(w => w.v); if (b.length) bl = mean(b); else warns.push("Nessun pozzetto «" + st.blank + "»: il bianco non è stato sottratto."); }
    let data = wells.filter(w => !(st.subBlank && isB(w.lab))).map(w => ({ lab: w.lab, v: w.v - bl }));
    let scale = 1, unit = "";
    if (st.norm) { const c = data.filter(w => isC(w.lab)).map(w => w.v); if (c.length && mean(c) !== 0) { scale = 100 / mean(c); unit = " (% del controllo)"; } else warns.push("Nessun pozzetto «" + st.ctrl + "»: nessuna normalizzazione."); }
    data = data.map(w => ({ lab: w.lab, v: w.v * scale }));
    const labs = Array.from(new Set(data.map(w => w.lab))), chart = { kind: "bars", title: "", xlabel: "", ylabel: "Valore" + unit, series: [], bars: [] };
    labs.forEach(l => { const ys = data.filter(w => w.lab === l).map(w => w.v); chart.bars.push({ label: l, ys, mean: mean(ys), sd: sdev(ys), n: ys.length }); });
    if (!labs.length) return { chart: null, summary: "", table: [], warns: warns.concat(["Inserisci layout e valori."]) };
    const table = [["Gruppo", "n", "Media" + unit, "DS"]].concat(chart.bars.map(b => [b.label, String(b.n), fmt(b.mean, 4), fmt(b.sd, 3)]));
    const lines = [];
    if (bl) lines.push("Bianco sottratto: " + fmt(bl, 4) + ".");
    const groups = chart.bars.filter(b => !isC(b.label) || chart.bars.length <= 2).map(b => b.ys);
    if (chart.bars.length === 2) { const w = welch(chart.bars[0].ys, chart.bars[1].ys); if (w) { lines.push("Test t di Welch: " + fmtP(w.p) + " (" + pStars(w.p) + ")."); chart.note = fmtP(w.p) + " (" + pStars(w.p) + ")"; } }
    else if (chart.bars.length > 2) { const a = anova1(chart.bars.map(b => b.ys)); if (a) { lines.push("ANOVA a una via: F(" + a.d1 + ", " + a.d2 + ") = " + fmt(a.F, 3) + ", " + fmtP(a.p) + " (" + pStars(a.p) + ")."); chart.note = "ANOVA " + fmtP(a.p) + " (" + pStars(a.p) + ")"; } }
    if (chart.bars.some(b => b.n < 3)) warns.push("Alcuni gruppi hanno meno di 3 pozzetti.");
    return { chart, summary: lines.join("\n"), table, warns: Array.from(new Set(warns)) };
  }
};

// ---------- Finestra per i tipi strutturati ----------
function openStructured(ds, kindId) {
  if (curId == null) return;
  const def = KIND_DEFS[kindId], pl = ds ? ds.payload : {};
  const st = (pl && pl.state) ? JSON.parse(JSON.stringify(pl.state)) : def.init();
  const title = h("input", { type: "text", placeholder: "Titolo", maxlength: "120" }); title.value = ds ? ds.title : STRUCT_KINDS[kindId];
  const prev = h("div", { class: "dsprev" }), summ = h("div", { class: "dssum" }), warnBox = h("div", { class: "warn", style: "font-size:13px" });
  let ed = null, last = null, timer = null;
  const refresh = () => {
    try {
      if (ed && ed.sync) ed.sync();
      last = def.analyze(st);
      if (ed && ed.after) ed.after();
      prev.innerHTML = last.chart ? chartSVG(last.chart) : ""; prev.style.display = last.chart ? "" : "none";
      summ.textContent = last.summary || ""; warnBox.textContent = last.warns.length ? "⚠️ " + last.warns.join(" · ") : "";
    } catch (e) { warnBox.textContent = "Errore nel calcolo: " + e.message; }
  };
  const on = () => { clearTimeout(timer); timer = setTimeout(refresh, 200); };
  ed = def.build(st, on);
  const close = () => bg.remove();
  const persist = async () => {
    refresh();
    if (!last.table.length && !last.summary) { alert("Compila prima i dati."); return null; }
    const r = await api("ds_save", { id: ds ? ds.id : null, exp: curId, title: title.value.trim() || STRUCT_KINDS[kindId], kind: kindId, payload: { state: st, summary: last.summary, table: last.table } });
    if (ds) ds.id = r.id; else ds = { id: r.id };
    return r.id;
  };
  const save = h("button", { class: "btn green", onclick: async () => { try { if (await persist() == null) return; close(); await refreshDs(); status("✅ Dati salvati", 2500); } catch (e) { fail(e); } } }, "💾 Salva i dati");
  const attach = h("button", { class: "btn violet", onclick: async () => {
    try {
      if (await persist() == null) return;
      if (!last.chart) { close(); await refreshDs(); return; }
      status("🖼️ Creo l'immagine del grafico…");
      const png = await svgToPng(chartSVG(Object.assign({}, last.chart, { title: title.value.trim() })));
      const pad = n => String(n).padStart(2, "0"), dt = new Date();
      const stamp = dt.getFullYear() + pad(dt.getMonth() + 1) + pad(dt.getDate()) + "-" + pad(dt.getHours()) + pad(dt.getMinutes()) + pad(dt.getSeconds());
      const nm = (title.value.trim().replace(/[^\w.\- ]+/g, "").replace(/\s+/g, "_").slice(0, 50) || "grafico");
      close();
      await uploadFiles([new File([png], "grafico-" + nm + "-" + stamp + ".png", { type: "image/png" })]);
      await refreshDs();
    } catch (e) { fail(e); }
  } }, "🖼️ Salva e allega il grafico");
  const hasChart = ["plate", "qpcr", "cfu", "mic"].indexOf(kindId) >= 0;
  const bg = modal([
    h("div", { class: "h2", style: "margin:0" }, TOOLS[kindId] ? TOOLS[kindId].icon + " " + TOOLS[kindId].label : STRUCT_KINDS[kindId]),
    h("div", { class: "dsgrid" }, h("div", { class: "dsleft" + (hasChart ? "" : " full"), style: hasChart ? "" : "flex-basis:100%" }, title, h("div", { class: "hint" }, def.hint), ed.el), hasChart ? h("div", { class: "dsright" }, prev, warnBox, summ) : h("div", { class: "dsright", style: "flex-basis:100%" }, warnBox, summ)),
    h("div", { class: "btns" }, save, hasChart ? attach : null, h("button", { class: "btn grey", onclick: close }, "Chiudi"))
  ]);
  bg.querySelector(".modal").classList.add("wide");
  refresh();
}

async function refreshDs() {
  if (curId == null) return;
  const r = await api("ds_list", { exp: curId });
  renderDs(r.datasets);
}
function renderDs(list) {
  const box = $("dslist"); box.innerHTML = "";
  if (!list.length) { box.append(h("div", { class: "muted" }, "Nessuna tabella di dati. Aggiungi misure, curve dose-risposta o confronti tra gruppi: compaiono anche nel Word.")); return; }
  list.forEach(d => {
    const sum = (d.payload && d.payload.summary) ? d.payload.summary.split("\n")[0] : "";
    box.append(h("div", { class: "att" }, h("span", null, "📈"),
      h("span", { class: "nm" }, d.title, h("div", { class: "muted", style: "font-size:12px" }, (DS_KINDS[d.kind] || "") + (sum ? " · " + sum : ""))),
      h("button", { class: "btn violet small", onclick: () => openAny(d) }, "Apri"),
      h("button", { class: "btn red small", onclick: async () => { if (!confirm("Eliminare questa tabella di dati?")) return; try { await api("ds_delete", { id: d.id }); await refreshDs(); } catch (e) { fail(e); } } }, "✕")));
  });
}


// ---------- avvio ----------
function build() {
  const box = $("sections");
  SECTIONS.forEach(([k, title, ph, rows]) => {
    const t = h("textarea", { id: "sec_" + k, rows: String(rows), placeholder: ph });
    t.addEventListener("focus", () => setActive(k));
    t.addEventListener("input", () => { autosize(t); scheduleSave(); });
    box.append(h("div", { class: "card", id: "card_" + k }, h("div", { class: "h2" }, title), t));
  });
  const bar = $("aibar");
  AIBTNS.forEach(([label, color, mode]) => {
    bar.append(h("button", { class: "btn aibtn " + color, onclick: () => runAI(mode) }, label));
  });
  bar.append(h("span", { id: "status" }));
  setActive("procedura");

  ["name", "date", "project"].forEach(id => $(id).addEventListener("input", scheduleSave));
  $("btnNew").onclick = () => newExp().catch(fail);
  $("btnSave").onclick = () => saveNow().catch(fail);
  $("btnDel").onclick = () => deleteExp().catch(fail);
  $("btnExport").onclick = async () => {
    try {
      await saveNow();
      status("📄 Creo il documento Word…");
      const d = await api("export", { id: curId });
      status("✅ Word salvato: " + d.file + " — cartella " + d.folder + (d.drive ? " · copiato anche su Drive" : ""), 9000);
    } catch (e) { fail(e); }
  };
  $("btnKey").onclick = () => openKey();
  $("btnDraw").onclick = () => openMolEditor().catch(fail);
  $("btnSync").onclick = () => syncDrive(false).catch(fail);
  $("btnChem").onclick = () => openChemDraw().catch(fail);
  $("btnPasteChem").onclick = () => pasteChem(false).catch(fail);
  $("btnSector").onclick = () => openSectors(false);

  try { const e = localStorage.getItem("diario_engine"); if (e === "claude" || e === "gemini") $("engine").value = e; } catch (e) {}
  $("engine").addEventListener("change", () => { try { localStorage.setItem("diario_engine", $("engine").value); } catch (e) {} });
  $("btnNewGroup").onclick = () => newGroup(null).catch(fail);
  document.addEventListener("click", closeMenu);
  $("list").addEventListener("scroll", closeMenu);
  window.addEventListener("keydown", ev => { if (ev.key === "Escape") closeMenu(); });
  $("btnArchive").onclick = () => { archiveMode = !archiveMode; renderList(); };
  $("groupsel").addEventListener("change", async () => {
    if (curId == null) return;
    const v = $("groupsel").value === "" ? null : Number($("groupsel").value);
    try {
      await api("exp_move", { id: curId, group_id: v });
      curGroup = v;
      await loadList();
      status("✅ Esperimento spostato", 2500);
    } catch (e) { fail(e); }
  });
  const lst = $("list");   // lasciare un elemento sullo sfondo dell'elenco lo toglie dal gruppo
  lst.addEventListener("dragover", ev => ev.preventDefault());
  lst.addEventListener("drop", ev => { ev.preventDefault(); handleDrop(ev.dataTransfer.getData("text/plain"), null); });
  $("search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadList().catch(() => {}), 250);
  });
  $("btnAdd").onclick = () => $("filepick").click();
  $("filepick").onchange = e => { uploadFiles(Array.from(e.target.files)).catch(fail); e.target.value = ""; };
  const drop = $("drop");
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => uploadFiles(Array.from(e.dataTransfer.files)).catch(fail));
  // evita che un file trascinato fuori dalla zona venga aperto dal browser
  window.addEventListener("dragover", e => e.preventDefault());
  window.addEventListener("drop", e => e.preventDefault());
  // incolla un'immagine (es. uno schema copiato da ChemDraw con ⌘C) come allegato
  window.addEventListener("paste", e => {
    const items = Array.from((e.clipboardData && e.clipboardData.items) || []);
    const it = items.find(x => x.kind === "file" && /^image\/(png|jpeg)$/.test(x.type));
    if (!it) {
      // ChemDraw (soprattutto su Mac) non mette un'immagine "normale" negli appunti del browser:
      // se non c'e' testo da incollare, la legge il programma direttamente dagli appunti di sistema.
      const hasText = items.some(x => x.kind === "string" && x.type === "text/plain");
      if (!hasText && curId != null) { e.preventDefault(); pasteChem(true).catch(() => {}); }
      return;
    }
    const f = it.getAsFile();
    if (!f) return;
    e.preventDefault();
    const pad = n => String(n).padStart(2, "0");
    const dt = new Date();
    const stamp = dt.getFullYear() + pad(dt.getMonth() + 1) + pad(dt.getDate()) + "-" +
      pad(dt.getHours()) + pad(dt.getMinutes()) + pad(dt.getSeconds());
    const name = "incollata-" + stamp + (f.type === "image/jpeg" ? ".jpg" : ".png");
    uploadFiles([new File([f], name, { type: f.type })]).catch(fail);
  });
  window.addEventListener("keydown", e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") { e.preventDefault(); saveNow().catch(fail); }
  });
  window.addEventListener("pagehide", () => {
    if (dirty && curId != null) {
      fetch("/api/save", { method: "POST", keepalive: true,
        headers: { "X-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify(collect()) });
    }
  });
}

(async () => {
  build();
  let firstRun = false;
  try { firstRun = await loadSectors(); } catch (e) {}
  const d = await api("list", { q: "" });
  if (d.items.length) await openExp(d.items[0].id); else await newExp();
  if (firstRun) openSectors(true);
})().catch(fail);
</script>
</body>
</html>
"""


def main():
    init_db()
    srv = None
    for port in range(8765, 8785):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if srv is None:
        print("Nessuna porta libera tra 8765 e 8784.")
        sys.exit(1)
    url = "http://127.0.0.1:%d/" % srv.server_port
    print("🔬 Diario del Ricercatore attivo su", url)
    print("Si apre nel browser. Per fermarlo chiudi questa finestra del Terminale (o premi Ctrl+C).")
    sys.stdout.flush()
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    threading.Thread(target=auto_sync_loop, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
