"""
WhatsApp messaging service with dry-run mode for development.
"""

import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_whatsapp_message(
    to: str,
    message: str,
    dry_run: bool = True,
) -> dict:
    """
    Send a WhatsApp message.
    
    Args:
        to: WhatsApp phone number (with country code, no +)
        message: Message text to send
        dry_run: If True, only log the message (don't actually send)
        
    Returns:
        dict with status and message_id (or None in dry-run)
    """
    if dry_run:
        logger.info(f"[DRY-RUN] Would send WhatsApp message to {to}: {message}")
        return {
            "status": "dry_run",
            "message_id": None,
            "to": to,
            "message": message,
        }
    
    try:
        import httpx
        
        url = f"https://graph.facebook.com/v18.0/{settings.whatsapp_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            
            return {
                "status": "sent",
                "message_id": result.get("messages", [{}])[0].get("id"),
                "to": to,
            }
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        raise


def format_summary_message(answers: dict) -> str:
    """
    Format a structured summary of the consultation.
    
    Args:
        answers: Dict mapping question_key to answer_text
        
    Returns:
        Formatted summary string
    """
    summary_lines = [
        "🎨 *Tattoo Consultation Summary*\n",
        "Here's what we've captured:\n",
    ]
    
    question_labels = {
        "idea": "💭 Tattoo Idea",
        "placement": "📍 Placement",
        "size": "📏 Size",
        "style": "🎨 Style",
        "budget_range": "💰 Budget Range",
        "reference_images": "🖼️ Reference Images",
        "preferred_days": "📅 Preferred Days/Times",
    }
    
    for key, label in question_labels.items():
        if key in answers:
            answer = answers[key]
            if answer and answer.lower() not in ["no", "none", "n/a"]:
                summary_lines.append(f"*{label}:* {answer}")
    
    summary_lines.append("\n✅ Perfect! Next step is to secure your booking with a deposit.")
    summary_lines.append("We'll send you a payment link shortly.")
    
    return "\n".join(summary_lines)


def format_deposit_link_message(checkout_url: str, amount_pence: int) -> str:
    """
    Format message for sending deposit payment link.
    
    Args:
        checkout_url: Stripe checkout URL
        amount_pence: Deposit amount in pence
        
    Returns:
        Formatted message string
    """
    amount_gbp = amount_pence / 100
    message = (
        f"💳 *Deposit Payment Link*\n\n"
        f"Great news! Your booking request has been approved.\n\n"
        f"To secure your booking, please pay the deposit of *£{amount_gbp:.2f}* using the link below:\n\n"
        f"{checkout_url}\n\n"
        f"Once your deposit is confirmed, I'll send you a booking link to schedule your appointment.\n\n"
        f"Thanks! 🙏"
    )
    return message


def format_payment_confirmation_message(amount_pence: int) -> str:
    """
    Format message confirming deposit payment.
    
    Args:
        amount_pence: Deposit amount in pence
        
    Returns:
        Formatted message string
    """
    amount_gbp = amount_pence / 100
    message = (
        f"✅ *Deposit Confirmed!*\n\n"
        f"Thank you! Your deposit of *£{amount_gbp:.2f}* has been received.\n\n"
        f"I'll send you a booking link shortly so you can schedule your appointment.\n\n"
        f"Looking forward to working with you! 🎨"
    )
    return message
