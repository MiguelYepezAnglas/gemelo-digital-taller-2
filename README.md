# Gemelo digital en vivo · línea de botellas

Dos apps de Streamlit que **solo se comunican por un Google Sheet**:

| App | Archivo | Qué hace |
|---|---|---|
| 🏭 Fábrica | `fabrica_app.py` | Planta simulada con un desgaste oculto. Escribe telemetría cada 5 s y ejecuta las órdenes de la pestaña `ordenes`. |
| 🧠 Gemelo | `gemelo_app.py` | Lee el Sheet, reconstruye el estado real, proyecta el turno (30 réplicas) y, si la meta peligra, prueba acciones y envía la mejor. |

```
fabrica_app.py ──► telemetria / estado ──► gemelo_app.py
      ▲                                         │
      └────────────── ordenes ◄─────────────────┘
```

## 1. Google Cloud (una sola vez)

1. En el proyecto de tu cuenta de servicio, activa la **Google Sheets API** (APIs y servicios → Biblioteca).
2. Crea un Google Sheet en blanco y **compártelo como Editor** con el `client_email` de la cuenta de servicio.
   No hace falta crear pestañas: la fábrica las crea al iniciar el turno.

## 2. Secrets

Usa el formato de `.streamlit/secrets.toml.example`. Las claves `sheet_url`, `clave_operador` y `OPENAI_API_KEY` van **arriba**, antes de `[gcp_service_account]`.

- **En Streamlit Cloud:** App settings → Secrets, en **las dos apps** (mismo contenido).
- **En local:** copia el ejemplo como `.streamlit/secrets.toml` (está en `.gitignore`, no se sube al repo).

## 3. Desplegar

En Streamlit Cloud crea **dos apps desde el mismo repo**, cambiando solo el *Main file path*:
- `fabrica_app.py` → la abre el operador (tú).
- `gemelo_app.py` → la URL que compartes con los alumnos.

En local, en dos terminales:

```bash
pip install -r requirements.txt
streamlit run fabrica_app.py --server.port 8501
streamlit run gemelo_app.py --server.port 8502
```

## 4. Usar en el taller

1. Abre el gemelo: mostrará "Esperando datos de la planta…".
2. En la fábrica, escribe la clave de operador y pulsa **▶ Iniciar turno** (8 minutos reales con la velocidad por defecto).
3. Hacia la hora 2.5–3 el gemelo detecta la deriva en etiquetado, la probabilidad de meta cae y:
   - **Modo autónomo:** envía la orden solo.
   - **Modo manual:** alerta, y la orden la envías tú desde la barra lateral o la escribes a mano en la pestaña `ordenes` (`tipo = abrir_maquina | mantenimiento`, `estacion`, `estado = pendiente`).

## Notas

- **Cuota de la API:** 60 lecturas y 60 escrituras por minuto por usuario. La fábrica usa unas 24 escrituras y 12 lecturas por minuto, y el gemelo 12 lecturas, **sin importar cuántas personas lo miren**: el ciclo del gemelo corre una sola vez en el servidor.
- **Ciclos en el servidor:** fábrica y gemelo corren en hilos del servidor. Siguen aunque cierres la pestaña, pero Streamlit Cloud duerme las apps sin visitas: ábrelas unos minutos antes del taller.
- Iniciar un turno **borra** las pestañas del turno anterior.
