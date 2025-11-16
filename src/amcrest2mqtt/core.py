from .mixins.helpers import HelpersMixin
from .mixins.mqtt import MqttMixin
from .mixins.events import EventsMixin
from .mixins.publish import PublishMixin
from .mixins.amcrest import AmcrestMixin
from .mixins.amcrest_api import AmcrestAPIMixin
from .mixins.refresh import RefreshMixin
from .mixins.loops import LoopsMixin
from .base import Base


class Amcrest2Mqtt(
    HelpersMixin,
    EventsMixin,
    PublishMixin,
    AmcrestMixin,
    AmcrestAPIMixin,
    RefreshMixin,
    LoopsMixin,
    MqttMixin,
    Base,
):
    pass
