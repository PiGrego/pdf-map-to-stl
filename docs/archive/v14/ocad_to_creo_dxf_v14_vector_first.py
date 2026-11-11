import os
import sys
import json
from collections import defaultdict
import pymupdf
import numpy as np
import cv2
from shapely.geometry import Polygon, LineString, MultiPolygon, GeometryCollection, box
from shapely.ops import unary_union
from shapely import set_precision, make_valid

# ================= CONFIGURAZIONE PDF -> CREO PARAMETRIC =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_PDF = "sample.pdf"
OUTPUT_DIR = os.path.join(BASE_DIR, "dxf_da_PDF_CREO")

# Larghezza massima (bounding box X) in millimetri del poligono dentro Creo
LARGHEZZA_CREO_MM = 120.0
VERSIONE = "V14 vector-first"
ERRORE_BEZIER_PT = 0.002
TOL_EXPORT_MM = 0.001
TOL_JOIN_PATH_PT = 0.001

# Coefficienti feature-adaptive (calibrati per layer, non sulla pagina).
K_AREA_DEFAULT = 0.040
K_WIDTH_DEFAULT = 0.060
K_HOLE_DEFAULT = 0.070
K_GRID_DEFAULT = 0.003
K_AREA_MURI = 0.012
K_WIDTH_MURI = 0.025
K_AREA_GIALLO = 0.015
K_HOLE_GIALLO = 0.030
FATTORE_RETINO_GIALLO = 2.10

# Pulizia geometrica relativa alla larghezza finale del modello.
# Le soglie scalano automaticamente con mappe e formati differenti.
AREA_MIN_FEATURE_REL = 1.0e-5       # frazione di W^2
AREA_MIN_MURI_REL = 2.8e-6          # frazione di W^2
LARGHEZZA_MIN_FEATURE_REL = 0.0025  # frazione di W
LARGHEZZA_MIN_MURI_REL = 0.0015     # frazione di W
AREA_MIN_FORO_REL = 1.4e-5          # frazione di W^2
GRIGLIA_FINALE_REL = 8.0e-5         # frazione di W

# Il giallo contiene superfici vere e micro-retini. Soglia relativa locale:
# una componente deve essere significativa rispetto all'area selezionata.
AREA_MIN_GIALLO_FRAZIONE_CLIP = 2.0e-6

# Soglia matematica (in punti PDF) tra linea nera SOTTILE (bordo) e SPESSA (muro)
SOGLIA_MURO_SPESSO_PT = 0.45

# Spessore lama (in punti PDF) per dividere i blocchi con le linee nere sottili
SPESSORE_TAGLIO_BORDI_PT = 0.10
LUNGHEZZA_MIN_BORDO_TAGLIO_PT = 0.80  # Ignora i puntini neri corti per non creare dentellature

# Soglia area (in pt^2 PDF) per riconoscere i pallini gialli del pattern "alberi bassi"
SOGLIA_AREA_PALLINO_GIALLO_PT2 = 4.2
RAGGIO_FUSIONE_PALLINI_GIALLI_PT = 1.45
# =========================================================================


def risolvi_percorso(nome_file):
    candidati = [
        nome_file,
        os.path.join(BASE_DIR, nome_file),
        os.path.join(os.path.dirname(BASE_DIR), nome_file),
    ]
    for p in candidati:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"File '{nome_file}' non trovato in '{BASE_DIR}'.")


def to_rgb255(col):
    if col is None:
        return None
    if isinstance(col, (int, float)):
        v = float(col) * 255.0
        return (v, v, v)
    if len(col) == 1:
        v = float(col[0]) * 255.0
        return (v, v, v)
    if len(col) == 3:
        return (float(col[0]) * 255.0, float(col[1]) * 255.0, float(col[2]) * 255.0)
    if len(col) == 4:
        c, m, y, k = [float(x) for x in col]
        r = 255.0 * (1.0 - c) * (1.0 - k)
        g = 255.0 * (1.0 - m) * (1.0 - k)
        b = 255.0 * (1.0 - y) * (1.0 - k)
        return (r, g, b)
    return None


