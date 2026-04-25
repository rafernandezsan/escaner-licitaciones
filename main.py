import os
from fastapi import FastAPI, Request
from typing import TypedDict
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate

app = FastAPI()

# 1. Definimos la estructura EXACTA que Gemini debe devolver
class EvaluacionLicitacion(BaseModel):
    puntuacion_software: int = Field(description="Puntuación del 1 al 10 de qué tan alineado está el texto a un proyecto de desarrollo de software o tecnología pura.")
    es_proyecto_objetivo: bool = Field(description="Devuelve True SOLAMENTE si requiere desarrollo de software, ingenieros, o bases de datos. Devuelve False si es obra civil, ferretería, limpieza, etc.")

# 2. La memoria de nuestro Agente
class LicitacionState(TypedDict):
    id_proceso: str
    texto_extraido: str
    puntuacion_software: int
    es_proyecto_objetivo: bool

# 3. El Nodo de Inteligencia (Gemini en acción)
def evaluar_licitacion(state: LicitacionState):
    print(f"🕵️‍♂️ Gemini analizando licitación: {state.get('id_proceso')}")
    
    # Conectamos con el modelo más rápido y eficiente de Google
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0)
    
    # Obligamos al modelo a respetar nuestro formato de respuesta Pydantic
    llm_estructurado = llm.with_structured_output(EvaluacionLicitacion)
    
    # El "Prompt" o instrucción del sistema
    prompt = PromptTemplate.from_template("""
    Eres un consultor experto en TI evaluando licitaciones públicas de la DGCP en República Dominicana.
    Tu único objetivo es leer el siguiente resumen de una licitación y determinar si es una oportunidad valiosa de TI y Desarrollo de Software.
    
    Texto de la licitación a evaluar:
    {texto}
    
    Analiza el texto y completa la evaluación estructurada.
    """)
    
    # Ejecutamos la IA
    cadena = prompt | llm_estructurado
    resultado_ia = cadena.invoke({"texto": state["texto_extraido"]})
    
    # Actualizamos el estado con lo que pensó Gemini
    return {
        "puntuacion_software": resultado_ia.puntuacion_software,
        "es_proyecto_objetivo": resultado_ia.es_proyecto_objetivo
    }

# 4. Construimos el Flujo de LangGraph
workflow = StateGraph(LicitacionState)
workflow.add_node("evaluador", evaluar_licitacion)
workflow.set_entry_point("evaluador")
workflow.add_edge("evaluador", END)
escaner_app = workflow.compile()

# 5. El Endpoint de recepción
@app.post("/")
async def recibir_evento(request: Request):
    try:
        body = await request.json()
        estado_inicial = {
            "id_proceso": body.get("id_proceso", "Desconocido"),
            "texto_extraido": body.get("texto_extraido", "Sin texto")
        }
        
        # Invocamos a nuestro agente LangGraph con Gemini
        resultado = escaner_app.invoke(estado_inicial)
        
        # Devolvemos la respuesta final
        return {
            "status": "success", 
            "id_proceso": resultado["id_proceso"],
            "puntuacion_software": resultado["puntuacion_software"],
            "es_proyecto_objetivo": resultado["es_proyecto_objetivo"]
        }
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"status": "error", "message": str(e)}   