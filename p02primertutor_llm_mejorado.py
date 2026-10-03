# ============================================================
# PRACTICA 2
# CINEBOT - ASISTENTE DE CINE CON LLM - VERSION MEJORADA
# ============================================================
#
# Objetivo:
# Crear un asistente educativo especializado utilizando
# un modelo de lenguaje LLM ejecutado mediante Ollama.
#
# Cambios realizados:
# 1. Nuevo perfil del asistente: asistente de cine y recomendaciones cinematograficas.
# 2. Interfaz grafica intuitiva con Tkinter.
# 3. Historial visible de la conversacion.
# 4. Boton para generar un resumen breve de la sesion.
# 5. Manejo de errores y ejecucion en segundo plano.
#
# Requisito:
# Ollama instalado y modelo llama3.2 descargado.
# ============================================================

import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
import ollama


MODELO = "llama3.2"

COLORES = {
    "fondo": "#0F172A",
    "panel": "#172033",
    "entrada": "#1E293B",
    "borde": "#334155",
    "azul": "#2563EB",
    "azul_hover": "#3B82F6",
    "texto": "#F1F5F9",
    "texto_suave": "#CBD5E1",
    "acento": "#67E8F9",
    "burbuja_usuario": "#164E63",
    "listo": "#4ADE80",
    "ocupado": "#FACC15",
    "error": "#FB7185",
}

# ------------------------------------------------------------
# CONFIGURACION DEL SISTEMA
# ------------------------------------------------------------
# El asistente se especializa en cine y recomendaciones cinematograficas.
# ------------------------------------------------------------

mensaje_sistema = """
Eres CineBot, un asistente especializado en cine y entretenimiento cinematografico.

Tu funcion es ayudar a las personas a descubrir y comprender peliculas de manera
clara, amigable y entretenida.

Debes:
1. Recomendar peliculas de acuerdo con los gustos, generos o preferencias del usuario.
2. Explicar brevemente por que una pelicula puede ser interesante para la persona.
3. Comentar de forma clara sobre generos, temas, estilos y elementos cinematograficos.
4. Evitar revelar spoilers importantes sin advertirlo previamente.
5. Cuando el usuario pida una recomendacion, considerar primero los datos que proporcione.
6. Cuando falten datos importantes, hacer una pregunta breve para conocer sus preferencias.
7. No inventar informacion sobre peliculas, personajes, directores o argumentos.
8. Diferenciar entre una recomendacion y un dato objetivo sobre una pelicula.
9. Mantener un tono amigable, natural y relacionado con el mundo del cine.
10. Organizar las respuestas de manera clara y facil de leer.
"""

# Historial de la conversacion
mensajes = [
    {"role": "system", "content": mensaje_sistema}
]

procesando = False


# ------------------------------------------------------------
# FUNCIONES DE LA INTERFAZ
# ------------------------------------------------------------

def agregar_mensaje(remitente, contenido):
    """Muestra un mensaje en el area de conversacion."""
    es_cinebot = remitente in ("CINEBOT", "RESUMEN DE LA SESION")
    etiqueta = "cinebot" if es_cinebot else "cinefilo"
    chat.configure(state="normal")
    chat.insert(tk.END, f"  {remitente}  \n", etiqueta)
    chat.insert(tk.END, f"{contenido}\n\n", f"texto_{etiqueta}")
    chat.configure(state="disabled")
    chat.see(tk.END)


def cambiar_estado(texto):
    if "Error" in texto or "error" in texto:
        color_estado = COLORES["error"]
    elif "Consultando" in texto or "Generando" in texto:
        color_estado = COLORES["ocupado"]
    else:
        color_estado = COLORES["listo"]
    estado.configure(text=texto, text_color=color_estado)
    ventana.update_idletasks()