def seleziona_poligono_pdf(page):
    rect = page.rect
    # Il ritaglio interattivo e' il comportamento predefinito e avviene PRIMA
    # dell'analisi. Per test automatici usare esplicitamente --full-page.
    if "--full-page" in sys.argv:
        print("Ritaglio: intera pagina richiesto con --full-page")
        return box(rect.x0, rect.y0, rect.x1, rect.y1), rect
    # Non controllare DISPLAY: su Windows la variabile normalmente non esiste,
    # anche quando OpenCV puo' aprire correttamente una finestra grafica.
    zoom = 2.5
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 3:
        img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    else:
        img_bgr = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)

    h_vis = 920
    scala_vis = h_vis / float(img_bgr.shape[0])
    w_vis = int(img_bgr.shape[1] * scala_vis)
    img_base = cv2.resize(img_bgr, (w_vis, h_vis))

    punti_px = []
    mouse_curr = [0, 0]
    titolo = "Poligono: [Click SX] Punto | [Click DX] Annulla | [INVIO/SPAZIO] Conferma"

    def on_mouse(event, x, y, flags, param):
        mouse_curr[0], mouse_curr[1] = x, y
        if event == cv2.EVENT_LBUTTONDOWN:
            punti_px.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and punti_px:
            punti_px.pop()

    try:
        cv2.namedWindow(titolo, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(titolo, min(w_vis, 1500), min(h_vis, 920))
        cv2.setMouseCallback(titolo, on_mouse)
    except cv2.error as exc:
        raise RuntimeError(
            "OpenCV non riesce ad aprire la finestra di ritaglio. "
            "Installa 'opencv-python' e non 'opencv-python-headless', oppure usa --full-page. "
            f"Dettaglio OpenCV: {exc}"
        ) from exc

    print("\n================= SELEZIONE POLIGONALE =================")
    print(" - CLICK SINISTRO : Aggiungi un vertice del poligono")
    print(" - CLICK DESTRO   : Rimuovi l'ultimo vertice inserito")
    print(" - INVIO o SPAZIO : Chiudi il poligono ed esporta i DXF")
    print("========================================================\n")

    while True:
        canvas = img_base.copy()
        if len(punti_px) >= 3:
            overlay = canvas.copy()
            pts_arr = np.array(punti_px, dtype=np.int32)
            cv2.fillPoly(overlay, [pts_arr], color=(0, 220, 100))
            cv2.addWeighted(overlay, 0.25, canvas, 0.75, 0, canvas)

        if len(punti_px) >= 2:
            pts_arr = np.array(punti_px, dtype=np.int32)
            cv2.polylines(canvas, [pts_arr], isClosed=False, color=(0, 0, 220), thickness=2, lineType=cv2.LINE_AA)

        if punti_px:
            cv2.line(canvas, punti_px[-1], tuple(mouse_curr), (255, 100, 0), 1, cv2.LINE_AA)
            cv2.line(canvas, tuple(mouse_curr), punti_px[0], (200, 180, 0), 1, cv2.LINE_AA)

        for idx, pt in enumerate(punti_px):
            cv2.circle(canvas, pt, 5, (0, 0, 255), -1, cv2.LINE_AA)
            cv2.putText(canvas, str(idx + 1), (pt[0] + 6, pt[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 180), 1, cv2.LINE_AA)

        try:
            cv2.imshow(titolo, canvas)
            if cv2.getWindowProperty(titolo, cv2.WND_PROP_VISIBLE) < 1:
                punti_px.clear()
                break
            key = cv2.waitKey(20) & 0xFF
        except cv2.error as exc:
            cv2.destroyAllWindows()
            raise RuntimeError(f"Errore durante il ritaglio OpenCV: {exc}") from exc
        if key in (10, 13, 32):
            if len(punti_px) >= 3:
                break
            print("Aggiungi almeno 3 punti!")
        elif key == 27:
            punti_px.clear()
            break

    cv2.destroyAllWindows()

    if len(punti_px) < 3:
        poly_full = box(rect.x0, rect.y0, rect.x1, rect.y1)
        return poly_full, rect

    fattore = 1.0 / (zoom * scala_vis)
    pts_pdf = [(rect.x0 + x * fattore, rect.y0 + y * fattore) for x, y in punti_px]
    poly_clip = Polygon(pts_pdf)
    if not poly_clip.is_valid:
        poly_clip = poly_clip.buffer(0)

    minx, miny, maxx, maxy = poly_clip.bounds
    return poly_clip, pymupdf.Rect(minx, miny, maxx, maxy)


def colore_vicino(rgb, target, tolleranza=8.0):
    if rgb is None:
        return False
    return all(abs(float(v) - float(t)) <= tolleranza for v, t in zip(rgb, target))


def is_linea_riferimento(rgb):
    """Scarta i riferimenti OCAD non cartografici presenti nel sample."""
    if rgb is None:
        return False
    if colore_vicino(rgb, (63.0, 176.0, 228.0), 10.0):  # azzurro verticale
        return True
    if colore_vicino(rgb, (207.0, 117.0, 24.0), 12.0):  # marrone-arancio
        return True
    r, g, b = rgb
    return r > 145 and b > 115 and g < 80  # viola-magenta


def is_colore_blu_acqua(rgb):
    if rgb is None:
        return False
    r, g, b = rgb
    # Acqua OCAD del sample: RGB circa (0, 157, 221).
    return r < 35 and 125 <= g <= 190 and b > 190 and (b - g) > 35


def is_colore_verde_vegetazione(rgb):
    if rgb is None:
        return False
    r, g, b = rgb
    # Include verde scuro (siepi), verde brillante (alberi/croci verdi) e verde oliva (aiuole)
    verde_puro = (g > (r + 18) and g > (b + 15) and g > 60)
    verde_oliva = (g > 115 and r > 95 and b < 105 and abs(r - g) < 55)
    return verde_puro or verde_oliva


def classifica_colore_riempimento(col):
    rgb = to_rgb255(col)
    if rgb is None:
        return None
    r, g, b = rgb

    # Scarta viola/magenta del percorso gara
    if r > 140 and b > 120 and g < 90:
        return None

    # 1. Nero pieno -> Muri spessi
    if r < 40 and g < 40 and b < 40:
        return ("1_MURI_SPESSI", 90)

    # 2. Blu / Ciano -> Acqua e Tondo Blu
    if is_colore_blu_acqua(rgb):
        return ("6_ACQUA_BLU", 85)

    # 3. Grigio scuro -> Edifici
    if abs(r - g) < 20 and abs(g - b) < 20 and 40 <= r <= 165:
        return ("2_EDIFICI", 75)

    # 4. Grigio chiaro -> Portici
    if abs(r - g) < 20 and abs(g - b) < 20 and 166 <= r <= 232:
        return ("3_PORTICI", 65)

    # 5. Qualsiasi Verde (Siepi, Aiuole, Alberi) -> Unico layer 4_AIUOLE_E_SIEPI
    if is_colore_verde_vegetazione(rgb):
        return ("4_AIUOLE_E_SIEPI", 55)

    # 6. Bianco puro -> Candidato per aree bianche (alberi bassi / cortili)
    if r > 242 and g > 242 and b > 242:
        return ("BIANCO", 25)

    # 7. Giallo / Arancio -> Aree aperte o pallini gialli
    if r > 210 and 135 <= g <= 230 and b < 150:
        return ("7_AREE_GIALLE", 20)

    # Beige/rosa stampato: maschera delle strade e superfici di fondo.
    # Serve come cutter geometrico del giallo, ma non viene esportato come layer.
    if r >= 232 and 195 <= g <= 235 and 170 <= b <= 215 and r > g > b:
        return ("8_STRADE_BASE", 10)

    # Altri beige / rosa: piastra base, ignorati.
    # Viene deliberatamente ignorato: la base è finestra_clip.
    return None


def _dist_punto_retta(p, a, b):
    p = np.asarray(p, dtype=float); a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    ab = b - a
    den = float(np.dot(ab, ab))
    if den <= 1e-24:
        return float(np.linalg.norm(p - a))
    t = float(np.clip(np.dot(p - a, ab) / den, 0.0, 1.0))
    return float(np.linalg.norm(p - (a + t * ab)))


def campionamento_bezier(p0, p1, p2, p3, errore=ERRORE_BEZIER_PT, max_depth=12):
    """Flattening adattivo della cubica con errore cordale massimo in punti PDF."""
    a=np.array([p0.x,p0.y],float); b=np.array([p1.x,p1.y],float)
    c=np.array([p2.x,p2.y],float); d=np.array([p3.x,p3.y],float)
    out=[tuple(a)]
    def rec(q0,q1,q2,q3,depth):
        flat=max(_dist_punto_retta(q1,q0,q3), _dist_punto_retta(q2,q0,q3))
        if flat <= errore or depth >= max_depth:
            out.append(tuple(q3)); return
        q01=(q0+q1)/2; q12=(q1+q2)/2; q23=(q2+q3)/2
        q012=(q01+q12)/2; q123=(q12+q23)/2; q0123=(q012+q123)/2
        rec(q0,q01,q012,q0123,depth+1)
        rec(q0123,q123,q23,q3,depth+1)
    rec(a,b,c,d,0)
    return out


def items_to_shapely_paths(items):
    subpaths = []
    corrente = []

    for it in items:
        tipo = it[0]
        if tipo == "l":
            p1, p2 = it[1], it[2]
            pt1, pt2 = (p1.x, p1.y), (p2.x, p2.y)
            if not corrente:
                corrente = [pt1, pt2]
            elif np.hypot(pt1[0] - corrente[-1][0], pt1[1] - corrente[-1][1]) > TOL_JOIN_PATH_PT:
                subpaths.append(corrente)
                corrente = [pt1, pt2]
            else:
                corrente.append(pt2)
        elif tipo == "c":
            p1, p2, p3, p4 = it[1], it[2], it[3], it[4]
            pts_c = campionamento_bezier(p1, p2, p3, p4)
            if not corrente:
                corrente = pts_c
            elif np.hypot(pts_c[0][0] - corrente[-1][0], pts_c[0][1] - corrente[-1][1]) > TOL_JOIN_PATH_PT:
                subpaths.append(corrente)
                corrente = pts_c
            else:
                corrente.extend(pts_c[1:])
        elif tipo == "re":
            r = it[1]
            subpaths.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)])
        elif tipo == "qu":
            q = it[1]
            subpaths.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y), (q.ul.x, q.ul.y)])

    if corrente:
        subpaths.append(corrente)
    return subpaths


