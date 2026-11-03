"""Atomic task admission and source-independent display publication."""

from info_tv_service.device.session import DeviceSession
from info_tv_service.device.views import build_card, build_notification
from info_tv_service.tasks.models import TaskEvent
from info_tv_service.tasks.store import AdmissionError, TaskStore


class TaskService:
    """Coordinate business state and bounded device delivery on one event loop."""

    def __init__(self, store: TaskStore, device: DeviceSession) -> None:
        """Retain explicit dependencies.

        Parameters
        ----------
        store : TaskStore
            Application-owned current task state.
        device : DeviceSession
            Application-owned downstream session.
        """
        self.store = store
        self.device = device

    def submit_event(self, event: TaskEvent) -> dict[str, object]:
        """Validate ordering, reserve capacity, and commit without yielding.

        Parameters
        ----------
        event : TaskEvent
            Validated producer event.

        Returns
        -------
        dict[str, object]
            Admission outcome, card revision, and notification disposition.

        Raises
        ------
        AdmissionError
            If input conflicts or bounded state cannot admit the update.
        """
        update = self.store.prepare(event)
        notification = "none"
        if update.outcome == "accepted":
            if update.notify and self.device.online and not self.device.can_notify():
                raise AdmissionError("Notification queue is full; retry the event", 503)
            self.store.commit(update)
            self.device.publish_card(build_card(update.record))
            if update.notify:
                notification = "queued" if self.device.online else "skipped_offline"
                if self.device.online:
                    self.device.enqueue_notification(build_notification(update.record))
        return {"outcome": update.outcome, "card_id": update.record.card_id,
                "revision": update.record.revision, "notification": notification,
                "device_state": self.device.get_status()["state"]}
