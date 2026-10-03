"""Aplicacion de escritorio LogiSmart con MongoDB y Ollama local."""

import csv
import io
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
from ollama import Client
from pydantic import ValidationError
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from database.connection import DATABASE_NAME, MONGO_URI
from database.repository import (
    COLECCIONES,
    actualizar_documento,
    crear_documento,
    eliminar_documento,
    incidentes_por_categoria_y_semana,
    listar_documentos,
    obtener_documento,
)
from logic.access_rules import (
    evaluar_acceso,
    guardar_decision,
    tabla_verdad_reglas_nuevas,
)
from services.assistant import responder_con_contexto
from services.classifier import (
    MODELO_CLASIFICACION,
    ClasificacionCorreo,
    clasificar_hibrido,
    clasificar_por_reglas,
    fusionar_clasificaciones,
)
from services.evaluation import evaluar_clasificadores


PALETA = {
    "fondo": "#F3F5F1",
    "superficie": "#FFFFFF",
    "tinta": "#17231F",
    "suave": "#78847E",
    "linea": "#E3E9E5",
    "bosque": "#1D3029",
    "verde": "#387052",
    "menta": "#B9D9C3",
    "azul": "#267A82",
    "azul_hover": "#318F96",
    "rojo": "#BE5149",
    "rojo_claro": "#F9E9E7",
    "ambar": "#B9852D",
    "ambar_claro": "#F8F1DF",
    "verde_claro": "#EDF5EF",
}

COLECCIONES_UI = {
    "Camiones": "camiones",
    "Accesos": "accesos",
    "Incidentes": "incidentes",
    "Riesgos éticos": "riesgos_eticos",
    "Evaluaciones LLM": "evaluaciones_llm",
}

ESTADOS = ("nuevo", "en_atencion", "cerrado")


def _crear_etiqueta(master, texto, size=12, color=None, bold=False, **kwargs):
    font = kwargs.pop(
        "font",
        ctk.CTkFont(
            family="Segoe UI",
            size=size,
            weight="bold" if bold else "normal",
        ),
    )
    return ctk.CTkLabel(
        master,
        text=texto,
        font=font,
        text_color=color or PALETA["tinta"],
        anchor=kwargs.pop("anchor", "w"),
        **kwargs,
    )


