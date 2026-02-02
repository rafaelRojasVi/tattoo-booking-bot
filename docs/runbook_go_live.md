# Go-Live Runbook

This runbook provides a comprehensive checklist and recovery procedures for going live with the tattoo booking bot.

## Pre-Launch Checklist

### Environment Configuration

- [ ] **Production Environment Variables**
  - [ ] `APP_ENV=production` is set
  - [ ] `ADMIN_API_KEY` is set (strong random key, 32+ characters)
  - [ ] `WHATSAPP_DRY_RUN=false` (to enable real message sending)
  - [ ] `WHATSAPP_ACCESS_TOKEN` is set (production token)
  - [ ] `WHATSAPP_PHONE_NUMBER_ID` is set (production phone number ID)
  - [ ] `WHATSAPP_APP_SECRET` is set (for signature verification)
  - [ ] `WHATSAPP_VERIFY_TOKEN` is set (for webhook verification)
  - [ ] `STRIPE_SECRET_KEY` is set (production key, starts with `sk_live_`)
  - [ ] `STRIPE_WEBHOOK_SECRET` is set (production webhook secret)
  - [ ] `DATABASE_URL` points to production database
  - [ ] `ACTION_TOKEN_BASE_URL` is set to production domain
  - [ ] `STRIPE_SUCCESS_URL` and `STRIPE_CANCEL_URL` are configured

- [ ] **Feature Flags**
  - [ ] `FEATURE_SHEETS_ENABLED=true` (if using Google Sheets)
  - [ ] `FEATURE_CALENDAR_ENABLED=true` (if using Google Calendar)
  - [ ] `FEATURE_NOTIFICATIONS_ENABLED=true` (if using artist notifications)
  - [ ] `FEATURE_REMINDERS_ENABLED=true` (if using reminders)
  - [ ] `DEMO_MODE=false`
  - [ ] `PILOT_MODE_ENABLED=false` (unless in pilot phase)

- [ ] **WhatsApp Templates**
  - [ ] All required templates are approved in WhatsApp Manager
  - [ ] Template language code matches `TEMPLATE_LANGUAGE_CODE` setting
  - [ ] Templates tested in sandbox environment
  - [ ] Template fallback messages are configured for 24h window scenarios

### Database

- [ ] **Migrations**
  - [ ] All migrations applied: `alembic upgrade head`
  - [ ] Database backup created before migration
  - [ ] Migration rollback plan documented

- [ ] **Indexes and Constraints**
  - [ ] Unique constraints verified (payment_intent_id, checkout_session_id)
  - [ ] Indexes created for performance (wa_from, lead_id, message_id)
  - [ ] Foreign key constraints verified

### External Services

- [ ] **WhatsApp Business API**
  - [ ] Webhook endpoint configured in Meta Business Manager
  - [ ] Webhook verification token matches `WHATSAPP_VERIFY_TOKEN`
  - [ ] Webhook signature verification enabled
  - [ ] Test webhook received and verified

- [ ] **Stripe**
  - [ ] Webhook endpoint configured in Stripe Dashboard
  - [ ] Webhook secret matches `STRIPE_WEBHOOK_SECRET`
  - [ ] Test webhook received and verified
  - [ ] Checkout success/cancel URLs configured
  - [ ] Deposit amounts verified (SMALL, MEDIUM, LARGE, XL)

- [ ] **Google Services** (if enabled)
  - [ ] Google Sheets API credentials configured
  - [ ] Google Calendar API credentials configured
  - [ ] Test writes to Sheets verified
  - [ ] Calendar slot fetching tested

### Monitoring and Observability

- [ ] **Logging**
  - [ ] Structured logging configured
  - [ ] Correlation IDs enabled for webhook events
  - [ ] Log aggregation configured (if using external service)
  - [ ] Error alerting configured

- [ ] **Health Checks**
  - [ ] `/health` endpoint tested
  - [ ] Health check monitoring configured
  - [ ] Database connectivity verified

- [ ] **Debug Endpoints**
  - [ ] `/admin/debug/lead/{id}` tested (admin access only)
  - [ ] `/admin/events` tested for system event viewing
  - [ ] Admin API key authentication verified

### Testing

- [ ] **Guardrail Tests**
  - [ ] All tests in `test_go_live_guardrails.py` pass
  - [ ] No external HTTP calls in tests
  - [ ] Idempotency tests pass
  - [ ] Out-of-order message handling verified
  - [ ] Two-strikes handover logic tested
  - [ ] Deposit locking verified
  - [ ] Template window behavior tested

- [ ] **Integration Tests**
  - [ ] End-to-end flow tested (new lead → booked)
  - [ ] Payment flow tested (deposit → payment confirmation)
  - [ ] Handover scenarios tested
  - [ ] Edge cases tested (flexible location, ambiguous slots, etc.)

- [ ] **Load Testing** (optional)
  - [ ] Concurrent webhook handling tested
  - [ ] Database connection pool sized appropriately
  - [ ] Rate limiting configured (if applicable)

