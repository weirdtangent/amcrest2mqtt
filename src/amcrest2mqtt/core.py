from .base import Base
from .mixins.amcrest import AmcrestMixin
from .mixins.amcrest_api import AmcrestAPIMixin
from .mixins.events import EventsMixin
from .mixins.helpers import HelpersMixin
from .mixins.loops import LoopsMixin
from .mixins.mqtt import MqttMixin
from .mixins.publish import PublishMixin
from .mixins.refresh import RefreshMixin


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
