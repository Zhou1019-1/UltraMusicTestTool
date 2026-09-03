# -*- coding: utf-8 -*-
from .base import DetectionMethod, MethodResult
from .cutoff import SpectralCutoffMethod
from .bitdepth import BitDepthMethod
from .codec_artifacts import CodecArtifactMethod
from .upsampling import UpsamplingMethod

ALL_METHODS = [SpectralCutoffMethod, CodecArtifactMethod,
               BitDepthMethod, UpsamplingMethod]

__all__ = ["DetectionMethod", "MethodResult", "ALL_METHODS",
           "SpectralCutoffMethod", "CodecArtifactMethod",
           "BitDepthMethod", "UpsamplingMethod"]
