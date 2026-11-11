# HANDOFF V15 - OCAD/PDF to Creo DXF

## Istruzione per la nuova chat

Riprendere lo sviluppo dalla baseline **V15 Vector-first / Raster-guided M1**, usando il pacchetto `V15_VECTOR_FIRST_RASTER_GUIDED_M1.zip` come ultimo stato coerente prima dell'esperimento M2. Non ripartire dalla V14 e non assumere che le percentuali globali riportate nelle ultime prove siano affidabili finché non è stata risolta la riproducibilità geometrica.

## Obiettivo reale

Convertire un PDF vettoriale di una carta da orientamento in layer DXF chiusi, validi e importabili in PTC Creo Parametric, mantenendo:

- fedeltà alla versione visibile/stampata;
- precisione dei path vettoriali del PDF;
- corretta sovrapposizione tra layer;
- aree ISOM 402/404 omogeneizzate per l'estrusione;
- eliminazione degli artefatti azzurri e marroni;
- geometrie watertight e non self-intersecting.

Layer di produzione:

1. `1_MURI_SPESSI`
2. `2_EDIFICI`
3. `3_PORTICI`
4. `4_AIUOLE_E_SIEPI`
5. `5_BOSCO_BIANCO`
6. `6_ACQUA_BLU`
7. `7_AREE_GIALLE`

`8_STRADE_BASE` deve delimitare giallo e bianco, ma non deve essere esportato.

## Principio architetturale da mantenere

La soluzione deve essere **vector-first, raster-guided**:

- i vettori PDF sono la sorgente primaria dei contorni, curve, stroke, larghezze e DXF;
- il raster determina classe visibile, visibilità dopo sovrapposizione e validazione;
- il raster non deve sostituire indiscriminatamente la geometria vettoriale;
- una nuova vettorializzazione raster è ammessa soltanto per pattern ISOM 402/404, clipping risultante da più oggetti o piccole correzioni locali;
- geometria visibile e geometria di estrusione devono rimanere distinte.

Formula operativa:

> Il vettore definisce la forma. Il raster decide significato e visibilità.

## Ordine visibile dei layer

Dal basso verso l'alto:

1. giallo;
2. bosco bianco;
3. strada/base beige;
4. verde;
5. portici;
6. edifici;
7. acqua;
8. muri neri.

Le geometrie di estrusione possono sovrapporsi. In particolare, verde e muri possono stare sopra giallo o bianco senza perforarli.

## File da caricare nella nuova chat

Priorità:

1. `V15_VECTOR_FIRST_RASTER_GUIDED_M1.zip`
2. questo handoff
3. `sample.pdf`
4. `orienteering-map-sample-Navile.pdf`
5. `3. Simbologia.pdf`

Facoltativo per confronto storico:

- `V15_FINAL_CANDIDATE_RC2.zip`
- `V15_VECTOR_FIRST_RASTER_GUIDED_M2.zip`

## Cronologia sintetica

### M9 Hybrid

Passaggio fondamentale a PyMuPDF come sorgente della geometria trasformata e del `seqno`. Pikepdf resta utile per diagnostica e content stream.

### M10

- bosco derivato dal bianco esplicito, senza fallback residuo indiscriminato;
- giallo rifinito via raster;
- forte miglioramento locale di giallo e bosco.

### M11-M12

- recupero edifici, verde, acqua, muri e portici;
- classificazione cromatica esclusiva;
- portici separati dagli edifici;
- stroke neri convertiti in superfici.

### M13

- 3 gruppi di punti bianchi nel giallo colmati;
- 3 regioni di punti gialli su bianco omogeneizzate;
- pattern ISOM 402/404 assimilati al giallo tattile;
- 7 componenti marroni allungate rilevate ed escluse;
- filtro per artefatto azzurro lineare;
- 14 test superati.

### RC2

- composizione visibile esplicita dei layer sovrapposti;
- confronto originale/ricostruzione/errori;
- corrispondenza riportata circa 84%, giudicata insufficiente.

### Vector-first / Raster-guided M1

Aggiunti:

- maschere visibili esclusive;
- accuracy globale;
- precisione, recall, F1 e IoU per classe;
- matrice di confusione;
- ASD e HD95 dei bordi;
- limiti espliciti per pixel esclusi, incerti e antialiasing.

È la baseline consigliata per riprendere il lavoro.

## Errore critico emerso alla fine

L'ultimo tentativo M2 ha mostrato che la metrica globale non era riproducibile:

- in una prima esecuzione era stata riportata accuratezza visibile circa 84,85%;
- rieseguendo il pacchetto M1 da zero, il valore risultava circa 50,06%;
- il problema coinvolgeva più classi, non soltanto i muri;
- quindi la causa probabile è un disallineamento sistematico tra geometrie e griglia raster.

Non usare né 84,85% né 50,06% come baseline definitiva prima di risolvere questo problema.

Possibili cause:

1. trasformazione fra coordinate PDF e pixel;
2. origine e dimensioni del ritaglio;
3. CropBox vs MediaBox;
4. coordinate locali PyMuPDF vs coordinate native PDF;
5. differenza tra rendering completo e rendering con `clip`;
6. uso incoerente del bounding box nella rasterizzazione delle geometrie;
7. risoluzioni diverse fra classificatore, vettorializzatore e validatore.

## Unico primo task della nuova chat

Implementare una **calibrazione geometrica deterministica vettore-pixel** prima di modificare qualsiasi classificatore.

### Procedura richiesta