## Launch Day Procedures

### Pre-Launch (1 hour before)

1. **Final Verification**
   - [ ] Run health check: `curl https://your-domain.com/health`
   - [ ] Verify database connectivity
   - [ ] Check recent system events: `GET /admin/events?limit=10`
   - [ ] Verify WhatsApp webhook is receiving test messages
   - [ ] Verify Stripe webhook is receiving test events

2. **Backup**
   - [ ] Create database backup
   - [ ] Document current system state
   - [ ] Save current environment variable values (securely)

3. **Communication**
   - [ ] Notify team of launch time
   - [ ] Prepare rollback plan communication
   - [ ] Set up monitoring alerts

### Launch

1. **Enable Production Mode**
   - [ ] Set `WHATSAPP_DRY_RUN=false` (if not already set)
   - [ ] Verify `APP_ENV=production`
   - [ ] Restart application services

2. **Monitor Initial Traffic**
   - [ ] Watch system events: `GET /admin/events?limit=50`
   - [ ] Monitor error logs
   - [ ] Check database performance
   - [ ] Verify webhook delivery

3. **Test First Real Lead**
   - [ ] Send test message from production WhatsApp number
   - [ ] Verify lead creation
   - [ ] Verify message responses
   - [ ] Check system events for correlation IDs

### Post-Launch (First 24 hours)

1. **Continuous Monitoring**
   - [ ] Monitor system events every 15 minutes
   - [ ] Check for ERROR-level events
   - [ ] Verify no duplicate message processing
   - [ ] Monitor payment webhook delivery

2. **Key Metrics to Track**
   - [ ] Lead creation rate
   - [ ] Qualification completion rate
   - [ ] Deposit payment rate
   - [ ] Error rate (should be < 1%)
   - [ ] Average response time

3. **Common Issues to Watch For**
   - [ ] Template messages not configured (24h window issues)
   - [ ] Stripe webhook delivery failures
   - [ ] WhatsApp API rate limits
   - [ ] Database connection pool exhaustion

## Recovery Procedures

### Issue: WhatsApp Messages Not Sending

**Symptoms:**
- Messages not delivered to clients
- Error logs show `whatsapp.send_failure` events
- Health check shows WhatsApp API errors

**Recovery Steps:**

1. **Check Credentials**
   ```bash
   # Verify environment variables
   echo $WHATSAPP_ACCESS_TOKEN | head -c 10  # Should show token prefix
   echo $WHATSAPP_PHONE_NUMBER_ID
   ```

2. **Check API Status**
   - Visit Meta Status page: https://developers.facebook.com/status/
   - Check WhatsApp Business API status

3. **Verify Webhook Configuration**
   - Check Meta Business Manager webhook settings
   - Verify webhook URL is accessible
   - Test webhook verification: `GET /webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test`

4. **Check Rate Limits**
   - Review WhatsApp API rate limit documentation
   - Check for rate limit errors in logs
   - Implement rate limiting if needed

5. **Enable Dry Run Mode (Emergency)**
   - Set `WHATSAPP_DRY_RUN=true` to pause sending
   - Messages will be logged but not sent
   - Allows system to continue processing without sending

### Issue: Stripe Payments Not Processing

**Symptoms:**
- Deposit links created but payments not confirmed
- Stripe webhook events not received
- `stripe.webhook_failure` events in logs

**Recovery Steps:**

1. **Verify Webhook Configuration**
   - Check Stripe Dashboard → Webhooks
   - Verify webhook URL is correct
   - Verify webhook secret matches `STRIPE_WEBHOOK_SECRET`

2. **Test Webhook**
   - Use Stripe CLI: `stripe listen --forward-to https://your-domain.com/webhooks/stripe`
   - Send test event: `stripe trigger checkout.session.completed`

3. **Check Webhook Logs**
   - View webhook delivery logs in Stripe Dashboard
   - Check for 4xx/5xx responses
   - Verify signature verification is working

4. **Manual Payment Verification**
   - Check Stripe Dashboard for successful payments
   - Manually update lead status if needed (via admin API)
   - Use `/admin/debug/lead/{id}` to inspect lead state

### Issue: Database Performance Degradation

**Symptoms:**
- Slow API responses
- Database connection pool exhaustion
- Timeout errors

**Recovery Steps:**

1. **Check Database Metrics**
   - Monitor connection pool usage
   - Check query performance
   - Review slow query log

2. **Scale Database**
   - Increase connection pool size
   - Scale database instance (if cloud-hosted)
   - Add read replicas (if applicable)

3. **Optimize Queries**
   - Review recent migrations for missing indexes
   - Check for N+1 query patterns
   - Add database indexes if needed

4. **Emergency: Enable Panic Mode**
   - Set `FEATURE_PANIC_MODE_ENABLED=true`
   - Pauses automation, only logs and notifies artist
   - Allows manual intervention while investigating

### Issue: Invalid Status Transitions

