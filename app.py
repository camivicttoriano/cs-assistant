import os
import re
import json
import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# === CONFIGURACIÓN ===
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
HUBSPOT_API_KEY = os.environ["HUBSPOT_API_KEY"]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Canal donde funciona el bot automáticamente
CANAL_CONSULTA = "consulta-cliente"

# Propiedades de HubSpot que queremos consultar
HUBSPOT_PROPERTIES = [
    "firstname",
    "lastname",
    "email",
    "enc_profile_link",
    "profesion",
    "subscription_plan_name",
    "subscription_plan",
    "is_agenda_closed",
    "valid_until",
    "hs_whatsapp_phone_number",
    "is_prescriptions_subscriber",
    "is_subscriber",
    "last_30_days_payment_amount_via_encuadrado",
    "last_30_days_bookings_count",
    "has_encuadrado_app",
    "active_not_hidden_vitrinos_count",
    "services_quantity",
    "range",
    "health_score_valle",
    "last_30_days_abandoned_cart_total_amount",
    "last_30_days_ia_wsp_assistant_bookings_count",
    "last_30_days_wsp_reviews_count",
    "center_id",
    "center_type",
    "center_member_role",
]

# === INICIALIZAR APP ===
app = App(token=SLACK_BOT_TOKEN)


# === FUNCIONES HUBSPOT ===

def buscar_contacto_por_email(email):
    """Busca un contacto en HubSpot por email."""
    url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
    headers = {
        "Authorization": f"Bearer {HUBSPOT_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": "email",
                        "operator": "EQ",
                        "value": email.strip(),
                    }
                ]
            }
        ],
        "properties": HUBSPOT_PROPERTIES,
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        return []

    data = response.json()
    return data.get("results", [])


def buscar_contacto_por_nombre(nombre):
    """Busca contactos en HubSpot por nombre usando búsqueda general."""
    url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
    headers = {
        "Authorization": f"Bearer {HUBSPOT_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": nombre.strip(),
        "properties": HUBSPOT_PROPERTIES,
        "limit": 5,
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        return []

    data = response.json()
    return data.get("results", [])


def obtener_notas_contacto(contact_id):
    """Obtiene las últimas notas asociadas a un contacto en HubSpot."""
    headers = {
        "Authorization": f"Bearer {HUBSPOT_API_KEY}",
        "Content-Type": "application/json",
    }

    # Paso 1: Obtener IDs de notas asociadas al contacto
    url = f"https://api.hubapi.com/crm/v4/objects/contacts/{contact_id}/associations/notes"
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return []

    data = response.json()
    resultados = data.get("results", [])

    if not resultados:
        return []

    # Paso 2: Obtener el contenido de las últimas 5 notas
    notas = []
    for asociacion in resultados[:5]:
        note_id = asociacion.get("toObjectId")
        if not note_id:
            continue

        url_nota = f"https://api.hubapi.com/crm/v3/objects/notes/{note_id}"
        params = {"properties": "hs_note_body,hs_timestamp,hs_createdate"}
        resp = requests.get(url_nota, headers=headers, params=params)

        if resp.status_code == 200:
            props = resp.json().get("properties", {})
            body = props.get("hs_note_body", "")
            fecha = props.get("hs_timestamp") or props.get("hs_createdate") or ""
            if body:
                # Limpiar HTML básico de las notas
                body_limpio = re.sub(r'<[^>]+>', '', body).strip()
                if body_limpio:
                    notas.append({"fecha": fecha[:10] if fecha else "", "texto": body_limpio})

    return notas


def resumir_notas_con_claude(notas):
    """Usa la API de Claude para resumir las notas del contacto."""
    if not ANTHROPIC_API_KEY or not notas:
        return None

    textos = []
    for n in notas:
        fecha = n.get("fecha", "sin fecha")
        texto = n.get("texto", "")
        textos.append(f"[{fecha}] {texto}")

    notas_combinadas = "\n\n".join(textos)

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 300,
                "messages": [
                    {
                        "role": "user",
                        "content": f"""Resume estas notas de un cliente de forma muy breve (máximo 3 líneas).
El resumen es para dar contexto rápido antes de una asesoría.
Usa español chileno, sé directo y conciso. No uses bullet points.

Notas:
{notas_combinadas}""",
                    }
                ],
            },
        )

        if response.status_code == 200:
            data = response.json()
            return data["content"][0]["text"]
        else:
            return None
    except Exception:
        return None


