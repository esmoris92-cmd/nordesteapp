"""Preguntas de la Ficha de Anamnesis Multidisciplinaria, para la exportación de una clínica.

Es una COPIA de ``frontend/src/pages/anamnesisForm.ts`` (la interfaz es la que define las
preguntas; la base solo guarda {clave: respuesta}). La exportación la usa para mostrar cada
respuesta con su pregunta. La prueba ``tests/test_exportacion_clinica.py`` compara las dos
listas: si alguien cambia una pregunta en un lado y no en el otro, la prueba falla y avisa.

Igual que en la interfaz: NO cambiar ni reutilizar una clave existente.
"""

from typing import NamedTuple


class Field(NamedTuple):
    key: str
    label: str
    type: str = "text"  # "text", "long", "yesno", "date" u "options"


class Group(NamedTuple):
    title: str | None
    fields: tuple[Field, ...]
    siblings: bool = False  # lista de hermanos (hermano_N_nombre / hermano_N_edad)


class Section(NamedTuple):
    id: str
    title: str
    groups: tuple[Group, ...]


MAX_SIBLINGS = 8


def sibling_keys(n: int) -> tuple[str, str]:
    return f"hermano_{n}_nombre", f"hermano_{n}_edad"


SECTIONS: tuple[Section, ...] = (
    Section("encabezado", "Datos de la entrevista", (
        Group(None, (
            Field("fecha_entrevista", "Fecha de la entrevista", "date"),
            Field("grado", "Grado que cursa"),
            Field("asistencia_medica", "Asistencia médica"),
        )),
    )),
    Section("motivo", "1. Motivo de consulta", (
        Group(None, (
            Field("motivo_dificultad", "¿Cuál es la dificultad del niño/a? ¿Desde cuándo la notó?", "long"),
            Field("motivo_derivado_por", "Derivado por"),
            Field("motivo_tratamientos_previos", "Tratamientos y/o evaluaciones anteriores", "long"),
            Field("motivo_presenta_informes", "Presenta informes", "yesno"),
        )),
    )),
    Section("antecedentes", "2. Antecedentes del caso", (
        Group(None, (
            Field("antecedentes_familia_similar", "¿Algún antecedente similar en la familia?", "long"),
        )),
    )),
    Section("familia", "3. Grupo familiar y convivencia", (
        Group(None, (
            Field("familia_vive_con", "Vive con"),
        )),
        Group("Datos de la madre", (
            Field("madre_nombre", "Nombre y apellidos"),
            Field("madre_edad", "Edad"),
            Field("madre_ocupacion", "Ocupación"),
        )),
        Group("Datos del padre", (
            Field("padre_nombre", "Nombre y apellidos"),
            Field("padre_edad", "Edad"),
            Field("padre_ocupacion", "Ocupación"),
        )),
        Group("Hermanos", (), siblings=True),
        Group(None, (
            Field("familia_relacion", "¿Cómo es la relación con los miembros de la familia?", "long"),
            Field("familia_quien_cuida", "¿Quién lo/a cuida habitualmente?"),
            Field("familia_evento_critico", "¿Ha habido algún evento determinante o crítico en su vida?", "long"),
        )),
    )),
    Section("desarrollo", "4. Antecedentes de desarrollo", (
        Group("Embarazo", (
            Field("embarazo_numero_gesta", "Número de gesta"),
            Field("embarazo_complicaciones", "Complicaciones", "long"),
        )),
        Group("Parto", (
            Field("parto_tipo", "Tipo de parto", "options"),
            Field("parto_peso", "Peso al nacer"),
            Field("parto_incubadora", "Incubadora", "yesno"),
        )),
        Group("Desarrollo motor", (
            Field("motor_sentarse", "Edad al sentarse"),
            Field("motor_gateo", "Edad del gateo"),
            Field("motor_caminar", "Edad al caminar"),
            Field("motor_caidas", "¿Sufrió caídas?"),
        )),
        Group("Lenguaje", (
            Field("lenguaje_primeras_palabras", "Primeras palabras (edad / pronunciación)"),
            Field("lenguaje_primeras_frases", "Primeras frases"),
            Field("lenguaje_intencion", "Intención comunicativa"),
        )),
        Group("Sueño", (
            Field("sueno_duerme_solo", "¿Duerme solo/a? ¿Desde qué edad?"),
            Field("sueno_dificultades", "¿Dificultades para dormir o despertarse?"),
            Field("sueno_temores", "Temores, pesadillas"),
            Field("sueno_horas", "¿Cuántas horas duerme?"),
        )),
        Group("Control de esfínteres", (
            Field("esfinteres_edad", "Edad de control (diurno / nocturno)"),
            Field("esfinteres_orina", "Orina"),
            Field("esfinteres_materia_fecal", "Materia fecal"),
        )),
    )),
    Section("salud", "5. Salud", (
        Group(None, (
            Field("salud_vision", "Visión"),
        )),
        Group("Lenguaje", (
            Field("salud_lenguaje_comunicacion", "Forma de comunicación actual"),
            Field("salud_lenguaje_dificultades", "¿Presenta dificultades en el lenguaje?"),
        )),
        Group("Audición", (
            Field("salud_audicion", "Audición"),
            Field("salud_audicion_antecedentes", "Antecedentes familiares de problemas de audición"),
        )),
        Group(None, (
            Field("salud_patologias_familia", "¿Hay antecedentes de patologías en la familia?", "long"),
            Field("salud_enfermedades", "Enfermedades / operaciones / internaciones / accidentes (con la edad)", "long"),
            Field("salud_medicacion", "Toma medicación", "yesno"),
            Field("salud_medicacion_cual", "¿Cuál?"),
            Field("salud_ultimo_control", "Último control pediátrico"),
        )),
    )),
    Section("juegos", "6. Juegos y socialización", (
        Group(None, (
            Field("juegos_preferidos", "¿Qué juegos le gustan?"),
            Field("juegos_juguetes", "Juguetes favoritos"),
            Field("juegos_solo", "¿Le gusta jugar solo/a?", "yesno"),
            Field("juegos_con_quien", "¿Con quién juega?"),
            Field("juegos_pantallas", "Tiempo de uso de pantallas"),
            Field("juegos_controles_parentales", "¿Tiene controles parentales en dispositivos electrónicos?", "yesno"),
        )),
    )),
    Section("escolaridad", "7. Escolaridad", (
        Group(None, (
            Field("escuela_edad_inicio", "Edad en que inició la etapa escolar"),
            Field("escuela_curso_desempeno", "Curso actual y desempeño", "long"),
            Field("escuela_repeticiones", "Repeticiones"),
            Field("escuela_apoyo", "Apoyo escolar", "yesno"),
            Field("escuela_extracurriculares", "Actividades extracurriculares"),
            Field("escuela_relacion", "Relación con pares y adultos", "long"),
            Field("escuela_actitud", "Actitud frente a las tareas escolares", "long"),
            Field("escuela_tiempo_deberes", "Tiempo que demora en realizar los deberes"),
            Field("escuela_maestra", "Maestra actual"),
        )),
    )),
    Section("areas", "8. Evaluación por áreas específicas", (
        Group("Fonoaudiología", (
            Field("fono_dificultades", "¿Ha tenido dificultades en el lenguaje en cuanto a la pronunciación y/o comprensión?", "long"),
            Field("fono_antecedentes", "¿Tiene antecedentes familiares con dificultades en el lenguaje?", "long"),
            Field("fono_desarrollo", "¿Cómo describiría su desarrollo del lenguaje?", "long"),
            Field("fono_motricidad_orofacial", "A nivel de motricidad orofacial (ortodoncia)", "long"),
            Field("fono_malos_habitos", "¿Presenta malos hábitos orales?", "long"),
            Field("fono_consulta_previa", "¿Alguna vez había acudido a fonoaudiólogo/a antes?", "long"),
        )),
        Group("Psicopedagogía", (
            Field("psicoped_desempeno", "¿Cómo es su desempeño en las tareas escolares?", "long"),
            Field("psicoped_lectoescritura", "¿Tiene dificultades para leer, escribir o en matemáticas?", "long"),
            Field("psicoped_apoyo", "¿Recibe apoyo escolar adicional?", "long"),
            Field("psicoped_antecedentes", "¿Presenta antecedentes de dificultad de aprendizaje, fracaso escolar o asistencia a escuelas especiales?", "long"),
        )),
        Group("Psicología", (
            Field("psico_animo", "¿Ha mostrado cambios en su estado de ánimo o comportamiento?", "long"),
            Field("psico_temores", "¿Tiene temores o ansiedades notables?", "long"),
            Field("psico_frustracion", "¿Cómo maneja la frustración o situaciones de estrés?", "long"),
        )),
        Group("Educación especial", (
            Field("edesp_evaluado", "¿Ha sido evaluado/a para necesidades educativas especiales?", "long"),
            Field("edesp_diagnostico", "¿Tiene algún diagnóstico previo relacionado con el aprendizaje?", "long"),
            Field("edesp_entorno", "¿Cómo se desenvuelve en el entorno escolar?", "long"),
        )),
        Group("Terapia ocupacional", (
            Field("to_motricidad_fina", "¿Tiene dificultades en la motricidad fina (abotonarse, atarse los cordones)?", "long"),
            Field("to_motricidad_gruesa", "¿Hay problemas en la motricidad gruesa (saltar, correr)?", "long"),
            Field("to_independencia", "¿Muestra independencia en actividades cotidianas (vestirse, comer)?", "long"),
        )),
        Group("Psicomotricidad", (
            Field("psicomot_coordinacion", "¿Presenta dificultades en la coordinación motora?", "long"),
            Field("psicomot_equilibrio", "¿Cómo es su equilibrio al caminar o correr?", "long"),
            Field("psicomot_planificacion", "¿Muestra dificultades en la planificación de movimientos?", "long"),
            Field("psicomot_actividad_fisica", "¿Realiza actividades físicas (deportes, juegos de movimiento)?", "long"),
            Field("psicomot_coordinacion_diaria", "¿Tiene problemas para coordinar movimientos en actividades diarias (dibujar, escribir, manipular objetos)?", "long"),
            Field("psicomot_conducta_hogar", "¿Cómo es su conducta en el hogar?", "long"),
            Field("psicomot_dificultades_hogar", "En casa, ¿presenta dificultades en el desarrollo de habilidades motoras, cognitivas, emocionales o sociales?", "long"),
            Field("psicomot_sensorial", "Según la edad: ¿disfruta manipular distintos elementos sensoriales (arena, agua, masa, etc.)?", "long"),
            Field("psicomot_pintar", "¿Le gusta pintar, dibujar con lápices de colores, pintura?", "long"),
        )),
    )),
    Section("entrevistado", "Persona entrevistada", (
        Group(None, (
            Field("entrevistado_nombre", "Nombre de la persona entrevistada"),
            Field("entrevistado_parentesco", "Parentesco con el niño/a"),
        )),
    )),
)