def enviar_pregunta(event=None):
    """Obtiene la pregunta y consulta al modelo."""
    global procesando

    if procesando:
        return

    pregunta = entrada.get("1.0", tk.END).strip()

    if not pregunta:
        return

    entrada.delete("1.0", tk.END)
    agregar_mensaje("CINEFILO", pregunta)

    mensajes.append({
        "role": "user",
        "content": pregunta
    })

    procesando = True
    boton_enviar.configure(state="disabled")
    boton_resumen.configure(state="disabled")
    cambiar_estado("Consultando a Ollama...")

    hilo = threading.Thread(
        target=consultar_llm,
        args=(pregunta,),
        daemon=True
    )
    hilo.start()


def consultar_llm(pregunta):
    """Realiza la consulta al LLM en un hilo separado."""
    global procesando

    try:
        respuesta = ollama.chat(
            model=MODELO,
            messages=mensajes
        )

        contenido = respuesta["message"]["content"]

        mensajes.append({
            "role": "assistant",
            "content": contenido
        })

        ventana.after(
            0,
            lambda: mostrar_respuesta(contenido)
        )

    except Exception as error:
        # Eliminamos la pregunta que no pudo procesarse.
        if mensajes and mensajes[-1]["role"] == "user":
            mensajes.pop()

        ventana.after(
            0,
            lambda: mostrar_error(str(error))
        )


def mostrar_respuesta(contenido):
    global procesando

    agregar_mensaje("CINEBOT", contenido)
    procesando = False
    boton_enviar.configure(state="normal")
    boton_resumen.configure(state="normal")
    cambiar_estado("Ollama conectado")


def mostrar_error(error):
    global procesando

    agregar_mensaje(
        "SISTEMA",
        "No fue posible obtener una respuesta.\n"
        "Verifica que Ollama este activo y que exista el modelo "
        f"{MODELO}.\n\nDetalle: {error}"
    )

    procesando = False
    boton_enviar.configure(state="normal")
    boton_resumen.configure(state="normal")
    cambiar_estado("Error de conexion")


def generar_resumen():
    """Genera un resumen breve usando el historial actual."""
    global procesando

    if procesando:
        return

    conversaciones = [
        m for m in mensajes
        if m["role"] in ("user", "assistant")
    ]

    if not conversaciones:
        messagebox.showinfo(
            "Resumen",
            "Todavia no hay una conversacion para resumir."
        )
        return

    historial_texto = "\n".join(
        f"{'Cinefilo' if m['role'] == 'user' else 'CineBot'}: {m['content']}"
        for m in conversaciones
    )

    prompt_resumen = f"""
Analiza el siguiente historial de una conversacion sobre cine.

{historial_texto}

Genera un resumen breve para el usuario que incluya:
- Peliculas, generos o temas tratados.
- Preferencias cinematograficas identificadas.
- Dudas o intereses detectados.
- Una recomendacion concreta de cine para continuar explorando.

Usa un maximo de 8 lineas y lenguaje claro.
"""

    procesando = True
    boton_enviar.configure(state="disabled")
    boton_resumen.configure(state="disabled")
    cambiar_estado("Generando resumen de la sesion...")

    hilo = threading.Thread(
        target=consultar_resumen,
        args=(prompt_resumen,),
        daemon=True
    )
    hilo.start()