def subpaths_to_polygons_list(subpaths):
    """Restituisce i singoli anelli poligonali e il poligono combinato (con eventuali fori)."""
    anelli = []
    for sp in subpaths:
        if len(sp) >= 3:
            if sp[0] != sp[-1]:
                sp = sp + [sp[0]]
            if len(sp) >= 4:
                poly = Polygon(sp)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if not poly.is_empty and poly.area > 0.0005:
                    anelli.append(poly)
    if not anelli:
        return [], None
    combinato = anelli[0]
    for p in anelli[1:]:
        combinato = combinato.symmetric_difference(p)
    if not combinato.is_valid:
        combinato = combinato.buffer(0)
    return anelli, (combinato if not combinato.is_empty else None)


def rimuovi_fori_interni_piccoli(geom, area_min_foro_pt2=4.0):
    if geom is None or geom.is_empty:
        return geom
    if isinstance(geom, Polygon):
        interiors = [ring for ring in geom.interiors if Polygon(ring).area >= area_min_foro_pt2]
        return Polygon(geom.exterior, interiors)
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        parti = [rimuovi_fori_interni_piccoli(g, area_min_foro_pt2) for g in geom.geoms if isinstance(g, Polygon)]
        return unary_union(parti) if parti else Polygon()
    return geom


def pulisci_topologia(geom, griglia_pt=0.005, area_min_pt2=0.002):
    """Dissolve duplicati, chiude microfessure e rimuove frammenti non estrudibili."""
    if geom is None or geom.is_empty:
        return Polygon()
    geom = make_valid(geom)
    geom = set_precision(geom, grid_size=griglia_pt, mode="valid_output")
    geom = unary_union(geom).buffer(0)

    parti = []
    if isinstance(geom, Polygon):
        candidati = [geom]
    elif isinstance(geom, (MultiPolygon, GeometryCollection)):
        candidati = [g for g in geom.geoms if isinstance(g, Polygon)]
    else:
        candidati = []

    for g in candidati:
        if g.area >= area_min_pt2:
            parti.append(g)
    return unary_union(parti).buffer(0) if parti else Polygon()


def deduplica_segmenti(segmenti, decimali=4):
    """Elimina segmenti coincidenti, compresi quelli con verso opposto."""
    unici = {}
    for p1, p2 in segmenti:
        a = (round(p1[0], decimali), round(p1[1], decimali))
        b = (round(p2[0], decimali), round(p2[1], decimali))
        if a == b:
            continue
        chiave = tuple(sorted((a, b)))
        unici[chiave] = (a, b)
    return list(unici.values())


