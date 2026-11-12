"""La planta "real": SimPy + desgaste oculto. Solo se comunica con el exterior por el Sheet."""
import threading
import time
from datetime import datetime

import numpy as np
import simpy

from nucleo.modelo import BASE, ESTACIONES, FIN_TURNO, MAX_MAQUINAS, muestrear_tiempo
from nucleo.sheets import ESQUEMA, ZONA, InsertDataOption, ValueRenderOption, ahora, con_reintentos


def preparar_hoja(libro):
    """Crea las pestañas que falten, escribe cabeceras y borra el turno anterior."""
    existentes = {ws.title: ws for ws in libro.worksheets()}
    hojas = {}
    for nombre, cabeceras in ESQUEMA.items():
        ws = existentes.get(nombre) or con_reintentos(
            libro.add_worksheet, title=nombre, rows=2000, cols=len(cabeceras))
        con_reintentos(ws.batch_clear, ["A:Z"])
        con_reintentos(ws.update, values=[cabeceras], range_name="A1")
        hojas[nombre] = ws
    return hojas


class PlantaFisica:
    """La planta 'real'. Sus parámetros nunca salen de este notebook: solo sus eventos."""

    def __init__(self, semilla=8, desgaste=True):
        self.rng = np.random.default_rng(semilla)
        self.env = simpy.Environment()
        self.desgaste = desgaste
        self.reparada = set()
        self.maquinas = dict(BASE["maquinas"])
        self.recursos = {e: simpy.PriorityResource(self.env, capacity=MAX_MAQUINAS) for e in ESTACIONES}
        self.bloqueos = {e: [] for e in ESTACIONES}
        for e in ESTACIONES:
            for _ in range(MAX_MAQUINAS - self.maquinas[e]):
                self.bloqueos[e].append(self.recursos[e].request(priority=-1))
        self.eventos, self.enviados, self.siguiente_id = [], 0, 0
        self.llegadas, self.terminadas = 0, 0
        self.env.process(self._llegadas())

    def _media_real(self, e):
        media = BASE["tiempos"][e]
        if e == "etiquetado" and self.desgaste and e not in self.reparada:
            # Secreto de la planta: el rodillo se desgasta entre la hora 1.5 y la 3.5
            avance = min(1.0, max(0.0, (self.env.now - 90) / 120))
            media *= 1 + 0.35 * avance
        return media

    def _registrar(self, evento, estacion="", botella="", detalle=""):
        self.eventos.append([round(self.env.now, 2), evento, estacion, botella, detalle])

    def _llegadas(self):
        while True:
            yield self.env.timeout(self.rng.exponential(60 / BASE["demanda"]))
            self.siguiente_id += 1
            self.llegadas += 1
            self._registrar("llegada", botella=self.siguiente_id)
            self.env.process(self._botella(self.siguiente_id))

    def _botella(self, bid):
        for e in ESTACIONES:
            with self.recursos[e].request(priority=1) as turno:
                yield turno
                self._registrar("inicio", e, bid)
                yield self.env.timeout(muestrear_tiempo(
                    self._media_real(e), BASE["cv"][e], BASE["distribuciones"][e], self.rng))
                self._registrar("fin", e, bid)
        self.terminadas += 1

    def _mantenimiento(self, e, duracion):
        turnos = [self.recursos[e].request(priority=0) for _ in range(self.maquinas[e])]
        yield self.env.all_of(turnos)
        self._registrar("parada_inicio", e, detalle=f"mantenimiento {duracion:.0f} min")
        yield self.env.timeout(duracion)
        self.reparada.add(e)
        for t in turnos:
            self.recursos[e].release(t)
        self._registrar("parada_fin", e)

    @property
    def minuto(self):
        return self.env.now

    def avanzar(self, minutos):
        self.env.run(until=min(FIN_TURNO, self.env.now + minutos))
        nuevos = self.eventos[self.enviados:]
        self.enviados = len(self.eventos)
        return nuevos

    def medias_reales(self):
        """El secreto de la planta: tiempo medio real de cada estación en este instante."""
        return {e: self._media_real(e) for e in ESTACIONES}

    def foto(self):
        """Lo que mostraría el panel del SCADA en este instante."""
        colas = {e: sum(1 for r in self.recursos[e].queue if r.priority == 1) for e in ESTACIONES}
        return {"llegadas": self.llegadas, "terminadas": self.terminadas, "colas": colas,
                "maquinas": dict(self.maquinas)}

    def aplicar(self, tipo, estacion, duracion=30):
        if estacion not in ESTACIONES:
            raise ValueError(f"estación desconocida: {estacion!r}")
        if tipo == "abrir_maquina":
            if self.maquinas[estacion] >= MAX_MAQUINAS:
                raise ValueError(f"{estacion} ya tiene {MAX_MAQUINAS} máquinas")
            self.recursos[estacion].release(self.bloqueos[estacion].pop())
            self.maquinas[estacion] += 1
            self._registrar("accion", estacion, detalle=f"abre máquina ({self.maquinas[estacion]} activas)")
        elif tipo == "mantenimiento":
            duracion = float(duracion or 30)
            if not 5 <= duracion <= 120:
                raise ValueError("duración de mantenimiento fuera de rango (5 a 120 min)")
            self._registrar("accion", estacion, detalle=f"inicia mantenimiento {duracion:.0f} min")
            self.env.process(self._mantenimiento(estacion, duracion))
        else:
            raise ValueError(f"tipo de orden desconocido: {tipo!r}")