# === FUNCIONES DE FORMATO ===

def val(valor):
    """Formatea un valor para mostrar en Slack."""
    if valor is None or valor == "" or valor == "null":
        return "Sin información"
    return str(valor)


def monto(valor):
    """Formatea montos en pesos chilenos con separador de miles."""
    if valor is None or valor == "" or valor == "null":
        return "Sin información"
    try:
        numero = float(valor)
        if numero == int(numero):
            numero = int(numero)
        return f"${numero:,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return str(valor)


def sino(valor):
    """Convierte true/false a Sí/No."""
    if valor is None or valor == "" or valor == "null":
        return "Sin información"
    if str(valor).lower() in ("true", "1", "yes", "sí"):
        return "Sí"
    if str(valor).lower() in ("false", "0", "no"):
        return "No"
    return str(valor)


def health_score(valor):
    """Convierte el número de Health Score Valle a número + etiqueta."""
    if valor is None or valor == "" or valor == "null":
        return "Sin información"
    try:
        numero = int(float(valor))
        if numero >= 75:
            return f"{numero} — 🟢 High"
        elif numero >= 50:
            return f"{numero} — 🟡 Medium"
        else:
            return f"{numero} — 🔴 Low"
    except (ValueError, TypeError):
        return str(valor)


# === CONSTRUIR RESUMEN ===

def construir_resumen(props, contact_id=None):
    """Construye el mensaje de resumen para Slack con secciones."""
    nombre = f"{val(props.get('firstname'))} {val(props.get('lastname'))}".strip()
    if nombre == "Sin información Sin información":
        nombre = "Sin información"

    perfil = props.get("enc_profile_link")
    perfil_texto = f"<{perfil}|Ver perfil>" if perfil and perfil != "null" else "Sin información"

    plan = val(props.get("subscription_plan_name"))
    frecuencia = val(props.get("subscription_plan"))

    # === Datos generales ===
    resumen = f"""📋 *Resumen de cliente: {nombre}*

━━ *Datos generales* ━━
🔗 Perfil: {perfil_texto}
👤 Profesión: {val(props.get('profesion'))}
📊 Plan: {plan} ({frecuencia})
🔒 Agenda cerrada: {sino(props.get('is_agenda_closed'))}
📞 Teléfono: {val(props.get('hs_whatsapp_phone_number'))}
💊 Suscrito a recetas: {sino(props.get('is_prescriptions_subscriber'))}

━━ *Estado de cuenta* ━━
✅ Suscriptor activo: {sino(props.get('is_subscriber'))}
📅 Valid Until: {val(props.get('valid_until'))}
💰 Transado últimos 30 días: {monto(props.get('last_30_days_payment_amount_via_encuadrado'))}
📅 Bookings últimos 30 días: {val(props.get('last_30_days_bookings_count'))}

━━ *Uso de producto* ━━
📱 App descargada: {sino(props.get('has_encuadrado_app'))}
🏪 Vitrinas activas: {val(props.get('active_not_hidden_vitrinos_count'))}
🛍️ Servicios: {val(props.get('services_quantity'))}
📈 Flujo de pacientes: {val(props.get('range'))}
💚 Health Score Valle: {health_score(props.get('health_score_valle'))}"""

    # === Plan Avanzado (solo si es premium) ===
    if plan and plan.lower() == "premium":
        resumen += f"""

━━ *Información Plan Avanzado* ━━
💸 Dinero recuperado últimos 30 días: {monto(props.get('last_30_days_abandoned_cart_total_amount'))}
🤖 Agendamientos por Dania últimos 30 días: {val(props.get('last_30_days_ia_wsp_assistant_bookings_count'))}
⭐ Evaluaciones WSP últimos 30 días: {val(props.get('last_30_days_wsp_reviews_count'))}"""

    # === Centros (solo si tiene center_id) ===
    center_id = props.get("center_id")
    if center_id and center_id != "null" and center_id != "":
        resumen += f"""

━━ *Información Centros* ━━
🏢 Center ID: {val(center_id)}
📋 Center Type: {val(props.get('center_type'))}
👤 Center Member Role: {val(props.get('center_member_role'))}"""

    # === Notas recientes ===
    if contact_id:
        notas = obtener_notas_contacto(contact_id)
        if notas:
            resumen_notas = resumir_notas_con_claude(notas)
            if resumen_notas:
                resumen += f"""

━━ *Notas recientes* ━━
📝 {resumen_notas}"""
            else:
                # Sin Claude, mostrar la última nota truncada
                ultima = notas[0]
                texto_truncado = ultima["texto"][:200]
                if len(ultima["texto"]) > 200:
                    texto_truncado += "..."
                resumen += f"""

━━ *Notas recientes* ━━
📝 Última nota ({ultima['fecha']}): {texto_truncado}"""

    return resumen