1. Aprire `sample.pdf` con PyMuPDF.
2. Registrare:
   - `page.rect`;
   - `page.cropbox`;
   - `page.mediabox`;
   - rotazione;
   - dimensioni del pixmap a 300, 600 e 1200 dpi.
3. Scegliere almeno 10 punti di controllo vettoriali facilmente riconoscibili:
   - vertici netti di edifici;
   - angoli di rettangoli;
   - estremità di stroke;
   - punti sulle strade.
4. Convertire ogni punto PDF in pixel con un'unica funzione ufficiale:

   `px = (x - crop_x0) * dpi / 72`

   `py = (y - crop_y0) * dpi / 72`

   oppure la sua variante con inversione Y, verificata empiricamente. Non assumere l'orientamento.
5. Verificare visivamente e numericamente che ogni punto ricada sullo stesso bordo a 300, 600 e 1200 dpi.
6. Salvare `CONTROL_POINTS.csv` con:
   - coordinate PDF;
   - pixel atteso;
   - pixel osservato;
   - errore X/Y;
   - errore euclideo;
   - dpi.
7. Accettare la trasformazione solo se:
   - errore medio ≤ 0,5 pixel;
   - P95 ≤ 1 pixel;
   - nessun errore sistematico di traslazione o inversione.
8. Aggiungere test automatici di regressione.
9. Solo dopo, rieseguire M1 due volte in cartelle pulite e verificare che hash e metriche siano identici.

## Criterio di riproducibilità obbligatorio

Prima di ottimizzare i layer:

- due esecuzioni pulite devono produrre metriche identiche almeno a 1e-9;
- le maschere PNG devono avere lo stesso SHA-256;
- i DXF devono avere lo stesso SHA-256, salvo timestamp eliminati;
- CropBox, DPI e dimensioni raster devono essere registrati nel manifest;
- nessun parametro può dipendere da file rimasti da una precedente esecuzione.

## Miglioramento M2 che può essere recuperato dopo la calibrazione

La riduzione della soglia dei muri da 0,45 pt a 0,25 pt aveva mostrato, nella metrica locale dell'esecuzione M2:

- recall muri circa 96,36%;
- precisione circa 91,81%;
- F1 circa 94,03%;
- IoU circa 88,73%.

Questo intervento è promettente ma deve essere rivalutato dopo la calibrazione geometrica. Non accettarlo automaticamente.

## Maschere e metriche definitive

Maschere visibili esclusive:

- `Y_VIS`: giallo;
- `W_VIS`: bianco;
- `R_VIS`: beige/strade;
- `G_VIS`: verde;
- `B_VIS`: edifici;
- `P_VIS`: portici;
- `A_VIS`: acqua;
- `K_VIS`: muri;
- `X_VIS`: esclusi;
- `U_VIS`: incerti.

Maschere/geometrie di estrusione, non necessariamente esclusive:

- `Y_EXT`;
- `W_EXT`;
- `G_EXT`;
- `B_EXT`;
- `P_EXT`;
- `A_EXT`;
- `K_EXT`.

Dominio della metrica primaria:

`Omega_eval = Omega - (X + AA + U)`

Limiti:

- esclusi `X` ≤ 6%;
- antialias `AA` ≤ 5%;
- incerti `U` ≤ 1%;
- totale escluso ≤ 12%.

Target finali, dopo che la metrica è riproducibile:

- accuracy visibile ≥ 99%;
- Macro F1 ≥ 98%;
- balanced accuracy ≥ 98%;
- precisione e recall di ogni classe principale ≥ 95%;
- pattern coverage ≥ 99,5%;
- pattern leakage ≤ 1%;
- puntini residui = 0;
- attraversamenti strade/edifici/portici = 0;
- geometrie invalide = 0;
- loop DXF chiusi = 100%;
- HD95 dei contorni principali ≤ 0,05 mm sul modello.

## Regole da non violare

- Non tornare alla V14.
- Non sostituire globalmente i vettori con contorni raster.
- Non utilizzare l'IoU del pattern puntinato contro il raster originale come unica metrica dopo l'omogeneizzazione.
- Non sottrarre verde e muri dal giallo o dal bianco quando sono layer sovrapposti.
- Non esportare `8_STRADE_BASE`.
- Non includere marrone, percorso magenta, testo o artefatti azzurri nei layer tattili.
- Non aumentare artificialmente la metrica escludendo più pixel.
- Non modificare soglie cromatiche finché la trasformazione vettore-pixel non è validata.
- Non dichiarare il 99% senza risultati riproducibili da due esecuzioni pulite.

## Output richiesti nella prossima milestone

- `CONTROL_POINTS.csv`
- `coordinate_transform.json`
- `REPRODUCIBILITY_REPORT.json`
- `VISIBLE_MASKS/*.png`
- `EXTRUSION_MASKS/*.png`
- `global_metrics.json`
- `per_class_metrics.csv`
- `confusion_matrix.csv`
- `border_metrics.csv`
- `confusion_map.png`
- pacchetto `V15_VECTOR_RASTER_CALIBRATED.zip`

## Prompt suggerito per la nuova chat

> Riprendi la V15 usando `V15_VECTOR_FIRST_RASTER_GUIDED_M1.zip` e questo handoff. Prima di qualsiasi ottimizzazione, correggi e valida in modo deterministico la trasformazione tra coordinate vettoriali PDF e pixel raster usando almeno 10 punti di controllo a 300, 600 e 1200 dpi. Produci `CONTROL_POINTS.csv`, test di regressione e un report di riproducibilità basato su due esecuzioni pulite. Non modificare soglie cromatiche o geometrie finché la calibrazione non passa.
