"""El gemelo digital: lee el Sheet, sincroniza, proyecta, decide y envía órdenes."""
import copy
import threading
import time
from datetime import datetime

import numpy as np
import pandas as pd
import simpy

from nucleo.modelo import BASE, ESTACIONES, FIN_TURNO, MAX_MAQUINAS, META, muestrear_tiempo
from nucleo.sheets import ESQUEMA, ZONA, InsertDataOption, ahora, con_reintentos


class LectorSheet:
    """Lee solo lo nuevo del Sheet. Todo en UNA solicitud por lectura (cuota de la API)."""

    def __init__(self, libro):
        self.libro = libro
        self.reiniciar()

    def reiniciar(self):
        self.filas_telemetria = 0
        self.filas_estado = 0
        self.turno_id = None

    def leer(self):
        rangos = [f"telemetria!A{self.filas_telemetria + 2}:F",
                  f"estado!A{self.filas_estado + 2}:L",
                  "estado!A2:A2",
                  "ordenes!A2:I"]
        r = con_reintentos(self.libro.values_batch_get, rangos,
                           params={"valueRenderOption": "UNFORMATTED_VALUE"})
        tele, est, primera, ordenes = [v.get("values", []) for v in r["valueRanges"]]

        turno = primera[0][0] if primera and primera[0] else None
        nuevo_turno = turno is not None and turno != self.turno_id and self.turno_id is not None
        if nuevo_turno:                     # la fábrica reinició: empezamos de cero
            self.reiniciar()
            return self.leer() | {"nuevo_turno": True}
        self.turno_id = turno

        self.filas_telemetria += len(tele)
        self.filas_estado += len(est)
        return {
            "telemetria": self._tabla(tele, "telemetria"),
            "estado": self._tabla(est, "estado"),
            "ordenes": self._tabla(ordenes, "ordenes"),
            "nuevo_turno": False,
        }

    @staticmethod
    def _tabla(filas, hoja):
        cab = ESQUEMA[hoja]
        filas = [list(f) + [""] * (len(cab) - len(f)) for f in filas]
        return pd.DataFrame(filas, columns=cab)


class Gemelo:
    """Reconstruye el estado de la línea solo con la telemetría del Sheet."""

    def __init__(self, plan=BASE, meta=META):
        self.p = copy.deepcopy(plan)
        self.meta = meta
        self.eventos = pd.DataFrame(columns=["minuto", "evento", "estacion", "botella", "detalle"])
        self.historial = pd.DataFrame(columns=ESQUEMA["estado"])
        self.minuto = 0.0
        self.estado_planta = "esperando"

    def recibir(self, lectura):
        tele = lectura["telemetria"]
        if len(tele):
            ev = tele.rename(columns={"minuto_turno": "minuto", "botella_id": "botella"})
            ev = ev[["minuto", "evento", "estacion", "botella", "detalle"]].copy()
            ev["minuto"] = pd.to_numeric(ev["minuto"])
            ev["botella"] = pd.to_numeric(ev["botella"], errors="coerce")
            self.eventos = pd.concat([self.eventos, ev], ignore_index=True) if len(self.eventos) else ev
            for _, a in ev[ev["evento"] == "accion"].iterrows():
                if str(a["detalle"]).startswith("abre máquina"):
                    self.p["maquinas"][a["estacion"]] = int(str(a["detalle"]).split("(")[1].split()[0])
        est = lectura["estado"]
        if len(est):
            self.historial = pd.concat([self.historial, est], ignore_index=True) if len(self.historial) else est
            self.minuto = float(est.iloc[-1]["minuto_turno"])
            self.estado_planta = est.iloc[-1]["estado_planta"]

    def tiempos_observados(self, ultimos=15):
        ev = self.eventos[self.eventos["evento"].isin(["inicio", "fin"])]
        if ev.empty:
            return {e: (self.p["tiempos"][e], 0) for e in ESTACIONES}
        par = ev.pivot_table(index=["botella", "estacion"], columns="evento", values="minuto").dropna()
        if "fin" not in par:
            return {e: (self.p["tiempos"][e], 0) for e in ESTACIONES}
        par["duracion"] = par["fin"] - par["inicio"]
        par = par.reset_index().sort_values("fin")
        salida = {}
        for e in ESTACIONES:
            d = par[par["estacion"] == e]
            fin_parada = self.eventos.query("evento == 'parada_fin' and estacion == @e")["minuto"]
            if len(fin_parada):
                d = d[d["inicio"] >= fin_parada.max()]
            d = d.tail(ultimos)
            salida[e] = (float(d["duracion"].mean()), len(d)) if len(d) >= 5 else (self.p["tiempos"][e], len(d))
        return salida

    def estado(self):
        ev = self.eventos[self.eventos["botella"].notna()]
        ultimo = ev.groupby("botella").tail(1)
        colas = {e: 0 for e in ESTACIONES}
        en_servicio, producidas = [], 0
        for _, f in ultimo.iterrows():
            if f["evento"] == "llegada":
                colas["llenado"] += 1
            elif f["evento"] == "inicio":
                en_servicio.append((f["estacion"], max(0.0, self.minuto - f["minuto"])))
            elif f["estacion"] == ESTACIONES[-1]:
                producidas += 1
            else:
                colas[ESTACIONES[ESTACIONES.index(f["estacion"]) + 1]] += 1

        parada = None
        pa = self.eventos[self.eventos["evento"].isin(["parada_inicio", "parada_fin"])]
        if len(pa) and pa.iloc[-1]["evento"] == "parada_inicio":
            ini = pa.iloc[-1]
            dur = float(str(ini["detalle"]).split()[1])
            parada = (ini["estacion"], max(0.0, ini["minuto"] + dur - self.minuto))

        tiempos = self.tiempos_observados()
        return {
            "minuto": self.minuto,
            "producidas": producidas,
            "llegadas": int((self.eventos["evento"] == "llegada").sum()),
            "colas": colas,
            "en_servicio": en_servicio,
            "maquinas": dict(self.p["maquinas"]),
            "tiempos": {e: tiempos[e][0] for e in ESTACIONES},
            "desvio": {e: 100 * (tiempos[e][0] / self.p["tiempos"][e] - 1) for e in ESTACIONES},
            "parada": parada,
        }


