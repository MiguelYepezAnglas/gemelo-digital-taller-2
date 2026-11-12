"""Plan de producción: parámetros base compartidos por la fábrica y el gemelo."""
import math

BASE = {
    "tiempos": {"llenado": 2.0, "etiquetado": 4.0, "empaquetado": 3.0},
    "distribuciones": {"llenado": "gamma", "etiquetado": "lognormal", "empaquetado": "gamma"},
    "cv": {"llenado": 0.12, "etiquetado": 0.30, "empaquetado": 0.18},
    "maquinas": {"llenado": 1, "etiquetado": 1, "empaquetado": 1},
    "demanda": 18,
    "horas": 8,
    "averia": None,
}
ESTACIONES = list(BASE["tiempos"])


def muestrear_tiempo(media, cv, familia, rng):
    if familia == "gamma":
        forma = 1 / (cv ** 2)
        escala = media / forma
        return float(rng.gamma(shape=forma, scale=escala))
    if familia == "lognormal":
        sigma2 = math.log(1 + cv ** 2)
        sigma = math.sqrt(sigma2)
        mu = math.log(media) - sigma2 / 2
        return float(rng.lognormal(mean=mu, sigma=sigma))
    raise ValueError(f"Distribución no reconocida: {familia}")


META = 100
FIN_TURNO = BASE["horas"] * 60
MAX_MAQUINAS = 4
