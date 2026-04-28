import os
import re
import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
 
# === CONFIGURACIÓN ===
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
HUBSPOT_API_KEY = os.environ["HUBSPOT_API_KEY"]
 
# Canal donde funciona el bot automáticamente
CANAL_CONSULTA = "consulta-cliente"
 
# Propiedades de HubSpot que queremos consultar
HUBSPOT_PROPERTIES = [
    "enc_profile_link",
    "profesion",
    "range",
    "services_quantity",
    "is_agenda_closed",
    "is_subscriber",
    "last_30_days_payment_amount_via_encuadrado",
    "subscription_plan_name",
    "subscription_plan",
    "active_not_hidden_vitrinos_count",
    "has_encuadrado_app",
    "firstname",
    "lastname",
    "email",
]
 
# === INICIALIZAR APP ===
app = App(token=SLACK_BOT_TOKEN)
 
 
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
 
 
def formatear_valor(valor):
    """Formatea un valor para mostrar en Slack."""
    if valor is None or valor == "" or valor == "null":
        return "Sin información"
    return str(valor)
 
 
def formatear_monto(valor):
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
 
 
def formatear_booleano(valor):
    """Convierte true/false a Sí/No."""
    if valor is None or valor == "" or valor == "null":
        return "Sin información"
    if str(valor).lower() in ("true", "1", "yes", "sí"):
        return "Sí"
    if str(valor).lower() in ("false", "0", "no"):
        return "No"
    return str(valor)
 
 
def construir_resumen(props):
    """Construye el mensaje de resumen para Slack."""
    nombre = f"{formatear_valor(props.get('firstname'))} {formatear_valor(props.get('lastname'))}".strip()
    if nombre == "Sin información Sin información":
        nombre = "Sin información"
 
    perfil = props.get("enc_profile_link")
    perfil_texto = f"<{perfil}|Ver perfil>" if perfil and perfil != "null" else "Sin información"
 
    resumen = f"""📋 *Resumen de cliente: {nombre}*
 
🔗 Perfil: {perfil_texto}
👤 Profesión: {formatear_valor(props.get('profesion'))}
📊 Plan: {formatear_valor(props.get('subscription_plan_name'))} ({formatear_valor(props.get('subscription_plan'))})
✅ Suscriptor activo: {formatear_booleano(props.get('is_subscriber'))}
🔒 Agenda cerrada: {formatear_booleano(props.get('is_agenda_closed'))}
📱 App descargada: {formatear_booleano(props.get('has_encuadrado_app'))}
🏪 Vitrinas activas: {formatear_valor(props.get('active_not_hidden_vitrinos_count'))}
🛍️ Servicios: {formatear_valor(props.get('services_quantity'))}
📈 Flujo de pacientes: {formatear_valor(props.get('range'))}
💰 Transado últimos 30 días: {formatear_monto(props.get('last_30_days_payment_amount_via_encuadrado'))}"""
 
    return resumen
 
 
def construir_lista_resultados(resultados):
    """Construye un mensaje con la lista de resultados encontrados."""
    mensaje = f"🔍 Encontré *{len(resultados)} resultados*. Escribe el email del que necesitas:\n\n"
    for r in resultados:
        props = r.get("properties", {})
        nombre = f"{formatear_valor(props.get('firstname'))} {formatear_valor(props.get('lastname'))}".strip()
        email = formatear_valor(props.get("email"))
        plan = formatear_valor(props.get("subscription_plan_name"))
        mensaje += f"• *{nombre}* — {email} — Plan: {plan}\n"
    return mensaje
 
 
def extraer_email(texto):
    """Extrae la primera dirección de email de un texto."""
    patron = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
    resultado = re.search(patron, texto)
    if resultado:
        return resultado.group(0)
    return None
 
 
def limpiar_texto(texto):
    """Limpia el texto de menciones de Slack y espacios extra."""
    # Remover menciones tipo <@U04G8LEN25S>
    texto = re.sub(r'<@[A-Z0-9]+>', '', texto)
    return texto.strip()
 
 
def procesar_consulta(texto, say, thread_ts):
    """Procesa una consulta de cliente por email o nombre."""
    texto_limpio = limpiar_texto(texto)
    email = extraer_email(texto_limpio)
 
    if email:
        # Búsqueda por email
        say(text=f"🔍 Buscando *{email}* en HubSpot...", thread_ts=thread_ts)
        resultados = buscar_contacto_por_email(email)
 
        if not resultados:
            say(
                text=f"❌ No encontré un contacto con el email *{email}* en HubSpot. Revisa que esté bien escrito.",
                thread_ts=thread_ts,
            )
            return
 
        resumen = construir_resumen(resultados[0].get("properties", {}))
        say(text=resumen, thread_ts=thread_ts)
 
    else:
        # Búsqueda por nombre
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
            # Un solo resultado — mostrar resumen directo
            resumen = construir_resumen(resultados[0].get("properties", {}))
            say(text=resumen, thread_ts=thread_ts)
        else:
            # Múltiples resultados — mostrar lista
            lista = construir_lista_resultados(resultados)
            say(text=lista, thread_ts=thread_ts)
 
 
# === EVENTO: Mensaje en canal ===
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
 
 
# === EVENTO: Mención de la app ===
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
 
