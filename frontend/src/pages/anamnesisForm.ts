// Estructura de la Ficha de Anamnesis Multidisciplinaria (según el modelo en Word de la clínica).
//
// Cada campo tiene una clave fija: es lo que se guarda en la base (anamnesis_versions.data).
// Se pueden cambiar los textos de las preguntas o agregar campos nuevos sin perder nada, pero
// NO cambiar ni reutilizar una clave existente: lo ya guardado dejaría de mostrarse.

export type FieldType = "text" | "long" | "yesno" | "date" | { options: string[] };

export interface FieldDef {
  key: string;
  label: string;
  type?: FieldType; // por defecto "text" (una línea)
}

export interface Group {
  title?: string;
  fields: FieldDef[];
  /** Lista de hermanos (nombre y edad), con filas que se agregan según haga falta. */
  siblings?: boolean;
}

export interface Section {
  id: string;
  title: string;
  groups: Group[];
  /** Sección de áreas: cada grupo es una profesión (se resalta la de quien la completa). */
  areas?: boolean;
}

export const MAX_SIBLINGS = 8;
export const siblingKeys = (n: number) => ({ name: `hermano_${n}_nombre`, age: `hermano_${n}_edad` });

export const ANAMNESIS_SECTIONS: Section[] = [
  {
    id: "encabezado", title: "Datos de la entrevista", groups: [{ fields: [
      { key: "fecha_entrevista", label: "Fecha de la entrevista", type: "date" },
      { key: "grado", label: "Grado que cursa" },
      { key: "asistencia_medica", label: "Asistencia médica" },
    ] }],
  },
  {
    id: "motivo", title: "1. Motivo de consulta", groups: [{ fields: [
      { key: "motivo_dificultad", label: "¿Cuál es la dificultad del niño/a? ¿Desde cuándo la notó?", type: "long" },
      { key: "motivo_derivado_por", label: "Derivado por" },
      { key: "motivo_tratamientos_previos", label: "Tratamientos y/o evaluaciones anteriores", type: "long" },
      { key: "motivo_presenta_informes", label: "Presenta informes", type: "yesno" },
    ] }],
  },
  {
    id: "antecedentes", title: "2. Antecedentes del caso", groups: [{ fields: [
      { key: "antecedentes_familia_similar", label: "¿Algún antecedente similar en la familia?", type: "long" },
    ] }],
  },
  {
    id: "familia", title: "3. Grupo familiar y convivencia", groups: [
      { fields: [{ key: "familia_vive_con", label: "Vive con" }] },
      { title: "Datos de la madre", fields: [
        { key: "madre_nombre", label: "Nombre y apellidos" },
        { key: "madre_edad", label: "Edad" },
        { key: "madre_ocupacion", label: "Ocupación" },
      ] },
      { title: "Datos del padre", fields: [
        { key: "padre_nombre", label: "Nombre y apellidos" },
        { key: "padre_edad", label: "Edad" },
        { key: "padre_ocupacion", label: "Ocupación" },
      ] },
      { title: "Hermanos", fields: [], siblings: true },
      { fields: [
        { key: "familia_relacion", label: "¿Cómo es la relación con los miembros de la familia?", type: "long" },
        { key: "familia_quien_cuida", label: "¿Quién lo/a cuida habitualmente?" },
        { key: "familia_evento_critico", label: "¿Ha habido algún evento determinante o crítico en su vida?", type: "long" },
      ] },
    ],
  },
  {
    id: "desarrollo", title: "4. Antecedentes de desarrollo", groups: [
      { title: "Embarazo", fields: [
        { key: "embarazo_numero_gesta", label: "Número de gesta" },
        { key: "embarazo_complicaciones", label: "Complicaciones", type: "long" },
      ] },
      { title: "Parto", fields: [
        { key: "parto_tipo", label: "Tipo de parto", type: { options: ["Normal", "Cesárea"] } },
        { key: "parto_peso", label: "Peso al nacer" },
        { key: "parto_incubadora", label: "Incubadora", type: "yesno" },
      ] },
      { title: "Desarrollo motor", fields: [
        { key: "motor_sentarse", label: "Edad al sentarse" },
        { key: "motor_gateo", label: "Edad del gateo" },
        { key: "motor_caminar", label: "Edad al caminar" },
        { key: "motor_caidas", label: "¿Sufrió caídas?" },
      ] },
      { title: "Lenguaje", fields: [
        { key: "lenguaje_primeras_palabras", label: "Primeras palabras (edad / pronunciación)" },
        { key: "lenguaje_primeras_frases", label: "Primeras frases" },
        { key: "lenguaje_intencion", label: "Intención comunicativa" },
      ] },
      { title: "Sueño", fields: [
        { key: "sueno_duerme_solo", label: "¿Duerme solo/a? ¿Desde qué edad?" },
        { key: "sueno_dificultades", label: "¿Dificultades para dormir o despertarse?" },
        { key: "sueno_temores", label: "Temores, pesadillas" },
        { key: "sueno_horas", label: "¿Cuántas horas duerme?" },
      ] },
      { title: "Control de esfínteres", fields: [
        { key: "esfinteres_edad", label: "Edad de control (diurno / nocturno)" },
        { key: "esfinteres_orina", label: "Orina" },
        { key: "esfinteres_materia_fecal", label: "Materia fecal" },
      ] },
    ],
  },
  {
    id: "salud", title: "5. Salud", groups: [
      { fields: [{ key: "salud_vision", label: "Visión" }] },
      { title: "Lenguaje", fields: [
        { key: "salud_lenguaje_comunicacion", label: "Forma de comunicación actual" },
        { key: "salud_lenguaje_dificultades", label: "¿Presenta dificultades en el lenguaje?" },
      ] },
      { title: "Audición", fields: [
        { key: "salud_audicion", label: "Audición" },
        { key: "salud_audicion_antecedentes", label: "Antecedentes familiares de problemas de audición" },
      ] },
      { fields: [
        { key: "salud_patologias_familia", label: "¿Hay antecedentes de patologías en la familia?", type: "long" },
        { key: "salud_enfermedades", label: "Enfermedades / operaciones / internaciones / accidentes (con la edad)", type: "long" },
        { key: "salud_medicacion", label: "Toma medicación", type: "yesno" },
        { key: "salud_medicacion_cual", label: "¿Cuál?" },
        { key: "salud_ultimo_control", label: "Último control pediátrico" },
      ] },
    ],
  },
  {
    id: "juegos", title: "6. Juegos y socialización", groups: [{ fields: [
      { key: "juegos_preferidos", label: "¿Qué juegos le gustan?" },
      { key: "juegos_juguetes", label: "Juguetes favoritos" },
      { key: "juegos_solo", label: "¿Le gusta jugar solo/a?", type: "yesno" },
      { key: "juegos_con_quien", label: "¿Con quién juega?" },
      { key: "juegos_pantallas", label: "Tiempo de uso de pantallas" },
      { key: "juegos_controles_parentales", label: "¿Tiene controles parentales en dispositivos electrónicos?", type: "yesno" },
    ] }],
  },
  {
    id: "escolaridad", title: "7. Escolaridad", groups: [{ fields: [
      { key: "escuela_edad_inicio", label: "Edad en que inició la etapa escolar" },
      { key: "escuela_curso_desempeno", label: "Curso actual y desempeño", type: "long" },
      { key: "escuela_repeticiones", label: "Repeticiones" },
      { key: "escuela_apoyo", label: "Apoyo escolar", type: "yesno" },
      { key: "escuela_extracurriculares", label: "Actividades extracurriculares" },
      { key: "escuela_relacion", label: "Relación con pares y adultos", type: "long" },
      { key: "escuela_actitud", label: "Actitud frente a las tareas escolares", type: "long" },
      { key: "escuela_tiempo_deberes", label: "Tiempo que demora en realizar los deberes" },
      { key: "escuela_maestra", label: "Maestra actual" },
    ] }],
  },
  {
    id: "areas", title: "8. Evaluación por áreas específicas", areas: true, groups: [
      { title: "Fonoaudiología", fields: [
        { key: "fono_dificultades", label: "¿Ha tenido dificultades en el lenguaje en cuanto a la pronunciación y/o comprensión?", type: "long" },
        { key: "fono_antecedentes", label: "¿Tiene antecedentes familiares con dificultades en el lenguaje?", type: "long" },
        { key: "fono_desarrollo", label: "¿Cómo describiría su desarrollo del lenguaje?", type: "long" },
        { key: "fono_motricidad_orofacial", label: "A nivel de motricidad orofacial (ortodoncia)", type: "long" },
        { key: "fono_malos_habitos", label: "¿Presenta malos hábitos orales?", type: "long" },
        { key: "fono_consulta_previa", label: "¿Alguna vez había acudido a fonoaudiólogo/a antes?", type: "long" },
      ] },
      { title: "Psicopedagogía", fields: [
        { key: "psicoped_desempeno", label: "¿Cómo es su desempeño en las tareas escolares?", type: "long" },
        { key: "psicoped_lectoescritura", label: "¿Tiene dificultades para leer, escribir o en matemáticas?", type: "long" },
        { key: "psicoped_apoyo", label: "¿Recibe apoyo escolar adicional?", type: "long" },
        { key: "psicoped_antecedentes", label: "¿Presenta antecedentes de dificultad de aprendizaje, fracaso escolar o asistencia a escuelas especiales?", type: "long" },
      ] },
      { title: "Psicología", fields: [
        { key: "psico_animo", label: "¿Ha mostrado cambios en su estado de ánimo o comportamiento?", type: "long" },
        { key: "psico_temores", label: "¿Tiene temores o ansiedades notables?", type: "long" },
        { key: "psico_frustracion", label: "¿Cómo maneja la frustración o situaciones de estrés?", type: "long" },
      ] },
      { title: "Educación especial", fields: [
        { key: "edesp_evaluado", label: "¿Ha sido evaluado/a para necesidades educativas especiales?", type: "long" },
        { key: "edesp_diagnostico", label: "¿Tiene algún diagnóstico previo relacionado con el aprendizaje?", type: "long" },
        { key: "edesp_entorno", label: "¿Cómo se desenvuelve en el entorno escolar?", type: "long" },
      ] },
      { title: "Terapia ocupacional", fields: [
        { key: "to_motricidad_fina", label: "¿Tiene dificultades en la motricidad fina (abotonarse, atarse los cordones)?", type: "long" },
        { key: "to_motricidad_gruesa", label: "¿Hay problemas en la motricidad gruesa (saltar, correr)?", type: "long" },
        { key: "to_independencia", label: "¿Muestra independencia en actividades cotidianas (vestirse, comer)?", type: "long" },
      ] },
      { title: "Psicomotricidad", fields: [
        { key: "psicomot_coordinacion", label: "¿Presenta dificultades en la coordinación motora?", type: "long" },
        { key: "psicomot_equilibrio", label: "¿Cómo es su equilibrio al caminar o correr?", type: "long" },
        { key: "psicomot_planificacion", label: "¿Muestra dificultades en la planificación de movimientos?", type: "long" },
        { key: "psicomot_actividad_fisica", label: "¿Realiza actividades físicas (deportes, juegos de movimiento)?", type: "long" },
        { key: "psicomot_coordinacion_diaria", label: "¿Tiene problemas para coordinar movimientos en actividades diarias (dibujar, escribir, manipular objetos)?", type: "long" },
        { key: "psicomot_conducta_hogar", label: "¿Cómo es su conducta en el hogar?", type: "long" },
        { key: "psicomot_dificultades_hogar", label: "En casa, ¿presenta dificultades en el desarrollo de habilidades motoras, cognitivas, emocionales o sociales?", type: "long" },
        { key: "psicomot_sensorial", label: "Según la edad: ¿disfruta manipular distintos elementos sensoriales (arena, agua, masa, etc.)?", type: "long" },
        { key: "psicomot_pintar", label: "¿Le gusta pintar, dibujar con lápices de colores, pintura?", type: "long" },
      ] },
    ],
  },
  {
    id: "entrevistado", title: "Persona entrevistada", groups: [{ fields: [
      { key: "entrevistado_nombre", label: "Nombre de la persona entrevistada" },
      { key: "entrevistado_parentesco", label: "Parentesco con el niño/a" },
    ] }],
  },
];

/** "Psicología" y "psicologia " son la misma profesión. */
export function sameArea(a: string, b: string): boolean {
  const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").trim().toLowerCase();
  return norm(a) === norm(b);
}