**Symptoms:**
- `Invalid status transition` errors in logs
- Leads stuck in unexpected states
- Admin actions failing

**Recovery Steps:**

1. **Inspect Lead State**
   ```bash
   # Use debug endpoint
   curl -H "X-Admin-API-Key: YOUR_KEY" \
     https://your-domain.com/admin/debug/lead/{lead_id}
   ```

2. **Review Status History**
   - Check `status_history` in debug output
   - Identify where transition failed
   - Review system events for that lead

3. **Manual Status Correction**
   - Use admin API to manually transition status
   - Ensure transition is allowed (check `state_machine.py`)
   - Log manual intervention in admin_notes

4. **Prevent Future Issues**
   - Review code for race conditions
   - Ensure all status changes use `state_machine.transition()`
   - Add more status transition tests

### Issue: Template Messages Not Configured

**Symptoms:**
- `template_not_configured` warnings in logs
- Messages blocked outside 24h window
- `window_closed_template_not_configured` events

**Recovery Steps:**

1. **Identify Missing Templates**
   - Check system events: `GET /admin/events?event_type=template_not_configured`
   - Review `whatsapp.template_not_configured.*` events

2. **Configure Templates**
   - Create missing templates in WhatsApp Manager
   - Wait for template approval (can take hours)
   - Update `TEMPLATE_LANGUAGE_CODE` if needed

3. **Temporary Workaround**
   - Use existing templates as fallback
   - Manually send messages via WhatsApp Business app
   - Enable panic mode to pause automation

### Issue: Duplicate Message Processing

**Symptoms:**
- Same message processed multiple times
- Duplicate leads created
- Duplicate payments processed

**Recovery Steps:**

1. **Verify Idempotency**
   - Check `processed_messages` table for duplicates
   - Review message_id uniqueness
   - Check for race conditions in webhook handler

2. **Check Processed Messages**
   ```sql
   -- Find duplicate message IDs
   SELECT message_id, COUNT(*) 
   FROM processed_messages 
   GROUP BY message_id 
   HAVING COUNT(*) > 1;
   ```

3. **Fix Duplicates**
   - Remove duplicate processed_messages entries (if safe)
   - Re-process affected leads manually
   - Add additional idempotency checks if needed

### Issue: Location Parsing Failures

**Symptoms:**
- Multiple handovers due to location parsing
   - `parse_failure` events for `location_city`
   - Leads stuck in `NEEDS_ARTIST_REPLY` due to location

**Recovery Steps:**

1. **Review Parse Failures**
   - Check `parse_failure_counts` in debug output
   - Identify common failure patterns
   - Review location parsing logic

2. **Improve Parsing**
   - Add new city/country mappings to `location_parsing.py`
   - Update flexible keyword detection
   - Test with real user inputs

3. **Manual Intervention**
   - Use admin API to update lead location
   - Resume flow for affected leads
   - Add admin notes explaining manual fix

## Post-Launch Monitoring

### Daily Checks

- [ ] Review system events for errors
- [ ] Check funnel metrics
- [ ] Verify payment processing
- [ ] Monitor response times
- [ ] Review handover reasons

### Weekly Reviews

- [ ] Analyze conversion rates
- [ ] Review common parse failures
- [ ] Check template usage
- [ ] Review system performance
- [ ] Update documentation based on learnings

### Monthly Maintenance

- [ ] Database optimization
- [ ] Review and update location parsing rules
- [ ] Update WhatsApp templates if needed
- [ ] Review and rotate API keys
- [ ] Performance testing

## Emergency Contacts

- **Technical Lead**: [Contact Info]
- **Stripe Support**: https://support.stripe.com
- **WhatsApp Business Support**: https://business.facebook.com/help
- **Database Admin**: [Contact Info]

## Rollback Plan

If critical issues occur, follow this rollback procedure:

1. **Immediate Actions**
   - Set `WHATSAPP_DRY_RUN=true` to stop sending messages
   - Set `FEATURE_PANIC_MODE_ENABLED=true` to pause automation
   - Notify team of rollback

2. **Database Rollback** (if needed)
   - Restore from backup
   - Run migration rollback: `alembic downgrade -1`
   - Verify data integrity

3. **Code Rollback** (if needed)
   - Revert to previous git tag
   - Rebuild and redeploy
   - Verify deployment

4. **Post-Rollback**
   - Document issues encountered
   - Create tickets for fixes
   - Schedule post-mortem

## Success Criteria

Launch is considered successful when:

- [ ] No critical errors for 24 hours
- [ ] First real lead successfully completes flow
- [ ] Payment processing working correctly
- [ ] System events showing normal operation
- [ ] Response times within acceptable limits (< 2s)
- [ ] Error rate < 1%

## Additional Resources

- [Operations Runbook](ops_runbook.md) - Detailed production operations
- [Development Summary](DEVELOPMENT_SUMMARY.md) - System architecture
- [Quality Audit](QUALITY_AUDIT.md) - Code quality assessment
- [File Organization](FILE_ORGANIZATION.md) - Project structure
