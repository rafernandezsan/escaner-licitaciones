import os
import psycopg2
from fastapi import FastAPI, UploadFile, File, Form
from google.cloud import storage
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage

app = FastAPI()
BUCKET_NAME = "escaner-licitaciones-docs-escanerlicitaciones"

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
    
    # 1. Obtener el Documento
    gcs_uri = None
    if archivo:
        file_bytes = await archivo.read()
        gcs_uri = upload_to_gcs(file_bytes, f"{id_proceso}.pdf")
    else:
        cur.execute("SELECT documento_url FROM analisis_licitaciones WHERE id_proceso = %s", (id_proceso,))
        res = cur.fetchone()
        if res and res[0]: gcs_uri = res[0]

    # 2. Obtener Memoria (Notas)
    cur.execute("SELECT notas FROM analisis_licitaciones WHERE id_proceso = %s", (id_proceso,))
    memoria = cur.fetchone()
    notas = memoria[0] if memoria and memoria[0] else "Sin notas adicionales."
    
    # 3. Razonamiento Nativo con Vertex AI (Lee el gs:// directamente)
    # Importante: location debe coincidir con la región de tu Cloud Run
    llm = ChatVertexAI(model_name="gemini-2.5-flash", location="us-east1", temperature=0)
    
    instruccion = f"""Analiza esta licitación técnica. 
    CONTEXTO DEL CONSULTOR: {notas}
    Si hay notas, ajusta el score basándote en ellas. 
    Responde estrictamente en JSON: {{"puntuacion": 8, "razonamiento": "explicación", "es_objetivo": true}}"""
    
    contenido_mensaje = [{"type": "text", "text": instruccion}]
    
    if gcs_uri:
        # Así se le envía un archivo nativo a Vertex AI
        contenido_mensaje.append({
            "type": "media", 
            "file_uri": gcs_uri, 
            "mime_type": "application/pdf"
        })
    else:
        contenido_mensaje[0]["text"] += "\n[ADVERTENCIA: No hay documento.]"

    mensaje = HumanMessage(content=contenido_mensaje)
    resultado = llm.invoke([mensaje])
    
    # Extraemos el JSON
    import json
    texto_ia = resultado.content.replace('```json', '').replace('```', '').strip()
    try:
        data_ia = json.loads(texto_ia)
    except:
        data_ia = {"puntuacion": 0, "razonamiento": "Error de formato.", "es_objetivo": False}

    # 4. Sincronizar Base de Datos
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