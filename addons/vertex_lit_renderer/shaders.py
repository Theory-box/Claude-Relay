# vertex_lit_renderer/shaders.py

SHADOW_VERT = """
uniform mat4 uLightSpace;
uniform mat4 uModel;
in vec3 position;
void main() {
    gl_Position = uLightSpace * uModel * vec4(position, 1.0);
}
"""
SHADOW_FRAG = """void main() {}"""

# ---------------------------------------------------------------------------
# Shared lighting: uniforms + functions used by BOTH the per-vertex (Gouraud)
# and per-pixel (Phong) paths. Included in whichever stage computes lighting
# (vertex for Gouraud, fragment for Phong) so each program declares them once.
# ---------------------------------------------------------------------------
LIGHT_UNIFORMS = """
uniform mat4 uLightSpace;
uniform vec3  uLPos[8];
uniform vec3  uLDir[8];
uniform vec3  uLCol[8];
uniform float uLEnergy[8];
uniform int   uLType[8];
uniform float uLRadius[8];
uniform int   uNumLights;
uniform vec3  uSkyColor;
uniform vec3  uGroundColor;
uniform float uBounceStrength;
uniform sampler2D uShadowMap;
uniform int       uUseShadow;
uniform float     uShadowBias;
uniform float     uShadowDark;
"""

LIGHT_FUNCS = """
vec3 vlr_light(vec3 wPos, vec3 N, vec3 bounce) {
    float hemi = dot(N, vec3(0.0, 0.0, 1.0)) * 0.5 + 0.5;
    vec3 light = mix(uGroundColor, uSkyColor, hemi);
    for (int i = 0; i < 8; i++) {
        float lightOn = (i < uNumLights) ? 1.0 : 0.0;
        vec3  L; float att = 1.0;
        if (uLType[i] == 1) {
            L = normalize(-uLDir[i]);
        } else {
            vec3  d  = uLPos[i] - wPos;
            float di = length(d);
            L   = d / max(di, 1e-5);
            float x = di / max(uLRadius[i], 0.001);
            att = pow(max(1.0 - x*x*x*x, 0.0), 2.0);
        }
        float diff = max(dot(N, L), 0.0);
        light += uLCol[i] * (uLEnergy[i] * diff * att) * lightOn;
    }
    light += bounce * uBounceStrength;
    return light;
}

float vlr_shadow(vec3 wPos) {
    if (uUseShadow == 0) return 1.0;
    vec4 lsPos = uLightSpace * vec4(wPos, 1.0);
    vec3 proj  = lsPos.xyz / lsPos.w * 0.5 + 0.5;
    if (proj.x >= 0.0 && proj.x <= 1.0 &&
        proj.y >= 0.0 && proj.y <= 1.0 && proj.z <= 1.0) {
        float d = textureLod(uShadowMap, proj.xy, 0.0).r;
        return (proj.z - uShadowBias > d) ? uShadowDark : 1.0;
    }
    return 1.0;
}
"""

LIGHT_CHUNK = LIGHT_UNIFORMS + LIGHT_FUNCS

_VERT_HEADER = """
uniform mat4 uViewProj;
uniform mat4 uModel;
uniform mat3 uNormalMat;
in vec3 position;
in vec3 normal;
in vec4 vertColor;
in vec2 texCoord;
in vec3 bounceColor;   /* one-bounce GI baked at rebuild time */
"""

# ---- Per-vertex (Gouraud): lighting in the vertex shader -> vLight ----------
MAIN_VERT = _VERT_HEADER + LIGHT_CHUNK + """
out vec4 vLight;
out vec2 vUV;
void main() {
    vec4 wPos4 = uModel * vec4(position, 1.0);
    vec3 N     = normalize(uNormalMat * normal);
    vec3 light = vlr_light(wPos4.xyz, N, bounceColor);
    float sh   = vlr_shadow(wPos4.xyz);
    vLight      = vec4(clamp(light, 0.0, 12.0) * sh * vertColor.rgb, vertColor.a);
    vUV         = texCoord;
    gl_Position = uViewProj * wPos4;
}
"""

MAIN_FRAG = """
uniform sampler2D uAlbedo;
uniform int       uHasTexture;
in vec4 vLight;
in vec2 vUV;
out vec4 outColor;
void main() {
    vec4 albedo = (uHasTexture != 0) ? texture(uAlbedo, vUV) : vec4(1.0);
    outColor = vec4(vLight.rgb * albedo.rgb, vLight.a * albedo.a);
}
"""