def consultar_resumen(prompt):
    """Consulta Ollama para generar el resumen sin modificar el historial."""
    global procesando

    try:
        respuesta = ollama.chat(
            model=MODELO,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres un asistente academico que resume "
                        "sesiones de estudio de manera clara y breve."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        resumen = respuesta["message"]["content"]

        ventana.after(
            0,
            lambda: mostrar_resumen(resumen)
        )

    except Exception as error:
        ventana.after(
            0,
            lambda: mostrar_error_resumen(str(error))
        )


def mostrar_resumen(resumen):
    global procesando

    agregar_mensaje("RESUMEN DE LA SESION", resumen)
    procesando = False
    boton_enviar.configure(state="normal")
    boton_resumen.configure(state="normal")
    cambiar_estado("Ollama conectado")


def mostrar_error_resumen(error):
    global procesando

    messagebox.showerror(
        "Error al generar resumen",
        f"No fue posible generar el resumen.\n\n{error}"
    )

    procesando = False
    boton_enviar.configure(state="normal")
    boton_resumen.configure(state="normal")
    cambiar_estado("Ollama conectado")


def limpiar_chat():
    """Limpia solamente la visualizacion y reinicia el historial."""
    global mensajes

    if procesando:
        return

    confirmado = messagebox.askyesno(
        "Nueva sesion",
        "¿Deseas borrar la conversacion actual y comenzar una nueva?"
    )

    if not confirmado:
        return

    mensajes = [
        {"role": "system", "content": mensaje_sistema}
    ]

    chat.configure(state="normal")
    chat.delete("1.0", tk.END)
    chat.configure(state="disabled")

    agregar_mensaje(
        "CINEBOT",
        "Nueva sesion iniciada. Dime que pelicula o genero quieres explorar."
    )


def cerrar_programa():
    """Cierra la aplicacion."""
    if procesando:
        messagebox.showinfo(
            "Procesando",
            "Espera a que termine la consulta actual."
        )
        return

    ventana.destroy()


# ------------------------------------------------------------
# CREACION DE LA VENTANA
# ------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ventana = ctk.CTk()
ventana.title("CineBot - Asistente de Cine")
ancho_pantalla = ventana.winfo_screenwidth()
alto_pantalla = ventana.winfo_screenheight()
ancho_ventana = min(980, int(ancho_pantalla * 0.88))
alto_ventana = min(720, int(alto_pantalla * 0.72))
posicion_x = max(0, (ancho_pantalla - ancho_ventana) // 2)
posicion_y = max(0, (alto_pantalla - alto_ventana) // 2)
ventana.geometry(
    f"{ancho_ventana}x{alto_ventana}+{posicion_x}+{posicion_y}"
)
ventana.minsize(min(700, ancho_ventana), min(500, alto_ventana))
ventana.configure(fg_color=COLORES["fondo"])

# Encabezado
encabezado = ctk.CTkFrame(
    ventana,
    corner_radius=0,
    fg_color=COLORES["panel"]
)
encabezado.pack(fill="x")

marca = ctk.CTkFrame(encabezado, fg_color="transparent")
marca.pack(fill="x", padx=22, pady=(16, 0))

ctk.CTkLabel(
    marca,
    text="🎬  CINEBOT",
    font=ctk.CTkFont(family="Segoe UI", size=21, weight="bold"),
    text_color=COLORES["texto"]
).pack(side="left", anchor="w")

ctk.CTkLabel(
    marca,
    text=f"●  MODELO LOCAL  ·  {MODELO}",
    font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
    fg_color="#12352F",
    text_color=COLORES["listo"],
    corner_radius=18,
    padx=12,
    pady=7
).pack(side="right", anchor="e")

ctk.CTkLabel(
    encabezado,
    text="Historias para descubrir. Recomendaciones a tu medida.",
    font=ctk.CTkFont(family="Segoe UI", size=12),
    text_color=COLORES["texto_suave"],
    anchor="w"
).pack(fill="x", padx=22, pady=(6, 16))

ctk.CTkFrame(
    ventana,
    height=2,
    corner_radius=0,
    fg_color=COLORES["azul"]
).pack(fill="x")

# Area de chat
chat_marco = ctk.CTkFrame(
    ventana,
    corner_radius=18,
    border_width=1,
    border_color=COLORES["borde"],
    fg_color=COLORES["entrada"]
)
chat_marco.pack(fill="both", expand=True, padx=20, pady=(16, 12))

chat = ctk.CTkTextbox(
    chat_marco,
    wrap="word",
    height=320,
    font=ctk.CTkFont(family="Segoe UI", size=13),
    state="disabled",
    corner_radius=16,
    border_width=0,
    fg_color=COLORES["entrada"],
    text_color=COLORES["texto"],
    scrollbar_button_color=COLORES["borde"],
    scrollbar_button_hover_color=COLORES["azul"]
)
chat.pack(fill="both", expand=True, padx=9, pady=9)
chat.tag_config(
    "cinebot",
    foreground=COLORES["acento"],
    background=COLORES["panel"],
    lmargin1=8,
    rmargin=110,
    spacing1=10,
    spacing3=4
)
chat.tag_config(
    "cinefilo",
    foreground="#BAE6FD",
    background=COLORES["burbuja_usuario"],
    lmargin1=110,
    rmargin=8,
    justify="right",
    spacing1=10,
    spacing3=4
)
chat.tag_config(
    "texto_cinebot",
    foreground=COLORES["texto"],
    background=COLORES["panel"],
    lmargin1=8,
    lmargin2=8,
    rmargin=110,
    spacing3=12
)
chat.tag_config(
    "texto_cinefilo",
    foreground=COLORES["texto"],
    background=COLORES["burbuja_usuario"],
    lmargin1=110,
    lmargin2=110,
    rmargin=8,
    justify="right",
    spacing3=12
)

agregar_mensaje(
    "CINEBOT",
    "Hola, soy CineBot. Estoy listo para hablar de peliculas, generos "
    "y recomendaciones. ¿Que te gustaria ver hoy?"
)

entrada_marco = ctk.CTkFrame(
    ventana,
    corner_radius=18,
    border_width=1,
    border_color=COLORES["borde"],
    fg_color=COLORES["entrada"]
)
entrada_marco.pack(fill="x", padx=20, pady=(0, 3))

entrada_frame = ctk.CTkFrame(entrada_marco, fg_color="transparent")
entrada_frame.pack(fill="x", padx=10, pady=9)

entrada = ctk.CTkTextbox(
    entrada_frame,
    height=82,
    wrap="word",
    font=ctk.CTkFont(family="Segoe UI", size=13),
    fg_color=COLORES["entrada"],
    text_color=COLORES["texto"],
    corner_radius=12,
    border_width=0,
    activate_scrollbars=False
)
entrada.pack(side="left", fill="x", expand=True)
entrada.bind("<Control-Return>", enviar_pregunta)

botones = ctk.CTkFrame(ventana, fg_color="transparent")
botones.pack(fill="x")

boton_enviar = ctk.CTkButton(
    botones,
    text="Enviar",
    command=enviar_pregunta,
    width=136,
    height=42,
    corner_radius=12,
    fg_color=COLORES["azul"],
    hover_color=COLORES["azul_hover"],
    text_color=COLORES["texto"],
    font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
)
boton_enviar.pack(side="left", padx=(20, 0), pady=(8, 12))

boton_resumen = ctk.CTkButton(
    botones,
    text="Resumen de sesion",
    command=generar_resumen,
    width=160,
    height=42,
    corner_radius=12,
    fg_color=COLORES["panel"],
    hover_color=COLORES["borde"],
    text_color=COLORES["texto"]
)
boton_resumen.pack(side="left", padx=8, pady=(8, 12))

boton_nueva = ctk.CTkButton(
    botones,
    text="Nueva sesion",
    command=limpiar_chat,
    width=132,
    height=42,
    corner_radius=12,
    fg_color=COLORES["panel"],
    hover_color=COLORES["borde"],
    text_color=COLORES["texto"]
)
boton_nueva.pack(side="left", pady=(8, 12))

boton_salir = ctk.CTkButton(
    botones,
    text="Salir",
    command=cerrar_programa,
    width=88,
    height=42,
    corner_radius=12,
    fg_color=COLORES["panel"],
    hover_color="#7F1D1D",
    text_color=COLORES["texto"]
)
boton_salir.pack(side="right", padx=(0, 20), pady=(8, 12))

estado = ctk.CTkLabel(
    ventana,
    text="Ollama listo",
    anchor="w",
    height=34,
    corner_radius=0,
    fg_color=COLORES["panel"],
    text_color=COLORES["listo"],
    font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold")
)
estado.pack(fill="x", side="bottom")

ventana.bind("<Control-Return>", enviar_pregunta)
ventana.protocol("WM_DELETE_WINDOW", cerrar_programa)

entrada.focus_set()
ventana.mainloop()