def simular_desde(estado, p, semilla=0, parada=None):
    """Simula el resto del turno partiendo del estado actual de la línea.
    parada = (estacion, minutos_parada, media_despues) o None."""
    rng = np.random.default_rng(semilla)
    env = simpy.Environment()
    recursos = {e: simpy.PriorityResource(env, capacity=p["maquinas"][e]) for e in ESTACIONES}
    producidas = [estado["producidas"]]
    curva = []
    fin_parada = {}

    def media(e):
        if parada and e == parada[0] and e in fin_parada and env.now >= fin_parada[e]:
            return parada[2]
        return p["tiempos"][e]

    def botella(desde, restante=None):
        for e in ESTACIONES[ESTACIONES.index(desde):]:
            with recursos[e].request(priority=1) as turno:
                yield turno
                t = muestrear_tiempo(media(e), p["cv"][e], p["distribuciones"][e], rng)
                if restante is not None:
                    t, restante = max(0.05, restante), None
                yield env.timeout(t)
        producidas[0] += 1

    def detener(e, duracion):
        turnos = [recursos[e].request(priority=0) for _ in range(p["maquinas"][e])]
        yield env.all_of(turnos)
        yield env.timeout(duracion)
        fin_parada[e] = env.now
        for t in turnos:
            recursos[e].release(t)

    def llegadas():
        while True:
            yield env.timeout(rng.exponential(60 / p["demanda"]))
            env.process(botella(ESTACIONES[0]))

    def monitor():
        while True:
            curva.append((estado["minuto"] + env.now, producidas[0]))
            yield env.timeout(5)

    for e, transcurrido in estado["en_servicio"]:
        t = muestrear_tiempo(p["tiempos"][e], p["cv"][e], p["distribuciones"][e], rng)
        env.process(botella(e, restante=t - transcurrido))
    if parada:
        env.process(detener(parada[0], parada[1]))
    for e in ESTACIONES:
        for _ in range(estado["colas"][e]):
            env.process(botella(e))
    env.process(llegadas())
    env.process(monitor())

    horizonte = FIN_TURNO - estado["minuto"]
    if horizonte > 0:
        env.run(until=horizonte)
    curva.append((FIN_TURNO, producidas[0]))
    return producidas[0], curva


