"""S04 publication boundary. No installed-core imports or model-selected version.

D24 is deliberately unresolved: there is no principal-proof issuer in this slice.
Consequently even an authenticated fixture host cannot publish hosted tools.
D22/D30/risk acceptance remain independent gates for future consumers.
"""
from dataclasses import dataclass
import re

HOST_PROTOCOL = "studiotwin.host-gateway.v1"
GATEWAY_PROTOCOL = "studiotwin.gateway.v1"
CAPABILITIES = (
    "trustedToolContextV1", "onceOnlyElicitation", "noWriteReplay",
    "portableMcpOwnership", "pluginBackendNamespace",
    "profileScopedInterpolationFailClosed", "gatewayMigration",
)
_VERSION = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)(?:([-+])[0-9A-Za-z.-]{1,32})?", re.ASCII)


def version_status(version):
    if not isinstance(version, str) or not (match := _VERSION.fullmatch(version)):
        return "unknown"
    parts = tuple(int(match[i]) for i in (1, 2, 3))
    # Prereleases have not met the stable host floor, even if numerically newer.
    if match[4] == "-" or parts < (0, 22, 3):
        return "below-floor"
    return "at-or-above-floor"


@dataclass(frozen=True)
class _VerifiedCapabilities:
    """Internal result of peer-key verification, never constructed from model JSON."""
    version: str | None
    flags: tuple[bool, ...]

    def as_dict(self):
        return {"protocol": HOST_PROTOCOL, "hostVersion": self.version,
                "hostVersionStatus": version_status(self.version),
                "versionSource": "running-distribution-metadata",
                "capabilities": dict(zip(CAPABILITIES, self.flags))}


def _authenticated_capabilities(payload):
    """Called only AFTER HostContextGate verifies the initialize MAC.

    The receiver normalizes the advisory version-status field rather than trusting
    it; malformed protocol/flags/source never produce a verified wrapper.
    """
    required = {"protocol", "hostVersion", "hostVersionStatus", "versionSource", "capabilities"}
    if not isinstance(payload, dict) or set(payload) != required:
        return None
    flags = payload["capabilities"]
    if (payload["protocol"] != HOST_PROTOCOL
            or payload["versionSource"] != "running-distribution-metadata"
            or payload["hostVersionStatus"] not in {"unknown", "below-floor", "at-or-above-floor"}
            or not isinstance(flags, dict) or set(flags) != set(CAPABILITIES)
            or any(type(flags[k]) is not bool for k in CAPABILITIES)):
        return None
    version = payload["hostVersion"]
    if version_status(version) == "unknown":
        version = None
    return _VerifiedCapabilities(version, tuple(flags[k] for k in CAPABILITIES))


def host_ready(capabilities):
    return (isinstance(capabilities, _VerifiedCapabilities)
            and version_status(capabilities.version) == "at-or-above-floor"
            and all(capabilities.flags))


def publication_decision(capabilities=None):
    """Return PublicationDecisionV1. No boolean/dict can claim D24 principal proof.

    The unmodified host sends no authenticated initialize extension, so the
    conservative diagnostic has an unknown version and all flags false. Never
    substitute importlib.metadata from the gateway's Python installation.
    """
    if not isinstance(capabilities, _VerifiedCapabilities):
        capabilities = _VerifiedCapabilities(None, (False,) * len(CAPABILITIES))
    return {"protocol": GATEWAY_PROTOCOL, "hostCapabilities": capabilities.as_dict(),
            "principalIdentity": "unproven", "publishedTiers": ["setup"]}


def published_tools(decision, hosted_tools=()):
    """S04 has no D24 issuer: neither caller JSON nor a tier list enables tools.

    Classification/registration is owned by S08/S28; no hosted schema is published
    by this gate, including supposedly free reads before principal proof.
    """
    return ["studiotwin_setup_status"]
