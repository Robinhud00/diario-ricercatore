# 🔬 Diario del Ricercatore

> I tuoi dati e le chiavi API non stanno in questo repository: vivono solo sul tuo computer in `~/DiarioRicercatore/` (vedi «Dove sono i dati»). L'app non invia nulla online, salvo i testi che scegli tu di mandare all'AI (Claude o Gemini) e, se lo attivi, la copia nella tua cartella Google Drive.

**Requisiti:** Python 3 recente (provato con la 3.13; le versioni 3.9+ dovrebbero andare bene), nessuna libreria da installare.
- **Mac:** Python 3 di solito c'è già; altrimenti https://www.python.org/downloads/macos/
- **Windows 10/11:** installa Python da https://www.python.org/downloads/windows/ e **spunta «Add python.exe to PATH»** nella prima schermata dell'installatore. Serve anche `curl`, già incluso in Windows 10/11 aggiornato.
- Linux: `python3 diario_web.py` funziona, ma ChemDraw non è supportato.

## Scaricare
```bash
git clone <URL-DI-QUESTO-REPOSITORY> diario-ricercatore
cd diario-ricercatore
python3 diario_web.py        # Mac/Linux — oppure doppio clic su "Avvia Diario.command"
py -3 diario_web.py          # Windows — oppure doppio clic su "Avvia Diario.bat"
```

*(Versione browser)*

Quaderno di laboratorio digitale per **Mac e Windows**. Si apre nel browser ma gira tutto sul tuo computer: nessuna libreria da installare, serve solo Python 3.

## Avvio (il più semplice possibile)
**Opzione A – app già pronta (consigliata per chi non è esperto).** Nella pagina *Releases* di GitHub (o dal workflow «Crea app pronte», vedi sotto) ci sono `Diario-Windows.zip` e `Diario-Mac-Apple-Silicon.zip`: scarica, estrai, doppio clic. Non serve installare Python. La prima volta Windows (SmartScreen: «Ulteriori informazioni» → «Esegui comunque») e Mac (tasto destro → «Apri») mostrano un avviso perché l'app non è firmata: è normale.

**Opzione B – con Python (tutti i computer).**
- **Windows:** doppio clic su `Avvia Diario.bat`. Se Python non c'è lo installa da solo (winget); se non può, apre la pagina di download con le istruzioni.
- **Mac:** una sola volta `chmod +x ` + trascina `Avvia Diario.command` nel Terminale + Invio; poi doppio clic. In alternativa: `python3 diario_web.py`.

In tutti i casi il Diario **parte in background**: la finestra nera si chiude da sola (o si può chiudere senza paura, non ferma niente). Fare di nuovo doppio clic non lo avvia due volte: riapre solo la scheda del browser. Per spegnerlo usa il pulsante **⏻ Chiudi il Diario** nella barra a sinistra (da terminale: `python3 diario_web.py --stop`). Se nessuno lo usa per 8 ore si spegne da solo. Eventuali errori sono nel file `~/DiarioRicercatore/diario.log`.

### Creare le app pronte (una volta, per chi distribuisce)
Su GitHub: **Actions → «Crea app pronte» → Run workflow** (oppure crea una release con un tag, es. `v1.0`). Dopo qualche minuto trovi gli zip in *Artifacts* (e nella release). Le app Mac sono per i chip Apple (M1–M4); sui Mac Intel usa l'opzione B.

## Documenti Word automatici
Ogni volta che scrivi o modifichi un esperimento il Diario crea/aggiorna da solo il suo Word nella cartella `~/DiarioRicercatore/Documenti/`, organizzata come nella barra a sinistra:

```
Documenti/
  Gruppo/
    Sottogruppo/
      Nome esperimento (n.12)/
        Nome esperimento (n.12).docx
        Allegati/   (immagini, file, .cdx…)
```
Se rinomini o sposti un gruppo o un esperimento, le cartelle si spostano di conseguenza; un esperimento eliminato finisce in `Documenti/_Eliminati` (mai cancellato). Con la cartella Google Drive impostata la stessa struttura viene copiata su Drive: **condividi con il supervisore la cartella «Diario del Ricercatore» di Drive e lui vede i Word sempre aggiornati**.
Al primo avvio dopo l'aggiornamento i vecchi Word «piatti» (`esportazioni/` e `Esperimenti/` su Drive) vengono messi in ordine e archiviati in `_gia_riordinati` / `Esperimenti_vecchi` (nulla viene cancellato). Puoi rifarlo quando vuoi con **🗂️ Riordina documenti**; **📂 Cartella documenti** apre la cartella.

