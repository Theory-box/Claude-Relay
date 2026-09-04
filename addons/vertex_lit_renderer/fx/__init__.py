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


def default_effects():
    # order matters: AO darkens colour before any later grading/compositing pass.
    return [SSAO()]


def make_pipeline():
    return Pipeline(default_effects())
