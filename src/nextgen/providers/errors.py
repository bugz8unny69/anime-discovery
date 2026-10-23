"""Safe provider outcomes shared by clients and job adapters."""
class ProviderUnavailable(RuntimeError):
    reason_code = "PROVIDER_UNAVAILABLE"
    def __init__(self):
        super().__init__("An information provider is temporarily unavailable.")


class ProviderDeferred(RuntimeError):
    reason_code = "JOB_WAITING"
    def __init__(self, delay_ms):
        if type(delay_ms) is not int or not 1 <= delay_ms <= 86400000:
            raise ValueError("invalid provider wait")
        self.delay_ms = delay_ms
        super().__init__("Work is waiting for a prerequisite.")


class ProviderInvalidResponse(RuntimeError):
    reason_code = "PROVIDER_RESPONSE_INVALID"
    def __init__(self):
        super().__init__("An information provider returned an unusable response.")


class ProviderAuthenticationFailed(RuntimeError):
    reason_code = "PROVIDER_AUTH_FAILED"
    def __init__(self):
        super().__init__("An information provider could not authorize access.")
