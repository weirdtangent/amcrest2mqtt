from .mixins.helpers import HelpersMixin
from .mixins.mqtt import MqttMixin
from .mixins.topics import TopicsMixin
from .mixins.events import EventsMixin
from .mixins.service import ServiceMixin
from .mixins.amcrest import AmcrestMixin
from .mixins.amcrest_api import AmcrestAPIMixin
from .mixins.refresh import RefreshMixin
from .mixins.loops import LoopsMixin
from .base import Base


class Amcrest2Mqtt(
    HelpersMixin,
    EventsMixin,
    TopicsMixin,
    ServiceMixin,
    AmcrestMixin,
    AmcrestAPIMixin,
    RefreshMixin,
    LoopsMixin,
    MqttMixin,
    Base,
):
    pass
