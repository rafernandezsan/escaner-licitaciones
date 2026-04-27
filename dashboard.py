import streamlit as st
import pandas as pd
import requests
import psycopg2
import os
import hashlib

# Configuración de la página
st.set_page_config(page_title="Escaner de Licitaciones", page_icon="🤖", layout="wide")
API_URL = "https://langgraph-orchestrator-worker-1066450737358.us-east1.run.app" # <-- Reemplaza por tu URL real

# --- FUNCIÓN AUXILIAR DE CONEXIÓN ---
def get_db_connection():
    # En Cloud Run leemos las variables de entorno, localmente usamos st.secrets
    if "DB_HOST" in os.environ:
        return psycopg2.connect(
            host=os.environ["DB_HOST"], database=os.environ["DB_NAME"],
            user=os.environ["DB_USER"], password=os.environ["DB_PASS"]
        )
    else:
        return psycopg2.connect(
            host=st.secrets["DB_HOST"], database=st.secrets["DB_NAME"],
            user=st.secrets["DB_USER"], password=st.secrets["DB_PASS"]
        )

# --- INICIALIZACIÓN DE BASE DE DATOS DE USUARIOS ---
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL, rol VARCHAR(50) NOT NULL
        )
    """)
    def_email = os.environ.get("ADMIN_EMAIL") or st.secrets.get("ADMIN_EMAIL")
    def_pass = os.environ.get("ADMIN_PASSWORD") or st.secrets.get("ADMIN_PASSWORD")
    if def_email and def_pass:
        hashed = hashlib.sha256(def_pass.encode()).hexdigest()
        cur.execute("""
            INSERT INTO usuarios (email, password_hash, rol) VALUES (%s, %s, 'administrador') 
            ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash, rol = 'administrador'
        """, (def_email, hashed))
    conn.commit()
    cur.close()
    conn.close()

init_db()

# --- 1. CONEXIÓN A LA BASE DE DATOS ---
@st.cache_data(ttl=5)
def obtener_licitaciones():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id_proceso, titulo, estado, puntuacion, notas, reporte_completo, documento_url FROM analisis_licitaciones")
        rows = cursor.fetchall()
        columnas = ["ID", "Título", "Estado", "Puntuación", "Notas", "Reporte", "Documento_URL"]
        df = pd.DataFrame(rows, columns=columnas)
        cursor.close()
        conn.close()
        return df
    except Exception as e:
        st.error(f"Error BD: {e}")
        return pd.DataFrame()

def obtener_documentos_vinculados(id_proceso):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nombre_archivo, documento_url, mime_type 
            FROM documentos_licitacion 
            WHERE id_proceso = %s 
            ORDER BY fecha_subida DESC
        """, (id_proceso,))
        docs = cur.fetchall()
        cur.close()
        conn.close()
        return docs
    except Exception as e:
        st.error(f"Error BD: {e}")
        return pd.DataFrame()
    

def eliminar_documento_api(id_doc):
    try:
        # Llamamos al endpoint de eliminar que creamos en el main.py
        response = requests.post(
            f"{API_URL}/eliminar_documento", 
            data={"id_doc": id_doc}
        )
        return response.status_code == 200
    except Exception as e:
        st.error(f"Error al conectar con la API: {e}")
        return False
    

def obtener_enlace_descarga(id_doc):
    try:
        res = requests.post(f"{API_URL}/generar_descarga", data={"id_doc": id_doc})
        if res.status_code == 200:
            return res.json().get("url_descarga")
    except:
        return None

