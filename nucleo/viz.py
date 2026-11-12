"""Gráficos Plotly con paleta validada (daltonismo y contraste)."""
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

from nucleo.modelo import BASE, ESTACIONES, META, FIN_TURNO

# Paleta validada (daltonismo y contraste) · superficie clara
TINTA = {"primaria": "#0b0b0b", "secundaria": "#52514e", "tenue": "#898781",
         "grilla": "#e1e0d9", "eje": "#c3c2b7", "fondo": "#fcfcfb"}
COLORES = {"llenado": "#2a78d6", "etiquetado": "#eb6834", "empaquetado": "#1baf7a"}
ESTADO = {"ok": ("#0ca30c", "●", "Normal"), "atencion": ("#fab219", "▲", "Atención"),
          "critico": ("#d03b3b", "■", "Crítico"), "parada": ("#898781", "⏸", "En mantenimiento")}
AZUL, NARANJA = "#2a78d6", "#eb6834"

pio.templates["gemelo"] = go.layout.Template(layout=dict(
    font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=13, color=TINTA["secundaria"]),
    title=dict(font=dict(size=17, color=TINTA["primaria"]), x=0.01, xanchor="left"),
    paper_bgcolor=TINTA["fondo"], plot_bgcolor=TINTA["fondo"],
    colorway=[AZUL, NARANJA, "#1baf7a"],
    xaxis=dict(gridcolor=TINTA["grilla"], linecolor=TINTA["eje"], zeroline=False, ticks=""),
    yaxis=dict(gridcolor=TINTA["grilla"], linecolor=TINTA["eje"], zeroline=False, ticks=""),
    hoverlabel=dict(bgcolor="white", bordercolor=TINTA["eje"], font=dict(color=TINTA["primaria"])),
    legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, bgcolor="rgba(0,0,0,0)"),
    margin=dict(l=60, r=30, t=80, b=50),
))
pio.templates.default = "gemelo"


def _rgba(hex_color, alfa):
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alfa})"


def produccion_real(gemelo):
    fin = gemelo.eventos.query("evento == 'fin' and estacion == @ESTACIONES[-1]")["minuto"].sort_values()
    return [0.0] + list(fin / 60), [0] + list(range(1, len(fin) + 1))


def nivel_estacion(estado, e):
    if estado["parada"] and estado["parada"][0] == e:
        return "parada"
    if estado["colas"][e] >= 10 or estado["desvio"][e] > 20:
        return "critico"
    if estado["colas"][e] >= 5 or estado["desvio"][e] > 10:
        return "atencion"
    return "ok"


def fig_linea(estado):
    """Sinóptico tipo SCADA: estado de cada estación en este momento."""
    fig = go.Figure()
    xs = {e: i * 3 for i, e in enumerate(ESTACIONES)}
    en_uso = {e: sum(1 for s, _ in estado["en_servicio"] if s == e) for e in ESTACIONES}
    cola_max = max(12, max(estado["colas"].values()))

    for e, x in xs.items():
        color, icono, texto = ESTADO[nivel_estacion(estado, e)]
        fig.add_shape(type="rect", x0=x - 1.3, x1=x + 1.3, y0=0.9, y1=2.6, line=dict(color=color, width=3),
                      fillcolor="white", layer="below")
        fig.add_shape(type="rect", x0=x - 1.3, x1=x - 1.15, y0=0.9, y1=2.6, line_width=0, fillcolor=COLORES[e])
        fig.add_annotation(x=x, y=2.95, text=f"<b>{icono} {texto}</b>", showarrow=False,
                           font=dict(size=12, color=TINTA["primaria"]))
        fig.add_annotation(x=x, y=2.25, text=f"<b>{e.capitalize()}</b>", showarrow=False,
                           font=dict(size=16, color=TINTA["primaria"]))
        fig.add_annotation(x=x, y=1.75, showarrow=False, font=dict(size=12),
                           text=f"{en_uso[e]} de {estado['maquinas'][e]} máquina(s) en uso")
        signo = "+" if estado["desvio"][e] >= 0 else ""
        fig.add_annotation(x=x, y=1.3, showarrow=False, font=dict(size=12),
                           text=f"ciclo {estado['tiempos'][e]:.1f} min · plan {BASE['tiempos'][e]:.1f} "
                                f"(<b>{signo}{estado['desvio'][e]:.0f}%</b>)")
        alto = 0.75 * estado["colas"][e] / cola_max
        fig.add_shape(type="rect", x0=x - 0.5, x1=x + 0.5, y0=0.55 - alto, y1=0.55,
                      line_width=0, fillcolor=_rgba(COLORES[e], 0.85))
        fig.add_shape(type="line", x0=x - 0.9, x1=x + 0.9, y0=0.55, y1=0.55, line=dict(color=TINTA["eje"], width=1))
        fig.add_annotation(x=x, y=0.55 - alto - 0.18, showarrow=False, font=dict(size=12, color=TINTA["primaria"]),
                           text=f"cola: <b>{estado['colas'][e]}</b>")
        if e != ESTACIONES[-1]:
            fig.add_annotation(x=x + 1.65, y=1.75, ax=x + 1.35, ay=1.75, xref="x", yref="y", axref="x", ayref="y",
                               showarrow=True, arrowhead=2, arrowwidth=2, arrowcolor=TINTA["eje"], text="")

    fig.add_annotation(x=-1.4, y=1.75, ax=-2.3, ay=1.75, axref="x", ayref="y", showarrow=True, arrowhead=2,
                       arrowwidth=2, arrowcolor=TINTA["eje"], text="")
    fig.add_annotation(x=-2.4, y=1.75, text=f"<b>{estado['llegadas']}</b><br>llegaron", showarrow=False,
                       xanchor="right", font=dict(size=12))
    ultimo = xs[ESTACIONES[-1]]
    fig.add_annotation(x=ultimo + 2.35, y=1.75, ax=ultimo + 1.35, ay=1.75, axref="x", ayref="y", showarrow=True,
                       arrowhead=2, arrowwidth=2, arrowcolor=TINTA["eje"], text="")
    fig.add_annotation(x=ultimo + 2.45, y=1.75, text=f"<b>{estado['producidas']}</b><br>terminadas",
                       showarrow=False, xanchor="left", font=dict(size=12))

    fig.update_xaxes(visible=False, range=[-3.6, ultimo + 3.6])
    fig.update_yaxes(visible=False, range=[-0.5, 3.2])
    fig.update_layout(height=330, margin=dict(l=10, r=10, t=50, b=10),
                      title=f"Estado de la línea · hora {estado['minuto'] / 60:.1f} del turno")
    return fig


