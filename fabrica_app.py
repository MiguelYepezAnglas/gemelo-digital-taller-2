"""
Gemelo Digital · App 1: LA FÁBRICA (planta física simulada → Google Sheet)

Ejecutar:  streamlit run fabrica_app.py
"""
import plotly.graph_objects as go
import streamlit as st

from nucleo.modelo import BASE, ESTACIONES, FIN_TURNO
from nucleo.planta import Fabrica
from nucleo.sheets import conectar, es_operador, url_del_sheet
from nucleo.viz import COLORES, TINTA

st.set_page_config(page_title="Fábrica · Línea de botellas", page_icon="🏭", layout="wide")


@st.cache_resource
def obtener_fabrica(url):
    """Una sola fábrica por servidor, aunque la app la abran varias personas."""
    return Fabrica(conectar(url))


url = url_del_sheet()
fabrica = obtener_fabrica(url)

# ---- Barra lateral: controles del operador -------------------------------------
with st.sidebar:
    st.header("Panel del operador")
    operador = es_operador()
    semilla = st.number_input("Semilla del turno", 0, 9999, 8, disabled=fabrica.activa)
    desgaste = st.toggle("Desgaste oculto en etiquetado", True, disabled=fabrica.activa,
                         help="El secreto de la planta: el rodillo se desgasta entre la hora 1.5 y la 3.5.")
    velocidad = st.select_slider("Velocidad", options=[2.0, 1.0, 0.5], value=1.0, disabled=fabrica.activa,
                                 format_func=lambda s: f"1 min de planta = {s:g} s reales")
    c1, c2 = st.columns(2)
    if c1.button("▶ Iniciar turno", type="primary", disabled=fabrica.activa or not operador,
                 width="stretch"):
        fabrica.iniciar(semilla=int(semilla), desgaste=desgaste, segundos_por_minuto=velocidad)
        st.rerun()
    if c2.button("■ Detener", disabled=not fabrica.activa or not operador, width="stretch"):
        fabrica.detener()
        st.rerun()
    if not operador:
        st.caption("Escribe la clave de operador para controlar la fábrica.")
    st.divider()
    st.markdown(f"[Abrir el Google Sheet]({url})")
    st.caption("Al iniciar un turno se borran las pestañas `telemetria`, `estado` y `ordenes`.")

st.title("🏭 Fábrica · línea de botellas")
st.caption("Esta app hace de planta física: produce, envía telemetría al Google Sheet cada 5 s "
           "y ejecuta las órdenes que aparezcan en la pestaña `ordenes`.")


@st.fragment(run_every="1s")
def panel():
    # Si el turno arranca o termina, refresca toda la app para actualizar los botones
    if st.session_state.get("activa") != fabrica.activa:
        cambio = "activa" in st.session_state
        st.session_state.activa = fabrica.activa
        if cambio:
            st.rerun(scope="app")
    if fabrica.error:
        st.error(f"La fábrica se detuvo por un error: {fabrica.error}")
    planta = fabrica.planta
    if planta is None:
        st.info("Fábrica apagada. Inicia un turno desde la barra lateral.")
        return

    estado_txt = {"operando": "🟢 Operando", "fin de turno": "⚪ Turno terminado",
                  "detenida": "⏸ Detenida", "error": "🔴 Error"}.get(fabrica.estado_planta, fabrica.estado_planta)
    st.markdown(f"**{estado_txt}** · turno `{fabrica.turno_id}` · último envío al Sheet: {fabrica.ultimo_envio or '—'}")
    st.progress(min(1.0, planta.minuto / FIN_TURNO),
                text=f"Hora {planta.minuto / 60:.1f} de {FIN_TURNO / 60:.0f}")

    f = planta.foto()
    c = st.columns(5)
    c[0].metric("Llegaron", f["llegadas"])
    c[1].metric("Terminadas", f["terminadas"])
    for i, e in enumerate(ESTACIONES, start=2):
        c[i].metric(f"Cola {e}", f["colas"][e], help=f"{f['maquinas'][e]} máquina(s) activas")

    izq, der = st.columns([3, 2])
    with izq:
        fig = go.Figure(go.Bar(
            x=[e.capitalize() for e in ESTACIONES], y=[f["colas"][e] for e in ESTACIONES],
            marker=dict(color=[COLORES[e] for e in ESTACIONES], cornerradius=4),
            text=[f"{f['colas'][e]} en cola · {f['maquinas'][e]} máq." for e in ESTACIONES],
            textposition="outside", textfont=dict(color=TINTA["primaria"]),
            hovertemplate="%{x}: %{y} botellas<extra></extra>"))
        fig.update_layout(title="Botellas esperando ahora", height=320,
                          yaxis=dict(title="botellas", rangemode="tozero",
                                     range=[0, max(10, *f["colas"].values()) * 1.25]))
        st.plotly_chart(fig, theme=None, width="stretch", key="colas_fabrica")
    with der:
        st.markdown("##### 🔒 Lo que el gemelo **no** ve")
        medias = planta.medias_reales()
        for e in ESTACIONES:
            delta = 100 * (medias[e] / BASE["tiempos"][e] - 1)
            st.metric(f"Tiempo real de {e}", f"{medias[e]:.2f} min",
                      f"{delta:+.0f}% vs. plan" if abs(delta) >= 0.5 else "igual al plan",
                      delta_color="inverse")
        st.caption("Estos valores nunca se escriben en el Sheet: el gemelo los tiene que deducir.")

    st.markdown("##### Bitácora de la planta")
    if fabrica.bitacora:
        for linea in fabrica.bitacora:
            st.write("▸", linea)
    else:
        st.caption("Sin órdenes recibidas todavía.")


panel()
