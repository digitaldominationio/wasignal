"""Demo data so the API is useful the moment it boots.

Idempotent: does nothing when a partner already exists.
"""
from __future__ import annotations

import time

from . import repo
from .services import billing


def seed_demo() -> None:
    if repo.count_partners():
        return

    now = int(time.time())
    pid = repo.create_partner("9999000001", "Ambition Academy")
    repo.set_wa_linked(pid, True)
    org = repo.create_org(pid, "Ambition Academy", "ambition-academy")
    billing.ensure_plans()
    billing.subscribe(int(org["id"]), "growth")
    account_id = repo.create_account_full(
        int(org["id"]), pid, "Ambition Academy", "+919999000001", "Asia/Kolkata", "active"
    )

    aarav = repo.ensure_room(account_id, "919900000001@s.whatsapp.net", "dm", "Aarav Sharma")
    _team = repo.ensure_room(account_id, "120363000000000001@g.us", "group", "Sales team")
    _meera = repo.ensure_room(account_id, "919900000002@s.whatsapp.net", "dm", "Meera (no reply)")

    agent = repo.create_agent(account_id, {
        "name": "Admissions counsellor",
        "system_prompt": (
            "You are the admissions counsellor for Ambition Academy, a NEET/JEE coaching centre in Jaipur. "
            "You answer fee, batch, hostel and scholarship questions from the price list, qualify the lead "
            "(exam, year, city), and book a counselling slot when they are ready. "
            "Never quote a discount that is not in the knowledge base. If a parent is upset or asks for a human, hand over."
        ),
        "trigger_type": "event",
        "trigger_scope": "room",
        "trigger_condition": "fees, fee, price, batch, hostel, admission, NEET, JEE, counselling",
        "chat_type": "all",
        "capabilities": ["read", "send", "send_other"],
        "tool_suites": ["messaging", "media", "knowledge"],
    })

    source = repo.create_source(account_id, {
        "name": "Fee & batch details",
        "source_room_id": aarav["external_id"],
        "extraction_instruction": "Extract every batch, fee, hostel charge and scholarship rule.",
    })
    repo.create_entry(source["id"], {
        "keys": ["neet", "dropper", "fee", "batch"],
        "title": "NEET dropper batch 2026",
        "content": "Starts 15 July. Full year ₹1,45,000. EMI available. Hostel ₹9,500/month including mess.",
        "metadata": {"currency": "INR"},
    })
    repo.create_entry(source["id"], {
        "keys": ["jee", "crash", "fee"],
        "title": "JEE crash course",
        "content": "6-week crash course, ₹38,000, weekday evenings 6–9 PM. No hostel included.",
        "metadata": {"currency": "INR"},
    })
    repo.create_entry(source["id"], {
        "keys": ["scholarship", "discount"],
        "title": "Scholarship",
        "content": "10% off for students scoring above 90% in the previous board exam. Proof required at admission.",
        "metadata": {"currency": "INR"},
    })
    repo.set_agent_knowledge(agent["id"], [source["id"]])

    webhook = repo.create_webhook(account_id, {
        "name": "Log hot lead",
        "description": "Log a qualified lead in the CRM. Use when the customer is ready for a counselling call.",
        "url": "https://httpbin.org/post",
        "method": "POST",
        "headers": [{"name": "X-Api-Key", "value": "replace-me", "secret": True}],
        "body_fields": [
            {"key": "name", "description": "Customer name", "type": "string", "required": False,
             "source": "agent"},
            {"key": "phone", "description": "Customer WhatsApp number", "type": "string", "required": False,
             "source": "context", "context_key": "room_name"},
            {"key": "note", "description": "What they asked for", "type": "string", "required": False,
             "source": "agent"},
        ],
    })
    repo.update_agent(account_id, agent["id"], {"webhook_ids": [webhook["id"]]})

    repo.put_followup_rules(account_id, agent["id"], {
        "enabled": False,
        "rules": [
            {"id": "r1", "message": "Nudge referencing what they asked, 12 hours later.",
             "message_mode": "generated", "delay_seconds": 12 * 3600},
            {"id": "r2", "message": "Softer second nudge, capped at two touches.",
             "message_mode": "generated", "delay_seconds": 48 * 3600},
        ],
        "send_window": {"timezone": "Asia/Kolkata", "days": [0, 1, 2, 3, 4, 5], "start": "09:00", "end": "21:00"},
    })

    repo.add_message(account_id, aarav["id"], "in",
                     "Hi, what's the fee for the NEET dropper batch? Is hostel available?",
                     sender=aarav["external_id"], sender_name="Aarav Sharma")
    repo.add_message(account_id, aarav["id"], "out",
                     "Hi Aarav! Dropper batch starts 15 July — ₹1,45,000 for the full year, EMI available. "
                     "Hostel is ₹9,500/month including mess. Would you like to book a counselling slot?",
                     source="whatsapp", agent_id=agent["id"], status="delivered")

    # Assistant inbox: the same system events the running product writes.
    system = repo.ensure_system_room(account_id)
    repo.add_message(
        account_id, system["id"], "in",
        "Your dashboard OTP is 486197. Valid for the next 10 minutes.",
        sender="wasignal", sender_name="Wasignal", source="otp", ts=now - 2 * 86_400 - 120,
    )
    repo.add_message(
        account_id, system["id"], "in",
        "Scan this QR code in WhatsApp → Settings → Linked devices → Link a device",
        sender="wasignal", sender_name="Wasignal", source="system",
        media=[{"type": "qr", "name": "WhatsApp QR code", "url": None}],
        ts=now - 2 * 86_400 + 240,
    )
    repo.add_message(
        account_id, system["id"], "in",
        "[WHATSAPP_ACCOUNT_DISCONNECTED] Your WhatsApp account has been disconnected from Wasignal. "
        "Please re-link your WhatsApp account to continue using Wasignal.",
        sender="wasignal", sender_name="Wasignal", source="system", ts=now - 2 * 86_400 + 900,
    )
    repo.add_message(
        account_id, system["id"], "in",
        "WhatsApp connected · +919999000001. Your automations are live.",
        sender="wasignal", sender_name="Wasignal", source="system", ts=now - 3 * 3600,
    )

    print(f"[seed] partner pid={pid} account={account_id} agent={agent['id']} room={aarav['id']}")
