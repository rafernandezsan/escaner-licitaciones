import os
import psycopg2
from fastapi import FastAPI, Request
from typing import TypedDict
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate

app = FastAPI()

# --- 1. FUNCIÓN DE BASE DE DATOS ---
def guardar_en_db(id_proceso, titulo, estado, puntuacion, es_objetivo):
    try:
        # Conectamos a PostgreSQL usando las variables de entorno de Cloud Run
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            database=os.environ.get("DB_NAME", "licitaciones_db"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASS", "password")
        )
        cursor = conn.cursor()

        # Aseguramos que la tabla exista
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analisis_licitaciones (
                id_proceso VARCHAR(50) PRIMARY KEY,
                titulo TEXT,
                estado VARCHAR(20),
                puntuacion INT,
                es_objetivo BOOLEAN,
                notas TEXT
            )
        """)

        # Insertamos el resultado (o lo actualizamos si ya existía el ID)
        cursor.execute("""
            INSERT INTO analisis_licitaciones (id_proceso, titulo, estado, puntuacion, es_objetivo)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id_proceso) DO UPDATE 
            SET estado = EXCLUDED.estado, 
                puntuacion = EXCLUDED.puntuacion, 
                es_objetivo = EXCLUDED.es_objetivo
        """, (id_proceso, titulo, estado, puntuacion, es_objetivo))

        conn.commit()
        cursor.close()
        conn.close()
        print(f"💾 Guardado exitoso en PostgreSQL para la licitación: {id_proceso}")
    except Exception as e:
        print(f"❌ Error guardando en la base de datos: {e}")

# --- 2. ESTRUCTURA Y AGENTE (Igual que antes) ---
class EvaluacionLicitacion(BaseModel):
    puntuacion_software: int = Field(description="Puntuación del 1 al 10")
    es_proyecto_objetivo: bool = Field(description="True si requiere desarrollo de software")

class LicitacionState(TypedDict):
    id_proceso: str
    texto_extraido: str
    puntuacion_software: int
    es_proyecto_objetivo: bool

def evaluar_licitacion(state: LicitacionState):
    print(f"🕵️‍♂️ Gemini analizando: {state.get('id_proceso')}")
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    llm_estructurado = llm.with_structured_output(EvaluacionLicitacion)
    
    prompt = PromptTemplate.from_template("""
    Eres un consultor experto en TI evaluando licitaciones públicas de la DGCP en República Dominicana.
    Texto de la licitación a evaluar:
    {texto}
    Analiza el texto y completa la evaluación estructurada.
    """)
    
    cadena = prompt | llm_estructurado
    resultado_ia = cadena.invoke({"texto": state["texto_extraido"]})
    
    return {
        "puntuacion_software": resultado_ia.puntuacion_software,
        "es_proyecto_objetivo": resultado_ia.es_proyecto_objetivo
    }

workflow = StateGraph(LicitacionState)
workflow.add_node("evaluador", evaluar_licitacion)
workflow.set_entry_point("evaluador")
workflow.add_edge("evaluador", END)
escaner_app = workflow.compile()

# --- 3. ENDPOINT (El Timbre) ---
@app.post("/")
async def recibir_evento(request: Request):
    try:
        body = await request.json()
        estado_inicial = {
            "id_proceso": body.get("id_proceso", "Desconocido"),
            "texto_extraido": body.get("texto_extraido", "Sin texto")
        }
        
        # 1. La IA evalúa
        resultado = escaner_app.invoke(estado_inicial)
        
        # 2. Guardamos físicamente en la Base de Datos
        guardar_en_db(
            id_proceso=resultado["id_proceso"],
            titulo=body.get("titulo", "Licitación sin título"),
            estado="Analizada",
            puntuacion=resultado["puntuacion_software"],
            es_objetivo=resultado["es_proyecto_objetivo"]
        )
        
        return {"status": "success", "id_proceso": resultado["id_proceso"]}
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"status": "error", "message": str(e)} 