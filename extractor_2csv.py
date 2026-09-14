# extractor_2csv.py
import os
import csv
import io
import sys
import logging
import requests

# ============================================================
# CONFIGURACIÓN
# ============================================================
SHEET_ID = "1j3HugUF6YbEiyk7nVzuYOjro4Rxh9FWU"
REGION   = 177
RUTA_CSV = "2.csv"

# Mapa de etapas (texto → código SOAP)
ETAPAS = {
    "PREFACTIBILIDAD": 3,
    "FACTIBILIDAD":    4,
    "DISEÑO":          5,
    "DISENO":          5,   # por si viene sin tilde
    "EJECUCION":       6,
    "EJECUCIÓN":       6    # por si viene con tilde
}

# Encabezados conocidos (para detectar la fila correcta y limpiar celdas)
HEADERS_CONOCIDOS = [
    "CODIGO BIP", "NOMBRE INICIATIVA", "REGION", "COMUNA", "ETAPA POSTULA",
    "COSTO TOTAL M$", "AÑO POSTULACION", "RATE", "FECHA RATE", "SECTOR",
    "MAGNITUD VALOR", "MAGNITUD", "FUENTE FINANCIERA"
]

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ============================================================
# 1. DESCARGAR CSV DEL SHEET
# ============================================================
def descargar_sheet(sheet_id):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    log.info("📥 Descargando Sheet desde Google Sheets...")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    if r.text.lstrip().startswith("<"):
        raise RuntimeError("El Sheet no es público. Compártelo con 'Cualquiera con el enlace → Lector'.")
    return r.text

# ============================================================
# 2. LIMPIAR CELDAS CON RUIDO
# ============================================================
def limpiar_celda(celda):
    """
    Quita ruido como 'RESULTADO CONSULTA: ...' que aparece pegado al
    encabezado real ('CODIGO BIP') en la misma celda.
    """
    s = str(celda).strip()

    # Si hay saltos de línea, quedarse con la última
    if "\n" in s or "\r" in s:
        partes = [p.strip() for p in s.replace("\r", "\n").split("\n") if p.strip()]
        s = partes[-1] if partes else ""

    # Si hay un header conocido precedido de ruido, cortar desde ahí
    s_upper = s.upper()
    for h in HEADERS_CONOCIDOS:
        idx = s_upper.rfind(h)
        if idx > 0:
            s = s[idx:].strip()
            break
    return s

# ============================================================
# 3. DETECTAR FILA DE ENCABEZADOS
# ============================================================
def detectar_cabecera(filas):
    """
    Busca en las primeras 10 filas cuál tiene más encabezados conocidos.
    Devuelve el índice de esa fila.
    """
    mejor_idx, mejor_score = -1, 0
    for i, fila in enumerate(filas[:10]):
        texto = " ".join(str(c) for c in fila).upper()
        score = sum(1 for h in HEADERS_CONOCIDOS if h in texto)
        if score > mejor_score:
            mejor_score = score
            mejor_idx = i
    if mejor_score < 3:
        raise RuntimeError(f"No se detectaron encabezados (score={mejor_score})")
    return mejor_idx

# ============================================================
# 4. PROCESAR: extraer los 5 parámetros SOAP únicos
# ============================================================
def procesar(csv_texto):
    filas = list(csv.reader(io.StringIO(csv_texto)))

    idx_cab = detectar_cabecera(filas)
    cabeceras = [limpiar_celda(c).upper() for c in filas[idx_cab]]
    log.info(f"📄 Cabeceras detectadas: {cabeceras[:5]}...")

    idx_bip   = cabeceras.index("CODIGO BIP") if "CODIGO BIP" in cabeceras else -1
    idx_anio  = cabeceras.index("AÑO POSTULACION") if "AÑO POSTULACION" in cabeceras else -1
    idx_etapa = cabeceras.index("ETAPA POSTULA") if "ETAPA POSTULA" in cabeceras else -1

    if -1 in (idx_bip, idx_anio, idx_etapa):
        raise RuntimeError(f"Faltan columnas requeridas. Encontradas: {cabeceras}")

    datos = filas[idx_cab + 1:]
    log.info(f"📄 {len(datos)} filas de datos")

    registros = []
    vistos = set()
    descartadas = 0

    for fila in datos:
        if not fila or len(fila) <= max(idx_bip, idx_anio, idx_etapa):
            descartadas += 1
            continue

        bip_raw = str(fila[idx_bip]).strip()
        if not bip_raw or "CODIGO BIP" in bip_raw.upper():
            continue

        partes = bip_raw.split("-")
        try:
            codigo_bip = int(partes[0])
            codigo_parte = int(partes[1]) if len(partes) > 1 and partes[1].strip() else 0
            anio = int(str(fila[idx_anio]).strip())
        except (ValueError, IndexError):
            descartadas += 1
            continue

        etapa_texto = str(fila[idx_etapa]).strip().upper()
        codigo_etapa = ETAPAS.get(etapa_texto)
        if not codigo_etapa:
            descartadas += 1
            continue

        # Clave única para deduplicar
        clave = (codigo_bip, codigo_parte, anio, codigo_etapa)
        if clave in vistos:
            continue
        vistos.add(clave)

        registros.append({
            "codigoBip": codigo_bip,
            "codigoParte": codigo_parte,
            "anio": anio,
            "codigoEtapaPostula": codigo_etapa,
            "region": REGION
        })

    return registros, len(datos), descartadas

# ============================================================
# 5. BORRAR Y ESCRIBIR 2.csv
# ============================================================
def escribir_csv(registros, ruta):
    # Borrar si existe
    if os.path.exists(ruta):
        os.remove(ruta)
        log.info(f"🗑️  Borrado: {ruta}")

    # Crear de nuevo
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "codigoBip", "codigoParte", "anio", "codigoEtapaPostula", "region"
        ])
        writer.writeheader()
        writer.writerows(registros)

    log.info(f"✅ Creado: {ruta} ({len(registros)} filas)")

# ============================================================
# MAIN
# ============================================================
def main():
    try:
        csv_texto = descargar_sheet(SHEET_ID)
        registros, total, desc = procesar(csv_texto)

        log.info("")
        log.info("📊 RESUMEN:")
        log.info(f"   Filas del Sheet:       {total}")
        log.info(f"   Parámetros únicos:     {len(registros)}")
        log.info(f"   Duplicados eliminados: {total - len(registros) - desc}")
        log.info(f"   Descartadas:           {desc}")
        log.info("")

        escribir_csv(registros, RUTA_CSV)
        log.info(f"🎉 Listo. Archivo '{RUTA_CSV}' regenerado.")
    except Exception as e:
        log.error(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