def proyectar(estado, cambios=None, parada=None, replicas=30, meta=META):
    """Corre varias réplicas desde el estado actual y resume la incertidumbre."""
    p = copy.deepcopy(BASE)
    p["tiempos"].update(estado["tiempos"])
    p["maquinas"].update(estado["maquinas"])
    for e, n in (cambios or {}).get("maquinas", {}).items():
        p["maquinas"][e] = n
    if parada is None and estado["parada"]:
        e, restante = estado["parada"]
        parada = (e, restante, BASE["tiempos"][e])

    finales, curvas = [], []
    for r in range(replicas):
        final, curva = simular_desde(estado, p, semilla=r, parada=parada)
        finales.append(final)
        curvas.append(pd.Series(dict(curva), name=r))
    curvas = pd.concat(curvas, axis=1).ffill()
    finales = np.array(finales)
    return {
        "finales": finales,
        "mediana": float(np.median(finales)),
        "p10": float(np.percentile(finales, 10)),
        "p90": float(np.percentile(finales, 90)),
        "prob_meta": float((finales >= meta).mean()),
        "banda": pd.DataFrame({"p10": curvas.quantile(0.10, axis=1),
                               "p50": curvas.quantile(0.50, axis=1),
                               "p90": curvas.quantile(0.90, axis=1)}),
    }


ACCIONES = {
    "No hacer nada": None,
    "Abrir 2.ª etiquetadora": {"tipo": "abrir_maquina", "estacion": "etiquetado"},
    "Mantenimiento etiquetadora (30 min)": {"tipo": "mantenimiento", "estacion": "etiquetado", "duracion": 30},
    "Abrir 2.ª empaquetadora": {"tipo": "abrir_maquina", "estacion": "empaquetado"},
    "Abrir 2.ª llenadora": {"tipo": "abrir_maquina", "estacion": "llenado"},
}


def evaluar_acciones(estado, replicas=30):
    filas = []
    for nombre, acc in ACCIONES.items():
        cambios, parada = None, None
        if acc and acc["tipo"] == "abrir_maquina":
            if estado["maquinas"][acc["estacion"]] >= MAX_MAQUINAS:
                continue
            cambios = {"maquinas": {acc["estacion"]: estado["maquinas"][acc["estacion"]] + 1}}
        elif acc and acc["tipo"] == "mantenimiento":
            parada = (acc["estacion"], acc["duracion"], BASE["tiempos"][acc["estacion"]])
        r = proyectar(estado, cambios, parada, replicas)
        filas.append({"Acción": nombre, "Prob. meta": r["prob_meta"], "Mediana": r["mediana"],
                      "P10": r["p10"], "P90": r["p90"], "orden": acc, "proyeccion": r})
    return (pd.DataFrame(filas)
            .sort_values(["Prob. meta", "Mediana"], ascending=False)
            .reset_index(drop=True))


def enviar_orden(libro, orden, motivo=""):
    """Flujo gemelo → planta: escribe una fila 'pendiente' en la pestaña ordenes."""
    orden_id = "G-" + datetime.now(ZONA).strftime("%H%M%S")
    fila = [ahora(), orden_id, "gemelo", orden["tipo"], orden["estacion"],
            orden.get("duracion", ""), "pendiente", "", motivo]
    con_reintentos(libro.worksheet("ordenes").append_rows, [fila],
                   insert_data_option=InsertDataOption.insert_rows, table_range="A1")
    return orden_id


def hay_pendientes(ordenes):
    return bool(len(ordenes)) and (ordenes["estado"].astype(str).str.lower() == "pendiente").any()


SISTEMA_ALERTA = """
Eres el sistema de alertas de un gemelo digital de una línea de botellas. Escribes al supervisor de turno.
- Español, máximo 4 líneas, tono directo.
- Usa SOLO las cifras del diagnóstico. No inventes números.
- Di qué está pasando, en qué estación, qué pasará si no se actúa y qué acción recomiendas con su probabilidad.
"""


def diagnosticar(estado, proy, ranking, meta=META):
    critica = max(ESTACIONES, key=lambda e: estado["desvio"][e])
    return {
        "hora_turno": round(estado["minuto"] / 60, 1),
        "producidas": estado["producidas"],
        "meta": meta,
        "proyeccion_cierre": f"{proy['mediana']:.0f} (banda 80%: {proy['p10']:.0f}-{proy['p90']:.0f})",
        "probabilidad_meta": f"{proy['prob_meta']:.0%}",
        "estacion_critica": critica,
        "desvio_tiempo_ciclo": f"{estado['desvio'][critica]:+.0f}%",
        "cola_actual": estado["colas"][critica],
        "acciones": [f"{r['Acción']}: {r['Prob. meta']:.0%}, {r['Mediana']:.0f} botellas"
                     for _, r in ranking.iterrows()],
    }