def fig_tiempos(gemelo, ventana=10):
    """Tiempos de ciclo medidos por la telemetría vs. el plan: aquí se ve la deriva."""
    ev = gemelo.eventos[gemelo.eventos["evento"].isin(["inicio", "fin"])]
    par = ev.pivot_table(index=["botella", "estacion"], columns="evento", values="minuto").dropna().reset_index()
    par["duracion"] = par["fin"] - par["inicio"]
    fig = make_subplots(rows=1, cols=3, subplot_titles=[e.capitalize() for e in ESTACIONES],
                        horizontal_spacing=0.06)
    for i, e in enumerate(ESTACIONES, start=1):
        d = par[par["estacion"] == e].sort_values("fin")
        fig.add_trace(go.Scatter(x=d["fin"] / 60, y=d["duracion"], mode="markers", name="Cada botella",
                                 marker=dict(size=8, color=_rgba(COLORES[e], 0.35), line=dict(width=0)),
                                 showlegend=(i == 1), legendgroup="pts",
                                 hovertemplate="hora %{x:.2f}<br>%{y:.2f} min<extra></extra>"), 1, i)
        fig.add_trace(go.Scatter(x=d["fin"] / 60, y=d["duracion"].rolling(ventana, min_periods=3).mean(),
                                 mode="lines", line=dict(color=COLORES[e], width=2.5), name="Promedio móvil",
                                 showlegend=(i == 1), legendgroup="media",
                                 hovertemplate="promedio %{y:.2f} min<extra></extra>"), 1, i)
        fig.add_hline(y=BASE["tiempos"][e], line=dict(color=TINTA["tenue"], dash="dash", width=1.5), row=1, col=i,
                      annotation_text=f"plan {BASE['tiempos'][e]:.0f} min", annotation_position="top left",
                      annotation_font=dict(color=TINTA["secundaria"], size=11))
    fig.update_xaxes(title_text="hora del turno")
    fig.update_yaxes(title_text="min por botella", col=1)
    fig.update_layout(height=380, title="Tiempos de ciclo medidos por los sensores",
                      legend=dict(x=1, xanchor="right", y=1.2), margin=dict(t=100))
    return fig