def construir_lista_resultados(resultados):
    """Construye un mensaje con la lista de resultados encontrados."""
    mensaje = f"🔍 Encontré *{len(resultados)} resultados*. Escribe el email del que necesitas:\n\n"
    for r in resultados:
        props = r.get("properties", {})
        nombre = f"{val(props.get('firstname'))} {val(props.get('lastname'))}".strip()
        email = val(props.get("email"))
        plan = val(props.get("subscription_plan_name"))
        mensaje += f"• *{nombre}* — {email} — Plan: {plan}\n"
    return mensaje


# === FUNCIONES AUXILIARES ===

def extraer_email(texto):
    """Extrae la primera dirección de email de un texto."""
    patron = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
    resultado = re.search(patron, texto)
    if resultado:
        return resultado.group(0)
    return None


def limpiar_texto(texto):
    """Limpia el texto de menciones de Slack y espacios extra."""
    texto = re.sub(r'<@[A-Z0-9]+>', '', texto)
    return texto.strip()


def procesar_consulta(texto, say, thread_ts):
    """Procesa una consulta de cliente por email o nombre."""
    texto_limpio = limpiar_texto(texto)
    email = extraer_email(texto_limpio)

    if email:
        say(text=f"🔍 Buscando *{email}* en HubSpot...", thread_ts=thread_ts)
        resultados = buscar_contacto_por_email(email)

        if not resultados:
            say(
                text=f"❌ No encontré un contacto con el email *{email}* en HubSpot. Revisa que esté bien escrito.",
                thread_ts=thread_ts,
            )
            return

        contact_id = resultados[0].get("id")
        resumen = construir_resumen(resultados[0].get("properties", {}), contact_id)
        say(text=resumen, thread_ts=thread_ts)

    else:
        nombre = texto_limpio
        if not nombre:
            say(
                text="👋 Escribe el email o nombre del cliente que quieres consultar.",
                thread_ts=thread_ts,
            )
            return

        say(text=f"🔍 Buscando *{nombre}* en HubSpot...", thread_ts=thread_ts)
        resultados = buscar_contacto_por_nombre(nombre)

        if not resultados:
            say(
                text=f"❌ No encontré ningún contacto con el nombre *{nombre}* en HubSpot.",
                thread_ts=thread_ts,
            )
            return

        if len(resultados) == 1:
            contact_id = resultados[0].get("id")
            resumen = construir_resumen(resultados[0].get("properties", {}), contact_id)
            say(text=resumen, thread_ts=thread_ts)
        else:
            lista = construir_lista_resultados(resultados)
            say(text=lista, thread_ts=thread_ts)


# === EVENTOS SLACK ===

@app.event("message")
def manejar_mensaje(event, say, client):
    """Responde cuando alguien escribe en #consulta-cliente."""

    if event.get("bot_id") or event.get("subtype"):
        return

    canal_info = client.conversations_info(channel=event["channel"])
    canal_nombre = canal_info["channel"]["name"]

    if canal_nombre != CANAL_CONSULTA:
        return

    procesar_consulta(event.get("text", ""), say, event["ts"])


@app.event("app_mention")
def manejar_mencion(event, say, client):
    """Responde cuando alguien etiqueta a la app con un email o nombre."""
    thread_ts = event.get("thread_ts", event["ts"])
    procesar_consulta(event.get("text", ""), say, thread_ts)


# === INICIAR ===
if __name__ == "__main__":
    print("🤖 CS Assistant está corriendo...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