def redactar_alerta(diag, client=None, modelo="gpt-4o-mini"):
    if client is None:
        return (f"Hora {diag['hora_turno']}: {diag['estacion_critica']} va {diag['desvio_tiempo_ciclo']} "
                f"sobre el plan y tiene {diag['cola_actual']} botellas en cola. Al ritmo actual cerramos en "
                f"{diag['proyeccion_cierre']} vs. meta {diag['meta']} (probabilidad {diag['probabilidad_meta']}). "
                f"Recomendación: {diag['acciones'][0]}.")
    r = client.chat.completions.create(
        model=modelo,
        messages=[{"role": "system", "content": SISTEMA_ALERTA},
                  {"role": "user", "content": str(diag)}])
    return r.choices[0].message.content


class AgenteGemelo:
    """Ciclo del gemelo en un hilo del servidor. Lee el Sheet UNA vez por ciclo para todos
    los que estén mirando la app, así no se agota la cuota de la cuenta de servicio."""

    def __init__(self, libro, leer_cada=5, umbral=0.5, replicas=30, espera_entre_ordenes=60,
                 autonomo=True, client=None, modelo="gpt-4o-mini"):
        self.libro = libro
        self.leer_cada, self.umbral, self.replicas = leer_cada, umbral, replicas
        self.espera_entre_ordenes = espera_entre_ordenes
        self.autonomo = autonomo
        self.client, self.modelo = client, modelo
        self.lock = threading.Lock()
        self.foto = None            # último análisis completo, listo para dibujar
        self.bitacora = []
        self.error = None
        self.ultima_lectura = None
        self._reiniciar()
        threading.Thread(target=self._bucle, daemon=True).start()

    def _reiniciar(self):
        self.lector, self.gemelo = LectorSheet(self.libro), Gemelo()
        self.ultima_orden = self.ultima_alerta = -1e9
        self.ranking = self.ranking_hora = None

    def enviar(self, orden, motivo):
        oid = enviar_orden(self.libro, orden, motivo)
        with self.lock:
            self.bitacora.append(f"Hora {self.gemelo.minuto / 60:.1f} · orden {oid} enviada: "
                                 f"{orden['tipo']} en {orden['estacion']} ({motivo})")
            self.ultima_orden = self.gemelo.minuto
        return oid

    def _bucle(self):
        while True:
            inicio = time.time()
            try:
                self._ciclo()
                self.error = None
            except Exception as error:  # se muestra en la app y se reintenta
                self.error = f"{type(error).__name__}: {error}"
            time.sleep(max(0.5, self.leer_cada - (time.time() - inicio)))

    def _ciclo(self):
        lectura = self.lector.leer()
        self.ultima_lectura = ahora()
        if lectura["nuevo_turno"]:
            self.gemelo = Gemelo()
            self.ultima_orden = self.ultima_alerta = -1e9
            self.ranking = self.ranking_hora = None
            with self.lock:
                self.bitacora = ["Nuevo turno detectado"]
        self.gemelo.recibir(lectura)

        if self.gemelo.minuto <= 0 or self.gemelo.eventos.empty:
            with self.lock:
                self.foto = {"esperando": True, "ordenes": lectura["ordenes"],
                             "turno": self.lector.turno_id, "estado_planta": self.gemelo.estado_planta}
            return

        estado = self.gemelo.estado()
        proy = proyectar(estado, replicas=self.replicas)
        abierto = self.gemelo.estado_planta == "operando"
        pendiente = hay_pendientes(lectura["ordenes"])

        if abierto and proy["prob_meta"] < self.umbral:
            self.ranking = evaluar_acciones(estado, self.replicas)
            self.ranking_hora = self.gemelo.minuto / 60
            mejor = self.ranking.iloc[0]
            ultima = max(self.ultima_orden, self.ultima_alerta)
            if (mejor["orden"] is not None and not pendiente
                    and self.gemelo.minuto - ultima >= self.espera_entre_ordenes):
                alerta = redactar_alerta(diagnosticar(estado, proy, self.ranking), self.client, self.modelo)
                with self.lock:
                    self.bitacora.append(alerta)
                if self.autonomo:
                    self.enviar(mejor["orden"], f"P(meta) {mejor['Prob. meta']:.0%}")
                else:
                    with self.lock:
                        self.bitacora.append("Modo manual: el supervisor decide la orden.")
                    self.ultima_alerta = self.gemelo.minuto

        with self.lock:
            self.foto = {
                "esperando": False, "turno": self.lector.turno_id, "estado": estado, "proy": proy,
                "gemelo": copy.deepcopy(self.gemelo), "ranking": self.ranking,
                "ranking_hora": self.ranking_hora,
                "ordenes": lectura["ordenes"], "pendiente": pendiente,
                "estado_planta": self.gemelo.estado_planta, "filas": self.lector.filas_telemetria,
            }
