from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Tone(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TONE_UNSPECIFIED: _ClassVar[Tone]
    TONE_NEUTRAL: _ClassVar[Tone]
    TONE_ATTENTION: _ClassVar[Tone]
    TONE_POSITIVE: _ClassVar[Tone]
    TONE_NEGATIVE: _ClassVar[Tone]

class TaskIcon(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TASK_ICON_TASK: _ClassVar[TaskIcon]
    TASK_ICON_CODE: _ClassVar[TaskIcon]
    TASK_ICON_TEST: _ClassVar[TaskIcon]
    TASK_ICON_BUILD: _ClassVar[TaskIcon]
    TASK_ICON_REVIEW: _ClassVar[TaskIcon]
    TASK_ICON_DEPLOY: _ClassVar[TaskIcon]

class Priority(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PRIORITY_UNSPECIFIED: _ClassVar[Priority]
    PRIORITY_ORDINARY: _ClassVar[Priority]
    PRIORITY_IMPORTANT: _ClassVar[Priority]

class AckStage(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ACK_STAGE_UNSPECIFIED: _ClassVar[AckStage]
    ACK_STAGE_ACCEPTED: _ClassVar[AckStage]
    ACK_STAGE_PRESENTED: _ClassVar[AckStage]

class ErrorCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ERROR_CODE_UNSPECIFIED: _ClassVar[ErrorCode]
    ERROR_CODE_INVALID: _ClassVar[ErrorCode]
    ERROR_CODE_BUSY: _ClassVar[ErrorCode]
    ERROR_CODE_UNSUPPORTED: _ClassVar[ErrorCode]
    ERROR_CODE_EXPIRED: _ClassVar[ErrorCode]
TONE_UNSPECIFIED: Tone
TONE_NEUTRAL: Tone
TONE_ATTENTION: Tone
TONE_POSITIVE: Tone
TONE_NEGATIVE: Tone
TASK_ICON_TASK: TaskIcon
TASK_ICON_CODE: TaskIcon
TASK_ICON_TEST: TaskIcon
TASK_ICON_BUILD: TaskIcon
TASK_ICON_REVIEW: TaskIcon
TASK_ICON_DEPLOY: TaskIcon
PRIORITY_UNSPECIFIED: Priority
PRIORITY_ORDINARY: Priority
PRIORITY_IMPORTANT: Priority
ACK_STAGE_UNSPECIFIED: AckStage
ACK_STAGE_ACCEPTED: AckStage
ACK_STAGE_PRESENTED: AckStage
ERROR_CODE_UNSPECIFIED: ErrorCode
ERROR_CODE_INVALID: ErrorCode
ERROR_CODE_BUSY: ErrorCode
ERROR_CODE_UNSUPPORTED: ErrorCode
ERROR_CODE_EXPIRED: ErrorCode

class Envelope(_message.Message):
    __slots__ = ("protocol_version", "session_id", "message_id", "hello", "snapshot", "card_upsert", "notification", "acknowledgment", "error", "ping", "pong")
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    HELLO_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    CARD_UPSERT_FIELD_NUMBER: _ClassVar[int]
    NOTIFICATION_FIELD_NUMBER: _ClassVar[int]
    ACKNOWLEDGMENT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    PING_FIELD_NUMBER: _ClassVar[int]
    PONG_FIELD_NUMBER: _ClassVar[int]
    protocol_version: int
    session_id: str
    message_id: str
    hello: Hello
    snapshot: Snapshot
    card_upsert: CardUpsert
    notification: Notification
    acknowledgment: Acknowledgment
    error: Error
    ping: Ping
    pong: Pong
    def __init__(self, protocol_version: _Optional[int] = ..., session_id: _Optional[str] = ..., message_id: _Optional[str] = ..., hello: _Optional[_Union[Hello, _Mapping]] = ..., snapshot: _Optional[_Union[Snapshot, _Mapping]] = ..., card_upsert: _Optional[_Union[CardUpsert, _Mapping]] = ..., notification: _Optional[_Union[Notification, _Mapping]] = ..., acknowledgment: _Optional[_Union[Acknowledgment, _Mapping]] = ..., error: _Optional[_Union[Error, _Mapping]] = ..., ping: _Optional[_Union[Ping, _Mapping]] = ..., pong: _Optional[_Union[Pong, _Mapping]] = ...) -> None: ...

class Hello(_message.Message):
    __slots__ = ("boot_id", "max_cards", "task_icons")
    BOOT_ID_FIELD_NUMBER: _ClassVar[int]
    MAX_CARDS_FIELD_NUMBER: _ClassVar[int]
    TASK_ICONS_FIELD_NUMBER: _ClassVar[int]
    boot_id: int
    max_cards: int
    task_icons: bool
    def __init__(self, boot_id: _Optional[int] = ..., max_cards: _Optional[int] = ..., task_icons: bool = ...) -> None: ...

class Ping(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Pong(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StatusView(_message.Message):
    __slots__ = ("text", "tone", "detail", "progress_percent")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    TONE_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_PERCENT_FIELD_NUMBER: _ClassVar[int]
    text: str
    tone: Tone
    detail: str
    progress_percent: int
    def __init__(self, text: _Optional[str] = ..., tone: _Optional[_Union[Tone, str]] = ..., detail: _Optional[str] = ..., progress_percent: _Optional[int] = ...) -> None: ...

class View(_message.Message):
    __slots__ = ("title", "source", "context", "icon", "status")
    TITLE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    ICON_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    title: str
    source: str
    context: str
    icon: TaskIcon
    status: StatusView
    def __init__(self, title: _Optional[str] = ..., source: _Optional[str] = ..., context: _Optional[str] = ..., icon: _Optional[_Union[TaskIcon, str]] = ..., status: _Optional[_Union[StatusView, _Mapping]] = ...) -> None: ...

class Card(_message.Message):
    __slots__ = ("card_id", "revision", "view")
    CARD_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    VIEW_FIELD_NUMBER: _ClassVar[int]
    card_id: str
    revision: int
    view: View
    def __init__(self, card_id: _Optional[str] = ..., revision: _Optional[int] = ..., view: _Optional[_Union[View, _Mapping]] = ...) -> None: ...

class Snapshot(_message.Message):
    __slots__ = ("cards",)
    CARDS_FIELD_NUMBER: _ClassVar[int]
    cards: _containers.RepeatedCompositeFieldContainer[Card]
    def __init__(self, cards: _Optional[_Iterable[_Union[Card, _Mapping]]] = ...) -> None: ...

class CardUpsert(_message.Message):
    __slots__ = ("card",)
    CARD_FIELD_NUMBER: _ClassVar[int]
    card: Card
    def __init__(self, card: _Optional[_Union[Card, _Mapping]] = ...) -> None: ...

class Notification(_message.Message):
    __slots__ = ("notification_id", "priority", "display_duration_ms", "valid_for_ms", "view", "card_id")
    NOTIFICATION_ID_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    VALID_FOR_MS_FIELD_NUMBER: _ClassVar[int]
    VIEW_FIELD_NUMBER: _ClassVar[int]
    CARD_ID_FIELD_NUMBER: _ClassVar[int]
    notification_id: str
    priority: Priority
    display_duration_ms: int
    valid_for_ms: int
    view: View
    card_id: str
    def __init__(self, notification_id: _Optional[str] = ..., priority: _Optional[_Union[Priority, str]] = ..., display_duration_ms: _Optional[int] = ..., valid_for_ms: _Optional[int] = ..., view: _Optional[_Union[View, _Mapping]] = ..., card_id: _Optional[str] = ...) -> None: ...

class Acknowledgment(_message.Message):
    __slots__ = ("in_reply_to", "stage", "card_id", "revision")
    IN_REPLY_TO_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    CARD_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    in_reply_to: str
    stage: AckStage
    card_id: str
    revision: int
    def __init__(self, in_reply_to: _Optional[str] = ..., stage: _Optional[_Union[AckStage, str]] = ..., card_id: _Optional[str] = ..., revision: _Optional[int] = ...) -> None: ...

class Error(_message.Message):
    __slots__ = ("in_reply_to", "code", "detail")
    IN_REPLY_TO_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    in_reply_to: str
    code: ErrorCode
    detail: str
    def __init__(self, in_reply_to: _Optional[str] = ..., code: _Optional[_Union[ErrorCode, str]] = ..., detail: _Optional[str] = ...) -> None: ...
