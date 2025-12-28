import re
import math
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# Constantes y Regex (Portados de V1/analisis.py y V1/customtypes.py)
# ============================================================================

# Constantes de milímetros para detección de formato de página
PT2MM = 25.4 / 72.0
CLASES = [((210, 297), 'A4', 0),
          ((145, 210), 'A5', 0), # cuartilla?
          ((102.5, 145), 'A6', 0), # postal?
          ((53, 85), 'TJT', 0), # tarjeta credito
          ((86, 54), 'DNI', 0), 
          ((85, 125), 'PASAPORTE', 0), # pasaporte?
          ((210, 297/3.0), 'ACUSE', 0),
          ((297/3.0, 210), 'CN07', 0), # citaciones
          ((210/3.0, 297), 'A4largo', 0),
          ]

# Regex maestra
# Grupos:
# 1: @@@\d{15}@@@[^@]+@@@  (Masivo, código completo)
# 2: \d{15}                 (Expediente)
# 3: O\d{8}[es]\d{10}       (Registro)
# 4: (NA|CD)\d{21}          (Correos/CSV - ccorreos - excluye el check digit al final a veces?)
#                           Original: ((?:NA|CD)\d{21})\D   -> OJO con el \D final
# 5: EXT(?:-[a-f0-9]{4}){8} (CVE)
# 6: 90533...               (Tasa - ctasa)
# 7: EX\d\d                 (Formulario)
RX_PATTERN = r'(@@@\d{15}@@@[^@]+@@@)|\b(\d{15})\b|\b(O\d{8}[es]\d{10})\b|((?:NA|CD)\d{21})|(EXT(?:-[a-f0-9]{4}){8})|(90533\d{12}790\d{10}[A-Z0-9]\d{7}[A-Z0-9]\d)|(EX\d\d)'
RX = re.compile(RX_PATTERN)

# Regex adicionales para parsing fino (de customtypes.Data)
PAT_TASA = re.compile(r'^90533(\d{12})(790\d{10})([A-Z0-9]\d{7}[A-Z0-9])\d$')
PAT_CMASIVO_SPLIT = re.compile(r'^@@@(\d{15})@@@([^@]+)@@@$')

# ============================================================================
# Estructuras de Datos
# ============================================================================

@dataclass
class TasaInfo:
    raw: str
    modelo: str      # '790' + siguiente parte
    referencia: str  # parte 90533 + num
    cif_pasivo: str  # parte final

@dataclass
class MasivoInfo:
    raw: str
    expediente: str
    nombre_doc: str

@dataclass
class AnalisisResult:
    expedientes: List[str]
    codigos_masivos: List[MasivoInfo]
    codigos_tasa: List[TasaInfo]
    codigos_correos: List[str]  # NA/CD...
    codigos_cve: List[str]
    codigos_registro: List[str]
    formularios: List[str]
    
    # Metadatos de página
    es_acuse: bool = False
    es_pasaporte: bool = False
    formato_papel: str = "A4"

# ============================================================================
# Lógica de Análisis
# ============================================================================