class LogiSmartApp(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("green")
        super().__init__()

        self.title("LogiSmart | Centro de operaciones")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = min(1440, int(screen_width * 0.94))
        height = min(930, int(screen_height * 0.88))
        self.geometry(
            f"{width}x{height}+{max(0, (screen_width - width) // 2)}+"
            f"{max(0, (screen_height - height) // 2)}"
        )
        self.minsize(min(1000, width), min(690, height))
        self.configure(fg_color=PALETA["fondo"])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.mongo_client: MongoClient | None = None
        self.db = None
        self.config_path = Path.home() / ".logismart_settings.json"
        self.settings = self._load_settings()
        self.model_var = ctk.StringVar(value=self.settings["modelo"])
        self.simulation_var = ctk.BooleanVar(value=self.settings["simulacion"])
        self.access_vars = {
            key: ctk.BooleanVar(value=value)
            for key, value in {
                "P": True,
                "Q": False,
                "R": False,
                "S": True,
                "certificacion_vigente": True,
                "material_peligroso": False,
                "horario_permitido": True,
            }.items()
        }
        self.selected_incident_id: str | None = None
        self.selected_risk_id: str | None = None
        self.selected_record_id: str | None = None
        self.chat_history: list[dict[str, str]] = []
        self._build_header()
        self._build_tabs()
        self._build_statusbar()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(250, self.refresh_dashboard)

    def _load_settings(self) -> dict[str, Any]:
        defaults = {
            "modelo": os.getenv("OLLAMA_MODEL", MODELO_CLASIFICACION),
            "ollama_host": os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
            "umbral_riesgo": 15,
            "simulacion": False,
        }
        try:
            saved = json.loads(self.config_path.read_text(encoding="utf-8"))
            defaults.update(saved)
        except (OSError, json.JSONDecodeError):
            pass
        return defaults

    def _save_settings_file(self):
        self.config_path.write_text(
            json.dumps(self.settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _get_db(self):
        if self.db is not None:
            return self.db
        self.mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2500)
        try:
            self.mongo_client.admin.command("ping")
        except PyMongoError:
            self.mongo_client.close()
            self.mongo_client = None
            raise ConnectionError(
                "No se pudo conectar con MongoDB. Revisa el servicio y MONGO_URI."
            ) from None
        self.db = self.mongo_client[DATABASE_NAME]
        return self.db

    def _ollama_client(self):
        return Client(host=self.settings["ollama_host"])

    def _set_status(self, text, kind="ok"):
        colors_by_kind = {
            "ok": PALETA["verde"],
            "busy": PALETA["ambar"],
            "error": PALETA["rojo"],
        }
        self.status_label.configure(text=text, text_color=colors_by_kind[kind])

    def _build_header(self):
        header = ctk.CTkFrame(self, corner_radius=0, fg_color=PALETA["bosque"])
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=22, pady=14)
        ctk.CTkLabel(
            brand,
            text="▰",
            width=42,
            height=42,
            corner_radius=12,
            fg_color=PALETA["menta"],
            text_color=PALETA["bosque"],
            font=ctk.CTkFont(size=21, weight="bold"),
        ).pack(side="left", padx=(0, 12))
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left")
        _crear_etiqueta(
            names,
            "LogiSmart",
            21,
            "#F4F7F4",
            True,
            font=ctk.CTkFont(family="Georgia", size=21, weight="bold"),
        ).pack(anchor="w")
        _crear_etiqueta(names, "CENTRO DE OPERACIONES", 9, "#B5C4B9").pack(anchor="w")
        self.top_connection = ctk.CTkLabel(
            header,
            text="●  MongoDB / Ollama local",
            corner_radius=18,
            fg_color="#29483A",
            text_color="#B9D9C3",
            font=ctk.CTkFont(size=10, weight="bold"),
            padx=12,
            pady=7,
        )
        self.top_connection.grid(row=0, column=1, sticky="e", padx=22)

    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(
            self,
            fg_color=PALETA["fondo"],
            segmented_button_fg_color="#DDE5DF",
            segmented_button_selected_color=PALETA["bosque"],
            segmented_button_selected_hover_color=PALETA["bosque_suave"] if "bosque_suave" in PALETA else "#29483A",
            segmented_button_unselected_color="#DDE5DF",
            segmented_button_unselected_hover_color="#C9D6CC",
            text_color=PALETA["tinta"],
            corner_radius=12,
        )
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=16, pady=(10, 6))
        names = (
            "Resumen",
            "Control de acceso",
            "Incidentes",
            "Asistente",
            "Riesgos éticos",
            "Registros CRUD",
            "Reportes",
            "Configuración",
        )
        for name in names:
            self.tabs.add(name)
        self._build_dashboard_tab()
        self._build_access_tab()
        self._build_incidents_tab()
        self._build_assistant_tab()
        self._build_risks_tab()
        self._build_crud_tab()
        self._build_reports_tab()
        self._build_settings_tab()

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, corner_radius=0, fg_color=PALETA["superficie"])
        bar.grid(row=2, column=0, sticky="ew")
        self.status_label = _crear_etiqueta(bar, "Listo", 10, PALETA["verde"], True)
        self.status_label.pack(anchor="w", padx=19, pady=8)

    def _tab_scroll(self, name):
        frame = ctk.CTkScrollableFrame(
            self.tabs.tab(name),
            fg_color="transparent",
            scrollbar_button_color="#C8D2CB",
            scrollbar_button_hover_color="#9AAA9F",
        )
        frame.pack(fill="both", expand=True, padx=5, pady=5)
        return frame

    def _section_title(self, master, eyebrow, title, subtitle):
        block = ctk.CTkFrame(master, fg_color="transparent")
        block.pack(fill="x", padx=15, pady=(14, 13))
        _crear_etiqueta(block, eyebrow.upper(), 9, PALETA["verde"], True).pack(anchor="w")
        _crear_etiqueta(
            block,
            title,
            27,
            PALETA["tinta"],
            font=ctk.CTkFont(family="Georgia", size=27),
        ).pack(anchor="w", pady=(4, 0))
        _crear_etiqueta(block, subtitle, 11, PALETA["suave"]).pack(anchor="w", pady=(3, 0))

    def _card(self, master, title, subtitle=""):
        frame = ctk.CTkFrame(
            master,
            fg_color=PALETA["superficie"],
            corner_radius=12,
            border_width=1,
            border_color=PALETA["linea"],
        )
        if title:
            head = ctk.CTkFrame(frame, fg_color="transparent")
            head.pack(fill="x", padx=16, pady=(13, 10))
            _crear_etiqueta(
                head,
                title,
                16,
                PALETA["tinta"],
                font=ctk.CTkFont(family="Georgia", size=16, weight="bold"),
            ).pack(anchor="w")
            if subtitle:
                _crear_etiqueta(head, subtitle, 10, PALETA["suave"]).pack(
                    anchor="w", pady=(3, 0)
                )
            ctk.CTkFrame(frame, height=1, fg_color="#EDF0ED").pack(fill="x")
        return frame

    def _button(self, master, text, command, primary=False, width=120):
        return ctk.CTkButton(
            master,
            text=text,
            command=command,
            width=width,
            height=36,
            corner_radius=9,
            fg_color=PALETA["bosque"] if primary else "#E9EFEA",
            hover_color="#29483A" if primary else "#D9E4DC",
            text_color="#FFFFFF" if primary else PALETA["bosque"],
            font=ctk.CTkFont(size=11, weight="bold" if primary else "normal"),
        )

    def _entry(self, master, placeholder, **kwargs):
        return ctk.CTkEntry(
            master,
            placeholder_text=placeholder,
            height=36,
            corner_radius=8,
            border_color=PALETA["linea"],
            fg_color="#FFFFFF",
            text_color=PALETA["tinta"],
            **kwargs,
        )

    def _textbox(self, master, height=140, **kwargs):
        return ctk.CTkTextbox(
            master,
            height=height,
            wrap="word",
            corner_radius=9,
            border_width=1,
            border_color=PALETA["linea"],
            fg_color="#FFFFFF",
            text_color=PALETA["tinta"],
            font=ctk.CTkFont(family="Consolas", size=11),
            **kwargs,
        )

    def _build_dashboard_tab(self):
        page = self._tab_scroll("Resumen")
        self._section_title(
            page,
            "Vista general",
            "Operaciones del patio",
            "Indicadores y actividad consultados desde MongoDB.",
        )
        filters = ctk.CTkFrame(page, fg_color="transparent")
        filters.pack(fill="x", padx=15, pady=(0, 12))
        self.date_from = self._entry(filters, "Desde AAAA-MM-DD", width=155)
        self.date_from.pack(side="left", padx=(0, 7))
        self.date_to = self._entry(filters, "Hasta AAAA-MM-DD", width=155)
        self.date_to.pack(side="left", padx=(0, 7))
        self._button(filters, "Aplicar fechas", self.refresh_dashboard, primary=True).pack(side="left")

        kpis = ctk.CTkFrame(page, fg_color="transparent")
        kpis.pack(fill="x", padx=15)
        for col in range(3):
            kpis.grid_columnconfigure(col, weight=1, uniform="kpi")
        self.kpi_values = []
        for col, (title, color) in enumerate((
            ("Camiones atendidos", PALETA["verde"]),
            ("Incidentes abiertos", PALETA["ambar"]),
            ("Riesgos críticos", PALETA["rojo"]),
        )):
            card = self._card(kpis, "")
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 5, 5 if col < 2 else 0))
            _crear_etiqueta(card, title, 11, PALETA["suave"]).pack(anchor="w", padx=15, pady=(14, 3))
            value = _crear_etiqueta(card, "—", 29, color, font=ctk.CTkFont(family="Georgia", size=30))
            value.pack(anchor="w", padx=15)
            foot = _crear_etiqueta(card, "Esperando datos", 9, PALETA["suave"])
            foot.pack(anchor="w", padx=15, pady=(1, 13))
            self.kpi_values.append((value, foot))

        charts = ctk.CTkFrame(page, fg_color="transparent")
        charts.pack(fill="both", expand=True, padx=15, pady=(14, 0))
        charts.grid_columnconfigure((0, 1), weight=1, uniform="dash")
        self.category_chart = self._card(charts, "Incidentes por categoría y semana", "Agregación semanal de MongoDB")
        self.category_chart.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.category_rows = ctk.CTkFrame(self.category_chart, fg_color="transparent")
        self.category_rows.pack(fill="both", expand=True, padx=15, pady=12)
        self.recent_access = self._card(charts, "Últimos accesos", "Bitácora registrada")
        self.recent_access.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.access_rows = ctk.CTkFrame(self.recent_access, fg_color="transparent")
        self.access_rows.pack(fill="both", expand=True, padx=15, pady=12)

    def _date_filter(self, field):
        result = {}
        start_text = self.date_from.get().strip()
        end_text = self.date_to.get().strip()
        if start_text or end_text:
            dates = {}
            if start_text:
                dates["$gte"] = datetime.fromisoformat(start_text).replace(tzinfo=timezone.utc)
            if end_text:
                dates["$lte"] = datetime.fromisoformat(end_text).replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            result[field] = dates
        return result

    def refresh_dashboard(self):
        try:
            db = self._get_db()
            access_filter = self._date_filter("marca_tiempo")
            incident_filter = self._date_filter("fecha_creacion")
            risk_filter = self._date_filter("fecha_creacion")
            truck_count = len(db.accesos.distinct("camion_id", access_filter))
            open_incidents = db.incidentes.count_documents({
                **incident_filter,
                "estado": {"$in": ["nuevo", "en_atencion"]},
            })
            threshold = int(self.settings["umbral_riesgo"])
            critical_risks = db.riesgos_eticos.count_documents({
                **risk_filter,
                "puntaje_despues": {"$gte": threshold}
            })
            for (value, foot), number, note in zip(
                self.kpi_values,
                (truck_count, open_incidents, critical_risks),
                ("en el rango seleccionado", "nuevos o en atención", f"residual ≥ {threshold}"),
            ):
                value.configure(text=f"{number:02d}")
                foot.configure(text=note)
            self._render_category_chart(db)
            self._render_recent_access(db, access_filter)
            self.top_connection.configure(text="●  MongoDB conectado", text_color="#B9D9C3")
            self._set_status("Indicadores actualizados desde MongoDB.")
        except (ValueError, PyMongoError, ConnectionError) as error:
            self.top_connection.configure(text="●  MongoDB no disponible", text_color="#F3B4A8")
            self._set_status(f"No se pudo actualizar el tablero: {error}", "error")

    def _render_category_chart(self, db):
        for child in self.category_rows.winfo_children():
            child.destroy()
        try:
            rows = incidentes_por_categoria_y_semana(
                db,
                desde=self._optional_date(self.date_from.get(), end=False),
                hasta=self._optional_date(self.date_to.get(), end=True),
            )
        except TypeError:
            rows = incidentes_por_categoria_y_semana(db)
        if not rows:
            _crear_etiqueta(self.category_rows, "Sin incidentes para el periodo.", 11, PALETA["suave"]).pack(anchor="w")
            return
        max_count = max(item["total"] for item in rows)
        for item in rows[:8]:
            row = ctk.CTkFrame(self.category_rows, fg_color="transparent")
            row.pack(fill="x", pady=5)
            row.grid_columnconfigure(1, weight=1)
            _crear_etiqueta(row, f"{item['categoria']} · {item['semana']}", 10, PALETA["tinta"], wraplength=170).grid(row=0, column=0, sticky="w", padx=(0, 8))
            bar = ctk.CTkProgressBar(row, height=8, corner_radius=8, progress_color=PALETA["verde"], fg_color="#E8EEE9")
            bar.grid(row=0, column=1, sticky="ew", padx=5)
            bar.set(item["total"] / max_count)
            _crear_etiqueta(row, str(item["total"]), 10, PALETA["suave"], True, width=25, anchor="e").grid(row=0, column=2)

    @staticmethod
    def _optional_date(value, end=False):
        if not value.strip():
            return None
        parsed = datetime.fromisoformat(value.strip()).replace(tzinfo=timezone.utc)
        if end:
            parsed = parsed.replace(hour=23, minute=59, second=59)
        return parsed

    def _render_recent_access(self, db, filters):
        for child in self.access_rows.winfo_children():
            child.destroy()
        records = list(db.accesos.find(filters).sort("marca_tiempo", -1).limit(6))
        if not records:
            _crear_etiqueta(self.access_rows, "Aún no hay accesos en la bitácora.", 11, PALETA["suave"]).pack(anchor="w")
            return
        for record in records:
            allowed = bool(record.get("resultado_A"))
            icon_color = PALETA["verde"] if allowed else PALETA["rojo"]
            line = ctk.CTkFrame(self.access_rows, fg_color="transparent")
            line.pack(fill="x", pady=5)
            _crear_etiqueta(line, "●", 11, icon_color, True).pack(side="left", padx=(0, 8))
            _crear_etiqueta(line, record.get("camion_id", "Camión sin ID"), 11, PALETA["tinta"], True).pack(side="left")
            _crear_etiqueta(line, "AUTORIZADO" if allowed else "REVISAR", 9, icon_color, True).pack(side="right")

    def _build_access_tab(self):
        page = self._tab_scroll("Control de acceso")
        self._section_title(page, "Reglas proposicionales", "Control de acceso", "Activa las premisas; los resultados se actualizan en vivo y se pueden guardar en la bitácora.")
        grid = ctk.CTkFrame(page, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=15)
        grid.grid_columnconfigure((0, 1), weight=1, uniform="access")
        form = self._card(grid, "Datos de la unidad", "Buscar por placa o ingresar el identificador")
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        controls = ctk.CTkFrame(form, fg_color="transparent")
        controls.pack(fill="x", padx=15, pady=14)
        self.truck_id_entry = self._entry(controls, "CAM-102")
        self.truck_id_entry.pack(fill="x", pady=4)
        lookup_row = ctk.CTkFrame(controls, fg_color="transparent")
        lookup_row.pack(fill="x", pady=4)
        self.plate_entry = self._entry(lookup_row, "Placa, por ejemplo RST-4821")
        self.plate_entry.pack(side="left", fill="x", expand=True, padx=(0, 7))
        self._button(lookup_row, "Buscar", self.lookup_truck).pack(side="right")
        self.operator_entry = self._entry(controls, "Nombre del operador")
        self.operator_entry.pack(fill="x", pady=(5, 12))
        _crear_etiqueta(controls, "PREMISAS Y CONDICIONES", 9, PALETA["suave"], True).pack(anchor="w", pady=(0, 5))
        switch_names = (
            ("P", "Unidad registrada"),
            ("Q", "Restricción activa"),
            ("R", "Requiere revisión documental"),
            ("S", "Acceso programado"),
            ("certificacion_vigente", "Certificación del conductor vigente"),
            ("material_peligroso", "Transporta material peligroso"),
            ("horario_permitido", "Horario permitido para material peligroso"),
        )
        for key, label in switch_names:
            switch = ctk.CTkSwitch(
                controls,
                text=label,
                variable=self.access_vars[key],
                command=self.render_live_access,
                progress_color=PALETA["verde"],
                button_color=PALETA["bosque"],
                button_hover_color="#345F48",
                font=ctk.CTkFont(size=11),
            )
            switch.pack(anchor="w", pady=5)

        result = self._card(grid, "Resultado en vivo", "A = P ∧ S ∧ ¬Q · E = P ∧ (R ∨ Q)")
        result.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        result_body = ctk.CTkFrame(result, fg_color="transparent")
        result_body.pack(fill="both", expand=True, padx=15, pady=14)
        lights = ctk.CTkFrame(result_body, fg_color="transparent")
        lights.pack(fill="x")
        self.light_A = ctk.CTkLabel(lights, text="A · SIN EVALUAR", height=42, corner_radius=11, fg_color="#E9EFEA", text_color=PALETA["suave"], font=ctk.CTkFont(size=13, weight="bold"))
        self.light_A.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.light_E = ctk.CTkLabel(lights, text="E · SIN EVALUAR", height=42, corner_radius=11, fg_color="#E9EFEA", text_color=PALETA["suave"], font=ctk.CTkFont(size=13, weight="bold"))
        self.light_E.pack(side="left", fill="x", expand=True, padx=(5, 0))
        _crear_etiqueta(result_body, "Explicación paso a paso", 11, PALETA["tinta"], True).pack(anchor="w", pady=(15, 6))
        self.access_explanation = self._textbox(result_body, 210)
        self.access_explanation.pack(fill="both", expand=True)
        actions = ctk.CTkFrame(result_body, fg_color="transparent")
        actions.pack(fill="x", pady=(10, 0))
        self._button(actions, "Guardar decisión", self.save_access, primary=True).pack(side="left")
        self._button(actions, "Verificar conexión", self.check_connection).pack(side="right")

        truth = self._card(page, "Simulador de tablas de verdad", "Las condiciones activas de arriba actualizan A y E al instante.")
        truth.pack(fill="x", padx=15, pady=(14, 12))
        self.truth_output = self._textbox(truth, 125)
        self.truth_output.pack(fill="x", padx=15, pady=(0, 15))
        self.render_live_access()
        self._render_truth_table()

    def _current_conditions(self):
        return {name: variable.get() for name, variable in self.access_vars.items()}

    def render_live_access(self):
        try:
            result = evaluar_acceso(**self._current_conditions())
            allowed = result["resultado_A"]
            inspection = result["resultado_E"]
            self.light_A.configure(
                text="A · ACCESO AUTORIZADO" if allowed else "A · ACCESO BLOQUEADO",
                fg_color=PALETA["verde_claro"] if allowed else PALETA["rojo_claro"],
                text_color=PALETA["verde"] if allowed else PALETA["rojo"],
            )
            self.light_E.configure(
                text="E · INSPECCIÓN REQUERIDA" if inspection else "E · SIN INSPECCIÓN",
                fg_color=PALETA["ambar_claro"] if inspection else PALETA["verde_claro"],
                text_color=PALETA["ambar"] if inspection else PALETA["verde"],
            )
            self.access_explanation.configure(state="normal")
            self.access_explanation.delete("1.0", "end")
            self.access_explanation.insert("1.0", result["explicacion"])
            self.access_explanation.configure(state="disabled")
        except (ValueError, AttributeError):
            pass

    def _render_truth_table(self):
        self.truth_output.configure(state="normal")
        self.truth_output.delete("1.0", "end")
        rows = tabla_verdad_reglas_nuevas()
        headers = ("Cert. vigente", "Material peligroso", "Horario", "Permite", "Inspección")
        self.truth_output.insert("end", " | ".join(headers) + "\n")
        self.truth_output.insert("end", "-" * 82 + "\n")
        for row in rows:
            values = (
                row["certificacion_vigente"],
                row["material_peligroso"],
                row["horario_permitido"],
                row["permite_segun_reglas_nuevas"],
                row["requiere_inspeccion"],
            )
            self.truth_output.insert("end", " | ".join("Sí" if value else "No" for value in values) + "\n")
        self.truth_output.configure(state="disabled")

    def lookup_truck(self):
        plate = self.plate_entry.get().strip().upper()
        if not plate:
            self._set_status("Escribe una placa para buscar.", "error")
            return
        try:
            truck = self._get_db().camiones.find_one({"placa": plate})
            if not truck:
                self._set_status(f"No se encontró la placa {plate}.", "error")
                return
            self.truck_id_entry.delete(0, "end")
            self.truck_id_entry.insert(0, truck.get("camion_id", ""))
            certificate = truck.get("certificacion_conductor", {})
            if isinstance(certificate, dict):
                valid = bool(certificate.get("vigente", False))
            else:
                valid = bool(certificate)
            self.access_vars["certificacion_vigente"].set(valid)
            self.render_live_access()
            self._set_status(f"Unidad {truck.get('camion_id')} encontrada.")
        except (PyMongoError, ConnectionError) as error:
            self._set_status(f"Búsqueda fallida: {error}", "error")

    def save_access(self):
        try:
            saved = guardar_decision(
                self._get_db(),
                camion_id=self.truck_id_entry.get().strip(),
                operador=self.operator_entry.get().strip(),
                condiciones=self._current_conditions(),
            )
            self._set_status(f"Decisión guardada en accesos ({saved['registro_id']}).")
            self.refresh_dashboard()
        except (ValueError, PyMongoError, ConnectionError) as error:
            self._set_status(f"No se guardó la decisión: {error}", "error")

    def check_connection(self):
        try:
            db = self._get_db()
            db.command("ping")
            self._ollama_client().list()
            self._set_status("MongoDB y Ollama disponibles.")
        except Exception as error:
            self._set_status(f"Servicio no disponible: {error}", "error")

    def _build_incidents_tab(self):
        page = self._tab_scroll("Incidentes")
        self._section_title(page, "Clasificación híbrida", "Bandeja de incidentes", "Pega un correo, revisa la clasificación, edítala y registra el seguimiento.")
        columns = ctk.CTkFrame(page, fg_color="transparent")
        columns.pack(fill="both", expand=True, padx=15)
        columns.grid_columnconfigure((0, 1), weight=1, uniform="incidents")
        left = self._card(columns, "Correo recibido", "La prioridad alta de las reglas prevalece ante discrepancias.")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.email_input = self._textbox(left, 235)
        self.email_input.pack(fill="both", expand=True, padx=13, pady=(0, 10))
        self.email_input.insert("1.0", "Pega aquí el correo operativo para clasificarlo…")
        self.classify_incident_button = self._button(
            left,
            "Clasificar y guardar",
            self.classify_incident,
            primary=True,
            width=170,
        )
        self.classify_incident_button.pack(anchor="e", padx=13, pady=(0, 13))

        right = self._card(columns, "Resultado editable", "Esquema JSON: categoría, prioridad, entidades y resumen.")
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.classification_output = self._textbox(right, 235)
        self.classification_output.pack(fill="both", expand=True, padx=13, pady=(0, 9))
        tools = ctk.CTkFrame(right, fg_color="transparent")
        tools.pack(fill="x", padx=13, pady=(0, 13))
        self.state_var = ctk.StringVar(value="nuevo")
        ctk.CTkOptionMenu(tools, values=list(ESTADOS), variable=self.state_var, width=138, height=34).pack(side="left")
        self._button(tools, "Guardar cambios", self.update_incident, width=140).pack(side="right")

        eval_card = self._card(page, "Evaluación con 30 correos", "Compara reglas, modelo e híbrido; la latencia se mide durante la ejecución.")
        eval_card.pack(fill="x", padx=15, pady=(13, 0))
        eval_row = ctk.CTkFrame(eval_card, fg_color="transparent")
        eval_row.pack(fill="x", padx=13, pady=(0, 8))
        self._button(eval_row, "Ejecutar evaluación", self.run_evaluation, primary=True, width=170).pack(side="left")
        self.eval_output = self._textbox(eval_card, 155)
        self.eval_output.pack(fill="x", padx=13, pady=(0, 13))

        history = self._card(page, "Historial de incidentes", "Selecciona un registro para editar su clasificación o estado.")
        history.pack(fill="x", padx=15, pady=(13, 12))
        self.incident_list = ctk.CTkScrollableFrame(history, height=150, fg_color="transparent")
        self.incident_list.pack(fill="x", padx=12, pady=(0, 12))
        self.refresh_incidents()

    def classify_incident(self):
        email = self.email_input.get("1.0", "end").strip()
        if not email or email.startswith("Pega aquí"):
            self._set_status("Pega el texto del correo antes de clasificar.", "error")
            return
        simulation_mode = self.simulation_var.get()
        selected_model = self.settings["modelo"]
        ollama_host = self.settings["ollama_host"]
        self._set_status("Clasificando correo…", "busy")
        self._button_busy(self.classify_incident_button, True)

        def worker():
            try:
                if simulation_mode:
                    rules = clasificar_por_reglas(email)
                    final, needs_review, _ = fusionar_clasificaciones(rules, None)
                    result = {
                        **final.model_dump(),
                        "reglas": rules.model_dump(),
                        "respuesta_llm": None,
                        "modelo": selected_model,
                        "latencia_ms": 0.0,
                        "coincidio_reglas": False,
                        "requiere_revision_humana": needs_review,
                        "metodo": "reglas_respaldo_simulacion",
                        "error_llm": None,
                    }
                else:
                    result = clasificar_hibrido(
                        email,
                        cliente=Client(host=ollama_host),
                        modelo=selected_model,
                    )
                db = self._get_db()
                now = datetime.now(timezone.utc).isoformat()
                classification = {
                    key: result[key]
                    for key in ("categoria", "prioridad", "entidades", "resumen")
                }
                incident_id = crear_documento(db, "incidentes", {
                    "correo_original": email,
                    "clasificacion": classification,
                    "datos_extraidos": result["entidades"],
                    "estado": "nuevo",
                    "requiere_revision_humana": result["requiere_revision_humana"],
                    "metodo_clasificacion": result["metodo"],
                    "historico": [{"fecha": now, "evento": "clasificacion_creada", "estado": "nuevo"}],
                })
                create_evaluacion = {
                    "prompt": email,
                    "respuesta": {
                        "clasificacion": classification,
                        "reglas": result["reglas"],
                        "requiere_revision_humana": result["requiere_revision_humana"],
                    },
                    "modelo": result["modelo"],
                    "latencia_ms": result["latencia_ms"],
                    "coincidio_reglas": result["coincidio_reglas"],
                }
                evaluation_id = crear_documento(db, "evaluaciones_llm", create_evaluacion)
                result["incidente_id"] = incident_id
                result["evaluacion_id"] = evaluation_id
                self.after(0, lambda: self._classification_done(result))
            except Exception as error:
                message = f"No se pudo clasificar/guardar: {error}"
                self.after(0, lambda message=message: self._classification_error(message))

        threading.Thread(target=worker, daemon=True).start()

    def _classification_done(self, result):
        self._button_busy(self.classify_incident_button, False)
        self.selected_incident_id = result["incidente_id"]
        editable = {
            key: result[key]
            for key in ("categoria", "prioridad", "entidades", "resumen")
        }
        self._replace_text(self.classification_output, json.dumps(editable, ensure_ascii=False, indent=2))
        self.state_var.set("nuevo")
        self.refresh_incidents()
        self._set_status(
            f"Incidente guardado ({result['metodo']}); revisión humana: "
            f"{'sí' if result['requiere_revision_humana'] else 'no'}; "
            f"latencia LLM {result['latencia_ms']} ms."
        )

    def _classification_error(self, message):
        self._button_busy(self.classify_incident_button, False)
        self._set_status(message, "error")

    def _button_busy(self, button, busy):
        button.configure(state="disabled" if busy else "normal")

    def update_incident(self):
        if not self.selected_incident_id:
            self._set_status("Selecciona un incidente antes de guardar cambios.", "error")
            return
        try:
            classification = ClasificacionCorreo.model_validate_json(
                self.classification_output.get("1.0", "end").strip()
            )
            db = self._get_db()
            incident = obtener_documento(db, "incidentes", self.selected_incident_id)
            if not incident:
                raise ValueError("El incidente seleccionado ya no existe.")
            old_state = incident.get("estado", "nuevo")
            new_state = self.state_var.get()
            history = incident.get("historico", [])
            if not isinstance(history, list):
                history = []
            history.append({
                "fecha": datetime.now(timezone.utc).isoformat(),
                "evento": "edicion_clasificacion_o_estado",
                "estado_anterior": old_state,
                "estado": new_state,
            })
            updated = actualizar_documento(
                db,
                "incidentes",
                self.selected_incident_id,
                {
                    "clasificacion": classification.model_dump(),
                    "datos_extraidos": classification.entidades,
                    "estado": new_state,
                    "historico": history,
                },
            )
            if not updated:
                self._set_status("No hubo cambios que guardar.")
            else:
                self.refresh_incidents()
                self._set_status("Clasificación y estado actualizados; cambio agregado al historial.")
        except (ValueError, ValidationError, PyMongoError, ConnectionError) as error:
            self._set_status(f"Revisa los campos antes de guardar: {error}", "error")

    def refresh_incidents(self):
        if not hasattr(self, "incident_list"):
            return
        for child in self.incident_list.winfo_children():
            child.destroy()
        try:
            records = listar_documentos(self._get_db(), "incidentes", limite=100)
            for record in records:
                classification = record.get("clasificacion", {})
                title = (
                    f"{classification.get('prioridad', 'sin prioridad').upper()}  ·  "
                    f"{classification.get('categoria', 'sin categoría')}  ·  "
                    f"{record.get('estado', 'nuevo')}  ·  {record['_id'][:8]}"
                )
                ctk.CTkButton(
                    self.incident_list,
                    text=title,
                    anchor="w",
                    height=32,
                    fg_color="#F3F6F3",
                    hover_color="#E4EEE6",
                    text_color=PALETA["tinta"],
                    command=lambda item=record: self.select_incident(item),
                ).pack(fill="x", pady=2)
        except (PyMongoError, ConnectionError, ValueError) as error:
            _crear_etiqueta(self.incident_list, f"MongoDB no disponible: {error}", 10, PALETA["rojo"]).pack(anchor="w")

    def select_incident(self, incident):
        self.selected_incident_id = incident["_id"]
        self.email_input.delete("1.0", "end")
        self.email_input.insert("1.0", incident.get("correo_original", ""))
        self._replace_text(
            self.classification_output,
            json.dumps(incident.get("clasificacion", {}), ensure_ascii=False, indent=2),
        )
        self.state_var.set(incident.get("estado", "nuevo"))
        self._set_status(f"Editando incidente {self.selected_incident_id}.")

    def run_evaluation(self):
        if self.simulation_var.get():
            self._set_status("Desactiva modo simulación para comparar con Ollama.", "error")
            return
        self._set_status("Evaluando 30 correos con Ollama…", "busy")

        def worker():
            try:
                results = evaluar_clasificadores(
                    cliente=self._ollama_client(),
                    modelo=self.settings["modelo"],
                )
                self.after(0, lambda: self._evaluation_done(results))
            except Exception as error:
                message = f"Evaluación fallida: {error}"
                self.after(0, lambda message=message: self._set_status(message, "error"))

        threading.Thread(target=worker, daemon=True).start()

    def _evaluation_done(self, results):
        lines = [
            f"Muestras: {results['muestras']} · Modelo: {results['modelo']}",
            f"Latencia media LLM: {results['latencia_media_ms']} ms · Total: {results['latencia_total_ms']} ms",
            f"Respuestas inválidas/fallidas: {results['respuestas_llm_invalidas_o_fallidas']}",
        ]
        for method in ("reglas", "llm", "hibrido"):
            metrics = results[method]
            lines.extend((
                "",
                f"{method.upper()}: exactitud {metrics['exactitud']:.1%} ({metrics['aciertos']}/{metrics['total']})",
                json.dumps(metrics["matriz_confusion"], ensure_ascii=False),
            ))
        self._replace_text(self.eval_output, "\n".join(lines))
        self._set_status("Evaluación completada. Revisa exactitud, matrices y latencia.")

    def _build_assistant_tab(self):
        page = self._tab_scroll("Asistente")
        self._section_title(page, "RAG · MongoDB primero", "Asistente explicativo", "Las respuestas se basan en registros recuperados y muestran sus fuentes.")
        card = self._card(page, "Conversación", "Ejemplo: ¿por qué CAM-102 fue enviado a inspección?")
        card.pack(fill="both", expand=True, padx=15, pady=(0, 12))
        self.assistant_output = self._textbox(card, 380)
        self.assistant_output.pack(fill="both", expand=True, padx=13, pady=(0, 10))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=13, pady=(0, 13))
        self.assistant_input = self._entry(row, "Pregunta sobre CAM-ID, placa o incidente…")
        self.assistant_input.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._button(row, "Preguntar", self.ask_assistant, primary=True).pack(side="right")
        self.assistant_input.bind("<Return>", lambda _event: self.ask_assistant())

    def ask_assistant(self):
        question = self.assistant_input.get().strip()
        if not question:
            self._set_status("Escribe una pregunta.", "error")
            return
        self.assistant_input.delete(0, "end")
        self.assistant_output.configure(state="normal")
        self.assistant_output.insert("end", f"\nOPERADOR\n{question}\n\nASISTENTE · consultando MongoDB…\n")
        self.assistant_output.configure(state="disabled")
        self._set_status("Buscando registros y consultando Ollama…", "busy")

        def worker():
            try:
                response = responder_con_contexto(
                    self._get_db(),
                    question,
                    cliente=self._ollama_client(),
                    modelo=self.settings["modelo"],
                )
                self.after(0, lambda: self._assistant_done(response))
            except Exception as error:
                message = f"Asistente no disponible: {error}"
                self.after(0, lambda message=message: self._set_status(message, "error"))

        threading.Thread(target=worker, daemon=True).start()

    def _assistant_done(self, response):
        self.assistant_output.configure(state="normal")
        self.assistant_output.insert("end", f"{response['respuesta']}\n")
        if response["fuentes"]:
            citations = ", ".join(
                f"[{source['coleccion']}:{source['id']}]"
                for source in response["fuentes"]
            )
            self.assistant_output.insert("end", f"Fuentes: {citations}\n")
        self.assistant_output.insert("end", "\n")
        self.assistant_output.see("end")
        self.assistant_output.configure(state="disabled")
        self._set_status("Respuesta basada en contexto recuperado." if response["fuentes"] else "Sin información coincidente.")

    def _build_risks_tab(self):
        page = self._tab_scroll("Riesgos éticos")
        self._section_title(page, "Matriz ética", "Riesgos y mitigaciones", "Registra riesgo inherente y residual; la gráfica se calcula desde MongoDB.")
        cards = ctk.CTkFrame(page, fg_color="transparent")
        cards.pack(fill="both", expand=True, padx=15)
        cards.grid_columnconfigure(0, weight=5, uniform="risk")
        cards.grid_columnconfigure(1, weight=6, uniform="risk")
        form = self._card(cards, "Riesgo", "Selecciona uno para editar o crea un registro nuevo.")
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        body = ctk.CTkFrame(form, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=13, pady=13)
        self.risk_module = self._entry(body, "Módulo")
        self.risk_module.pack(fill="x", pady=3)
        self.risk_category = ctk.CTkOptionMenu(body, values=["seguridad", "sesgo", "privacidad", "automatización", "alucinación", "otro"], height=34)
        self.risk_category.pack(fill="x", pady=3)
        self.risk_description = self._textbox(body, 72)
        self.risk_description.pack(fill="x", pady=3)
        self.risk_mitigation = self._textbox(body, 72)
        self.risk_mitigation.pack(fill="x", pady=3)
        numbers = ctk.CTkFrame(body, fg_color="transparent")
        numbers.pack(fill="x", pady=3)
        self.risk_probability = self._entry(numbers, "Probabilidad 1–5", width=115)
        self.risk_probability.pack(side="left", padx=(0, 4))
        self.risk_impact = self._entry(numbers, "Impacto 1–5", width=105)
        self.risk_impact.pack(side="left", padx=4)
        self.risk_before = self._entry(numbers, "Antes 1–25", width=95)
        self.risk_before.pack(side="left", padx=4)
        self.risk_after = self._entry(numbers, "Residual 1–25", width=105)
        self.risk_after.pack(side="left", padx=(4, 0))
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", pady=(7, 0))
        self._button(actions, "Guardar", self.save_risk, primary=True).pack(side="left")
        self._button(actions, "Limpiar", self.clear_risk_form, width=90).pack(side="left", padx=6)
        self._button(actions, "Eliminar", self.delete_risk, width=90).pack(side="right")

        graph = self._card(cards, "Puntaje residual por riesgo", "Comparación antes/después · escala 1–25")
        graph.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.risk_graph = ctk.CTkScrollableFrame(graph, height=280, fg_color="transparent")
        self.risk_graph.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.risk_list = ctk.CTkScrollableFrame(graph, height=170, fg_color="transparent")
        self.risk_list.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.refresh_risks()

    def refresh_risks(self):
        for frame in (getattr(self, "risk_graph", None), getattr(self, "risk_list", None)):
            if frame:
                for child in frame.winfo_children():
                    child.destroy()
        try:
            records = listar_documentos(self._get_db(), "riesgos_eticos", limite=200)
            if not records:
                _crear_etiqueta(self.risk_graph, "No hay riesgos registrados.", 11, PALETA["suave"]).pack(anchor="w")
                return
            for risk in records:
                title = risk.get("descripcion", "Riesgo")[:48]
                row = ctk.CTkFrame(self.risk_graph, fg_color="transparent")
                row.pack(fill="x", pady=6)
                row.grid_columnconfigure(1, weight=1)
                _crear_etiqueta(row, title, 9, PALETA["tinta"], wraplength=180).grid(row=0, column=0, sticky="w", padx=(0, 8))
                bars = ctk.CTkFrame(row, fg_color="transparent")
                bars.grid(row=0, column=1, sticky="ew")
                before = ctk.CTkProgressBar(bars, height=7, progress_color=PALETA["ambar"], fg_color="#EDF0ED")
                before.pack(fill="x", pady=(1, 4))
                before.set(float(risk.get("puntaje_antes", 0)) / 25)
                after = ctk.CTkProgressBar(bars, height=7, progress_color=PALETA["verde"], fg_color="#EDF0ED")
                after.pack(fill="x")
                after.set(float(risk.get("puntaje_despues", 0)) / 25)
                _crear_etiqueta(row, f"{risk.get('puntaje_antes', 0)}→{risk.get('puntaje_despues', 0)}", 9, PALETA["suave"], True).grid(row=0, column=2, padx=(7, 0))
                ctk.CTkButton(
                    self.risk_list,
                    text=f"{risk.get('categoria', 'riesgo')} · {risk.get('modulo', '')} · {title}",
                    anchor="w",
                    height=29,
                    fg_color="#F2F5F2",
                    hover_color="#E2ECE4",
                    text_color=PALETA["tinta"],
                    command=lambda item=risk: self.select_risk(item),
                ).pack(fill="x", pady=2)
        except (PyMongoError, ConnectionError, ValueError) as error:
            _crear_etiqueta(self.risk_graph, f"No se pudo cargar riesgos: {error}", 10, PALETA["rojo"]).pack(anchor="w")

    def select_risk(self, risk):
        self.selected_risk_id = risk["_id"]
        self._set_entry(self.risk_module, risk.get("modulo", ""))
        self.risk_category.set(risk.get("categoria", "otro"))
        self._replace_text(self.risk_description, risk.get("descripcion", ""))
        self._replace_text(self.risk_mitigation, risk.get("mitigacion", ""))
        self._set_entry(self.risk_probability, str(risk.get("probabilidad", "")))
        self._set_entry(self.risk_impact, str(risk.get("impacto", "")))
        self._set_entry(self.risk_before, str(risk.get("puntaje_antes", "")))
        self._set_entry(self.risk_after, str(risk.get("puntaje_despues", "")))
        self._set_status(f"Riesgo seleccionado: {self.selected_risk_id}.")

    def _risk_payload(self):
        probability = int(self.risk_probability.get())
        impact = int(self.risk_impact.get())
        before = int(self.risk_before.get())
        after = int(self.risk_after.get())
        history = []
        if self.selected_risk_id:
            current = obtener_documento(self._get_db(), "riesgos_eticos", self.selected_risk_id)
            history = current.get("historico", []) if current else []
        history.append({
            "fecha": datetime.now(timezone.utc).isoformat(),
            "puntaje_antes": before,
            "puntaje_despues": after,
        })
        return {
            "modulo": self.risk_module.get().strip(),
            "descripcion": self.risk_description.get("1.0", "end").strip(),
            "categoria": self.risk_category.get(),
            "probabilidad": probability,
            "impacto": impact,
            "mitigacion": self.risk_mitigation.get("1.0", "end").strip(),
            "puntaje_antes": before,
            "puntaje_despues": after,
            "historico": history,
        }

    def save_risk(self):
        try:
            payload = self._risk_payload()
            if not payload["modulo"] or not payload["descripcion"] or not payload["mitigacion"]:
                raise ValueError("Completa módulo, descripción y mitigación.")
            if self.selected_risk_id:
                actualizar_documento(self._get_db(), "riesgos_eticos", self.selected_risk_id, payload)
            else:
                self.selected_risk_id = crear_documento(self._get_db(), "riesgos_eticos", payload)
            self.refresh_risks()
            self.refresh_dashboard()
            self._set_status("Riesgo guardado y gráfico actualizado.")
        except (ValueError, PyMongoError, ConnectionError) as error:
            self._set_status(f"No se guardó el riesgo: {error}", "error")

    def delete_risk(self):
        if not self.selected_risk_id:
            self._set_status("Selecciona un riesgo para eliminar.", "error")
            return
        if not messagebox.askyesno("Eliminar riesgo", "¿Eliminar el riesgo seleccionado?", parent=self):
            return
        try:
            eliminar_documento(self._get_db(), "riesgos_eticos", self.selected_risk_id)
            self.selected_risk_id = None
            self.clear_risk_form()
            self.refresh_risks()
            self.refresh_dashboard()
            self._set_status("Riesgo eliminado.")
        except (ValueError, PyMongoError, ConnectionError) as error:
            self._set_status(f"No se pudo eliminar: {error}", "error")

    def clear_risk_form(self):
        self.selected_risk_id = None
        for field in (self.risk_module, self.risk_probability, self.risk_impact, self.risk_before, self.risk_after):
            field.delete(0, "end")
        self.risk_category.set("seguridad")
        self._replace_text(self.risk_description, "")
        self._replace_text(self.risk_mitigation, "")

    def _build_crud_tab(self):
        page = self._tab_scroll("Registros CRUD")
        self._section_title(page, "Persistencia", "Administrar colecciones", "Alta, consulta, edición y baja para camiones, accesos, incidentes, riesgos y evaluaciones LLM.")
        tools = ctk.CTkFrame(page, fg_color="transparent")
        tools.pack(fill="x", padx=15, pady=(0, 10))
        self.collection_var = ctk.StringVar(value="camiones")
        ctk.CTkOptionMenu(tools, values=list(COLECCIONES), variable=self.collection_var, command=lambda _value: self.refresh_records(), width=190, height=36).pack(side="left", padx=(0, 8))
        self._button(tools, "Actualizar lista", self.refresh_records).pack(side="left")
        columns = ctk.CTkFrame(page, fg_color="transparent")
        columns.pack(fill="both", expand=True, padx=15)
        columns.grid_columnconfigure((0, 1), weight=1, uniform="records")
        list_card = self._card(columns, "Registros encontrados", "Selecciona un elemento para editarlo.")
        list_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.record_list = ctk.CTkScrollableFrame(list_card, height=420, fg_color="transparent")
        self.record_list.pack(fill="both", expand=True, padx=11, pady=(0, 11))
        form = self._card(columns, "Documento JSON", "La validación de campos se aplica al guardar.")
        form.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.record_json = self._textbox(form, 420)
        self.record_json.pack(fill="both", expand=True, padx=12, pady=(0, 9))
        actions = ctk.CTkFrame(form, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(0, 12))
        self._button(actions, "Crear", self.create_record, primary=True, width=82).pack(side="left")
        self._button(actions, "Actualizar", self.update_record, width=100).pack(side="left", padx=5)
        self._button(actions, "Eliminar", self.delete_record, width=82).pack(side="right")
        self.refresh_records()

    def refresh_records(self):
        if not hasattr(self, "record_list"):
            return
        for child in self.record_list.winfo_children():
            child.destroy()
        try:
            collection = self.collection_var.get()
            records = listar_documentos(self._get_db(), collection, limite=200)
            if not records:
                _crear_etiqueta(self.record_list, "No hay registros en esta colección.", 10, PALETA["suave"]).pack(anchor="w")
            for record in records:
                label = self._record_summary(collection, record)
                ctk.CTkButton(
                    self.record_list,
                    text=label,
                    anchor="w",
                    height=32,
                    fg_color="#F2F5F2",
                    hover_color="#E2ECE4",
                    text_color=PALETA["tinta"],
                    command=lambda item=record: self.select_record(item),
                ).pack(fill="x", pady=2)
        except (ValueError, PyMongoError, ConnectionError) as error:
            _crear_etiqueta(self.record_list, f"No se pudo consultar MongoDB: {error}", 10, PALETA["rojo"], wraplength=330).pack(anchor="w")

    @staticmethod
    def _record_summary(collection, record):
        for key in ("camion_id", "placa", "estado", "modulo", "modelo"):
            if record.get(key):
                return f"{key}: {record[key]} · {record['_id'][:8]}"
        classification = record.get("clasificacion")
        if isinstance(classification, dict):
            return f"{classification.get('categoria', 'incidente')} · {record['_id'][:8]}"
        return f"{collection} · {record['_id'][:8]}"

    def select_record(self, record):
        self.selected_record_id = record["_id"]
        self._replace_text(self.record_json, json.dumps(record, ensure_ascii=False, indent=2, default=str))
        self._set_status(f"Registro seleccionado: {self.selected_record_id}.")

    def create_record(self):
        try:
            document = json.loads(self.record_json.get("1.0", "end").strip())
            document.pop("_id", None)
            identifier = crear_documento(self._get_db(), self.collection_var.get(), document)
            self.selected_record_id = identifier
            self.refresh_records()
            self._set_status(f"Registro creado: {identifier}.")
        except (json.JSONDecodeError, TypeError, ValueError, PyMongoError, ConnectionError) as error:
            self._set_status(f"No se creó el registro: {error}", "error")

    def update_record(self):
        if not self.selected_record_id:
            self._set_status("Selecciona un registro para actualizar.", "error")
            return
        try:
            document = json.loads(self.record_json.get("1.0", "end").strip())
            document.pop("_id", None)
            updated = actualizar_documento(
                self._get_db(), self.collection_var.get(), self.selected_record_id, document
            )
            self.refresh_records()
            self._set_status("Registro actualizado." if updated else "No hubo cambios.")
        except (json.JSONDecodeError, TypeError, ValueError, PyMongoError, ConnectionError) as error:
            self._set_status(f"No se actualizó: {error}", "error")

    def delete_record(self):
        if not self.selected_record_id:
            self._set_status("Selecciona un registro para eliminar.", "error")
            return
        if not messagebox.askyesno("Eliminar registro", "¿Eliminar el registro seleccionado?", parent=self):
            return
        try:
            deleted = eliminar_documento(self._get_db(), self.collection_var.get(), self.selected_record_id)
            self.selected_record_id = None
            self._replace_text(self.record_json, "")
            self.refresh_records()
            self._set_status("Registro eliminado." if deleted else "Registro no encontrado.")
        except (ValueError, PyMongoError, ConnectionError) as error:
            self._set_status(f"No se pudo eliminar: {error}", "error")

    def _build_reports_tab(self):
        page = self._tab_scroll("Reportes")
        self._section_title(page, "Exportación", "Reportes del sistema", "Descarga registros de MongoDB en JSON, CSV o PDF.")
        card = self._card(page, "Exportar colección", "Los documentos se limitan a 1,000 registros por exportación.")
        card.pack(fill="x", padx=15, pady=(0, 15))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=15)
        self.export_collection_var = ctk.StringVar(value="incidentes")
        ctk.CTkOptionMenu(row, values=list(COLECCIONES), variable=self.export_collection_var, width=190, height=36).pack(side="left", padx=(0, 8))
        self.export_format_var = ctk.StringVar(value="csv")
        ctk.CTkOptionMenu(row, values=["json", "csv", "pdf"], variable=self.export_format_var, width=100, height=36).pack(side="left", padx=(0, 8))
        self._button(row, "Exportar", self.export_report, primary=True).pack(side="left")
        _crear_etiqueta(card, "La exportación incluye los documentos existentes; no genera datos de demostración.", 10, PALETA["suave"]).pack(anchor="w", padx=15, pady=(0, 15))

    def export_report(self):
        try:
            collection = self.export_collection_var.get()
            records = listar_documentos(self._get_db(), collection, limite=1000)
            fmt = self.export_format_var.get()
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Guardar reporte",
                defaultextension=f".{fmt}",
                initialfile=f"logismart_{collection}.{fmt}",
                filetypes=[(fmt.upper(), f"*.{fmt}")],
            )
            if not path:
                return
            if fmt == "json":
                Path(path).write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            elif fmt == "csv":
                self._write_csv(Path(path), records)
            else:
                self._write_pdf(Path(path), records)
            self._set_status(f"Reporte exportado: {path}")
        except (OSError, ValueError, PyMongoError, ConnectionError) as error:
            self._set_status(f"No se pudo exportar: {error}", "error")

    @staticmethod
    def _write_csv(path, records):
        fields = sorted({key for record in records for key in record})
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            if not fields:
                file.write("Sin registros\n")
                return
            writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for record in records:
                writer.writerow({
                    key: json.dumps(value, ensure_ascii=False, default=str)
                    if isinstance(value, (dict, list)) else value
                    for key, value in record.items()
                })

    @staticmethod
    def _write_pdf(path, records):
        fields = sorted({key for record in records for key in record})
        data = [[field.upper() for field in fields]] if fields else [["SIN REGISTROS"]]
        for record in records:
            data.append([
                json.dumps(record.get(field, ""), ensure_ascii=False, default=str)[:160]
                for field in fields
            ])
        document = SimpleDocTemplate(str(path), pagesize=landscape(letter))
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(PALETA["bosque"])),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor(PALETA["linea"])),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        document.build([table])

    def _build_settings_tab(self):
        page = self._tab_scroll("Configuración")
        self._section_title(page, "Servicios locales", "Configuración", "El modelo y host se guardan en tu perfil de usuario, no en el repositorio.")
        card = self._card(page, "Ollama y clasificación", "Puedes activar el modo simulación para clasificar con reglas sin invocar al modelo.")
        card.pack(fill="x", padx=15, pady=(0, 15))
        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="x", padx=15, pady=15)
        _crear_etiqueta(form, "Modelo Ollama", 10, PALETA["suave"], True).pack(anchor="w")
        self.settings_model = self._entry(form, "llama3.2")
        self.settings_model.insert(0, self.settings["modelo"])
        self.settings_model.pack(fill="x", pady=(4, 12))
        _crear_etiqueta(form, "Host Ollama", 10, PALETA["suave"], True).pack(anchor="w")
        self.settings_host = self._entry(form, "http://127.0.0.1:11434")
        self.settings_host.insert(0, self.settings["ollama_host"])
        self.settings_host.pack(fill="x", pady=(4, 12))
        _crear_etiqueta(form, "Umbral de riesgo crítico · 1–25", 10, PALETA["suave"], True).pack(anchor="w")
        self.settings_threshold = self._entry(form, "15")
        self.settings_threshold.insert(0, str(self.settings["umbral_riesgo"]))
        self.settings_threshold.pack(fill="x", pady=(4, 12))
        ctk.CTkSwitch(
            form,
            text="Modo simulación (reglas locales, sin Ollama)",
            variable=self.simulation_var,
            progress_color=PALETA["verde"],
        ).pack(anchor="w", pady=(1, 13))
        self._button(form, "Guardar configuración", self.save_settings, primary=True).pack(anchor="e")

    def save_settings(self):
        try:
            model = self.settings_model.get().strip()
            host = self.settings_host.get().strip()
            threshold = int(self.settings_threshold.get())
            if not model or not host:
                raise ValueError("Modelo y host son obligatorios.")
            if threshold < 1 or threshold > 25:
                raise ValueError("El umbral debe estar entre 1 y 25.")
            self.settings.update({
                "modelo": model,
                "ollama_host": host,
                "umbral_riesgo": threshold,
                "simulacion": self.simulation_var.get(),
            })
            self.model_var.set(model)
            self._save_settings_file()
            self.refresh_dashboard()
            self._set_status("Configuración guardada.")
        except (ValueError, OSError) as error:
            self._set_status(f"Configuración inválida: {error}", "error")

    @staticmethod
    def _replace_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)

    @staticmethod
    def _set_entry(widget, text):
        widget.delete(0, "end")
        widget.insert(0, text)

    def _close(self):
        if self.mongo_client is not None:
            self.mongo_client.close()
        self.destroy()


if __name__ == "__main__":
    LogiSmartApp().mainloop()