# vertex_lit_renderer/fx/__init__.py
"""
Screen-space post-processing package.

The engine owns one Pipeline built from `default_effects()`. To add an effect
(SSR, compositing, DoF, outline, cavity...), write a ScreenEffect subclass in a
new module here and append it to the list below — the engine and pipeline need
no changes.
"""
from .pipeline import Pipeline
from .ssao import SSAO
from .cavity import Cavity
from .outline import Outline
from .fxaa import FXAA


def default_effects():
    # order matters: AO + cavity shade the colour, outline draws lines, FXAA smooths last.
    return [SSAO(), Cavity(), Outline(), FXAA()]


def make_pipeline():
    return Pipeline(default_effects())
