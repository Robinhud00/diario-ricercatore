#!/usr/bin/env python3
"""
Diario del Ricercatore - quaderno di laboratorio digitale per Mac
- Esperimenti con nome, data, progetto
- Allegati ChemDraw (.cdx, .cdxml, .cd) e qualsiasi altro file
- Assistente AI (Claude) per stilare / correggere / tradurre il testo
Dati salvati in ~/DiarioRicercatore
"""
import os
import json
import shutil
import sqlite3
import subprocess
import threading
import datetime
import customtkinter as ctk
from tkinter import filedialog, messagebox

APP_DIR = os.path.expanduser("~/DiarioRicercatore")
ATT_DIR = os.path.join(APP_DIR, "allegati")
DB_PATH = os.path.join(APP_DIR, "diario.db")
CFG_PATH = os.path.join(APP_DIR, "config.json")
MODEL = "claude-sonnet-5-5"

os.makedirs(ATT_DIR, exist_ok=True)

# ---------- palette ----------
VIOLA = "#7C3AED"
VIOLA_SCURO = "#5B21B6"
VIOLA_CHIARO = "#EDE9FE"
VERDE = "#10B981"
BLU = "#3B82F6"
ARANCIO = "#F59E0B"
ROSA = "#EC4899"
GRIGIO = "#F8F7FF"

SECTIONS = [
    ("obiettivo", "🎯 Obiettivo", 90),
    ("procedura", "🧪 Procedura sperimentale", 260),
    ("risultati", "📊 Risultati e osservazioni", 160),
    ("note", "📝 Note e prossimi passi", 110),
]

# ---------- AI ----------
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
    "inglese": (
        "Traduci in inglese scientifico, stile sezione sperimentale (past tense, impersonal)."
    ),
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


def get_api_key():
    return os.environ.get("ANTHROPIC_API_KEY") or load_cfg().get("api_key", "")


def ask_claude(system, user):
    import anthropic
    client = anthropic.Anthropic(api_key=get_api_key())
    msg = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "text", None)).strip()


