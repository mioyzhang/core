from core.config import Configuration
from core.configservice.base import ConfigService, ConfigServiceMode
from core.emulator.enumerations import ConfigDataTypes


class SimpleService(ConfigService):
    name = "Simple"
    group = "SimpleGroup"
    directories = ["/etc/quagga", "/usr/local/lib"]
    files = ["test1.sh", "test2.sh"]
    executables = []
    dependencies = []
    startup = []
    validate = []
    shutdown = []
    validation_mode = ConfigServiceMode.BLOCKING
    default_configs = [
        Configuration(_id="value1", _type=ConfigDataTypes.STRING, label="Value 1"),
        Configuration(_id="value2", _type=ConfigDataTypes.STRING, label="Value 2"),
        Configuration(_id="value3", _type=ConfigDataTypes.STRING, label="Value 3"),
    ]
    modes = {
        "mode1": {"value1": "m1", "value2": "m1", "value3": "m1"},
        "mode2": {"value1": "m2", "value2": "m2", "value3": "m2"},
        "mode3": {"value1": "m3", "value2": "m3", "value3": "m3"},
    }

    def get_text_template(self, name: str) -> str:
        if name == "test1.sh":
            return """
            # sample script 1
            # node id(${node.id}) name(${node.name})
            # config: ${config}
            echo hello
            """
        elif name == "test2.sh":
            return """
            # sample script 2
            # node id(${node.id}) name(${node.name})
            # config: ${config}
            echo hello2
            """