def publicar(hojas, planta, telemetria, turno_id, estado_planta="operando"):
    """Envía al Sheet la telemetría acumulada y una foto del estado (2 escrituras)."""
    marca = ahora()
    if telemetria:
        filas = [[marca, *ev] for ev in telemetria]
        con_reintentos(hojas["telemetria"].append_rows, filas,
                       insert_data_option=InsertDataOption.insert_rows, table_range="A1")
    f = planta.foto()
    fila = [turno_id, marca, round(planta.minuto, 1), f["llegadas"], f["terminadas"],
            *[f["colas"][e] for e in ESTACIONES], *[f["maquinas"][e] for e in ESTACIONES], estado_planta]
    con_reintentos(hojas["estado"].append_rows, [fila],
                   insert_data_option=InsertDataOption.insert_rows, table_range="A1")
    return f


def atender_ordenes(hojas, planta):
    """Lee la pestaña 'ordenes' y ejecuta las pendientes (1 lectura + 1 escritura si hay)."""
    filas = con_reintentos(hojas["ordenes"].get, "A2:I",
                           value_render_option=ValueRenderOption.unformatted) or []
    cambios, aplicadas = [], []
    for i, fila in enumerate(filas, start=2):
        fila = list(fila) + [""] * (9 - len(fila))
        if str(fila[6]).strip().lower() != "pendiente":
            continue
        tipo, estacion, duracion = str(fila[3]).strip(), str(fila[4]).strip().lower(), fila[5]
        try:
            planta.aplicar(tipo, estacion, duracion)
            resultado = ["aplicada", round(planta.minuto, 1), fila[8]]
            aplicadas.append(f"{tipo} en {estacion}")
        except Exception as error:
            resultado = ["rechazada", "", str(error)]
        cambios.append({"range": f"G{i}:I{i}", "values": [resultado]})
    if cambios:
        con_reintentos(hojas["ordenes"].batch_update, cambios)
    return aplicadas


class Fabrica:
    """Corre el turno en un hilo del servidor: sigue aunque cierres la pestaña.
    1 minuto de planta cada `segundos_por_minuto`; envía al Sheet cada `enviar_cada` segundos."""

    def __init__(self, libro):
        self.libro = libro
        self.hilo = None
        self.parar_evento = threading.Event()
        self.planta = None
        self.turno_id = None
        self.bitacora = []
        self.error = None
        self.ultimo_envio = None
        self.estado_planta = "apagada"

    @property
    def activa(self):
        return self.hilo is not None and self.hilo.is_alive()

    def iniciar(self, semilla=8, desgaste=True, segundos_por_minuto=1.0, enviar_cada=5):
        if self.activa:
            return
        self.parar_evento.clear()
        self.error, self.bitacora = None, []
        self.hilo = threading.Thread(target=self._correr, daemon=True,
                                     args=(semilla, desgaste, segundos_por_minuto, enviar_cada))
        self.hilo.start()

    def detener(self):
        self.parar_evento.set()

    def _correr(self, semilla, desgaste, segundos_por_minuto, enviar_cada):
        try:
            hojas = preparar_hoja(self.libro)
            self.turno_id = "T-" + datetime.now(ZONA).strftime("%Y%m%d-%H%M%S")
            self.planta = planta = PlantaFisica(semilla, desgaste)
            self.estado_planta = "operando"
            publicar(hojas, planta, [], self.turno_id)
            pendiente, ultimo = [], time.time()

            while planta.minuto < FIN_TURNO and not self.parar_evento.is_set():
                inicio = time.time()
                pendiente += planta.avanzar(1)
                if time.time() - ultimo >= enviar_cada or planta.minuto >= FIN_TURNO:
                    self.estado_planta = "fin de turno" if planta.minuto >= FIN_TURNO else "operando"
                    publicar(hojas, planta, pendiente, self.turno_id, self.estado_planta)
                    pendiente, ultimo = [], time.time()
                    self.ultimo_envio = ahora()
                    for orden in atender_ordenes(hojas, planta):
                        self.bitacora.append(f"Hora {planta.minuto / 60:.1f} · orden aplicada: {orden}")
                time.sleep(max(0.0, segundos_por_minuto - (time.time() - inicio)))

            if self.parar_evento.is_set():
                self.estado_planta = "detenida"
                publicar(hojas, planta, pendiente, self.turno_id, "detenida")
                self.bitacora.append(f"Hora {planta.minuto / 60:.1f} · turno detenido por el operador")
        except Exception as error:  # se muestra en la app
            self.error = f"{type(error).__name__}: {error}"
            self.estado_planta = "error"