# ---------- DB ----------
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
        """
    )
    con.commit()
    con.close()


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---------- App ----------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        self.title("🔬 Diario del Ricercatore")
        self.geometry("1280x820")
        self.minsize(1000, 650)
        self.configure(fg_color=GRIGIO)

        self.cur_id = None
        self.active = "procedura"
        self.boxes = {}
        self.sec_labels = {}

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.build_sidebar()
        self.build_main()
        self.bind("<Command-s>", lambda e: self.save_current(True))
        self.bind("<Control-s>", lambda e: self.save_current(True))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.refresh_list()
        con = db()
        row = con.execute("SELECT id FROM experiments ORDER BY updated DESC LIMIT 1").fetchone()
        con.close()
        if row:
            self.load_experiment(row["id"])
        else:
            self.new_experiment()

    # ----- sidebar -----
    def build_sidebar(self):
        side = ctk.CTkFrame(self, width=300, corner_radius=0, fg_color=VIOLA)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(side, text="🔬 Diario del\nRicercatore", font=("Helvetica Neue", 26, "bold"),
                     text_color="white", justify="left").grid(row=0, column=0, padx=20, pady=(24, 10), sticky="w")

        ctk.CTkButton(side, text="＋  Nuovo esperimento", height=40, fg_color=ARANCIO, hover_color="#D97706",
                      text_color="white", font=("Helvetica Neue", 15, "bold"),
                      command=self.new_experiment).grid(row=1, column=0, padx=20, pady=6, sticky="ew")

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.refresh_list())
        ctk.CTkEntry(side, placeholder_text="🔍 Cerca esperimento…", textvariable=self.search_var,
                     height=36, fg_color="white", border_width=0).grid(row=2, column=0, padx=20, pady=6, sticky="ew")

        self.list_frame = ctk.CTkScrollableFrame(side, fg_color=VIOLA_SCURO, corner_radius=12)
        self.list_frame.grid(row=3, column=0, padx=14, pady=8, sticky="nsew")
        self.list_frame.grid_columnconfigure(0, weight=1)
        side.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(side, text="🔑  Chiave API Claude", height=32, fg_color="transparent",
                      border_width=1, border_color="white", hover_color=VIOLA_SCURO,
                      command=self.ask_key).grid(row=4, column=0, padx=20, pady=(4, 16), sticky="ew")

    def refresh_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        q = self.search_var.get().strip() if hasattr(self, "search_var") else ""
        con = db()
        rows = con.execute(
            "SELECT id,name,date FROM experiments WHERE name LIKE ? OR project LIKE ? ORDER BY updated DESC",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
        con.close()
        for r in rows:
            sel = r["id"] == self.cur_id
            ctk.CTkButton(
                self.list_frame, text=f"🧪 {r['name'] or 'Senza nome'}\n     {r['date'] or ''}",
                anchor="w", height=48, corner_radius=10,
                fg_color=VIOLA_CHIARO if sel else "transparent",
                text_color=VIOLA_SCURO if sel else "white",
                hover_color="#8B5CF6",
                command=lambda i=r["id"]: self.switch_to(i),
            ).grid(sticky="ew", pady=2, padx=2)

    # ----- main -----
    def build_main(self):
        main = ctk.CTkFrame(self, fg_color=GRIGIO, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        # header: nome, data, progetto
        head = ctk.CTkFrame(main, fg_color="white", corner_radius=14)
        head.grid(row=0, column=0, padx=20, pady=(18, 8), sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        self.name_entry = ctk.CTkEntry(head, placeholder_text="Nome dell'esperimento (es. NG012 – step 3)",
                                       font=("Helvetica Neue", 22, "bold"), height=46, border_width=0,
                                       fg_color=VIOLA_CHIARO)
        self.name_entry.grid(row=0, column=0, columnspan=3, padx=14, pady=(14, 6), sticky="ew")
        self.date_entry = ctk.CTkEntry(head, placeholder_text="Data", width=140, height=34)
        self.date_entry.grid(row=1, column=0, padx=(14, 6), pady=(0, 14), sticky="w")
        self.project_entry = ctk.CTkEntry(head, placeholder_text="Progetto / molecola target", height=34)
        self.project_entry.grid(row=1, column=1, padx=6, pady=(0, 14), sticky="ew")
        head.grid_columnconfigure(1, weight=2)
        ctk.CTkButton(head, text="💾 Salva", width=90, height=34, fg_color=VERDE, hover_color="#059669",
                      command=lambda: self.save_current(True)).grid(row=1, column=2, padx=(6, 6), pady=(0, 14))
        ctk.CTkButton(head, text="🗑", width=40, height=34, fg_color="#EF4444", hover_color="#DC2626",
                      command=self.delete_experiment).grid(row=1, column=3, padx=(0, 14), pady=(0, 14))

        # AI toolbar
        bar = ctk.CTkFrame(main, fg_color="white", corner_radius=14)
        bar.grid(row=1, column=0, padx=20, pady=6, sticky="ew")
        self.ai_label = ctk.CTkLabel(bar, text="✨ AI su: Procedura", font=("Helvetica Neue", 14, "bold"),
                                     text_color=VIOLA)
        self.ai_label.grid(row=0, column=0, padx=14, pady=10)
        btns = [
            ("✨ Stila", VIOLA, "stila"),
            ("🔤 Correggi", VERDE, "correggi"),
            ("🌍 In inglese", BLU, "inglese"),
            ("💡 Suggerisci titolo", ARANCIO, "titolo"),
            ("🪄 Istruzione libera", ROSA, "libera"),
        ]
        for i, (t, c, m) in enumerate(btns, start=1):
            ctk.CTkButton(bar, text=t, height=34, fg_color=c, hover_color=VIOLA_SCURO,
                          command=lambda m=m: self.run_ai(m)).grid(row=0, column=i, padx=4, pady=10)
        self.status = ctk.CTkLabel(bar, text="", text_color="#6B7280")
        self.status.grid(row=0, column=len(btns) + 1, padx=10)

        # corpo scorrevole
        body = ctk.CTkScrollableFrame(main, fg_color="transparent")
        body.grid(row=2, column=0, padx=14, pady=(4, 14), sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        r = 0
        for key, title, h in SECTIONS:
            card = ctk.CTkFrame(body, fg_color="white", corner_radius=14)
            card.grid(row=r, column=0, padx=6, pady=6, sticky="ew")
            card.grid_columnconfigure(0, weight=1)
            lbl = ctk.CTkLabel(card, text=title, font=("Helvetica Neue", 16, "bold"), text_color=VIOLA_SCURO)
            lbl.grid(row=0, column=0, padx=14, pady=(10, 2), sticky="w")
            tb = ctk.CTkTextbox(card, height=h, wrap="word", font=("Helvetica Neue", 14),
                                fg_color="#FAFAFF", border_width=1, border_color="#DDD6FE")
            tb.grid(row=1, column=0, padx=14, pady=(2, 12), sticky="ew")
            tb.bind("<FocusIn>", lambda e, k=key: self.set_active(k))
            self.boxes[key] = tb
            self.sec_labels[key] = title
            r += 1

        # allegati
        att = ctk.CTkFrame(body, fg_color="white", corner_radius=14)
        att.grid(row=r, column=0, padx=6, pady=6, sticky="ew")
        att.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(att, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        ctk.CTkLabel(top, text="📎 Allegati (ChemDraw e altri file)", font=("Helvetica Neue", 16, "bold"),
                     text_color=VIOLA_SCURO).pack(side="left")
        ctk.CTkButton(top, text="＋ Aggiungi file", height=32, fg_color=BLU, hover_color="#1D4ED8",
                      command=self.add_attachments).pack(side="right")
        self.att_frame = ctk.CTkFrame(att, fg_color="transparent")
        self.att_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        self.att_frame.grid_columnconfigure(0, weight=1)

    def set_active(self, key):
        self.active = key
        self.ai_label.configure(text="✨ AI su: " + self.sec_labels[key].split(" ", 1)[1])

    # ----- logic -----
    def switch_to(self, exp_id):
        if exp_id == self.cur_id:
            return
        self.save_current()
        self.load_experiment(exp_id)

    def new_experiment(self):
        self.save_current()
        con = db()
        cur = con.execute(
            "INSERT INTO experiments(name,date,project,updated) VALUES(?,?,?,?)",
            ("Nuovo esperimento", datetime.date.today().strftime("%d/%m/%Y"), "", now()),
        )
        con.commit()
        new_id = cur.lastrowid
        con.close()
        self.load_experiment(new_id)

    def load_experiment(self, exp_id):
        con = db()
        row = con.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
        con.close()
        if not row:
            return
        self.cur_id = exp_id
        for e, v in ((self.name_entry, row["name"]), (self.date_entry, row["date"]),
                     (self.project_entry, row["project"])):
            e.delete(0, "end")
            e.insert(0, v or "")
        for key, tb in self.boxes.items():
            tb.delete("1.0", "end")
            tb.insert("1.0", row[key] or "")
        self.refresh_attachments()
        self.refresh_list()

    def save_current(self, show=False):
        if self.cur_id is None:
            return
        con = db()
        con.execute(
            "UPDATE experiments SET name=?,date=?,project=?,obiettivo=?,procedura=?,risultati=?,note=?,updated=? WHERE id=?",
            (self.name_entry.get().strip(), self.date_entry.get().strip(), self.project_entry.get().strip(),
             *[self.boxes[k].get("1.0", "end-1c") for k, _, _ in SECTIONS], now(), self.cur_id),
        )
        con.commit()
        con.close()
        if show:
            self.set_status("✅ Salvato")
            self.refresh_list()

    def delete_experiment(self):
        if self.cur_id is None:
            return
        if not messagebox.askyesno("Elimina", "Eliminare questo esperimento e i suoi allegati?"):
            return
        con = db()
        con.execute("DELETE FROM attachments WHERE exp_id=?", (self.cur_id,))
        con.execute("DELETE FROM experiments WHERE id=?", (self.cur_id,))
        con.commit()
        con.close()
        shutil.rmtree(os.path.join(ATT_DIR, str(self.cur_id)), ignore_errors=True)
        self.cur_id = None
        self.refresh_list()
        con = db()
        row = con.execute("SELECT id FROM experiments ORDER BY updated DESC LIMIT 1").fetchone()
        con.close()
        if row:
            self.load_experiment(row["id"])
        else:
            self.new_experiment()

    def set_status(self, text):
        self.status.configure(text=text)
        if text.startswith("✅"):
            self.after(2500, lambda: self.status.configure(text=""))

    # ----- allegati -----
    def add_attachments(self):
        if self.cur_id is None:
            return
        paths = filedialog.askopenfilenames(
            title="Scegli file ChemDraw o altri file",
            filetypes=[("ChemDraw", "*.cdx *.cdxml *.cd *.c3xml *.chm"), ("Tutti i file", "*.*")],
        )
        if not paths:
            return
        dest_dir = os.path.join(ATT_DIR, str(self.cur_id))
        os.makedirs(dest_dir, exist_ok=True)
        con = db()
        for p in paths:
            name = os.path.basename(p)
            dest = os.path.join(dest_dir, name)
            base, ext = os.path.splitext(name)
            n = 1
            while os.path.exists(dest):
                dest = os.path.join(dest_dir, f"{base}_{n}{ext}")
                n += 1
            shutil.copy2(p, dest)
            con.execute("INSERT INTO attachments(exp_id,filename,path) VALUES(?,?,?)",
                        (self.cur_id, os.path.basename(dest), dest))
        con.commit()
        con.close()
        self.refresh_attachments()

    def refresh_attachments(self):
        for w in self.att_frame.winfo_children():
            w.destroy()
        con = db()
        rows = con.execute("SELECT * FROM attachments WHERE exp_id=?", (self.cur_id,)).fetchall()
        con.close()
        if not rows:
            ctk.CTkLabel(self.att_frame, text="Nessun allegato. Aggiungi i tuoi schemi ChemDraw.",
                         text_color="#9CA3AF").grid(sticky="w")
        for i, r in enumerate(rows):
            line = ctk.CTkFrame(self.att_frame, fg_color=VIOLA_CHIARO, corner_radius=10)
            line.grid(row=i, column=0, sticky="ew", pady=3)
            line.grid_columnconfigure(0, weight=1)
            icon = "⚗️" if r["filename"].lower().endswith((".cdx", ".cdxml", ".cd", ".c3xml")) else "📄"
            ctk.CTkLabel(line, text=f"{icon}  {r['filename']}", anchor="w").grid(row=0, column=0, padx=12, pady=6, sticky="w")
            ctk.CTkButton(line, text="Apri", width=60, height=28, fg_color=VIOLA,
                          command=lambda p=r["path"]: subprocess.run(["open", p])).grid(row=0, column=1, padx=3)
            ctk.CTkButton(line, text="Finder", width=60, height=28, fg_color=BLU,
                          command=lambda p=r["path"]: subprocess.run(["open", "-R", p])).grid(row=0, column=2, padx=3)
            ctk.CTkButton(line, text="✕", width=30, height=28, fg_color="#EF4444",
                          command=lambda a=r["id"], p=r["path"]: self.remove_attachment(a, p)).grid(row=0, column=3, padx=(3, 8))

    def remove_attachment(self, att_id, path):
        if not messagebox.askyesno("Rimuovi", "Rimuovere l'allegato?"):
            return
        con = db()
        con.execute("DELETE FROM attachments WHERE id=?", (att_id,))
        con.commit()
        con.close()
        try:
            os.remove(path)
        except OSError:
            pass
        self.refresh_attachments()

    # ----- AI -----
    def ask_key(self):
        win = ctk.CTkToplevel(self)
        win.title("Chiave API")
        win.geometry("480x190")
        win.transient(self)
        ctk.CTkLabel(win, text="Incolla la tua chiave API Anthropic\n(console.anthropic.com → API keys)",
                     justify="left").pack(padx=20, pady=(18, 6), anchor="w")
        e = ctk.CTkEntry(win, show="•", height=36)
        e.pack(padx=20, fill="x")
        e.insert(0, load_cfg().get("api_key", ""))

        def ok():
            cfg = load_cfg()
            cfg["api_key"] = e.get().strip()
            save_cfg(cfg)
            win.destroy()

        ctk.CTkButton(win, text="Salva", fg_color=VERDE, command=ok).pack(pady=16)

    def run_ai(self, mode):
        if not get_api_key():
            self.ask_key()
            return
        self.save_current()
        if mode == "titolo":
            text = "\n\n".join(f"{t}:\n{self.boxes[k].get('1.0', 'end-1c')}" for k, t, _ in SECTIONS)
            target = "name"
        else:
            text = self.boxes[self.active].get("1.0", "end-1c")
            target = self.active
        if not text.strip():
            messagebox.showinfo("Testo vuoto", "Scrivi prima qualcosa nella sezione selezionata.")
            return

        if mode == "libera":
            win = ctk.CTkToplevel(self)
            win.title("Istruzione libera")
            win.geometry("520x200")
            win.transient(self)
            ctk.CTkLabel(win, text="Cosa vuoi che faccia Claude con questo testo?").pack(padx=20, pady=(18, 6), anchor="w")
            e = ctk.CTkEntry(win, height=36, placeholder_text="es. riassumi in 3 righe / aggiungi le rese in tabella")
            e.pack(padx=20, fill="x")

            def go():
                instr = e.get().strip()
                win.destroy()
                if instr:
                    self._call(BASE_RULES + " Istruzione dell'utente: " + instr, text, target)

            ctk.CTkButton(win, text="Vai ✨", fg_color=ROSA, command=go).pack(pady=16)
            return
        self._call(BASE_RULES + " " + MODES[mode], text, target)

    def _call(self, system, text, target):
        self.set_status("✨ Claude sta lavorando…")

        def worker():
            try:
                res = ask_claude(system, text)
                self.after(0, lambda: self.show_preview(res, target))
            except Exception as ex:
                self.after(0, lambda: messagebox.showerror("Errore AI", str(ex)))
            finally:
                self.after(0, lambda: self.set_status(""))

        threading.Thread(target=worker, daemon=True).start()

    def show_preview(self, result, target):
        win = ctk.CTkToplevel(self)
        win.title("✨ Proposta di Claude")
        win.geometry("760x520")
        win.transient(self)
        ctk.CTkLabel(win, text="Controlla e modifica la proposta prima di applicarla:",
                     font=("Helvetica Neue", 15, "bold"), text_color=VIOLA_SCURO).pack(padx=20, pady=(16, 6), anchor="w")
        tb = ctk.CTkTextbox(win, wrap="word", font=("Helvetica Neue", 14))
        tb.pack(padx=20, pady=6, fill="both", expand=True)
        tb.insert("1.0", result)
        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(pady=14)

        def apply(append=False):
            new = tb.get("1.0", "end-1c")
            if target == "name":
                self.name_entry.delete(0, "end")
                self.name_entry.insert(0, new.strip())
            else:
                box = self.boxes[target]
                if append:
                    box.insert("end", "\n\n" + new)
                else:
                    box.delete("1.0", "end")
                    box.insert("1.0", new)
            self.save_current(True)
            win.destroy()

        ctk.CTkButton(row, text="✅ Sostituisci", fg_color=VERDE, command=apply).pack(side="left", padx=6)
        if target != "name":
            ctk.CTkButton(row, text="➕ Aggiungi sotto", fg_color=BLU, command=lambda: apply(True)).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Annulla", fg_color="#9CA3AF", command=win.destroy).pack(side="left", padx=6)

    def on_close(self):
        self.save_current()
        self.destroy()


if __name__ == "__main__":
    init_db()
    App().mainloop()
