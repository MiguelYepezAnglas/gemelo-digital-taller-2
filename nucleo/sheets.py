"""Conexión con Google Sheets usando la cuenta de servicio guardada en st.secrets."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import streamlit as st
from gspread.utils import InsertDataOption, ValueRenderOption  # noqa: F401  (se reexportan)

ZONA = ZoneInfo("America/Lima")

# Una pestaña por flujo de datos
ESQUEMA = {
    "telemetria": ["marca_tiempo", "minuto_turno", "evento", "estacion", "botella_id", "detalle"],
    "estado": ["turno_id", "marca_tiempo", "minuto_turno", "llegadas", "terminadas",
               "cola_llenado", "cola_etiquetado", "cola_empaquetado",
               "maq_llenado", "maq_etiquetado", "maq_empaquetado", "estado_planta"],
    "ordenes": ["marca_tiempo", "orden_id", "origen", "tipo", "estacion", "duracion_min",
                "estado", "minuto_aplicada", "comentario"],
}

_EXTRAS = ("sheet_url", "clave_operador", "OPENAI_API_KEY")


def ahora():
    return datetime.now(ZONA).strftime("%Y-%m-%d %H:%M:%S")


def con_reintentos(funcion, *args, intentos=5, **kwargs):
    """Si Google responde 429 (cuota) o un error temporal, espera y reintenta."""
    for i in range(intentos):
        try:
            return funcion(*args, **kwargs)
        except gspread.exceptions.APIError:
            if i == intentos - 1:
                raise
            time.sleep(2 ** i)


def secreto(nombre, defecto=None):
    """Busca un valor en la raíz de los secrets o, por si quedó ahí, dentro de [gcp_service_account]."""
    try:
        if nombre in st.secrets:
            return st.secrets[nombre]
        return st.secrets.get("gcp_service_account", {}).get(nombre, defecto)
    except FileNotFoundError:
        return defecto


def credenciales():
    if "gcp_service_account" not in st.secrets:
        raise RuntimeError("Falta la sección [gcp_service_account] en los Secrets de Streamlit.")
    info = {k: v for k, v in dict(st.secrets["gcp_service_account"]).items() if k not in _EXTRAS}
    info["private_key"] = info["private_key"].replace("\\n", "\n")
    return info


@st.cache_resource(show_spinner="Conectando con Google Sheets…")
def conectar(url):
    cliente = gspread.service_account_from_dict(credenciales())
    return cliente.open_by_url(url)


def url_del_sheet():
    url = secreto("sheet_url")
    if not url:
        url = st.sidebar.text_input("URL del Google Sheet", placeholder="https://docs.google.com/spreadsheets/d/…")
    if not url:
        st.info("Agrega `sheet_url` en los Secrets (o pega la URL en la barra lateral) para empezar.")
        st.stop()
    return url


def es_operador():
    """Si definiste `clave_operador` en Secrets, solo quien la escriba puede controlar."""
    clave = secreto("clave_operador")
    if not clave:
        return True
    return st.sidebar.text_input("Clave de operador", type="password") == clave