def view_crear_usuario():
    st.title("➕ Alta de Nuevos Usuarios")
    st.info("Para crear un nuevo usuario, ingresa los detalles y confirma con tu contraseña de administrador.")

    with st.form("form_crear_usuario"):
        new_email = st.text_input("Correo Electrónico del Nuevo Usuario")
        new_password = st.text_input("Contraseña Temporal para el Nuevo Usuario", type="password")
        new_rol = st.selectbox("Rol del Nuevo Usuario", ["analista", "invitado", "administrador"])
        st.divider()
        admin_password_verify = st.text_input("Tu Contraseña de Administrador (para confirmar)", type="password")
        
        submitted = st.form_submit_button("Registrar Usuario")

        if submitted:
            if not all([new_email, new_password, admin_password_verify]):
                st.warning("Por favor, completa todos los campos.")
                return

            payload = {
                "email": new_email,
                "password": new_password,
                "rol": new_rol,
                "admin_email": st.session_state.get("user_email"),
                "admin_password": admin_password_verify
            }

            try:
                response = requests.post(f"{API_URL}/signup", data=payload)
                if response.status_code == 200:
                    st.success(response.json().get("message", "Usuario creado con éxito."))
                else:
                    error_detail = response.json().get("detail", "Ocurrió un error desconocido.")
                    st.error(f"Error al crear usuario (HTTP {response.status_code}): {error_detail}")
            except requests.exceptions.RequestException as e:
                st.error(f"Error de conexión con la API: {e}")

def view_portafolio():
    st.title("🤖 Analizador de Licitaciones AI")
    df = obtener_licitaciones()

    # Mantenemos la barra lateral para registrar licitaciones dentro de esta vista
    with st.sidebar:
        if st.session_state.get("user_role") == "administrador":
            with st.expander("➕ Registrar Licitación", expanded=False):
                id_input = st.text_input("ID Proceso (ej. DGCP-2026)")
                titulo_input = st.text_input("Título")
                if st.button("Crear Registro"):
                    res = requests.post(API_URL, data={"id_proceso": id_input, "titulo": titulo_input})
                    if res.status_code == 200:
                        st.success("Licitación creada.")
                        st.cache_data.clear()
                        st.rerun()

    if df.empty:
        st.info("No hay licitaciones. Registra una en el menú lateral.")
        return

    st.subheader("📋 Portafolio de Licitaciones")
    for index, row in df.iterrows():
        score = row["Puntuación"] if pd.notna(row["Puntuación"]) else 0
        icono = "🟢" if score >= 8 else "🟡" if score >= 5 else "🔴"
        if score == 0: icono = "⚪"
        
        with st.expander(f"{icono} {row['ID']} - {row['Título']} (Score: {score})"):
            
        # Creamos 3 pestañas para organizar la información
            tab1, tab2, tab3 = st.tabs(["📊 Análisis de AI", "📝 Notas adicionales", "📁 Repositorio de Documentos"])
        
        # PESTAÑA 1: ANÁLISIS
            with tab1:
                st.write(f"**Estado:** {row['Estado']}")
                st.markdown(f"**Conclusión de Gemini:**\n> {row['Reporte'] if pd.notna(row['Reporte']) else 'Sin análisis aún.'}")
                
                if st.button("🤖 Ejecutar Análisis Global", key=f"btn_run_{row['ID']}"):
                    with st.spinner("El agente está procesando todo el expediente..."):
                        res_analisis = requests.post(f"{API_URL}/analizar", data={"id_proceso": row['ID']})
                        if res_analisis.status_code == 200:
                            st.success("Análisis completado.")
                            st.cache_data.clear()
                            st.rerun()
                        
                if st.button("📄 Preparar PDF Ejecutivo", key=f"pdf_prep_{row['ID']}"):
                    with st.spinner("Creando PDF en el servidor..."):
                        res_pdf = requests.post(f"{API_URL}/generar_reporte_pdf", data={"id_proceso": row['ID']})
                        if res_pdf.status_code == 200:
                            st.session_state[f"pdf_data_{row['ID']}"] = res_pdf.content
                        else:
                            st.error(f"Error al generar el PDF (HTTP {res_pdf.status_code}): {res_pdf.text}")
                
                if f"pdf_data_{row['ID']}" in st.session_state:
                    st.download_button(
                        label="📥 Descargar Reporte PDF",
                        data=st.session_state[f"pdf_data_{row['ID']}"],
                        file_name=f"Reporte_{row['ID']}.pdf",
                        mime="application/pdf",
                        key=f"dl_pdf_{row['ID']}"
                    )

                # if st.button("🔄 Ejecutar Re-evaluación IA", key=f"eval_{row['ID']}"):
                #    with st.spinner("Gemini está leyendo el documento en Cloud Storage..."):
                #        res = requests.post(API_URL, data={"id_proceso": row['ID']})
                #        if res.status_code == 200:
                #            st.success("Análisis completado.")
                #            st.cache_data.clear()
                #            st.rerun() 
        
            # PESTAÑA 2: NOTAS
            with tab2:
                nota_actual = row['Notas'] if pd.notna(row['Notas']) else ""
                nueva_nota = st.text_area("Contexto Estratégico (Modifica el pensamiento de la IA):", value=nota_actual, key=f"nota_{row['ID']}")
                
                # Nota: Asegúrate de tener tu endpoint de /guardar_notas en el main.py funcionando
                if st.button("💾 Sincronizar Notas", key=f"sync_{row['ID']}"):
                    st.info("Notas actualizadas (Requiere que el endpoint /guardar_notas esté activo).")
                    
            # PESTAÑA 3: DOCUMENTOS (LO NUEVO)
            with tab3:
                st.subheader("📂 Expediente Digital")
        
                docs_vinculados = obtener_documentos_vinculados(row['ID'])
                
                if docs_vinculados:
                    with st.expander(f"Ver {len(docs_vinculados)} documentos archivados", width="stretch", expanded=False):
                        for doc_id, nombre, url, mime in docs_vinculados:
                            col_nom, col_desc, col_bor = st.columns([2, 0.05, 0.05])
                            
                            with col_nom:
                                st.caption(f"📄 {nombre}")
                            
                            with col_desc:
                                # Botón de descarga (usando la URL de GCS o proxy)
                                # Nota: Para descarga directa desde GCS se requiere un Signed URL
                                url_segura = obtener_enlace_descarga(doc_id)
                                if url_segura:
                                    st.link_button("📥", url_segura, help="Descargar desde GCS", use_container_width=False)
                                else:
                                    st.error("Error de enlace")
                                #st.link_button("Descargar", url, use_container_width=True)
                            
                            with col_bor:
                                if st.button("🗑️", key=f"del_{doc_id}", help="Eliminar de GCS y Base de Datos", type="secondary"):
                                    with st.spinner("Eliminando..."):
                                        if eliminar_documento_api(doc_id):
                                            st.toast(f"✅ {nombre} eliminado correctamente")
                                            st.cache_data.clear() # Limpiamos caché para ver cambios
                                            st.rerun() # Refrescamos la UI
                                        else:
                                            st.error("No se pudo eliminar el archivo.")
                else:
                    st.info("No hay documentos vinculados aún.")
                    
                st.divider()
                archivo_nuevo = st.file_uploader("Agregar archivo al expediente", key=f"repo_{row['ID']}")
                if st.button("📁 Archivar Documento", key=f"btn_arc_{row['ID']}"):
                    if archivo_nuevo:
                        files = {"archivo": (archivo_nuevo.name, archivo_nuevo.getvalue(), archivo_nuevo.type)}
                        requests.post(f"{API_URL}/subir_documento", data={"id_proceso": row['ID']}, files=files)
                        st.success("Guardado en el repositorio.")
                            
                    else:
                        st.error("Por favor adjunta un archivo primero.")