def componenti_poligonali(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def scala_feature_adattiva(geom, nome_layer):
    comps = componenti_poligonali(make_valid(geom))
    aree = np.array([p.area for p in comps if p.area > 0], dtype=float)
    if aree.size == 0:
        return {"area_tipica": 0.002, "diametro_tipico": 0.05}
    # Esclude solo gli outlier grandi; preserva simboli minuti realmente ricorrenti.
    q10, q75 = np.quantile(aree, [0.10, 0.75]) if aree.size >= 4 else (aree.min(), aree.max())
    campione = aree[(aree >= max(q10, 1e-8)) & (aree <= q75)]
    if campione.size == 0:
        campione = aree
    area_tipica = float(np.median(campione))
    diametro = 2.0 * np.sqrt(area_tipica / np.pi)
    return {"area_tipica": area_tipica, "diametro_tipico": diametro}


def riconnetti_frammenti_vicini(geom, nome_layer):
    """Riaggancia striscioline quasi tangenti senza gonfiare i contorni principali."""
    comps = componenti_poligonali(make_valid(geom))
    if len(comps) < 2 or nome_layer in ("7_AREE_GIALLE", "5_BOSCO_BIANCO"):
        return geom
    aree = np.array([g.area for g in comps if g.area > 0], dtype=float)
    if aree.size == 0:
        return geom
    diam = 2.0 * np.sqrt(float(np.median(aree)) / np.pi)
    # Per il verde consente una saldatura leggermente maggiore delle sottili strisce.
    fattore = 0.10 if nome_layer == "4_AIUOLE_E_SIEPI" else 0.045
    gap = min(0.55, max(0.015, fattore * diam))
    chiuso = unary_union(geom.buffer(gap, join_style=2)).buffer(-gap, join_style=2)
    # Accetta soltanto una crescita minima: il bridge non puo' alterare le aree.
    if not chiuso.is_empty and chiuso.area <= geom.area + max(0.35, 0.012 * geom.area):
        return make_valid(chiuso).buffer(0)
    return geom

def ripara_solo_se_invalida(geom):
    """Preserva esattamente le geometrie valide; ripara solo quelle realmente invalide."""
    if geom is None or geom.is_empty or geom.is_valid:
        return geom
    return make_valid(geom)

def filtra_watertight(geom, scala_mm, nome_layer, w_mm=None, area_clip_pt2=None):
    """Pulizia feature-adaptive; nessun opening morfologico sul giallo."""
    if geom is None or geom.is_empty:
        return Polygon(), {"rimossi": 0, "fori_chiusi": 0, "area_tipica_pt2": 0.0}
    adatt = scala_feature_adattiva(geom, nome_layer)
    area_tipica = adatt["area_tipica"]
    diametro = adatt["diametro_tipico"]
    k_area = K_AREA_MURI if nome_layer == "1_MURI_SPESSI" else (K_AREA_GIALLO if nome_layer == "7_AREE_GIALLE" else K_AREA_DEFAULT)
    k_width = K_WIDTH_MURI if nome_layer == "1_MURI_SPESSI" else K_WIDTH_DEFAULT
    k_hole = K_HOLE_GIALLO if nome_layer == "7_AREE_GIALLE" else K_HOLE_DEFAULT
    area_min = max(1e-6, k_area * area_tipica)
    area_hole = max(1e-6, k_hole * area_tipica)
    r_pt = max(0.0005, 0.5 * k_width * diametro)
    grid_pt = min(0.002, max(0.00005, 0.00025 * diametro))
    g = ripara_solo_se_invalida(geom)
    g = unary_union(g)
    if not g.is_valid:
        g = make_valid(g)
    g = riconnetti_frammenti_vicini(g, nome_layer)
    kept, removed, holes_closed = [], 0, 0
    for poly in componenti_poligonali(g):
        if poly.area < area_min:
            removed += 1
            continue
        # Il giallo conserva il contorno originale; sugli altri layer elimina solo baffi
        # molto inferiori alla feature tipica del layer.
        # V14 vector-first: nessun opening morfologico sui contorni PDF validi.
        for part in componenti_poligonali(poly):
            holes = []
            for ring in part.interiors:
                hp = Polygon(ring)
                if hp.area >= area_hole:
                    holes.append(list(ring.coords))
                else:
                    holes_closed += 1
            clean = Polygon(list(part.exterior.coords), holes)
            clean = ripara_solo_se_invalida(clean)
            kept.extend(x for x in componenti_poligonali(clean) if x.area >= area_min)
    out = unary_union(kept) if kept else Polygon()
    if not out.is_valid:
        out = make_valid(out)
    return out, {"rimossi": removed, "fori_chiusi": holes_closed, "area_tipica_pt2": area_tipica,
                 "area_min_pt2": area_min, "grid_pt": grid_pt}

def verifica_profili(geom, scala_mm):
    """Conta problemi che renderebbero un profilo non chiuso/non manifold."""
    report = {"poligoni": 0, "invalidi": 0, "anelli_aperti": 0,
              "anelli_non_semplici": 0, "area_mm2": 0.0}
    if geom is None or geom.is_empty:
        return report
    polys = [geom] if isinstance(geom, Polygon) else [x for x in getattr(geom, "geoms", []) if isinstance(x, Polygon)]
    for poly in polys:
        report["poligoni"] += 1
        report["area_mm2"] += poly.area * scala_mm * scala_mm
        if not poly.is_valid:
            report["invalidi"] += 1
        rings = [poly.exterior] + list(poly.interiors)
        for ring in rings:
            coords = list(ring.coords)
            if not coords or coords[0] != coords[-1] or not ring.is_ring:
                report["anelli_aperti"] += 1
            if not ring.is_simple:
                report["anelli_non_semplici"] += 1
    return report


def raccogli_segmenti_da_geom(geom, scala_mm, x0_pt, y1_pt):
    """Converte i contorni in catene di segmenti CHIUSE al 100% per lo Sketcher di Creo."""
    segs = []
    if geom is None or geom.is_empty:
        return segs

    if isinstance(geom, Polygon):
        anelli = [geom.exterior] + list(geom.interiors)
        for anello in anelli:
            coords = list(anello.coords)
            if len(coords) < 4:
                continue
            pts_mm = [((c[0] - x0_pt) * scala_mm, (y1_pt - c[1]) * scala_mm) for c in coords]
            # Filtriamo i vertici troppo vicini ma mantenendo SEMPRE chiuso l'anello
            filtrati = [pts_mm[0]]
            for pt in pts_mm[1:-1]:
                if np.hypot(pt[0] - filtrati[-1][0], pt[1] - filtrati[-1][1]) >= TOL_EXPORT_MM:
                    filtrati.append(pt)
            if len(filtrati) >= 3:
                filtrati.append(filtrati[0])
                for i in range(len(filtrati) - 1):
                    segs.append((filtrati[i], filtrati[i + 1]))
    elif isinstance(geom, (MultiPolygon, GeometryCollection)):
        for g in geom.geoms:
            segs.extend(raccogli_segmenti_da_geom(g, scala_mm, x0_pt, y1_pt))
    return segs


def scrivi_dxf_creo(filepath, segmenti_base, segmenti_per_layer, w_mm, h_mm):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n")
        f.write("9\n$EXTMIN\n10\n0.0\n20\n0.0\n30\n0.0\n")
        f.write(f"9\n$EXTMAX\n10\n{w_mm:.4f}\n20\n{h_mm:.4f}\n30\n0.0\n0\nENDSEC\n")
        f.write("0\nSECTION\n2\nENTITIES\n")

        f.write("0\nPOINT\n8\n0_REF_ORIGINE\n10\n0.0\n20\n0.0\n30\n0.0\n")
        f.write(f"0\nPOINT\n8\n0_REF_ORIGINE\n10\n{w_mm:.4f}\n20\n{h_mm:.4f}\n30\n0.0\n")

        for (x1, y1), (x2, y2) in segmenti_base:
            f.write(f"0\nLINE\n8\n0_PIASTRA_BASE\n10\n{x1:.4f}\n20\n{y1:.4f}\n30\n0.0\n11\n{x2:.4f}\n21\n{y2:.4f}\n31\n0.0\n")

        for nome_layer, segs in segmenti_per_layer.items():
            for (x1, y1), (x2, y2) in segs:
                f.write(f"0\nLINE\n8\n{nome_layer}\n10\n{x1:.4f}\n20\n{y1:.4f}\n30\n0.0\n11\n{x2:.4f}\n21\n{y2:.4f}\n31\n0.0\n")

        f.write("0\nENDSEC\n0\nEOF\n")


def disegna_geom_riempita(canvas, geom, colore_bgr, crop_rect, sx, sy):
    """Rasterizza Polygon/MultiPolygon, preservando i fori interni."""
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, Polygon):
        geoms = [geom]
    elif isinstance(geom, (MultiPolygon, GeometryCollection)):
        geoms = [g for g in geom.geoms if isinstance(g, Polygon)]
    else:
        return

    def punti_px(coords):
        return np.array([
            [int(round((x - crop_rect.x0) * sx)), int(round((y - crop_rect.y0) * sy))]
            for x, y in coords
        ], dtype=np.int32)

    for poly in geoms:
        ext = punti_px(poly.exterior.coords)
        if len(ext) >= 3:
            cv2.fillPoly(canvas, [ext], colore_bgr, lineType=cv2.LINE_AA)
        for hole in poly.interiors:
            pts = punti_px(hole.coords)
            if len(pts) >= 3:
                cv2.fillPoly(canvas, [pts], (255, 255, 255), lineType=cv2.LINE_AA)