def analizar_pagina(text: str, width_pt: float = 0, height_pt: float = 0) -> AnalisisResult:
    """Analiza el texto de una página y devuelve los códigos encontrados.
    
    También intenta determinar el tipo de documento basándose en dimensiones si se proporcionan.
    """
    
    # 1. Determinación de formato de papel (si hay dimensiones)
    formato = "Desconocido"
    es_acuse = False
    es_pasaporte = False
    
    if width_pt > 0 and height_pt > 0:
        mm2 = width_pt * PT2MM * height_pt * PT2MM
        aspectn = max(width_pt, height_pt) / min(width_pt, height_pt)
        
        # Lógica de V1: Distancia euclídea ponderada al estándar más cercano
        # self.clases = sorted([ ((sqrt(mm2)-sqrt(c[0]))**2 + 10*(aspectn -  c[1])**2, c[2]) for c in CLASES])
        
        def calc_dist(c_dims, c_name):
             area_std = c_dims[0] * c_dims[1]
             # Nota: En V1 CLASES es ((w,h), name, ...). 
             # Pero en el loop de analisis.py: c[0] parece ser area? NO.
             # En V1 CLASES es [((210, 297), ...)] -> c[0] es la tupla (w, h).
             # Pero en la list comp: sqrt(c[0]) fallaría si es tupla.
             # Revisando V1/analisis.py:
             # self.clases = sorted([ ((sqrt(mm2)-sqrt(c[0]))**2 + 10*(aspectn -  c[1])**2, c[2]) for c in CLASES])
             # Esto asume que CLASES en V1 tiene otra estructura o 'c[0]' es el area precalculada.
             # Viendo el código V1 visto: CLASES tiene tuplas ((w,h), name).
             # Probablemente en V1 c[0] se refiera al área si CLASES está definido distinto en runtime o si mi lectura rápida
             # asumió tupla. Vamos a recalcular el área nosotros.
             w_std, h_std = c_dims
             area_std = w_std * h_std
             aspect_std = max(w_std, h_std) / min(w_std, h_std)
             
             dist = (math.sqrt(mm2) - math.sqrt(area_std))**2 + 10 * (aspectn - aspect_std)**2
             return dist, c_name

        candidates = [calc_dist(c[0], c[1]) for c in CLASES]
        best_match = sorted(candidates, key=lambda x: x[0])[0]
        formato = best_match[1]
        
        if formato in ['ACUSE', 'CN07']: es_acuse = True
        if formato == 'PASAPORTE': es_pasaporte = True

    # 2. Extracción de Regex
    data_matches = RX.findall(text)
    
    # DEBUG LOGGING (TEMPORARY)
    if data_matches:
        logger.info(f"[DEBUG] Analisis Regex Matches ({len(data_matches)}):")
        for i, m in enumerate(data_matches):
            logger.info(f"  [{i}] {m}")

    # 3. Clasificación de resultados
    expedientes = []
    masivos = []
    tasas = []
    correos = []
    cves = []
    registros = []
    formularios = []

    def clean(s): return s.strip()

    for m in data_matches:
        # Grupos del regex:
        # 0: Masivo, 1: Expe, 2: Reg, 3: Correos, 4: CVE, 5: Tasa, 6: Formulario
        
        if m[0]: # Masivo
            raw = clean(m[0])
            match_split = PAT_CMASIVO_SPLIT.match(raw)
            if match_split:
                 masivos.append(MasivoInfo(raw=raw, expediente=match_split.group(1), nombre_doc=match_split.group(2)))
        
        if m[1]: # Expediente
             expedientes.append(clean(m[1]))
             
        if m[2]: # Registro
             registros.append(clean(m[2]))
             
        if m[3]: # Correos
             correos.append(clean(m[3]))
             
        if m[4]: # CVE
             cves.append(clean(m[4]))
             
        if m[5]: # Tasa
             raw = clean(m[5])
             tmatch = PAT_TASA.match(raw)
             if tmatch:
                 # 90533(\d{12})(790\d{10})([A-Z0-9]\d{7}[A-Z0-9])\d
                 # Grupo 1: referencia (parte tras 90533)
                 # Grupo 2: modelo (790...)
                 # Grupo 3: cif_pasivo
                 tasas.append(TasaInfo(raw=raw, referencia="90533"+tmatch.group(1), modelo=tmatch.group(2), cif_pasivo=tmatch.group(3)))
             else:
                 # Fallback si no matchea el fino (raro pq la RX maestra es estricta)
                 logger.warning(f"[DEBUG] Tasa encontrada pero no parseada: {raw}")
                 
        if m[6]: # Formulario
             formularios.append(clean(m[6]))

    # Reducción de valores duplicados (preserving order ish)
    def unique(l): return list(dict.fromkeys(l))
    
    result = AnalisisResult(
        expedientes=unique(expedientes),
        codigos_masivos=masivos, # Masivos son objetos, difícil unique simple, asumimos OK
        codigos_tasa=tasas,
        codigos_correos=unique(correos),
        codigos_cve=unique(cves),
        codigos_registro=unique(registros),
        formularios=unique(formularios),
        es_acuse=es_acuse,
        es_pasaporte=es_pasaporte,
        formato_papel=formato
    )
    
    # DEBUG LOGGING (TEMPORARY)
    if any([result.expedientes, result.codigos_tasa, result.codigos_correos]):
        logger.info(f"[DEBUG] Resultado Analisis: Expes={len(result.expedientes)}, Tasas={len(result.codigos_tasa)}, Correos={len(result.codigos_correos)}")

    return result
