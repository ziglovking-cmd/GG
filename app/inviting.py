"""Public invitation API used by the HTTP and preflight adapters.

Implementation is composed in bootstrap; domain/application code never imports
this facade. Existing HTTP callers keep the same public operations and state.
"""
from app.bootstrap import invitations
from app.domain.invitations import WorkerRecoveryError, settings_json

STATE = invitations.runtime.state
RUNNERS = invitations.runtime.runners

start = invitations.campaigns.start
stop = invitations.campaigns.stop
run_campaign = invitations.campaigns.run_campaign
recover_campaign_account = invitations.recovery.recover_campaign_account
campaign_stats = invitations.repository.campaign_stats
build_targets = invitations.targets.build_targets
resolve_target_chat = invitations.gateway.resolve_target_chat
can_invite = invitations.gateway.can_invite
set_attempt_notifier = invitations.notifier.set