def fig_proyeccion(gemelo, proy, meta=META, alternativa=None, nombre_alt=None):
    """Producción real hasta ahora + abanico de lo que proyecta el gemelo al cierre."""
    fig = go.Figure()
    ahora = gemelo.minuto / 60

    def abanico(r, color, nombre):
        b = r["banda"]
        h = b.index / 60
        fig.add_trace(go.Scatter(x=list(h) + list(h[::-1]), y=list(b["p90"]) + list(b["p10"][::-1]),
                                 fill="toself", fillcolor=_rgba(color, 0.15), line=dict(width=0),
                                 hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=h, y=b["p50"], mode="lines", line=dict(color=color, width=2.5, dash="dash"),
                                 name=f"{nombre} (banda 80%)",
                                 hovertemplate="hora %{x:.1f}<br>proyección %{y:.0f}<extra></extra>"))
        fig.add_annotation(x=FIN_TURNO / 60, y=r["mediana"], xanchor="left", showarrow=False, xshift=6,
                           text=f"<b>{r['mediana']:.0f}</b> ({r['p10']:.0f}–{r['p90']:.0f})<br>"
                                f"P(meta) {r['prob_meta']:.0%}",
                           font=dict(size=12, color=TINTA["primaria"]), align="left",
                           bgcolor=TINTA["fondo"], borderpad=2)

    abanico(proy, AZUL, "Proyección actual")
    if alternativa is not None:
        abanico(alternativa, NARANJA, nombre_alt or "Con acción")

    x, y = produccion_real(gemelo)
    fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(color=TINTA["primaria"], width=2.5, shape="hv"),
                             name="Producción real", hovertemplate="hora %{x:.2f}<br>%{y} botellas<extra></extra>"))
    fig.add_hline(y=meta, line=dict(color=TINTA["secundaria"], dash="dot", width=1.5),
                  annotation_text=f"Meta {meta}", annotation_position="top left",
                  annotation_font=dict(color=TINTA["secundaria"]))
    fig.add_vline(x=ahora, line=dict(color=TINTA["eje"], width=1.5),
                  annotation_text="ahora", annotation_position="bottom right", annotation_font=dict(color=TINTA["tenue"]))

    color, icono, texto = ESTADO["ok" if proy["prob_meta"] >= 0.8 else
                                 "atencion" if proy["prob_meta"] >= 0.5 else "critico"]
    fig.update_layout(
        height=430, title=f"¿Llegamos a la meta?  <span style='color:{color}'>{icono}</span> {texto} · "
                          f"probabilidad {proy['prob_meta']:.0%}",
        xaxis=dict(title="hora del turno", range=[0, FIN_TURNO / 60 + 1.3], dtick=1),
        yaxis=dict(title="botellas terminadas (acumulado)", rangemode="tozero"),
    )
    return fig


def fig_decision(ranking, umbral=0.8):
    """El gemelo prueba cada acción en simulación antes de tocar la planta."""
    r = ranking.iloc[::-1]
    colores = [AZUL if i == 0 else "#c3c2b7" for i in ranking.index[::-1]]
    fig = go.Figure(go.Bar(
        y=r["Acción"], x=100 * r["Prob. meta"], orientation="h", marker=dict(color=colores, cornerradius=4),
        text=[f"{p:.0%} · {m:.0f} bot. ({a:.0f}–{b:.0f})" for p, m, a, b in
              zip(r["Prob. meta"], r["Mediana"], r["P10"], r["P90"])],
        textposition="outside", textfont=dict(color=TINTA["primaria"]),
        hovertemplate="%{y}<br>probabilidad %{x:.0f}%<extra></extra>"))
    fig.add_vline(x=100 * umbral, line=dict(color=TINTA["tenue"], dash="dot"),
                  annotation_text=f"confianza buscada {umbral:.0%}", annotation_position="top",
                  annotation_font=dict(color=TINTA["secundaria"], size=11))
    fig.update_layout(height=80 + 55 * len(r), title="Acciones probadas en el gemelo · probabilidad de cumplir la meta",
                      xaxis=dict(range=[0, 135], title="% de réplicas que llegan a la meta", dtick=20),
                      yaxis=dict(title=None, gridcolor="rgba(0,0,0,0)"), bargap=0.35, margin=dict(l=230))
    return fig


def fig_colas(gemelo):
    """Colas reportadas por la planta en cada envío (pestaña 'estado')."""
    h = gemelo.historial
    fig = go.Figure()
    for e in ESTACIONES:
        fig.add_trace(go.Scatter(x=pd.to_numeric(h["minuto_turno"]) / 60, y=pd.to_numeric(h[f"cola_{e}"]),
                                 mode="lines", name=e.capitalize(), line=dict(color=COLORES[e], width=2.5),
                                 hovertemplate=e + ": %{y} botellas<extra></extra>"))
    for _, a in gemelo.eventos[gemelo.eventos["evento"] == "accion"].iterrows():
        fig.add_vline(x=a["minuto"] / 60, line=dict(color=TINTA["tenue"], dash="dash", width=1.5),
                      annotation_text=str(a["detalle"]), annotation_position="top left",
                      annotation_font=dict(color=TINTA["secundaria"], size=11))
    fig.update_layout(height=360, title="Botellas en cola según la planta",
                      xaxis=dict(title="hora del turno", range=[0, FIN_TURNO / 60], dtick=1),
                      yaxis=dict(title="botellas esperando", rangemode="tozero"))
    return fig
