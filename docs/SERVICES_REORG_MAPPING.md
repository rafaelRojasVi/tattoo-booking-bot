# Phase B: app/services reorganization mapping

## Mapping table (old → new, reason)

| Old path | New path | Reason |
|----------|----------|--------|
| app/services/conversation.py | app/services/conversation/conversation.py | Main conversation flow orchestrator |
| app/services/conversation_booking.py | app/services/conversation/conversation_booking.py | Booking phase logic |
| app/services/conversation_qualifying.py | app/services/conversation/conversation_qualifying.py | Qualifying phase logic |
| app/services/conversation_policy.py | app/services/conversation/conversation_policy.py | Opt-in/out policy |
| app/services/conversation_deps.py | app/services/conversation/conversation_deps.py | Conversation dependency injection |
| app/services/state_machine.py | app/services/conversation/state_machine.py | Status transition logic |
| app/services/handover_service.py | app/services/conversation/handover_service.py | Handover decision logic |
| app/services/handover_packet.py | app/services/conversation/handover_packet.py | Handover packet builder |
| app/services/summary.py | app/services/conversation/summary.py | Artist summary builder |
| app/services/questions.py | app/services/conversation/questions.py | Consultation questions |
| app/services/time_window_collection.py | app/services/conversation/time_window_collection.py | Time window collection in flow |
| app/services/tour_service.py | app/services/conversation/tour_service.py | Tour cities / waitlist |
| app/services/leads.py | app/services/leads/leads.py | Lead CRUD and identity |
| app/services/sheets.py | app/services/integrations/sheets.py | Google Sheets integration |
| app/services/stripe_service.py | app/services/integrations/stripe_service.py | Stripe integration |
| app/services/calendar_service.py | app/services/integrations/calendar_service.py | Google Calendar integration |
| app/services/calendar_rules.py | app/services/integrations/calendar_rules.py | Calendar rules config |
| app/services/http_client.py | app/services/integrations/http_client.py | HTTP client factory |
| app/services/media_upload.py | app/services/integrations/media_upload.py | Media upload (Supabase) |
| app/services/artist_notifications.py | app/services/integrations/artist_notifications.py | Artist notification channel |
| app/services/messaging.py | app/services/messaging/messaging.py | Send WhatsApp messages |
| app/services/message_composer.py | app/services/messaging/message_composer.py | Compose messages from YAML |
| app/services/whatsapp_window.py | app/services/messaging/whatsapp_window.py | 24h window handling |
| app/services/whatsapp_templates.py | app/services/messaging/whatsapp_templates.py | Template helpers |
| app/services/whatsapp_verification.py | app/services/messaging/whatsapp_verification.py | Webhook verification |
| app/services/outbox_service.py | app/services/messaging/outbox_service.py | Outbox for deferred sends |
| app/services/template_registry.py | app/services/messaging/template_registry.py | Template registry |
| app/services/template_check.py | app/services/messaging/template_check.py | Startup template check |
| app/services/template_core.py | app/services/messaging/template_core.py | Core template config |
| app/services/bundle_guard.py | app/services/messaging/bundle_guard.py | Multi-answer guard |
| app/services/reminders.py | app/services/messaging/reminders.py | Reminder job (sends messages) |
| app/services/slot_parsing.py | app/services/parsing/slot_parsing.py | Parse slot selection |
| app/services/location_parsing.py | app/services/parsing/location_parsing.py | Parse location |
| app/services/parse_repair.py | app/services/parsing/parse_repair.py | Parse failure repair |
| app/services/text_normalization.py | app/services/parsing/text_normalization.py | Text normalization |
| app/services/estimation_service.py | app/services/parsing/estimation_service.py | Budget/dimensions parsing |
| app/services/region_service.py | app/services/parsing/region_service.py | Region/country logic |
| app/services/pricing_service.py | app/services/parsing/pricing_service.py | Price calculation |
| app/services/metrics.py | app/services/metrics/metrics.py | Metrics collection |
| app/services/funnel_metrics_service.py | app/services/metrics/funnel_metrics_service.py | Funnel metrics |
| app/services/system_event_service.py | app/services/metrics/system_event_service.py | System events |

## Left at app/services/ (root)

| File | Reason |
|------|--------|
| action_tokens.py | Cross-cutting; used by conversation and api |
| safety.py | Idempotency/processed events; cross-cutting |
| artist_config.py | Config used everywhere; keep at root to avoid cycles |
