# HANDOFF V15 - MILESTONE 6

## Istruzione operativa
Riprendere lo sviluppo dalla Milestone 5 usando esclusivamente i file caricati con questo handoff. I file arriveranno in gruppi di massimo tre e saranno tutti collocati in una sola cartella, senza sottocartelle.

Non iniziare l'esecuzione finché l'utente non scrive `HO FINITO`.

Dopo l'ultimo caricamento:
1. verificare che siano presenti tutti i 36 file dell'inventario;
2. rimuovere esclusivamente i prefissi numerici dai nomi;
3. ricostruire internamente la struttura `v15/`, `config/`, `tests/` senza chiedere altri caricamenti;
4. eseguire la baseline M5 e verificare i test;
5. procedere autonomamente con la Milestone 6.

## Obiettivo M6
Recuperare le grandi regioni gialle aperte mancanti dalla storia vettoriale delle operazioni PDF di paint, sovrapposizione e clipping.

Vincoli:
- architettura vector-first, raster-guided;
- non usare dilatazione globale o closing morfologico;
- non vettorializzare indiscriminatamente il raster;
- non ripartire dalla V14;
- mantenere calibrazione M1, semantica del nero M3, recupero ibrido M4 e gate topologico M5;
- confrontare M5 e M6 quantitativamente;
- aggiungere test specifici;
- verificare due esecuzioni bit-a-bit;
- produrre `V15_MILESTONE_6`, rapporto numerico e README finale in formato piatto per il passaggio successivo.

## Inventario e ordine di caricamento
GRUPPO 01
- 01_HANDOFF_M6.md
- 02_README_CARICAMENTO.txt
- 03_UPLOAD_ORDER.txt

GRUPPO 02
- 04_sample.pdf
- 05_ultimo_ritaglio.json
- 06_config_v15.json

GRUPPO 03
- 07___init__.py
- 08_main.py
- 09_config.py

GRUPPO 04
- 10_models.py
- 11_crop_selector.py
- 12_pymupdf_scene.py

GRUPPO 05
- 13_path_geometry.py
- 14_paint_engine.py
- 15_isom_classifier.py

GRUPPO 06
- 16_raster_grid.py
- 17_raster_refiner.py
- 18_stroke_geometry.py

GRUPPO 07
- 19_pattern_homogenizer.py
- 20_topology_analyzer.py
- 21_tactile_composer.py

GRUPPO 08
- 22_dxf_exporter.py
- 23_raster_validator.py
- 24_vector_raster_metrics.py

GRUPPO 09
- 25_print_comparator.py
- 26_diagnostics.py
- 27_test_geometry.py

GRUPPO 10
- 28_test_pymupdf_scene.py
- 29_test_vector_raster_metrics.py
- 30_test_raster_calibration.py

GRUPPO 11
- 31_test_wall_support.py
- 32_test_black_semantics.py
- 33_test_hybrid_yellow.py

GRUPPO 12
- 34_test_topology_gate.py
- 35_MILESTONE_5_REPORT.json
- 36_README_M5.md