def crea_confronto_riempito(page, crop_rect, finestra_clip, geometrie_finali,
                             strade_geom, output_dir, larghezza=1600):
    """Salva originale, ricostruzione riempita, overlay e confronto affiancato."""
    zoom = larghezza / float(crop_rect.width)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=crop_rect, alpha=False)
    originale = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    originale = cv2.cvtColor(originale[:, :, :3], cv2.COLOR_RGB2BGR)
    h, w = originale.shape[:2]
    sx = w / float(crop_rect.width)
    sy = h / float(crop_rect.height)

    # Colori BGR vicini ai colori effettivi della carta OCAD.
    colori_fill = {
        "7_AREE_GIALLE": (54, 186, 255),
        "5_BOSCO_BIANCO": (245, 245, 245),
        "4_AIUOLE_E_SIEPI": (5, 186, 167),
        "3_PORTICI": (210, 210, 210),
        "2_EDIFICI": (115, 115, 115),
        "6_ACQUA_BLU": (221, 157, 0),
        "1_MURI_SPESSI": (0, 0, 0),
    }

    ricostruita = np.full((h, w, 3), 255, dtype=np.uint8)
    ordine = [
        "7_AREE_GIALLE", "5_BOSCO_BIANCO", "4_AIUOLE_E_SIEPI",
        "3_PORTICI", "2_EDIFICI", "6_ACQUA_BLU", "1_MURI_SPESSI"
    ]
    diagnostiche = dict(geometrie_finali)
    if strade_geom is not None and not strade_geom.is_empty:
        diagnostiche["8_STRADE_BASE"] = strade_geom

    # Fondo limitato al poligono scelto.
    maschera = np.zeros((h, w), dtype=np.uint8)
    disegna_geom_riempita(ricostruita, finestra_clip, (255,255,255), crop_rect, sx, sy)
    for nome in ordine:
        disegna_geom_riempita(ricostruita, diagnostiche.get(nome), colori_fill[nome], crop_rect, sx, sy)

    # Contorni finali sottili per verificare chiusure e sovrapposizioni.
    for nome in ordine:
        geom = diagnostiche.get(nome)
        if geom is None or geom.is_empty:
            continue
        bordo = geom.boundary
        linee = list(bordo.geoms) if hasattr(bordo, "geoms") else [bordo]
        for line in linee:
            if not hasattr(line, "coords"):
                continue
            pts = np.array([[int(round((x-crop_rect.x0)*sx)), int(round((y-crop_rect.y0)*sy))]
                            for x,y in line.coords], dtype=np.int32)
            if len(pts) >= 2:
                cv2.polylines(ricostruita, [pts], False, (40,40,40), 1, cv2.LINE_AA)

    overlay = cv2.addWeighted(originale, 0.52, ricostruita, 0.48, 0)
    cv2.imwrite(os.path.join(output_dir, "_01_ORIGINALE_PDF.png"), originale)
    cv2.imwrite(os.path.join(output_dir, "_02_RICOSTRUZIONE_RIEMPITA.png"), ricostruita)
    cv2.imwrite(os.path.join(output_dir, "_03_OVERLAY_ORIGINALE_E_ESTRATTO.png"), overlay)

    fascia = 58
    confronto = np.full((h + fascia, w * 2, 3), 245, dtype=np.uint8)
    confronto[fascia:, :w] = originale
    confronto[fascia:, w:] = ricostruita
    cv2.putText(confronto, "ORIGINALE PDF", (22, 39), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20,20,20), 2, cv2.LINE_AA)
    cv2.putText(confronto, "RICOSTRUZIONE RIEMPITA", (w + 22, 39), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20,20,20), 2, cv2.LINE_AA)
    cv2.imwrite(os.path.join(output_dir, "_04_CONFRONTO_AFFIANCATO.png"), confronto)

