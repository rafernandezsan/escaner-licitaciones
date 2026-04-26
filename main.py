import os
import psycopg2
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate

app = FastAPI()

def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST"),
        database=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASS")
    )

class EvaluacionLicitacion(BaseModel):
    puntuacion: int = Field(description="Score 1-10")
    es_objetivo: bool = Field(description="¿Es desarrollo de software?")
    razonamiento: str = Field(description="Breve explicación de por qué esta nota")

@app.post("/")
async def analizar_con_memoria(request: Request):
    body = await request.json()
    id_proceso = body.get("id_proceso")
    texto = body.get("texto_extraido")
    
    # 1. Recuperar notas previas de la DB
    notas_previas = ""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT notas FROM analisis_licitaciones WHERE id_proceso = %s", (id_proceso,))
    row = cur.fetchone()
    if row and row[0]:
        notas_previas = f"\n[NOTAS IMPORTANTES DEL CONSULTOR]: {row[0]}"
    
    # 2. IA con Contexto
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    llm_estructurado = llm.with_structured_output(EvaluacionLicitacion)
    
    prompt = PromptTemplate.from_template("""
    Eres un consultor experto. Evalúa esta licitación.
    PLIEGO: {texto}
    {contexto}
    
    Si hay notas del consultor, dales prioridad absoluta para ajustar el score.
    """)
    
    res = (prompt | llm_estructurado).invoke({"texto": texto, "contexto": notas_previas})
    
    # 3. Guardar todo (incluyendo el reporte generado)
    cur.execute("""
        INSERT INTO analisis_licitaciones (id_proceso, titulo, estado, puntuacion, es_objetivo, reporte_completo)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (id_proceso) DO UPDATE 
        SET puntuacion = EXCLUDED.puntuacion, es_objetivo = EXCLUDED.es_objetivo, reporte_completo = EXCLUDED.reporte_completo
    """, (id_proceso, body.get("titulo", "Sin Título"), "Analizada", res.puntuacion, res.es_objetivo, res.razonamiento))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "score": res.puntuacion}

@app.post("/guardar_notas")
async def guardar_notas(request: Request):
    body = await request.json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE analisis_licitaciones SET notas = %s WHERE id_proceso = %s", (body['notas'], body['id_proceso']))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "nota_guardada"}