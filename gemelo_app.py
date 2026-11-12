"""
Gemelo Digital · App 2: EL GEMELO (Google Sheet → sincroniza, proyecta, decide, ordena)

Ejecutar:  streamlit run gemelo_app.py
"""
import pandas as pd
import streamlit as st

from nucleo.gemelo import ACCIONES, AgenteGemelo, hay_pendientes
from nucleo.modelo import ESTACIONES, FIN_TURNO, META
from nucleo.sheets import conectar, es_operador, secreto, url_del_sheet
from nucleo.viz import ESTADO, fig_colas, fig_decision, fig_linea, fig_proyeccion, fig_tiempos

st.set_page_config(page_title="Gemelo digital · Línea de botellas", page_icon="🧠", layout="wide")


@st.cache_resource
def obtener_agente(url):
    """Un solo ciclo del gemelo por servidor: lee el Sheet una vez para todos los espectadores."""
    client = None
    clave_ia = secreto("OPENAI_API_KEY")
    if clave_ia:
        from openai import OpenAI
        client = OpenAI(api_key=clave_ia)
    return AgenteGemelo(conectar(url), client=client)


url = url_del_sheet()
agente = obtener_agente(url)

# ---- Barra lateral ------------------------------------------------------------
with st.sidebar:
    st.header("Control del gemelo")
    operador = es_operador()
    autonomo = st.toggle("Modo autónomo", agente.autonomo, disabled=not operador,
                         help="Encendido: si la meta peligra, el gemelo envía la orden solo. "
                              "Apagado: solo alerta y decide una persona.")
    if operador and autonomo != agente.autonomo:
        agente.autonomo = autonomo

    st.subheader("Orden manual")
    accion = st.selectbox("Acción", [a for a in ACCIONES if ACCIONES[a]], disabled=not operador)
    if st.button("Enviar orden a la planta", disabled=not operador, width="stretch"):
        foto = agente.foto or {}
        if foto.get("ordenes") is not None and hay_pendientes(foto["ordenes"]):
            st.warning("Ya hay una orden pendiente. Espera a que la fábrica la aplique.")
        else:
            oid = agente.enviar(ACCIONES[accion], "enviada por el supervisor")
            st.success(f"Orden {oid} enviada.")
    if not operador:
        st.caption("Escribe la clave de operador para cambiar el modo o enviar órdenes.")
    st.divider()
    st.markdown(f"[Abrir el Google Sheet]({url})")
    st.caption(f"IA para alertas: {'activada' if agente.client else 'sin clave (usa plantilla)'}")

st.title("🧠 Gemelo digital · línea de botellas")
st.caption("No ve la planta: solo lo que llega al Google Sheet. Sincroniza el estado real, proyecta el "
           "turno con 30 réplicas y, si la meta peligra, prueba acciones en simulación antes de ordenarlas.")


def nivel(prob):
    return "ok" if prob >= 0.8 else "atencion" if prob >= 0.5 else "critico"


@st.fragment(run_every="3s")
def tablero():
    if agente.error:
        st.error(f"Problema leyendo el Sheet (se reintenta solo): {agente.error}")
    foto = agente.foto
    if foto is None:
        st.info("Conectando con el Sheet…")
        return
    if foto["esperando"]:
        st.info("Esperando datos de la planta… ¿está corriendo la app de la fábrica?")
        return

    estado, proy, gemelo = foto["estado"], foto["proy"], foto["gemelo"]
    color, icono, texto = ESTADO[nivel(proy["prob_meta"])]
    mensaje = (f"{icono} **{texto}** · probabilidad de llegar a la meta de {META} botellas: "
               f"**{proy['prob_meta']:.0%}** · planta: {foto['estado_planta']} · "
               f"última lectura {agente.ultima_lectura} · turno `{foto['turno']}`")
    {"ok": st.success, "atencion": st.warning, "critico": st.error}[nivel(proy["prob_meta"])](mensaje)

    cuello = max(ESTACIONES, key=lambda e: estado["colas"][e])
    c = st.columns(5)
    c[0].metric("Hora del turno", f"{estado['minuto'] / 60:.1f} h", f"de {FIN_TURNO / 60:.0f} h", delta_color="off")
    c[1].metric("Terminadas", estado["producidas"], f"llegaron {estado['llegadas']}", delta_color="off")
    c[2].metric("Proyección al cierre", f"{proy['mediana']:.0f}",
                f"banda 80%: {proy['p10']:.0f}–{proy['p90']:.0f}", delta_color="off")
    c[3].metric("Prob. de meta", f"{proy['prob_meta']:.0%}", f"{icono} {texto}", delta_color="off")
    c[4].metric("Mayor cola", cuello.capitalize(), f"{estado['colas'][cuello]} botellas", delta_color="off")

    st.plotly_chart(fig_linea(estado), theme=None, width="stretch", key="linea")

    ranking = foto["ranking"]
    en_riesgo = foto["estado_planta"] == "operando" and proy["prob_meta"] < 0.5
    alternativa = ranking.iloc[0] if ranking is not None and en_riesgo else None
    st.plotly_chart(
        fig_proyeccion(gemelo, proy,
                       alternativa=alternativa["proyeccion"] if alternativa is not None else None,
                       nombre_alt=alternativa["Acción"] if alternativa is not None else None),
        theme=None, width="stretch", key="proyeccion")

    t1, t2, t3, t4 = st.tabs(["📡 Sensores", "🧪 Decisión", "📋 Órdenes", "📝 Bitácora"])
    with t1:
        st.plotly_chart(fig_tiempos(gemelo), theme=None, width="stretch", key="tiempos")
        st.plotly_chart(fig_colas(gemelo), theme=None, width="stretch", key="colas")
    with t2:
        if ranking is None:
            st.info("El gemelo evalúa acciones cuando la probabilidad de meta cae bajo 50 %.")
        else:
            st.caption(f"Última evaluación: hora {foto['ranking_hora']:.1f} del turno.")
            st.plotly_chart(fig_decision(ranking), theme=None, width="stretch", key="decision")
    with t3:
        ordenes = foto["ordenes"]
        if len(ordenes):
            st.dataframe(ordenes, hide_index=True, width="stretch")
        else:
            st.caption("Sin órdenes en este turno.")
    with t4:
        with agente.lock:
            lineas = list(agente.bitacora)
        if lineas:
            for linea in reversed(lineas):
                st.write("▸", linea)
        else:
            st.caption("Sin alertas todavía.")


tablero()