## Lingua delle voci e versione inglese
In alto, accanto alla scelta Claude/Gemini, c'è **«Lingua della voce»**: *nativa* o *English*. L'AI (Stila, Correggi, Titolo) scrive nella lingua scelta e il Word ha titoli ed etichette in quella lingua. La scelta si ricorda per le nuove voci.
Il pulsante **🌍 Versione inglese (nuovo Word)** traduce titolo e sezioni e crea un secondo documento nella stessa cartella: `Nome (n.12) - English version.docx`, senza toccare il testo originale. Per aggiornarlo dopo modifiche, premilo di nuovo. (Le tabelle di dati restano come le hai scritte.)

## Documento unico di progetto
A fine progetto: menu **⋯ del gruppo → 📚 Unisci tutto in un documento…** (oppure il pulsante **📚 Documento di progetto**, che permette di scegliere anche un *progetto* invece di un gruppo). Il Diario crea un solo Word con indice e tutti gli esperimenti in ordine di data (sottogruppi compresi), ciascuno su una pagina nuova con le sue figure, tabelle e allegati. Lo trovi in `Documenti/_Riepiloghi/` (e su Drive); è un file a parte, i Word dei singoli esperimenti non cambiano. Con «in inglese» usa le versioni inglesi già create; gli esperimenti senza traduzione vengono segnalati.

## Uso
- **＋ Nuovo esperimento**: nome, data, progetto/molecola target.
- Sezioni: Obiettivo, Procedura, Risultati, Note. Salvataggio automatico dopo ogni modifica (⌘S per forzarlo).
- **📁 Gruppi e sottogruppi** (come le tracce di gruppo di Ableton): "📁＋ Gruppo" in alto a sinistra crea un gruppo. Ogni gruppo ha un colore, si apre/chiude con un clic e mostra il numero di esperimenti che contiene. Con il pulsante **⋯** del gruppo: nuovo esperimento dentro il gruppo, nuovo sottogruppo (anche a più livelli), rinomina, colore, archivia, elimina.
  - Per spostare: trascina un esperimento (o un intero gruppo) sopra un gruppo; trascinandolo sullo sfondo dell'elenco torna fuori dai gruppi. In alternativa usa il menu "📁 Gruppo" sotto il nome dell'esperimento.
  - **📦 Archivia**: il gruppo (con tutti i suoi sottogruppi ed esperimenti) scompare dall'elenco laterale. Non viene cancellato nulla: lo ritrovi con il pulsante "📦 Archivio" in basso a sinistra, dove ⋯ → Ripristina lo rimette nell'elenco. La ricerca cerca solo fra gli esperimenti visibili, oppure solo nell'archivio se la vista Archivio è aperta.
  - "Elimina il gruppo" toglie solo il contenitore: gli esperimenti non vengono cancellati e passano al gruppo superiore.
- **📎 Allegati**: "Aggiungi file" oppure trascina i file ChemDraw (.cdx, .cdxml, .cd) o altri file. "Apri" li apre con ChemDraw, "Finder" li mostra nella cartella.
- **Schemi ChemDraw nel Word**: Word non legge i file ChemDraw, quindi serve anche l'immagine dello schema, che compare nel documento Word (sezione "Schema di reazione e strutture", centrata e ridimensionata alla pagina). Due modi:
  1. In ChemDraw seleziona la struttura/lo schema, ⌘C (Ctrl+C su Windows), poi nel Diario premi **📋 Incolla da ChemDraw** (oppure ⌘V / Ctrl+V sulla pagina). Il Diario legge direttamente gli appunti del sistema: allega un PNG nitido (da PDF vettoriale a 288 dpi) e, se ChemDraw lo mette negli appunti, anche l'originale .cdx modificabile.
  2. Oppure in ChemDraw "Salva con nome" PNG (meglio ad alta risoluzione) e trascina il PNG nella pagina. Se ha lo stesso nome del file .cdx/.cdxml vengono abbinati.
  Se un file ChemDraw non ha un'immagine associata, il Diario te lo segnala con un avviso arancione. Sono accettati PNG e JPG.
