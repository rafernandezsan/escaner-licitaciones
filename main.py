import os
from fastapi import FastAPI, Request
from typing import TypedDict
from langgraph.graph import StateGraph, END

app = FastAPI()

# 1. Definimos la memoria de nuestro Agente (El Estado)
class LicitacionState(TypedDict):
    id_proceso: str
    texto_extraido: str
    puntuacion_software: int
    es_proyecto_objetivo: bool

# 2. Creamos nuestro Agente Evaluador (Nodo)
def evaluar_licitacion(state: LicitacionState):
    print(f"🕵️‍♂️ Analizando licitación: {state.get('id_proceso', 'Desconocido')}")
    
    # NOTA: Aquí conectaremos LangChain y OpenAI en el siguiente paso.
    # Por ahora, simulamos que encontró un proyecto de software.
    return {
        "puntuacion_software": 9,
        "es_proyecto_objetivo": True
    }

# 3. Construimos el Flujo de Trabajo (El Grafo)
workflow = StateGraph(LicitacionState)
workflow.add_node("evaluador", evaluar_licitacion)
workflow.set_entry_point("evaluador")
workflow.add_edge("evaluador", END)

# Compilamos el grafo para que esté listo para ejecutarse
escaner_app = workflow.compile()

# 4. Creamos el "Timbre" (Endpoint) para que Google Cloud (Pub/Sub) llame a nuestro agente
@app.post("/")
async def recibir_evento(request: Request):
    try:
        # GCP Pub/Sub envía los datos en un formato específico (Base64)
        body = await request.json()
        print("📥 Nuevo documento recibido desde la DGCP.")
        
        # Ejecutamos nuestro agente de IA
        estado_inicial = {"id_proceso": "PRUEBA-001"}
        resultado = escaner_app.invoke(estado_inicial)
        
        print(f"✅ Resultado de la evaluación: {resultado}")
        return {"status": "success", "message": "Licitación procesada"}
    
    except Exception as e:
        print(f"❌ Error procesando el mensaje: {e}")
        return {"status": "error"}