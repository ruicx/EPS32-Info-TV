"""Map task business state into source-independent device views."""

from info_tv_service.config import NOTIFICATION_VALIDITY_MS
from info_tv_service.device.generated import device_pb2 as pb
from info_tv_service.tasks.models import TaskIcon, TaskRecord, TaskState


def build_card(record: TaskRecord) -> pb.Card:
    """Build a generic status card.

    Parameters
    ----------
    record : TaskRecord
        Current accepted business state.

    Returns
    -------
    Card
        Device content without coordinates or producer-specific behavior.
    """
    tones = {
        TaskState.RUNNING: pb.TONE_NEUTRAL,
        TaskState.WAITING_INPUT: pb.TONE_ATTENTION,
        TaskState.COMPLETED: pb.TONE_POSITIVE,
        TaskState.FAILED: pb.TONE_NEGATIVE,
    }
    event = record.event
    icons = {
        TaskIcon.TASK: pb.TASK_ICON_TASK,
        TaskIcon.CODE: pb.TASK_ICON_CODE,
        TaskIcon.TEST: pb.TASK_ICON_TEST,
        TaskIcon.BUILD: pb.TASK_ICON_BUILD,
        TaskIcon.REVIEW: pb.TASK_ICON_REVIEW,
        TaskIcon.DEPLOY: pb.TASK_ICON_DEPLOY,
    }
    status = pb.StatusView(text=event.state.replace("_", " "), tone=tones[event.state],
                           detail=event.detail or (event.title if event.conversation_id else ""))
    if event.progress_percent is not None:
        status.progress_percent = event.progress_percent
    return pb.Card(card_id=record.card_id, revision=record.revision,
                   view=pb.View(title=event.conversation_title or event.title, source=event.source,
                                context=event.context, icon=icons[event.icon], status=status))


def build_notification(record: TaskRecord) -> pb.Notification:
    """Build an independent notification for a state transition.

    Parameters
    ----------
    record : TaskRecord
        Task state causing the event.

    Returns
    -------
    Notification
        Notification identity and priority with a generic status view.
    """
    return pb.Notification(
        notification_id=record.event.event_id,
        priority=pb.PRIORITY_ORDINARY if record.event.state == TaskState.COMPLETED else pb.PRIORITY_IMPORTANT,
        valid_for_ms=NOTIFICATION_VALIDITY_MS,
        view=build_card(record).view,
        card_id=record.card_id,
    )