- **📄 Esporta in Word**: crea un documento .docx dell'esperimento (titolo, data, progetto, sezioni compilate, elenco allegati), lo salva in `~/DiarioRicercatore/esportazioni/` e lo apre. Da Word puoi poi usare File → Esporta/Salva come per ottenere il PDF o un vecchio .doc. Il testo è giustificato, gli elenchi (`-`, `1)`) diventano elenchi, le immagini sono centrate, dimensionate al massimo 16×9 cm con didascalia «Figura n» e le pagine sono numerate.
  *Windows vs Mac:* su Windows ChemDraw può inserire in Word un oggetto OLE modificabile; su Mac non esiste. Il Diario usa quindi lo stesso metodo su entrambi: immagine nitida nel Word + file .cdx originale tra gli allegati (per modificare la struttura si riapre il .cdx con ChemDraw).
- **✨ AI** (agisce sulla sezione dove hai il cursore): Stila, Correggi, In inglese, Suggerisci titolo, Istruzione libera. La proposta compare in una finestra che puoi modificare prima di applicarla.

## 🧪 Disegnare le molecole
Nella card **Allegati**, il pulsante **🧪 Disegna molecola** apre un editor di strutture ([JSME](https://jsme-editor.github.io/), gratuito). Disegni la molecola o lo schema, dai un nome e premi «Aggiungi all'esperimento»: vengono allegati
- un'**immagine PNG** (compare nel documento Word e nell'anteprima) e
- un file **.mol** modificabile (si apre anche con ChemDraw), con lo SMILES mostrato sotto il disegno.

L'editor si carica da internet (jsme-editor.github.io). **Per usarlo anche offline:** scarica JSME dal suo sito, decomprimilo e metti la cartella `jsme` (quella che contiene `jsme.nocache.js`) accanto a `diario_web.py`: viene usata in automatico. La cartella `jsme/` è esclusa da git.

## ☁️ Google Drive (sincronizzazione e backup)
Serve l'app **Google Drive per desktop**: crea una cartella sincronizzata (Mac: di solito `~/Library/CloudStorage/GoogleDrive-…/Il mio Drive`; Windows: un'unità tipo `G:\Il mio Drive`). In «🔑 Chiavi API e impostazioni» → **Cartella di Google Drive** premi «🔎 Cerca Google Drive» (o scrivi il percorso) e salva.

Nella cartella scelta l'app crea **Diario del Ricercatore/** con:
- `Esperimenti/` — un documento **Word** per ogni esperimento (aggiornato quando lo modifichi);
- `Backup/` — copia del database e degli allegati.

Si aggiorna da solo ogni 5 minuti se hai fatto modifiche, a ogni «📄 Esporta in Word» e con il pulsante **☁️ Sincronizza con Drive**. Il database di lavoro resta sempre in `~/DiarioRicercatore/` (non in Drive: una cartella sincronizzata può rovinare un database aperto). È una copia a senso unico: le modifiche fatte su Drive non tornano nel Diario.

## 🧭 Settori e strumenti
Al primo avvio scegli il tuo settore (anche più di uno); il pulsante **🧭 Settore** lo cambia. Il primo settore scelto decide i titoli delle sezioni (per esempio «Materiali e metodi» per biologia e microbiologia), i titoli nel Word e lo stile dell'AI. Nella scheda **📈 Dati e grafici** di ogni esperimento compaiono gli strumenti del tuo settore; «Altri strumenti…» apre tutti gli altri. Ogni strumento si salva nell'esperimento e finisce nel Word (riassunto, tabella e, se vuoi, il grafico).

| Settore | Strumenti |
|---|---|
| **Chimica (sintesi)** | Reagenti e rese (mmol, equivalenti, concentrazione, resa dal reagente limitante), scheda di caratterizzazione (aspetto, p.f., Rf, NMR, MS, HPLC, IR, [α]D), **lastra TLC** (numero di macchie e Rf di ognuna, disegnata e allegabile al Word), disegno molecole e ChemDraw |
| **Farmacologia / biochimica** | Dose-risposta con IC50/EC50 e intervallo di confidenza al 95% (fit a 4 parametri), cinetica enzimatica (Km, Vmax), scheda del saggio, confronto tra gruppi |
| **Biologia molecolare e cellulare** | Piastra a 96 pozzetti (layout e valori, sottrazione del bianco, normalizzazione, test), qPCR (ΔCt, ΔΔCt, fold change), scheda campioni e reagenti (linea cellulare, anticorpi e lotti) |
| **Microbiologia** | Conte CFU (30-300 colonie, diluizioni), MIC, curva di crescita (tempo di raddoppio), scheda ceppo e condizioni |
| **Materiali / fisica / ingegneria** | Misure x-y con fit (retta, polinomio, esponenziale, legge di potenza), tabella libera con grafico, scheda materiale e condizioni di misura |
| **Informatica e dati** | Tabella parametri/metriche con grafico, confronto tra gruppi, scheda ambiente e riproducibilità (commit, versioni, seed, hardware) |

