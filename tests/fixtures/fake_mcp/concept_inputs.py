"""Port of the StudioTwin API's Concept effective-input transform (DESIGN §3.1).

Source: studiotwin-platform `api/src/concepts/concepts.service.ts` `buildOpInputs` and
`resolutionInputs`, plus `api/src/vp/vp-function.registry.ts` `GPT_IMAGE_2_RESOLUTIONS`, at
API commit 2eb0df1e44b9acd03a177dc2c28dcfdaf2ff1bf4. The fake server submits exactly these
inputs to `concept-lab-img-fn`, so S15/S23 contract tests can compare a quote's effective
inputs with the actual VP submission. This is a fixture of observed behaviour, not an
authority: v1 still fails closed for paid Concept actions (D22).
"""

from __future__ import annotations

import re
from typing import Any

API_SOURCE_COMMIT = "2eb0df1e44b9acd03a177dc2c28dcfdaf2ff1bf4"
CONCEPT_FUNCTION = "concept-lab-img-fn"  # CONCEPT_ACTION_FUNCTION for Generate and Edit

GPT_IMAGE_2_RESOLUTIONS = (
    (832, 832), (720, 1280), (768, 1152), (1280, 720), (1024, 1024), (1024, 1536), (1536, 1024),
    (1152, 2048), (2048, 1152), (1440, 2560), (2560, 1440), (1536, 2304), (2048, 2048),
    (2048, 3072), (2160, 3840), (2880, 2880), (3840, 2160),
)
_GPT_IMAGE_2_STRINGS = frozenset(f"{w}x{h}" for w, h in GPT_IMAGE_2_RESOLUTIONS)
CONTROLLED_FIELDS = ("prompt", "enhancePrompt", "mode", "sourceAsset", "conceptType", "n")
_DIMS = re.compile(r"^(\d+)x(\d+)$")


def is_gpt_image_2_resolution(size: str) -> bool:
    return size in _GPT_IMAGE_2_STRINGS


_UNDEFINED = object()  # JavaScript `undefined` (key absent); JSON null stays None


def resolution_inputs(resolution: Any = _UNDEFINED) -> dict[str, Any]:
    if resolution is _UNDEFINED:
        return {}
    if isinstance(resolution, str):
        match = _DIMS.match(resolution)
        if match:
            width, height = int(match.group(1)), int(match.group(2))
            if is_gpt_image_2_resolution(resolution):
                return {"size": resolution, "width": width, "height": height}
            return {"width": width, "height": height}
    return {"size": resolution}


def build_op_inputs(
    action: str,
    job_inputs: dict[str, Any],
    source_s3_uri: str | None,
    concept_type: str,
) -> dict[str, Any]:
    """Effective `concept-lab-img-fn` inputs for a Concept generate/edit operation.

    Key order follows the JavaScript object spread so a JSON dump matches the API's.
    """
    if action not in ("generate", "edit"):
        raise ValueError(f"Action '{action}' is not an image operation")
    tool_inputs: dict[str, Any] = dict(job_inputs.get("params") or {})
    resolution = tool_inputs.pop("resolution", _UNDEFINED)
    for key in CONTROLLED_FIELDS:
        tool_inputs.pop(key, None)
    if resolution is not _UNDEFINED:
        # The compatibility alias deterministically wins over native routing.
        for key in ("width", "height", "size"):
            tool_inputs.pop(key, None)
    out: dict[str, Any] = dict(tool_inputs)
    # JS spread: later keys overwrite but keep the first insertion position.
    for key, value in resolution_inputs(resolution).items():
        out[key] = value
    out["prompt"] = job_inputs["prompt"]["user"]
    out["conceptType"] = concept_type
    out["enhancePrompt"] = job_inputs["prompt"]["enhancement"]["enabled"]
    out["mode"] = "edit" if action == "edit" else "generate"
    if source_s3_uri:
        out["sourceAsset"] = source_s3_uri
    out["n"] = 1
    return out
