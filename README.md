# 🔬 Diario del Ricercatore

> I tuoi dati e le chiavi API non stanno in questo repository: vivono solo sul tuo computer in `~/DiarioRicercatore/` (vedi «Dove sono i dati»). L'app non invia nulla online, salvo i testi che scegli tu di mandare all'AI (Claude o Gemini) e, se lo attivi, la copia nella tua cartella Google Drive.

**Requisiti:** Mac con Python 3 (nessuna libreria da installare). Funziona anche su Linux/Windows avviando `python3 diario_web.py`, ma i pulsanti per ChemDraw e il Finder sono pensati per macOS.

## Scaricare
```bash
git clone <URL-DI-QUESTO-REPOSITORY> diario-ricercatore
cd diario-ricercatore
python3 diario_web.py        # oppure doppio clic su "Avvia Diario.command"
```

*(Versione browser)*

Quaderno di laboratorio digitale per Mac. Si apre nel browser (Safari/Chrome) ma gira tutto sul tuo Mac: nessuna installazione, nessuna libreria.

## Avvio
1. Metti nella stessa cartella: `diario_web.py` e `Avvia Diario.command`.
2. Una sola volta, da Terminale: `chmod +x ` (con lo spazio) e trascina dentro il file `Avvia Diario.command`, poi Invio.
3. Doppio clic su `Avvia Diario.command`: nel browser si apre il Diario.
4. Lascia aperta la finestra del Terminale mentre lavori. Per fermare il Diario chiudila (o Ctrl+C).
   Per riaprirlo basta rifare doppio clic sul file: non riaprire una vecchia scheda del browser.

## Uso
- **＋ Nuovo esperimento**: nome, data, progetto/molecola target.
- Sezioni: Obiettivo, Procedura, Risultati, Note. Salvataggio automatico dopo ogni modifica (⌘S per forzarlo).
- **📁 Gruppi e sottogruppi** (come le tracce di gruppo di Ableton): "📁＋ Gruppo" in alto a sinistra crea un gruppo. Ogni gruppo ha un colore, si apre/chiude con un clic e mostra il numero di esperimenti che contiene. Con il pulsante **⋯** del gruppo: nuovo esperimento dentro il gruppo, nuovo sottogruppo (anche a più livelli), rinomina, colore, archivia, elimina.
  - Per spostare: trascina un esperimento (o un intero gruppo) sopra un gruppo; trascinandolo sullo sfondo dell'elenco torna fuori dai gruppi. In alternativa usa il menu "📁 Gruppo" sotto il nome dell'esperimento.
  - **📦 Archivia**: il gruppo (con tutti i suoi sottogruppi ed esperimenti) scompare dall'elenco laterale. Non viene cancellato nulla: lo ritrovi con il pulsante "📦 Archivio" in basso a sinistra, dove ⋯ → Ripristina lo rimette nell'elenco. La ricerca cerca solo fra gli esperimenti visibili, oppure solo nell'archivio se la vista Archivio è aperta.
  - "Elimina il gruppo" toglie solo il contenitore: gli esperimenti non vengono cancellati e passano al gruppo superiore.
- **📎 Allegati**: "Aggiungi file" oppure trascina i file ChemDraw (.cdx, .cdxml, .cd) o altri file. "Apri" li apre con ChemDraw, "Finder" li mostra nella cartella.
- **Schemi ChemDraw nel Word**: Word non legge i file ChemDraw, quindi serve anche l'immagine dello schema, che compare nel documento Word (sezione "Schema di reazione e strutture", centrata e ridimensionata alla pagina). Due modi:
  1. In ChemDraw seleziona la struttura/lo schema, ⌘C, poi ⌘V sulla pagina del Diario: l'immagine viene allegata da sola.
  2. Oppure in ChemDraw "Salva con nome" PNG (meglio ad alta risoluzione) e trascina il PNG nella pagina. Se ha lo stesso nome del file .cdx/.cdxml vengono abbinati.
  Se un file ChemDraw non ha un'immagine associata, il Diario te lo segnala con un avviso arancione. Sono accettati PNG e JPG.
- **📄 Esporta in Word**: crea un documento .docx dell'esperimento (titolo, data, progetto, sezioni compilate, elenco allegati), lo salva in `~/DiarioRicercatore/esportazioni/` e lo apre. Da Word puoi poi usare File → Esporta/Salva come per ottenere il PDF o un vecchio .doc.
- **✨ AI** (agisce sulla sezione dove hai il cursore): Stila, Correggi, In inglese, Suggerisci titolo, Istruzione libera. La proposta compare in una finestra che puoi modificare prima di applicarla.

