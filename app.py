import os
import re
import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# === CONFIGURACIÓN ===
# Estos valores se leen de variables de entorno (archivo .env)
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]          # xoxb-...
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]           # xapp-...
HUBSPOT_API_KEY = os.environ["HUBSPOT_API_KEY"]           # pat-...

# Canal donde funciona el bot
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


def buscar_contacto_hubspot(email):
    """Busca un contacto en HubSpot por email y devuelve sus propiedades."""
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
        return None

    data = response.json()
    if data.get("total", 0) == 0:
        return None

    return data["results"][0]["properties"]


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


def extraer_email(texto):
    """Extrae la primera dirección de email de un texto."""
    patron = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
    resultado = re.search(patron, texto)
    if resultado:
        return resultado.group(0)
    return None


# === EVENTO: Mensaje en canal ===
@app.event("message")
def manejar_mensaje(event, say, client):
    """Responde cuando alguien escribe un email en #consulta-cliente."""

    # Ignorar mensajes de bots (incluido el propio)
    if event.get("bot_id") or event.get("subtype"):
        return

    # Obtener info del canal
    canal_info = client.conversations_info(channel=event["channel"])
    canal_nombre = canal_info["channel"]["name"]

    # Solo responder en #consulta-cliente
    if canal_nombre != CANAL_CONSULTA:
        return

    texto = event.get("text", "")
    email = extraer_email(texto)

    if not email:
        say(
            text="👋 Escribe el email del cliente que quieres consultar y te traigo su info de HubSpot.",
            thread_ts=event["ts"],
        )
        return

    # Buscar en HubSpot
    say(
        text=f"🔍 Buscando *{email}* en HubSpot...",
        thread_ts=event["ts"],
    )

    props = buscar_contacto_hubspot(email)

    if props is None:
        say(
            text=f"❌ No encontré un contacto con el email *{email}* en HubSpot. Revisa que esté bien escrito.",
            thread_ts=event["ts"],
        )
        return

    # Enviar resumen
    resumen = construir_resumen(props)
    say(
        text=resumen,
        thread_ts=event["ts"],
    )


# === EVENTO: Mención de la app ===
@app.event("app_mention")
def manejar_mencion(event, say, client):
    """Responde cuando alguien etiqueta a la app con un email."""

    texto = event.get("text", "")
    email = extraer_email(texto)

    if not email:
        say(
            text="👋 Etiquétame con el email del cliente, por ejemplo: `@CS Assistant cliente@ejemplo.com`",
            thread_ts=event.get("thread_ts", event["ts"]),
        )
        return

    say(
        text=f"🔍 Buscando *{email}* en HubSpot...",
        thread_ts=event.get("thread_ts", event["ts"]),
    )

    props = buscar_contacto_hubspot(email)

    if props is None:
        say(
            text=f"❌ No encontré un contacto con el email *{email}* en HubSpot. Revisa que esté bien escrito.",
            thread_ts=event.get("thread_ts", event["ts"]),
        )
        return

    resumen = construir_resumen(props)
    say(
        text=resumen,
        thread_ts=event.get("thread_ts", event["ts"]),
    )


# === INICIAR ===
if __name__ == "__main__":
    print("🤖 CS Assistant está corriendo...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
