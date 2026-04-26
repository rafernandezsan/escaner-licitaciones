import streamlit as st
import pandas as pd
import requests

# Configuración de la página
st.set_page_config(page_title="Radar de Licitaciones TI", page_icon="🎯", layout="wide")

# URL de tu API en Cloud Run (La que obtuvimos en los pasos anteriores)
API_URL = "https://langgraph-orchestrator-worker-xxxxx-uc.a.run.app" 

st.title("🎯 Radar de Licitaciones DGCP")
st.markdown("Plataforma de análisis impulsada por Gemini 2.5 Flash")

# --- 1. SIMULACIÓN DE DATOS (AQUÍ CONECTARÍAS A POSTGRESQL) ---
# En producción, usarías st.cache_data para consultar tu BD
@st.cache_data
def obtener_licitaciones():
    return pd.DataFrame({
        "ID": ["DGCP-TI-2026", "DGCP-HW-044", "DGCP-SW-089", "DGCP-TI-102"],
        "Título": ["Sistema de Información en la Nube", "Compra masiva de Laptops", "Mantenimiento ERP", "Pliego escaneado ilegible"],
        "Estado": ["Analizada", "Analizada", "Pendiente", "Error"],
        "Puntuación": [10, 2, None, None],
        "Es Objetivo": [True, False, None, None],
        "Notas": ["Oportunidad AAA. Hablar con Carlos.", "", "", "Revisar manualmente el PDF"]
    })

df = obtener_licitaciones()

# --- 2. PANEL DE MÉTRICAS (KPIs) ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Encontradas", len(df))
col2.metric("🎯 Alta Prioridad (Score > 8)", len(df[df["Puntuación"] >= 8]))
col3.metric("⏳ Pendientes", len(df[df["Estado"] == "Pendiente"]))
col4.metric("❌ Errores OCR/IA", len(df[df["Estado"] == "Error"]))

st.divider()

# --- 3. FILTROS ---
filtro_estado = st.selectbox("Filtrar por Estado:", ["Todas", "Analizadas", "Pendientes", "Errores"])

if filtro_estado != "Todas":
    # Ajustar el texto del filtro para que coincida con los datos
    estado_map = {"Analizadas": "Analizada", "Pendientes": "Pendiente", "Errores": "Error"}
    df_filtrado = df[df["Estado"] == estado_map[filtro_estado]]
else:
    df_filtrado = df

# --- 4. LISTA Y PANEL DE ACCIONES INTERACTIVAS ---
st.subheader("📋 Licitaciones Detectadas")

for index, row in df_filtrado.iterrows():
    # Asignar un color visual según el score
    icono = "🟢" if row["Puntuación"] == 10 else "🟡" if row["Estado"] == "Pendiente" else "🔴"
    
    # Cada licitación es un acordeón desplegable
    with st.expander(f"{icono} {row['ID']} - {row['Título']} (Score: {row['Puntuación']})"):
        st.write(f"**Estado de Análisis:** {row['Estado']}")
        
        # Grid para las 4 acciones solicitadas
        c1, c2, c3, c4 = st.columns(4)
        
        with c1:
            # ACCIÓN 1: RE-EVALUAR
            if st.button("🔄 Re-evaluar con IA", key=f"eval_{row['ID']}"):
                with st.spinner('Gemini está leyendo el documento...'):
                    try:
                        # Aquí disparamos el flujo a tu Cloud Run
                        payload = {"id_proceso": row['ID'], "texto_extraido": "Texto simulado del PDF"}
                        response = requests.post(API_URL, json=payload)
                        if response.status_code == 200:
                            st.success("¡Re-evaluación completada!")
                        else:
                            st.error("Error al conectar con la API")
                    except:
                        st.info("Simulación de re-evaluación exitosa (Conecta tu API real para activar).")
        
        with c2:
            # ACCIÓN 2: DESCARGAR PDF
            # En producción, esto apuntaría a la URL firmada de Google Cloud Storage
            st.download_button(
                label="📄 Descargar PDF Original",
                data=b"Simulacion de PDF Binario",
                file_name=f"{row['ID']}_pliego.pdf",
                mime="application/pdf",
                key=f"dl_{row['ID']}"
            )
            
        with c3:
            # ACCIÓN 3: COMPARTIR RESULTADOS
            resumen_compartir = f"🚨 *Oportunidad DGCP*\n*ID:* {row['ID']}\n*Proyecto:* {row['Título']}\n*Ajuste Técnico:* {row['Puntuación']}/10\n*¿Es objetivo?:* {'Sí' if row['Es Objetivo'] else 'No'}"
            st.code(resumen_compartir, language="markdown")
            st.caption("Copia el texto arriba para enviarlo a tu equipo.")

        with c4:
             st.write("") # Espaciador
             
        # ACCIÓN 4: ADJUNTAR NOTAS (Fuera de las columnas para tener más espacio)
        st.markdown("### 📝 Notas de Consultoría")
        nota_actual = row['Notas'] if pd.notna(row['Notas']) else ""
        nueva_nota = st.text_area("Comentarios sobre la estrategia o competidores:", value=nota_actual, key=f"nota_{row['ID']}")
        
        if st.button("💾 Guardar Nota", key=f"save_{row['ID']}"):
            # Aquí harías un UPDATE a tu base de datos PostgreSQL
            st.success("Nota guardada en la base de datos.")