## 🧪 Disegnare le molecole
Nella card **Allegati**, il pulsante **🧪 Disegna molecola** apre un editor di strutture ([JSME](https://jsme-editor.github.io/), gratuito). Disegni la molecola o lo schema, dai un nome e premi «Aggiungi all'esperimento»: vengono allegati
- un'**immagine PNG** (compare nel documento Word e nell'anteprima) e
- un file **.mol** modificabile (si apre anche con ChemDraw), con lo SMILES mostrato sotto il disegno.

L'editor si carica da internet (jsme-editor.github.io). **Per usarlo anche offline:** scarica JSME dal suo sito, decomprimilo e metti la cartella `jsme` (quella che contiene `jsme.nocache.js`) accanto a `diario_web.py`: viene usata in automatico. La cartella `jsme/` è esclusa da git.

## ☁️ Google Drive (sincronizzazione e backup)
Serve l'app **Google Drive per desktop** sul Mac: crea una cartella sincronizzata (di solito in `~/Library/CloudStorage/GoogleDrive-…/Il mio Drive`). In «🔑 Chiavi API e impostazioni» → **Cartella di Google Drive** premi «🔎 Cerca Google Drive» (o scrivi il percorso) e salva.

Nella cartella scelta l'app crea **Diario del Ricercatore/** con:
- `Esperimenti/` — un documento **Word** per ogni esperimento (aggiornato quando lo modifichi);
- `Backup/` — copia del database e degli allegati.

Si aggiorna da solo ogni 5 minuti se hai fatto modifiche, a ogni «📄 Esporta in Word» e con il pulsante **☁️ Sincronizza con Drive**. Il database di lavoro resta sempre in `~/DiarioRicercatore/` (non in Drive: una cartella sincronizzata può rovinare un database aperto). È una copia a senso unico: le modifiche fatte su Drive non tornano nel Diario.

## ⚗️ ChemDraw
Il pulsante **⚗️ ChemDraw** in alto apre l'app ChemDraw. La cerca da sola in Applicazioni; se non la trova ti chiede il nome (es. `ChemDraw 23.1`) o il percorso e se lo ricorda. Puoi cambiarlo in "🔑 Chiavi API e impostazioni".

## Scegliere l'AI: Claude o Gemini
Nella barra ✨ sopra le sezioni c'è il menu **🟣 Claude / 🔵 Gemini**: tutte le funzioni (Stila, Correggi, In inglese, Titolo, Istruzione libera) usano il motore scelto, che l'app ricorda. La proposta è sempre da controllare prima di applicarla.

## Chiavi API (per le funzioni AI)
Clic su "🔑 Chiavi API e impostazioni" in basso a sinistra.
- **Claude**: chiave Anthropic da console.anthropic.com → API keys → Create Key. L'uso dell'API è a consumo, separato dall'abbonamento Claude.
- **Gemini**: chiave da aistudio.google.com/apikey. Il modello viene scelto in automatico fra quelli disponibili per la tua chiave (di preferenza un "flash" stabile); se vuoi puoi scriverlo a mano (es. `gemini-2.5-flash`).
- Le chiavi sono salvate solo sul tuo Mac in `~/DiarioRicercatore/config.json`; l'app non le mostra più dopo il salvataggio ("già salvata"), puoi sostituirle o rimuoverle.
- **Chiavi Gemini che iniziano con `AQ.`**: è il nuovo formato di AI Studio e Google segnala che alcune non sono ancora accettate dalle chiamate normali (errore 401 «ACCESS_TOKEN_TYPE_UNSUPPORTED»). Se succede, l'app te lo dice: crea allora una chiave classica (inizia con `AIza`) da Google Cloud Console → API e servizi → Credenziali → Crea credenziali → Chiave API, con l'API «Generative Language» abilitata.

## Dove sono i dati
`~/DiarioRicercatore/` (database `diario.db`, cartella `allegati/`, `config.json` con la chiave). Per il backup copia quella cartella.

## Sicurezza
Il server ascolta solo su 127.0.0.1 (il tuo Mac) e ogni richiesta richiede un codice casuale generato a ogni avvio.

## Nota sull'AI
L'AI è istruita a non inventare dati e a segnalare con [da completare: …] ciò che manca. Controlla sempre quantità, rese e nomi prima di applicare il testo.

## File del repository
- `diario_web.py` — l'applicazione (server locale + pagina nel browser), un solo file.
- `Avvia Diario.command` — avvio con doppio clic su Mac.
- `legacy/diario_finestra_nativa.py` — vecchia versione con finestra nativa (richiede `customtkinter`); non più mantenuta.

## Prove automatiche
`python3 tests/test_sync.py` prova la sincronizzazione con una cartella Drive finta (in una cartella temporanea: non tocca i tuoi dati).

## Licenza
MIT — vedi il file `LICENSE`.
