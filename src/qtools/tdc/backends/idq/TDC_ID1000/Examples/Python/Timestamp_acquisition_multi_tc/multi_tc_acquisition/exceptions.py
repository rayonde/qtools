class AcquisitionError(Exception):
    pass


class CommandError(AcquisitionError):
    pass


class DataLinkCommandError(CommandError):
    def __init__(self, ip, error):
        super(CommandError, self).__init__(f"[DLT@{ip}] {error}")


class ScpiCommandError(CommandError):
    def __init__(self, ip, error):
        super(CommandError, self).__init__(f"[SCPI@{ip}] {error}")


class ConnexionError(AcquisitionError):
    pass


class DataLinkConnexionError(ConnexionError):
    pass


class ScpiConnexionError(ConnexionError):
    pass


class ConfigurationError(AcquisitionError):
    pass


class ConfigurationPropertyError(ConfigurationError):
    def _join_path(self, property_path):
        return "/" + "/".join(i for i in property_path if isinstance(i, str))

    def __init__(self, error, property_path):
        if isinstance(property_path, tuple) and len(property_path) > 1:
            message = f"{error}\nConfiguration properties path:"
            for i, path in enumerate(property_path, 1):
                message += f"\n  {i}) {self._join_path(path)}"
        else:
            message = f"{error}\nConfiguration property path: {self._join_path(property_path)}"
        super(ConfigurationError, self).__init__(message)
