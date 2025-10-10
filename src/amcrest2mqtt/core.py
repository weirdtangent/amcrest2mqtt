from .mixins.util import UtilMixin
from .mixins.mqtt import MqttMixin
from .mixins.topics import TopicsMixin
from .mixins.events import EventsMixin
from .mixins.service import ServiceMixin
from .mixins.amcrest import AmcrestMixin
from .mixins.amcrest_api import AmcrestAPIMixin
from .mixins.refresh import RefreshMixin
from .mixins.helpers import HelpersMixin
from .mixins.loops import LoopsMixin
from .base import Base


class Amcrest2Mqtt(
    UtilMixin,
    EventsMixin,
    TopicsMixin,
    ServiceMixin,
    AmcrestMixin,
    AmcrestAPIMixin,
    RefreshMixin,
    HelpersMixin,
    LoopsMixin,
    MqttMixin,
    Base,
):
    pass