# ---- Per-pixel (Phong): pass world data through, light in the fragment ------
PHONG_VERT = _VERT_HEADER + """
out vec2 vUV;
out vec4 vColor;
out vec3 vWpos;
out vec3 vNrm;
out vec3 vBounce;
void main() {
    vec4 wPos4 = uModel * vec4(position, 1.0);
    vWpos   = wPos4.xyz;
    vNrm    = uNormalMat * normal;
    vColor  = vertColor;
    vBounce = bounceColor;
    vUV     = texCoord;
    gl_Position = uViewProj * wPos4;
}
"""

PHONG_FRAG = """
uniform sampler2D uAlbedo;
uniform int       uHasTexture;
in vec2 vUV;
in vec4 vColor;
in vec3 vWpos;
in vec3 vNrm;
in vec3 vBounce;
out vec4 outColor;
""" + LIGHT_CHUNK + """
void main() {
    vec3 N     = normalize(vNrm);
    vec3 light = vlr_light(vWpos, N, vBounce);
    float sh   = vlr_shadow(vWpos);
    vec3 lit   = clamp(light, 0.0, 12.0) * sh * vColor.rgb;
    vec4 albedo = (uHasTexture != 0) ? texture(uAlbedo, vUV) : vec4(1.0);
    outColor = vec4(lit * albedo.rgb, vColor.a * albedo.a);
}
"""

# ---- Workbench-style studio shading (no scene lights, no GI, no shadows) -----
# A camera-following key light + flat ambient, per fragment. Matches Blender's
# Solid/Workbench "always lit" look. Pairs with PHONG_VERT (world normal + uv +
# vertex colour). uKeyDir is world-space, updated each frame to follow the view.
WORKBENCH_FRAG = """
uniform sampler2D uAlbedo;
uniform int   uHasTexture;
uniform vec3  uKeyDir;
uniform vec3  uKeyCol;
uniform float uAmbient;
in vec2 vUV;
in vec4 vColor;
in vec3 vNrm;
out vec4 outColor;
void main(){
    vec3 N = normalize(vNrm);
    float ndl = max(dot(N, normalize(uKeyDir)), 0.0);
    vec3 lit = uKeyCol * ndl + vec3(uAmbient);
    vec4 albedo = (uHasTexture != 0) ? texture(uAlbedo, vUV) : vec4(1.0);
    outColor = vec4(lit * albedo.rgb * vColor.rgb, albedo.a * vColor.a);
}
"""

MAT_FRAG_HEAD_WORKBENCH = ("in vec2 vUV;\nin vec4 vColor;\nin vec3 vNrm;\n"
                           "uniform vec3 uKeyDir;\nuniform vec3 uKeyCol;\n"
                           "uniform float uAmbient;\nout vec4 outColor;\n")
MAT_FRAG_MAIN_WORKBENCH = (
    "void main(){\n"
    "    vec3 N = normalize(vNrm);\n"
    "    float ndl = max(dot(N, normalize(uKeyDir)), 0.0);\n"
    "    vec3 lit = uKeyCol * ndl + vec3(uAmbient);\n"
    "    vec4 base = computeBaseColor(vUV);\n"
    "    outColor = vec4(lit * base.rgb, base.a);\n"
    "}\n"
)
MAT_FRAG_HEAD_VERTEX = "in vec4 vLight;\nin vec2 vUV;\nout vec4 outColor;\n"
MAT_FRAG_MAIN_VERTEX = (
    "void main() {\n"
    "    vec4 base = computeBaseColor(vUV);\n"
    "    outColor = vec4(vLight.rgb * base.rgb, vLight.a * base.a);\n"
    "}\n"
)

MAT_FRAG_HEAD_PIXEL = ("in vec2 vUV;\nin vec4 vColor;\nin vec3 vWpos;\n"
                       "in vec3 vNrm;\nin vec3 vBounce;\nout vec4 outColor;\n")
MAT_FRAG_MAIN_PIXEL = (
    "void main() {\n"
    "    vec3 N     = normalize(vNrm);\n"
    "    vec3 light = vlr_light(vWpos, N, vBounce);\n"
    "    float sh   = vlr_shadow(vWpos);\n"
    "    vec3 lit   = clamp(light, 0.0, 12.0) * sh * vColor.rgb;\n"
    "    vec4 base  = computeBaseColor(vUV);\n"
    "    outColor = vec4(lit * base.rgb, vColor.a * base.a);\n"
    "}\n"
)