if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔐 Acceso al Sistema")
    with st.form("login_form"):
        email = st.text_input("Correo Electrónico")
        password = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Iniciar Sesión"):
            conn = get_db_connection()
            cur = conn.cursor()
            hashed = hashlib.sha256(password.encode()).hexdigest()
            cur.execute("SELECT id, rol FROM usuarios WHERE email = %s AND password_hash = %s", (email, hashed))
            user = cur.fetchone()
            cur.close()
            conn.close()
            
            if user:
                st.session_state.authenticated = True
                st.session_state.user_id = user[0]
                st.session_state.user_role = user[1]
                st.session_state.user_email = email
                st.rerun()
            else:
                st.error("Credenciales incorrectas.")
    st.stop()


with st.sidebar:
    st.markdown(f"**Usuario:** {st.session_state.user_email}")
    st.markdown(f"**Rol:** {st.session_state.user_role.capitalize()}")
    if st.button("Cerrar Sesión"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
    st.divider()
    
    menu_options = ["Portafolio"]
    if st.session_state.get("user_role") == "administrador":
        menu_options.append("Crear Usuario")
        
    choice = st.radio("Menú Principal", menu_options, key="navigation")

if choice == "Portafolio":
    view_portafolio()
elif choice == "Crear Usuario":
    view_crear_usuario()