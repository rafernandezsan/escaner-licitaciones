import os
import psycopg2
from fastapi import FastAPI, UploadFile, File, Form, Request
from google.cloud import storage
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage

app = FastAPI()
BUCKET_NAME = f"escaner-licitaciones-docs-{os.environ.get('GOOGLE_CLOUD_PROJECT')}"

def get_db_connection():
    return psycopg2.connect(host=os.environ["DB_HOST"], database=os.environ["DB_NAME"], 
                            user=os.environ["DB_USER"], password=os.environ["DB_PASS"])

def upload_to_gcs(file_bytes, file_name):
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(file_name)
    blob.upload_from_string(file_bytes, content_type='application/pdf')
    return f"gs://{BUCKET_NAME}/{file_name}"

@app.post("/")
async def analizar_o_reevaluar(
    id_proceso: str = Form(...),
    titulo: str = Form(None),
    archivo: UploadFile = File(None)
):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Obtener el Documento (Nuevo o Existente)
    gcs_uri = None
    if archivo:
        file_bytes = await archivo.read()
        gcs_uri = upload_to_gcs(file_bytes, f"{id_proceso}.pdf")
    else:
        cur.execute("SELECT documento_url FROM analisis_licitaciones WHERE id_proceso = %s", (id_proceso,))
        res = cur.fetchone()
        if res: gcs_uri = res[0]

    # 2. Obtener Memoria (Notas y Reporte previo)
    cur.execute("SELECT notas, reporte_completo FROM analisis_licitaciones WHERE id_proceso = %s", (id_proceso,))
    memoria = cur.fetchone()
    notas = memoria[0] if memoria and memoria[0] else "Sin notas adicionales."
    
    # 3. Razonamiento de Gemini (Vertex AI lee directo de GCS)
    # Gemini 1.5 Flash es ideal por su ventana de contexto para documentos de 200+ páginas
    llm = ChatVertexAI(model_name="gemini-1.5-flash")
    
    instruccion = f"""Analiza esta licitación técnica. 
    CONTEXTO DEL CONSULTOR: {notas}
    Si hay notas, ajusta el score basándote en ellas. 
    Responde estrictamente en JSON: {{"puntuacion": int, "razonamiento": str, "es_objetivo": bool}}"""
    
    mensaje = HumanMessage(content=[
        {"type": "text", "text": instruccion},
        {"type": "media", "file_uri": gcs_uri, "mime_type": "application/pdf"}
    ])
    
    resultado = llm.invoke([mensaje])
    # Aquí parseamos el resultado (asumiendo formato JSON correcto)
    import json
    data_ia = json.loads(resultado.content.replace('```json', '').replace('```', ''))

    # 4. Sincronizar Persistencia
    cur.execute("""
        INSERT INTO analisis_licitaciones (id_proceso, titulo, documento_url, puntuacion, es_objetivo, reporte_completo, estado)
        VALUES (%s, %s, %s, %s, %s, %s, 'Analizada')
        ON CONFLICT (id_proceso) DO UPDATE SET 
            puntuacion = EXCLUDED.puntuacion,
            reporte_completo = EXCLUDED.reporte_completo,
            documento_url = COALESCE(EXCLUDED.documento_url, analisis_licitaciones.documento_url)
    """, (id_proceso, titulo, gcs_uri, data_ia['puntuacion'], data_ia['es_objetivo'], data_ia['razonamiento']))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "score": data_ia['puntuacion']}