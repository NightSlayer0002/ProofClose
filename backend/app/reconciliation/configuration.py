from app.domain.models import ConfigurationBundle
from app.reconciliation.rules import ReconciliationPolicyV2


def configuration_bundle_for(policy: ReconciliationPolicyV2) -> ConfigurationBundle:
    return ConfigurationBundle(
        version="2.0",
        values={
            "pending_hours": policy.pending_hours,
            "bank_match_window_hours": policy.bank_match_window_hours,
            "early_bank_tolerance_hours": policy.early_bank_tolerance_hours,
            "future_clock_skew_minutes": policy.future_clock_skew_minutes,
        },
    )


CONFIGURATION_BUNDLE_V2 = configuration_bundle_for(ReconciliationPolicyV2())


class ConfigurationRegistry:
    def __init__(self) -> None:
        self._bundles: dict[str, ConfigurationBundle] = {}
        self._current_version: str | None = None

    def register(self, bundle: ConfigurationBundle) -> None:
        stored = ConfigurationBundle.model_validate(bundle.model_dump(mode="python"))
        existing = self._bundles.get(stored.version)
        if existing is not None and existing != stored:
            raise ValueError(f"configuration version {bundle.version} is already registered")
        self._bundles[stored.version] = stored

    def resolve(self, version: str) -> ConfigurationBundle | None:
        bundle = self._bundles.get(version)
        if bundle is None:
            return None
        return ConfigurationBundle.model_validate(bundle.model_dump(mode="python"))

    def set_current(self, version: str) -> None:
        if version not in self._bundles:
            raise KeyError(version)
        self._current_version = version

    def current(self) -> ConfigurationBundle | None:
        if self._current_version is None:
            return None
        return self.resolve(self._current_version)
