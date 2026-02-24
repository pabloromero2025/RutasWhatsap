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
st.set_page_config(page_title="Ruta Pro | WhatsApp & GPS", page_icon="📲", layout="wide")

# --- FUNCIONES LÓGICAS ---
def extraer_telefono(texto):
    # Busca patrones comunes de teléfonos (Argentina: 11..., 15..., etc.)
    match = re.search(r'(\d{2,4}[-\s]?\d{4}[-\s]?\d{4})', texto)
    if match:
        # Limpia el número para que solo queden dígitos
        num = re.sub(r'\D', '', match.group(1))
        # Si no tiene el código de país, agregamos el de Argentina (54)
        if not num.startswith('54'):
            num = '54' + num
        return num
    return None

def limpieza_profunda_direccion(direccion):
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
st.title("📲 Ruta Logística con WhatsApp Directo")

with st.sidebar:
    st.header("Configuración")
    origen_input = st.text_input("📍 Origen", "Obelisco, Buenos Aires")
    fin_input = st.text_input("🏁 Fin", "Obelisco, Buenos Aires")
    archivo_subido = st.file_uploader("Archivo PDF", type="pdf")
    if st.button("🗑️ Limpiar Todo"):
        st.session_state.df_final = None
        st.rerun()

if archivo_subido and st.session_state.df_final is None:
    with st.status("Procesando direcciones y contactos...", expanded=True):
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
                # Dividimos por bloques de paradas
                bloques = re.split(r'\n(?=\d+[\s,]+\d+)', texto)
                for b in bloques:
                    lineas = b.strip().split('\n')
                    match_p = re.match(r'^(\d+)[\s,]+(\d+)', lineas[0])
                    if match_p:
                        # Buscamos el teléfono en todo el bloque de esta parada
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
                                        "Telefono": tel
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
        st.subheader("📝 Editar Paradas")
        # El editor permite cambiar el teléfono si el PDF lo leyó mal
        edited_df = st.data_editor(df, num_rows="dynamic", key="editor_wsp", use_container_width=True)
        if st.button("🔄 Aplicar Cambios"):
            st.session_state.df_final = edited_df
            st.rerun()

    with col_mapa:
        m = folium.Map(location=df.iloc[0]['Coords'], zoom_start=12)
        folium.PolyLine(df['Coords'].tolist(), color="#1e3c72", weight=4).add_to(m)

        for i, row in df.iterrows():
            lat, lon = row['Coords']
            g_maps = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            
            # Link de WhatsApp
            wsp_link = ""
            if row['Telefono']:
                wsp_msg = f"Hola! Soy el chofer de la entrega. Estoy cerca de tu domicilio en {row['Direccion']}."
                wsp_link = f"<a href='https://wa.me/{row['Telefono']}?text={requests.utils.quote(wsp_msg)}' target='_blank' style='display: block; text-align: center; background-color: #25D366; color: white; padding: 8px; border-radius: 5px; text-decoration: none; margin-top: 5px;'>💬 WhatsApp</a>"

            pop_html = f"""
            <div style='font-family: Arial; width: 200px;'>
                <b>{row['Tipo']} {f'#{i}' if row['Tipo']=='ENTREGA' else ''}</b><br>
                <small>{row['Direccion']}</small><br>
                <a href='{g_maps}' target='_blank' style='display: block; text-align: center; background-color: #4285F4; color: white; padding: 8px; border-radius: 5px; text-decoration: none; margin-top: 10px;'>📍 Google Maps</a>
                {wsp_link}
            </div>
            """
            
            color = "green" if row['Tipo'] == "ORIGEN" else ("red" if row['Tipo'] == "FIN" else "blue")
            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(pop_html, max_width=250),
                icon=plugins.BeautifyIcon(number=i if row['Tipo']=="ENTREGA" else None, border_color=color, text_color=color, icon_shape='marker')
            ).add_to(m)

        st_folium(m, width="100%", height=600, key="mapa_wsp")
