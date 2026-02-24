import streamlit as st
import pdfplumber
import pandas as pd
import re
import requests
import time
from geopy.geocoders import ArcGIS
from geopy.distance import geodesic
import io
import folium
from streamlit_folium import st_folium
from folium import plugins

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Ruta Pro | WhatsApp Validado", page_icon="📲", layout="wide")

# --- FUNCIONES LÓGICAS ---
def extraer_telefono(texto):
    # 1. Buscamos cualquier cadena que parezca un teléfono con los prefijos indicados
    # Soporta formatos con espacios, guiones o puntos.
    # Patrón: (011 o 11 o 15) + 8 números
    patron = r'(?:011|11|15)[\s.-]?\d{2,4}[\s.-]?\d{4,6}'
    matches = re.findall(patron, texto)
    
    for m in matches:
        # Limpiamos todo lo que no sea número
        num_limpio = re.sub(r'\D', '', m)
        
        # Si empieza con 011, lo convertimos a 11 para el estándar internacional
        if num_limpio.startswith('011'):
            num_limpio = '11' + num_limpio[3:]
            
        # Validamos que ahora tenga 10 dígitos (ej: 11 1234 5678)
        if len(num_limpio) == 10:
            return "549" + num_limpio  # Formato internacional WhatsApp (54 + 9 + 11...)
            
    return None

def limpieza_profunda_direccion(direccion):
    # Elimina números de parada al inicio y palabras comunes
    dir_limpia = re.sub(r'^\d+[\s,]+\d+\s+', '', direccion)
    palabras_ruido = [r'\bCalle\b', r'\bAvenida\b', r'\bAv\b', r'\bGral\b', r'\bGeneral\b']
    for p in palabras_ruido:
        dir_limpia = re.sub(p, '', dir_limpia, flags=re.IGNORECASE)
    return dir_limpia.strip()

def obtener_ruta_osrm(c1, c2):
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{c1[1]},{c1[0]};{c2[1]},{c2[0]}?overview=false"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get('code') == 'Ok':
            return round(data['routes'][0]['distance'] / 1000, 2), round(data['routes'][0]['duration'] / 60)
    except: return None, None
    return 0.0, 0

def optimizar_orden(coords_inicio, lista_puntos):
    puntos_pendientes = lista_puntos.copy()
    ruta_optimizada = []
    punto_actual = coords_inicio
    while puntos_pendientes:
        mas_cercano = min(puntos_pendientes, key=lambda x: geodesic(punto_actual, x['Coords']).km)
        ruta_optimizada.append(mas_cercano)
        punto_actual = mas_cercano['Coords']
        puntos_pendientes.remove(mas_cercano)
    return ruta_optimizada

# --- ESTADO DE SESIÓN ---
if 'df_final' not in st.session_state:
    st.session_state.df_final = None

# --- INTERFAZ ---
st.title("📲 Ruta con WhatsApp (Prefijos 11, 15, 011)")

with st.sidebar:
    st.header("Configuración")
    origen_input = st.text_input("📍 Origen", "Obelisco, Buenos Aires")
    fin_input = st.text_input("🏁 Fin", "Obelisco, Buenos Aires")
    archivo_subido = st.file_uploader("Archivo PDF", type="pdf")
    if st.button("🗑️ Limpiar Todo"):
        st.session_state.df_final = None
        st.rerun()

if archivo_subido and st.session_state.df_final is None:
    with st.status("Buscando contactos y optimizando...", expanded=True):
        geolocator = ArcGIS()
        loc_o = geolocator.geocode(origen_input)
        loc_f = geolocator.geocode(fin_input)
        c_inicio = [loc_o.latitude, loc_o.longitude]
        c_fin = [loc_f.latitude, loc_f.longitude]

        puntos_pdf = []
        with pdfplumber.open(archivo_subido) as pdf:
            for page in pdf.pages:
                texto = page.extract_text()
                if not texto: continue
                bloques = re.split(r'\n(?=\d+[\s,]+\d+)', texto)
                for b in bloques:
                    lineas = b.strip().split('\n')
                    match_p = re.match(r'^(\d+)[\s,]+(\d+)', lineas[0])
                    if match_p:
                        # Buscamos teléfono con la nueva lógica
                        tel = extraer_telefono(b)
                        for l in lineas:
                            if "Argentina" in l:
                                partes = [p.strip() for p in l.split(',')]
                                dir_b = f"{limpieza_profunda_direccion(partes[0])}, {partes[2]}, Argentina"
                                loc = geolocator.geocode(dir_b)
                                if loc:
                                    puntos_pdf.append({
                                        "Direccion": partes[0], 
                                        "Coords": [loc.latitude, loc.longitude],
                                        "Telefono": tel if tel else ""
                                    })
                                break

        ruta_opt = optimizar_orden(c_inicio, puntos_pdf)
        lista_completa = [{"Tipo": "ORIGEN", "Direccion": origen_input, "Coords": c_inicio, "Telefono": ""}] + \
                         [{"Tipo": "ENTREGA", "Direccion": p['Direccion'], "Coords": p['Coords'], "Telefono": p['Telefono']} for p in ruta_opt] + \
                         [{"Tipo": "FIN", "Direccion": fin_input, "Coords": c_fin, "Telefono": ""}]
        
        st.session_state.df_final = pd.DataFrame(lista_completa)

# --- PANEL DE EDICIÓN Y MAPA ---
if st.session_state.df_final is not None:
    df = st.session_state.df_final
    col_mapa, col_editor = st.columns([2, 1])

    with col_editor:
        st.subheader("📝 Verificación de Datos")
        st.caption("Si el teléfono es incorrecto, puedes editarlo aquí (Formato: 54911...)")
        edited_df = st.data_editor(df, num_rows="dynamic", key="editor_v3", use_container_width=True)
        if st.button("🔄 Actualizar"):
            st.session_state.df_final = edited_df
            st.rerun()

    with col_mapa:
        m = folium.Map(location=df.iloc[0]['Coords'], zoom_start=12)
        folium.PolyLine(df['Coords'].tolist(), color="#1e3c72", weight=4).add_to(m)

        for i, row in df.iterrows():
            lat, lon = row['Coords']
            g_maps = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"
            
            wsp_link = ""
            if row['Telefono']:
                msg = f"Hola! Soy el chofer. Estoy llegando a {row['Direccion']}."
                wsp_link = f"<a href='https://wa.me/{row['Telefono']}?text={requests.utils.quote(msg)}' target='_blank' style='display: block; text-align: center; background-color: #25D366; color: white; padding: 10px; border-radius: 5px; text-decoration: none; margin-top: 8px; font-weight: bold;'>💬 WhatsApp</a>"

            pop_html = f"""
            <div style='font-family: Arial; width: 220px;'>
                <b style='font-size: 14px;'>Parada {i}</b><br>
                <span style='font-size: 12px; color: #666;'>{row['Direccion']}</span><br>
                <a href='{g_maps}' target='_blank' style='display: block; text-align: center; background-color: #4285F4; color: white; padding: 10px; border-radius: 5px; text-decoration: none; margin-top: 10px; font-weight: bold;'>📍 Google Maps</a>
                {wsp_link}
            </div>
            """
            
            color = "green" if row['Tipo'] == "ORIGEN" else ("red" if row['Tipo'] == "FIN" else "blue")
            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(pop_html, max_width=250),
                icon=plugins.BeautifyIcon(number=i if row['Tipo']=="ENTREGA" else None, border_color=color, text_color=color, icon_shape='marker')
            ).add_to(m)

        st_folium(m, width="100%", height=600, key="mapa_final")