def crea_confronti_per_layer(page, crop_rect, finestra_clip, poligoni_per_layer,
                               geometrie_finali, output_dir, larghezza=1200):
    """Confronta per ogni layer: PDF originale, candidati grezzi, risultato finale."""
    zoom = larghezza / float(crop_rect.width)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=crop_rect, alpha=False)
    originale = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    originale = cv2.cvtColor(originale[:, :, :3], cv2.COLOR_RGB2BGR)
    h, w = originale.shape[:2]
    sx = w / float(crop_rect.width)
    sy = h / float(crop_rect.height)

    colori = {
        "1_MURI_SPESSI": (0, 0, 0),
        "2_EDIFICI": (115, 115, 115),
        "3_PORTICI": (210, 210, 210),
        "4_AIUOLE_E_SIEPI": (5, 186, 167),
        "6_ACQUA_BLU": (221, 157, 0),
        "7_AREE_GIALLE": (54, 186, 255),
        "5_BOSCO_BIANCO": (245, 245, 245),
    }
    nomi = [
        "1_MURI_SPESSI", "2_EDIFICI", "3_PORTICI", "4_AIUOLE_E_SIEPI",
        "6_ACQUA_BLU", "7_AREE_GIALLE"
    ]
    cartella = os.path.join(output_dir, "CONFRONTO_LAYER")
    os.makedirs(cartella, exist_ok=True)
    righe_csv = ["layer,area_grezza_pt2,area_finale_pt2,percentuale_mantenuta,componenti_grezzi,componenti_finali"]
    miniature = []

    def n_parti(g):
        if g is None or g.is_empty:
            return 0
        if isinstance(g, Polygon):
            return 1
        if hasattr(g, "geoms"):
            return sum(1 for x in g.geoms if isinstance(x, Polygon))
        return 0

    for nome in nomi:
        raw_list = poligoni_per_layer.get(nome, [])
        raw = pulisci_topologia(unary_union(raw_list)) if raw_list else Polygon()
        raw = raw.intersection(finestra_clip) if not raw.is_empty else raw
        finale = geometrie_finali.get(nome, Polygon())

        col = colori[nome]
        pannelli = []
        titoli = ["PDF ORIGINALE", "CLASSIFICATO GREZZO", "DOPO BOOLEANE"]
        for idx, geom in enumerate((None, raw, finale)):
            if idx == 0:
                pane = originale.copy()
            else:
                pane = np.full_like(originale, 255)
                disegna_geom_riempita(pane, finestra_clip, (250,250,250), crop_rect, sx, sy)
                disegna_geom_riempita(pane, geom, col, crop_rect, sx, sy)
                if geom is not None and not geom.is_empty:
                    bordo = geom.boundary
                    linee = list(bordo.geoms) if hasattr(bordo, "geoms") else [bordo]
                    for line in linee:
                        if not hasattr(line, "coords"):
                            continue
                        pts = np.array([[int(round((x-crop_rect.x0)*sx)), int(round((y-crop_rect.y0)*sy))]
                                        for x,y in line.coords], dtype=np.int32)
                        if len(pts) >= 2:
                            cv2.polylines(pane, [pts], False, (25,25,25), 1, cv2.LINE_AA)
            pannelli.append(pane)

        fascia = 78
        confronto = np.full((h + fascia, w * 3, 3), 245, dtype=np.uint8)
        for i, pane in enumerate(pannelli):
            confronto[fascia:, i*w:(i+1)*w] = pane
            cv2.putText(confronto, titoli[i], (i*w + 18, 34), cv2.FONT_HERSHEY_SIMPLEX,
                        0.72, (20,20,20), 2, cv2.LINE_AA)
        area_raw = float(raw.area) if not raw.is_empty else 0.0
        area_fin = float(finale.area) if finale is not None and not finale.is_empty else 0.0
        pct = 100.0 * area_fin / area_raw if area_raw > 0 else 0.0
        testo = f"{nome} | area grezza {area_raw:.1f} pt2 | finale {area_fin:.1f} pt2 | mantenuta {pct:.1f}%"
        cv2.putText(confronto, testo, (18, 66), cv2.FONT_HERSHEY_SIMPLEX,
                    0.58, (45,45,45), 1, cv2.LINE_AA)
        out = os.path.join(cartella, f"{nome}_CONFRONTO.png")
        cv2.imwrite(out, confronto)
        righe_csv.append(f"{nome},{area_raw:.6f},{area_fin:.6f},{pct:.3f},{n_parti(raw)},{n_parti(finale)}")

        thumb_w = 900
        thumb_h = int(confronto.shape[0] * thumb_w / confronto.shape[1])
        miniature.append(cv2.resize(confronto, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA))

    with open(os.path.join(cartella, "_STATISTICHE_LAYER.csv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(righe_csv) + "\n")

    # Contact sheet verticale, leggibile senza aprire otto file.
    gap = 16
    total_h = sum(x.shape[0] for x in miniature) + gap * (len(miniature)-1)
    sheet = np.full((total_h, 900, 3), 235, dtype=np.uint8)
    y = 0
    for img in miniature:
        sheet[y:y+img.shape[0], :img.shape[1]] = img
        y += img.shape[0] + gap
    cv2.imwrite(os.path.join(cartella, "_TUTTI_I_LAYER.png"), sheet)

def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Uso: python ocad_to_creo_dxf_v14_vector_first.py [--full-page]")
        print("Senza opzioni apre il ritaglio poligonale interattivo prima dell'analisi.")
        return
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    doc = pymupdf.open(risolvi_percorso(INPUT_PDF))
    page = doc[0]

    finestra_clip, crop_rect = seleziona_poligono_pdf(page)
    # Memorizza il ritaglio in coordinate PDF per ripetibilita' e debug.
    try:
        coords_crop = list(finestra_clip.exterior.coords) if isinstance(finestra_clip, Polygon) else []
        with open(os.path.join(BASE_DIR, "ultimo_ritaglio_v14.json"), "w", encoding="utf-8") as fcrop:
            json.dump({"pdf": os.path.basename(risolvi_percorso(INPUT_PDF)), "coordinate_pdf": coords_crop,
                       "bbox_pdf": list(finestra_clip.bounds)}, fcrop, indent=2)
    except Exception as exc:
        print(f"Avviso: impossibile salvare ultimo_ritaglio_v14.json: {exc}")
    area_finestra = finestra_clip.area

    w_pt = crop_rect.width
    h_pt = crop_rect.height
    scala_mm = LARGHEZZA_CREO_MM / float(w_pt)
    w_mm = LARGHEZZA_CREO_MM
    h_mm = h_pt * scala_mm

    segmenti_base_poligono = deduplica_segmenti(raccogli_segmenti_da_geom(finestra_clip, scala_mm, crop_rect.x0, crop_rect.y1))

    drawings = page.get_drawings()
    poligoni_per_layer = defaultdict(list)
    priorita_layer = {
        "1_MURI_SPESSI": 90,
        "6_ACQUA_BLU": 85,
        "2_EDIFICI": 75,
        "3_PORTICI": 65,
        "4_AIUOLE_E_SIEPI": 55,
        "5_BOSCO_BIANCO": 32,
        "7_AREE_GIALLE": 20,
    }

    linee_nere_sottili = []
    pallini_gialli_pattern = []
    candidati_gialli = []
    poligoni_bianchi = []
    elementi_verdi_puntuali = []  # Croci verdi, pallini alberi e siepi a tratto
    maschere_strade = []  # beige stampato, solo cutter; mai esportato

    for d in drawings:
        r_box = d.get("rect")
        if r_box is not None and not r_box.intersects(crop_rect):
            continue

        fill_rgb = to_rgb255(d.get("fill"))
        stroke_rgb = to_rgb255(d.get("color"))
        width_pt = float(d.get("width") or 0.0)
        subpaths = items_to_shapely_paths(d["items"])

        # A) GESTIONE RIEMPIMENTI (FORME ESATTE)
        if fill_rgb is not None:
            info = classifica_colore_riempimento(d.get("fill"))
            if info is not None:
                nome_l, _ = info
                anelli, poly_comb = subpaths_to_polygons_list(subpaths)

                if nome_l == "8_STRADE_BASE":
                    if poly_comb is not None:
                        strada = poly_comb.intersection(finestra_clip)
                        if not strada.is_empty:
                            maschere_strade.extend(componenti_poligonali(strada))

                elif nome_l == "BIANCO":
                    if poly_comb is not None:
                        pc = poly_comb.intersection(finestra_clip)
                        if not pc.is_empty and 0.3 <= pc.area <= 0.45 * area_finestra:
                            poligoni_bianchi.append(pc)

                elif nome_l == "7_AREE_GIALLE":
                    # PyMuPDF frammenta il riempimento giallo in molti piccoli path.
                    # Sono tessere della stessa area: vanno conservate, non fuse come pallini.
                    for an in anelli:
                        an_clip = an.intersection(finestra_clip)
                        if not an_clip.is_empty and an_clip.area > 0.0005:
                            candidati_gialli.extend(componenti_poligonali(an_clip))
                else:
                    # Edifici, Portici, Aiuole e Siepi (con le loro FORME ESATTE!), Acqua Blu, Muri
                    if poly_comb is not None:
                        poly_clip = poly_comb.intersection(finestra_clip)
                        if not poly_clip.is_empty:
                            poligoni_per_layer[nome_l].append(poly_clip)

        # B) GESTIONE TRACCIATI / LINEE (NERO, CROCE VERDE, TONDO BLU)
        if stroke_rgb is not None:
            sr, sg, sb = stroke_rgb

            # Elimina prima i riferimenti azzurri, marroni e viola.
            if is_linea_riferimento(stroke_rgb):
                continue

            # 1. Tracciati BLU / CIANO (es. Tondo Blu al centro dei 4 quadrati gialli)
            if is_colore_blu_acqua(stroke_rgb):
                spess = max(width_pt, 0.35) * 0.5
                for sp in subpaths:
                    if len(sp) >= 2:
                        ls = LineString(sp).intersection(finestra_clip)
                        if not ls.is_empty:
                            poligoni_per_layer["6_ACQUA_BLU"].append(ls.buffer(spess, cap_style=1, join_style=1))

            # 2. Tracciati VERDI (es. Croce Verde, siepi lineari, contorni verdi)
            elif is_colore_verde_vegetazione(stroke_rgb):
                spess = max(width_pt, 0.32) * 0.5
                for sp in subpaths:
                    if len(sp) >= 2:
                        # Se è un anello chiuso piccolo (pallino albero), teniamo il pieno esatto
                        if len(sp) >= 4 and np.hypot(sp[0][0] - sp[-1][0], sp[0][1] - sp[-1][1]) < 0.15:
                            p_alb = Polygon(sp).buffer(width_pt * 0.5).intersection(finestra_clip)
                            if not p_alb.is_empty and p_alb.area < 15.0:
                                elementi_verdi_puntuali.append(p_alb)
                                continue
                        ls = LineString(sp).intersection(finestra_clip)
                        if not ls.is_empty:
                            # Croce verde o linea siepe: buffer con spigoli vivi (cap_style=2)
                            elementi_verdi_puntuali.append(ls.buffer(spess, cap_style=2, join_style=2))

            # 3. Tracciati NERI (Muri spessi vs Bordi sottili)
            elif sr < 50 and sg < 50 and sb < 50:
                for sp in subpaths:
                    if len(sp) >= 2:
                        ls = LineString(sp).intersection(finestra_clip)
                        if ls.is_empty:
                            continue
                        if width_pt >= SOGLIA_MURO_SPESSO_PT:
                            muro_poly = ls.buffer(width_pt * 0.5, cap_style=2, join_style=2).intersection(finestra_clip)
                            if not muro_poly.is_empty:
                                poligoni_per_layer["1_MURI_SPESSI"].append(muro_poly)
                        elif ls.length >= LUNGHEZZA_MIN_BORDO_TAGLIO_PT:
                            linee_nere_sottili.append(ls)

    # Classificazione adattiva del giallo: individua il cluster dominante del retino.
    if candidati_gialli:
        aree_g = np.array([g.area for g in candidati_gialli], dtype=float)
        # Moda robusta in scala logaritmica, adatta a PDF e ritagli di dimensioni diverse.
        loga = np.log10(aree_g[aree_g > 0])
        bins = min(96, max(24, int(np.sqrt(loga.size))))
        hist, edges = np.histogram(loga, bins=bins)
        i = int(np.argmax(hist))
        cluster = aree_g[(loga >= edges[i]) & (loga <= edges[i + 1])]
        area_retino_tipica = float(np.median(cluster)) if cluster.size else float(np.median(aree_g))
        soglia_giallo = FATTORE_RETINO_GIALLO * area_retino_tipica
        poligoni_per_layer["7_AREE_GIALLE"] = [g for g in candidati_gialli if g.area >= soglia_giallo]
        print(f"Giallo: {len(candidati_gialli)} candidati, retino tipico={area_retino_tipica:.4f} pt2, "
              f"soglia={soglia_giallo:.4f} pt2, superfici={len(poligoni_per_layer['7_AREE_GIALLE'])}")

    # C) RETINI ISOM 402 E 404 COME LAYER DI AREA DISTINTI.
    # 402 = bianco con retino/punti gialli; 404 = giallo con punti bianchi.
    # I punti sono soltanto marcatori grafici: il volume segue il contorno dell'area,
    # non deve essere bucato punto per punto.
    geom_402 = Polygon()
    geom_404 = Polygon()
    if poligoni_per_layer.get("7_AREE_GIALLE"):
        giallo_grezzo = pulisci_topologia(unary_union(poligoni_per_layer["7_AREE_GIALLE"]))
        comps_gialle = componenti_poligonali(giallo_grezzo)
        bianchi_validi = [b for b in poligoni_bianchi if 0.30 <= b.area <= 80.0]
        parti_404, parti_401 = [], []
        for comp in comps_gialle:
            # Conta i dischi/zone bianche interne, evitando i normali cortili grandi.
            n_bianchi = sum(1 for b in bianchi_validi if comp.buffer(0.35).intersects(b.centroid))
            if n_bianchi >= 2:
                # Ricostruisce il supporto giallo continuo colmando i soli marcatori bianchi.
                forato = comp
                for b in bianchi_validi:
                    if comp.buffer(0.35).intersects(b.centroid):
                        forato = unary_union([forato, b.intersection(comp.buffer(1.0))])
                parti_404.append(pulisci_topologia(forato))
            else:
                parti_401.append(comp)
        geom_404 = pulisci_topologia(unary_union(parti_404)) if parti_404 else Polygon()
        poligoni_per_layer["7_AREE_GIALLE"] = parti_401
        if not geom_404.is_empty:
            poligoni_per_layer["9_TERRENO_GREZZO_ALBERI_SPARSI_404"] = componenti_poligonali(geom_404)

        # Il 402 appare come area bianca contenente molte tessere gialle del retino.
        # Usiamo la densita' dei candidati piccoli dentro ciascuna area bianca.
        piccoli_gialli = [g for g in candidati_gialli if g.area < soglia_giallo]
        aree_402 = []
        for bianco in poligoni_bianchi:
            if bianco.area < 4.0:
                continue
            n = sum(1 for d in piccoli_gialli if bianco.contains(d.centroid))
            densita = n / max(bianco.area, 1e-9)
            if n >= 5 and densita >= 0.025:
                aree_402.append(bianco)
        geom_402 = pulisci_topologia(unary_union(aree_402)) if aree_402 else Polygon()
        if not geom_402.is_empty:
            poligoni_per_layer["5_TERRENO_APERTO_ALBERI_SPARSI_402"] = componenti_poligonali(geom_402)
        print(f"ISOM riconosciuti (assimilati temporaneamente al giallo): "
              f"402={len(componenti_poligonali(geom_402))}, 404={len(componenti_poligonali(geom_404))}")
        # NOTA: 402 e 404 restano semanticamente distinti secondo ISOM 2000,
        # ma per l'attuale modello tattile vengono uniti a 7_AREE_GIALLE.
        gialli_unificati = list(poligoni_per_layer.get("7_AREE_GIALLE", []))
        gialli_unificati += componenti_poligonali(geom_402)
        gialli_unificati += componenti_poligonali(geom_404)
        poligoni_per_layer["7_AREE_GIALLE"] = componenti_poligonali(
            pulisci_topologia(unary_union(gialli_unificati)))
        poligoni_per_layer.pop("5_TERRENO_APERTO_ALBERI_SPARSI_402", None)
        poligoni_per_layer.pop("9_TERRENO_GREZZO_ALBERI_SPARSI_404", None)

        # Il bianco cartografico e' bosco percorribile (ISOM 405), non vuoto.
        # Esclude soltanto l'area 402, assimilata al giallo, e i bianchi minuscoli
        # usati come retino del 404.
        bosco = unary_union([b for b in poligoni_bianchi if b.area >= 4.0])
        if not geom_402.is_empty:
            bosco = bosco.difference(geom_402)
        if not bosco.is_empty:
            poligoni_per_layer["5_BOSCO_BIANCO"] = componenti_poligonali(pulisci_topologia(bosco))

    # Maschera strade: resta interna alla pipeline e non genera alcun DXF/layer.
    # Il PDF disegna il beige sopra un fondo giallo esteso: ignorarlo fa apparire
    # falsamente gialle strade e cortili beige.
    strade_geom = pulisci_topologia(unary_union(maschere_strade)) if maschere_strade else Polygon()
    if not strade_geom.is_empty:
        strade_geom = strade_geom.intersection(finestra_clip).buffer(0)
        print(f"Maschera strade beige: {len(maschere_strade)} componenti, area={strade_geom.area:.2f} pt2")

    # Bosco bianco ISOM 405: nel PDF il bianco e' spesso assenza di riempimento,
    # quindi non basta cercare path bianchi. Ricostruiamo il fondo residuo delimitato
    # da strade, giallo, edifici e portici. Simboli verdi e linee nere restano sopra
    # senza perforare il bosco.
    maschere_non_bosco = [strade_geom]
    for lk in ("7_AREE_GIALLE", "2_EDIFICI", "3_PORTICI"):
        if poligoni_per_layer.get(lk):
            maschere_non_bosco.append(pulisci_topologia(unary_union(poligoni_per_layer[lk])))
    bosco_residuo = pulisci_topologia(finestra_clip.difference(unary_union(maschere_non_bosco)))
    # Integra gli eventuali path bianchi espliciti, ma non il 402 assimilato al giallo.
    bosco_esplicito = pulisci_topologia(unary_union(poligoni_per_layer.get("5_BOSCO_BIANCO", [])))
    if not bosco_esplicito.is_empty:
        bosco_residuo = pulisci_topologia(unary_union([bosco_residuo, bosco_esplicito])).difference(strade_geom)
    poligoni_per_layer["5_BOSCO_BIANCO"] = componenti_poligonali(bosco_residuo)

    # D) INCASTRO BOOLEANO TOPOLOGICO (Dalla priorità più alta alla più bassa)
    lama_bordi_sottili = (
        unary_union(linee_nere_sottili).buffer(SPESSORE_TAGLIO_BORDI_PT * 0.5, cap_style=2, join_style=2)
        if linee_nere_sottili
        else None
    )

    layer_ordinati = sorted((k for k in poligoni_per_layer.keys() if k != "8_STRADE_BASE"), key=lambda k: priorita_layer.get(k, 0), reverse=True)
    ingombro_cumulativo = Polygon()
    ingombro_strutturale = Polygon()  # esclude le strade, per non cancellare alberi/siepi puntuali
    geometrie_finali = {}
    report_watertight = []

    for nome_l in layer_ordinati:
        unione_l = pulisci_topologia(unary_union(poligoni_per_layer[nome_l]))

        # Il giallo e i retini 402/404 sono aree di fondo: vengono delimitati dalle
        # strade beige, ma NON bucati da alberi, piccoli verdi, muri o linee nere.
        # Gli altri layer mantengono il normale incastro per priorita'.
        if nome_l in ("7_AREE_GIALLE", "5_BOSCO_BIANCO"):
            pulito = unione_l
            if not strade_geom.is_empty:
                pulito = pulito.difference(strade_geom)
        else:
            pulito = unione_l.difference(ingombro_cumulativo)

        # Tagliamo con i bordi neri sottili (tranne Muri Spessi e Tondo Blu)
        if lama_bordi_sottili is not None and nome_l not in (
            "1_MURI_SPESSI", "6_ACQUA_BLU", "7_AREE_GIALLE", "5_BOSCO_BIANCO"
        ):
            pulito = pulito.difference(lama_bordi_sottili)

        # Se è il layer 4_AIUOLE_E_SIEPI, uniamo anche le croci verdi e gli alberi puntuali
        # (tagliati solo da muri spessi ed edifici, così non vengono affettati dai bordi neri sottili)
        if nome_l == "4_AIUOLE_E_SIEPI" and elementi_verdi_puntuali:
            # Gli elementi verdi puntuali restano sopra la pavimentazione.
            verdi_extra = pulisci_topologia(unary_union(elementi_verdi_puntuali)).difference(ingombro_strutturale)
            pulito = pulisci_topologia(unary_union([pulito, verdi_extra]))

        pulito = pulisci_topologia(pulito.intersection(finestra_clip))
        pulito, stats_clean = filtra_watertight(pulito, scala_mm, nome_l, w_mm, area_finestra)
        check = verifica_profili(pulito, scala_mm)
        geometrie_finali[nome_l] = pulito
        report_watertight.append((nome_l, stats_clean, check))
        ingombro_cumulativo = pulisci_topologia(ingombro_cumulativo.union(unione_l))
        ingombro_strutturale = pulisci_topologia(ingombro_strutturale.union(unione_l))

    # E) ESPORTAZIONE DXF PER PTC CREO PARAMETRIC
    scrivi_dxf_creo(os.path.join(OUTPUT_DIR, "0_PIASTRA_BASE_POLIGONALE.dxf"), segmenti_base_poligono, {}, w_mm, h_mm)

    segs_per_layer = {}
    for nome_l, geom in geometrie_finali.items():
        segs = deduplica_segmenti(raccogli_segmenti_da_geom(geom, scala_mm, crop_rect.x0, crop_rect.y1))
        if segs:
            segs_per_layer[nome_l] = segs
            scrivi_dxf_creo(os.path.join(OUTPUT_DIR, f"{nome_l}.dxf"), segmenti_base_poligono, {nome_l: segs}, w_mm, h_mm)

    scrivi_dxf_creo(os.path.join(OUTPUT_DIR, "00_FIGURA_UNICA_DA_PDF.dxf"), segmenti_base_poligono, segs_per_layer, w_mm, h_mm)

    # F) CONFRONTO RASTER: originale PDF contro aree finali realmente riempite.
    with open(os.path.join(OUTPUT_DIR, "_REPORT_WATERTIGHT.csv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# V14 vector-first: bezier adattive errore<=0.002 pt; no simplify; no opening; repair invalid-only\n")
        f.write("layer,poligoni,area_mm2,feature_rimosse,fori_piccoli_chiusi,area_tipica_pt2,area_min_pt2,griglia_pt,invalidi,anelli_aperti,anelli_non_semplici\n")
        for nome, clean, check in report_watertight:
            f.write(f"{nome},{check['poligoni']},{check['area_mm2']:.6f},{clean['rimossi']},{clean['fori_chiusi']},{clean.get('area_tipica_pt2',0):.6f},{clean.get('area_min_pt2',0):.6f},{clean.get('grid_pt',0):.6f},{check['invalidi']},{check['anelli_aperti']},{check['anelli_non_semplici']}\n")

    crea_confronto_riempito(page, crop_rect, finestra_clip, geometrie_finali,
                             strade_geom, OUTPUT_DIR)
    crea_confronti_per_layer(page, crop_rect, finestra_clip, poligoni_per_layer,
                              geometrie_finali, OUTPUT_DIR)

    # G) ANTEPRIMA AD ALTA RISOLUZIONE (Con colori distinti per verificare ogni layer)
    w_img = 1800
    h_img = max(100, int(w_img * (h_mm / w_mm)))
    s_img = w_img / w_mm
    canvas = np.full((h_img, w_img, 3), 255, dtype=np.uint8)

    colori_preview = {
        "1_MURI_SPESSI": (0, 0, 0),            # Nero
        "2_EDIFICI": (90, 90, 90),             # Grigio scuro
        "3_PORTICI": (165, 165, 165),          # Grigio chiaro
        "4_AIUOLE_E_SIEPI": (35, 165, 45),     # Verde (Aiuole esatte + Siepi + Alberi + Croce verde)
        "5_ZONA_ALBERI_BASSI": (180, 220, 120),# Verde-Giallo chiaro (Ex bianco coi pallini gialli unificato!)
        "6_ACQUA_BLU": (240, 100, 0),          # Blu acceso (Tondo blu!)
        "7_AREE_GIALLE": (30, 185, 245),       # 401 giallo pieno
        "5_BOSCO_BIANCO": (245, 245, 245),
    }

    for (x1, y1), (x2, y2) in segmenti_base_poligono:
        p1 = (int(x1 * s_img), int((h_mm - y1) * s_img))
        p2 = (int(x2 * s_img), int((h_mm - y2) * s_img))
        cv2.line(canvas, p1, p2, (0, 0, 220), 2, cv2.LINE_AA)

    for nome_l in reversed(layer_ordinati):
        if nome_l not in segs_per_layer:
            continue
        col = colori_preview.get(nome_l, (50, 50, 50))
        for (x1, y1), (x2, y2) in segs_per_layer[nome_l]:
            p1 = (int(x1 * s_img), int((h_mm - y1) * s_img))
            p2 = (int(x2 * s_img), int((h_mm - y2) * s_img))
            cv2.line(canvas, p1, p2, col, 2, cv2.LINE_AA)

    preview_path = os.path.join(OUTPUT_DIR, "_ANTEPRIMA_DA_PDF_VETTORIALE.png")
    cv2.imwrite(preview_path, canvas)
    print(f"\nCompletato! Layer estratti: {list(segs_per_layer.keys())}")
    print(f"Controlla '{preview_path}' e i file DXF in '{OUTPUT_DIR}'.")


if __name__ == "__main__":
    main()