**Grafici di testo** (dose-risposta, x-y, barre, tabella libera): incolla i dati da Excel (tab o «;»), il grafico si aggiorna mentre scrivi. Asse x e y anche logaritmici. Barre con media ± DS e singoli punti, test t di Welch o ANOVA. I calcoli (fit, intervalli di confidenza, p) sono stati confrontati con SciPy.

## ⚗️ ChemDraw
Il pulsante **⚗️ ChemDraw** in alto apre l'app ChemDraw. La cerca da sola in Applicazioni (Mac) o in Programmi (Windows, `ChemDraw.exe`); se non la trova ti chiede il nome (es. `ChemDraw 23.1`) o il percorso e se lo ricorda. Puoi cambiarlo in "🔑 Chiavi API e impostazioni".

## Scegliere l'AI: Claude o Gemini
Nella barra ✨ sopra le sezioni c'è il menu **🟣 Claude / 🔵 Gemini**: tutte le funzioni (Stila, Correggi, In inglese, Titolo, Istruzione libera) usano il motore scelto, che l'app ricorda. La proposta è sempre da controllare prima di applicarla.

## Chiavi API (per le funzioni AI)
Clic su "🔑 Chiavi API e impostazioni" in basso a sinistra.
- **Claude**: chiave Anthropic da console.anthropic.com → API keys → Create Key. L'uso dell'API è a consumo, separato dall'abbonamento Claude.
- **Gemini**: chiave da aistudio.google.com/apikey. Il modello viene scelto in automatico fra quelli disponibili per la tua chiave (di preferenza un "flash" stabile); se vuoi puoi scriverlo a mano (es. `gemini-2.5-flash`).
- Le chiavi sono salvate solo sul tuo Mac in `~/DiarioRicercatore/config.json`; l'app non le mostra più dopo il salvataggio ("già salvata"), puoi sostituirle o rimuoverle.
- **Chiavi Gemini che iniziano con `AQ.`**: è il nuovo formato di AI Studio e Google segnala che alcune non sono ancora accettate dalle chiamate normali (errore 401 «ACCESS_TOKEN_TYPE_UNSUPPORTED»). Se succede, l'app te lo dice: crea allora una chiave classica (inizia con `AIza`) da Google Cloud Console → API e servizi → Credenziali → Crea credenziali → Chiave API, con l'API «Generative Language» abilitata.

## Dove sono i dati
`~/DiarioRicercatore/` — su Windows `C:\Users\IL_TUO_NOME\DiarioRicercatore\` (database `diario.db`, cartella `allegati/`, `config.json` con la chiave). Per il backup copia quella cartella.

## Sicurezza
Il server ascolta solo su 127.0.0.1 (il tuo Mac) e ogni richiesta richiede un codice casuale generato a ogni avvio.

## Nota sull'AI
L'AI è istruita a non inventare dati e a segnalare con [da completare: …] ciò che manca. Controlla sempre quantità, rese e nomi prima di applicare il testo.

## File del repository
- `diario_web.py` — l'applicazione (server locale + pagina nel browser), un solo file.
- `Avvia Diario.command` — avvio con doppio clic su Mac.
- `.github/workflows/build.yml` — crea le app pronte per Windows e Mac.
- `Avvia Diario.bat` — avvio con doppio clic su Windows.
- `legacy/diario_finestra_nativa.py` — vecchia versione con finestra nativa (richiede `customtkinter`); non più mantenuta.

## Prove automatiche
`python3 tests/test_sync.py` prova la sincronizzazione con una cartella Drive finta; `python3 tests/test_windows.py` prova le parti che cambiano tra Mac e Windows (simulate). Lavorano in cartelle temporanee e non toccano i tuoi dati.

## Licenza
MIT — vedi il file `LICENSE`.
