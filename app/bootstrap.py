"""Composition root: the only place binding invitation use cases to adapters."""
from dataclasses import dataclass

from app import accounts
from app.application.invitations.attempts import InvitationAttempt
from app.application.invitations.campaigns import CampaignRunner
from app.application.invitations.context import InviteContextResolver
from app.application.invitations.failures import InvitationFailureHandler
from app.application.invitations.ports import (
    AccountPort,
    AttemptNotifier,
    InvitationRepository,
    TelegramGateway,
)
from app.application.invitations.preparation import CampaignAccountPreparation
from app.application.invitations.recovery import CampaignAccountRecovery
from app.application.invitations.retry import ConnectionRetry
from app.application.invitations.runtime import CampaignRuntime
from app.application.invitations.scheduling import InvitationScheduler
from app.application.invitations.targets import CampaignTargetBuilder
from app.application.invitations.technical_failures import TechnicalFailureHandler
from app.application.invitations.verification import MembershipVerification
from app.application.invitations.worker import AccountWorker
from app.infrastructure.invitations.notifications import CallbackAttemptNotifier
from app.infrastructure.invitations.repository import SqliteInvitationRepository
from app.infrastructure.invitations.telegram import TelethonInvitationGateway


@dataclass
class InvitationApplication:
    runtime: CampaignRuntime
    repository: InvitationRepository
    gateway: TelegramGateway
    notifier: AttemptNotifier
    targets: CampaignTargetBuilder
    scheduler: InvitationScheduler
    retry: ConnectionRetry
    context: InviteContextResolver
    verification: MembershipVerification
    preparation: CampaignAccountPreparation
    attempts: InvitationAttempt
    worker: AccountWorker
    campaigns: CampaignRunner
    recovery: CampaignAccountRecovery


def create_invitation_application(
    repository: InvitationRepository | None = None,
    account_port: AccountPort = accounts,
    gateway: TelegramGateway | None = None,
    notifier: AttemptNotifier | None = None,
) -> InvitationApplication:
    """Each call creates isolated task state; ports can be replaced in tests."""
    repository = repository if repository is not None else SqliteInvitationRepository()
    gateway = gateway if gateway is not None else TelethonInvitationGateway(repository)
    notifier = notifier if notifier is not None else CallbackAttemptNotifier(repository)
    runtime = CampaignRuntime()
    targets = CampaignTargetBuilder(repository)
    scheduler = InvitationScheduler(repository, account_port, runtime)
    retry = ConnectionRetry(repository, account_port, gateway)
    context = InviteContextResolver(repository, account_port, gateway, runtime)
    verification = MembershipVerification(repository, gateway, context, account_port)
    preparation = CampaignAccountPreparation(repository, account_port, gateway, retry, runtime, notifier)
    technical = TechnicalFailureHandler(repository, account_port)
    failures = InvitationFailureHandler(repository, account_port, runtime, technical)
    attempts = InvitationAttempt(
        repository,
        account_port,
        gateway,
        context,
        retry,
        scheduler,
        verification,
        notifier,
        failures,
    )
    worker = AccountWorker(repository, account_port, runtime, preparation, verification, attempts)
    campaigns = CampaignRunner(repository, runtime, preparation, scheduler, worker)
    recovery = CampaignAccountRecovery(repository, account_port, runtime, preparation, campaigns.spawn_worker)
    return InvitationApplication(
        runtime,
        repository,
        gateway,
        notifier,
        targets,
        scheduler,
        retry,
        context,
        verification,
        preparation,
        attempts,
        worker,
        campaigns,
        recovery,
    )


invitations = create_invitation_application()
