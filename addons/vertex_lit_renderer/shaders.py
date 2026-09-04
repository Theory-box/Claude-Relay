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
uniform vec3  uKeyDir;       /* camera-following key light (world space) */
uniform vec3  uKeyCol;
uniform float uKeyIntensity;
uniform sampler2D uShadowMap;
uniform int       uUseShadow;
uniform float     uShadowBias;
uniform float     uShadowDark;
"""

LIGHT_FUNCS = """
vec3 vlr_light(vec3 wPos, vec3 N) {
    float hemi = dot(N, vec3(0.0, 0.0, 1.0)) * 0.5 + 0.5;
    vec3 light = mix(uGroundColor, uSkyColor, hemi);
    /* camera key light (headlamp) — follows the view, added on top of the hemisphere */
    light += uKeyCol * (max(dot(N, normalize(uKeyDir)), 0.0) * uKeyIntensity);
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
uniform vec3 uGenMin;
uniform vec3 uGenScale;
in vec3 position;
in vec3 normal;
in vec4 vertColor;
in vec2 texCoord;
out vec3 vGenerated;   /* object bbox-normalised position (Tex Coord: Generated) */
out vec3 vObjPos;      /* object-space position (Tex Coord: Object) */
"""

# ---- Per-pixel (Phong): pass world data through, light in the fragment ------
PHONG_VERT = _VERT_HEADER + """
out vec2 vUV;
out vec4 vColor;
out vec3 vWpos;
out vec3 vNrm;
void main() {
    vec4 wPos4 = uModel * vec4(position, 1.0);
    vWpos   = wPos4.xyz;
    vNrm    = uNormalMat * normal;
    vColor  = vertColor;
    vUV     = texCoord;
    vObjPos = position;
    vGenerated = (position - uGenMin) * uGenScale;
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
out vec4 outColor;
""" + LIGHT_CHUNK + """
void main() {
    vec3 N     = normalize(vNrm);
    vec3 light = vlr_light(vWpos, N);
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

MAT_FRAG_HEAD_WORKBENCH = ("in vec2 vUV;\nin vec4 vColor;\nin vec3 vNrm;\nin vec3 vGenerated;\nin vec3 vObjPos;\n"
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

MAT_FRAG_HEAD_PIXEL = ("in vec2 vUV;\nin vec4 vColor;\nin vec3 vWpos;\nin vec3 vGenerated;\nin vec3 vObjPos;\n"
                       "in vec3 vNrm;\nout vec4 outColor;\n")
MAT_FRAG_MAIN_PIXEL = (
    "void main() {\n"
    "    vec3 N     = normalize(vNrm);\n"
    "    vec3 light = vlr_light(vWpos, N);\n"
    "    float sh   = vlr_shadow(vWpos);\n"
    "    vec3 lit   = clamp(light, 0.0, 12.0) * sh * vColor.rgb;\n"
    "    vec4 base  = computeBaseColor(vUV);\n"
    "    outColor = vec4(lit * base.rgb, vColor.a * base.a);\n"
    "}\n"
)

# ---- Object-ID pass (flat per-object colour) for Workbench-style outline ------
ID_VERT = """
uniform mat4 uViewProj;
uniform mat4 uModel;
in vec3 position;
void main(){ gl_Position = uViewProj * uModel * vec4(position, 1.0); }
"""
ID_FRAG = """
uniform vec3 uId;
out vec4 fragColor;
void main(){ fragColor = vec4(uId, 1.0); }
"""

# View-space normal prepass, used by the Cavity (curvature) effect. Encodes the view
# normal into RGB (*0.5+0.5). Curvature needs view-space normals so the ridge/valley
# derivative is screen-aligned, exactly like Workbench's cavity.
NORMAL_VERT = """
uniform mat4 uViewProj;
uniform mat4 uModel;
uniform mat3 uNormalMat;   /* model world-space normal matrix (per object) */
uniform mat3 uViewMat3;    /* upper-left 3x3 of the view matrix (per frame)  */
in vec3 position;
in vec3 normal;
out vec3 vVN;
void main(){
    vVN = uViewMat3 * (uNormalMat * normal);
    gl_Position = uViewProj * uModel * vec4(position, 1.0);
}
"""

NORMAL_FRAG = """
in vec3 vVN;
out vec4 fragColor;
void main(){ fragColor = vec4(normalize(vVN) * 0.5 + 0.5, 1.0); }
"""


# ---- View-mode shader: Solid / Random / Attribute / Normal --------------------
# Pairs with PHONG_VERT (vUV, vColor, vWpos, vNrm). Textured mode uses the material
# programs instead; this covers the non-material colour modes with the same lighting.
VIEWMODE_FRAG = ("in vec2 vUV;\nin vec4 vColor;\nin vec3 vWpos;\nin vec3 vNrm;\n"
                 "in vec3 vGenerated;\nin vec3 vObjPos;\nout vec4 outColor;\n"
                 + LIGHT_CHUNK +
                 "uniform int  uViewMode;   /* 1=solid 2=random 3=attribute 4=normal 5=depth */\n"
                 "uniform vec3 uSolidColor;\n"
                 "uniform vec3 uObjColor;\n"
                 "uniform vec3 uCamPos;\n"
                 "uniform float uDepthMin;\n"
                 "uniform float uDepthMax;\n"
                 "void main(){\n"
                 "    vec3 N = normalize(vNrm);\n"
                 "    if(uViewMode == 4){ outColor = vec4(N * 0.5 + 0.5, 1.0); return; }\n"
                 "    if(uViewMode == 5){\n"
                 "        float dist = length(vWpos - uCamPos);\n"
                 "        float t = clamp((dist - uDepthMin) / max(uDepthMax - uDepthMin, 1e-4), 0.0, 1.0);\n"
                 "        outColor = vec4(vec3(1.0 - t), 1.0); return;\n"
                 "    }\n"
                 "    vec3 albedo;\n"
                 "    if(uViewMode == 1) albedo = uSolidColor;\n"
                 "    else if(uViewMode == 2) albedo = uObjColor;\n"
                 "    else albedo = vColor.rgb;\n"
                 "    vec3 light = clamp(vlr_light(vWpos, N), 0.0, 12.0) * vlr_shadow(vWpos);\n"
                 "    outColor = vec4(light * albedo, 1.0);\n"
                 "}\n")


# ---- Background: hemisphere sky/ground gradient (world space) or flat colour ---
BG_VERT = """
in vec2 pos;
out vec2 vNdc;
void main(){ vNdc = pos; gl_Position = vec4(pos, 1.0, 1.0); }
"""

BG_FRAG = """
uniform mat4 uInvViewProj;
uniform vec3 uCamPos;
uniform vec3 uSkyColor;
uniform vec3 uGroundColor;
uniform int  uBgMode;      /* 0 = world gradient, 1 = flat colour */
uniform vec3 uBgColor;
in vec2 vNdc;
out vec4 fragColor;
void main(){
    if(uBgMode == 1){ fragColor = vec4(uBgColor, 1.0); return; }
    /* reconstruct the world-space view ray at this pixel and gradient by its up (world +Z) */
    vec4 wp = uInvViewProj * vec4(vNdc, 1.0, 1.0);
    vec3 world = wp.xyz / wp.w;
    vec3 dir = normalize(world - uCamPos);
    float t = clamp(dir.z * 0.5 + 0.5, 0.0, 1.0);
    fragColor = vec4(mix(uGroundColor, uSkyColor, t), 1.0);
}
"""


# ---- Bake: rasterise the mesh in UV space and evaluate computeBaseColor per texel ---------
BAKE_VERT = """
uniform vec3 uGenMin;
uniform vec3 uGenScale;
in vec3 position;
in vec3 normal;
in vec4 vertColor;
in vec2 texCoord;
out vec2 vUV;
out vec4 vColor;
out vec3 vWpos;
out vec3 vNrm;
out vec3 vGenerated;
out vec3 vObjPos;
void main(){
    vUV        = texCoord;
    vColor     = vertColor;
    vNrm       = normal;
    vWpos      = position;
    vGenerated = (position - uGenMin) * uGenScale;
    vObjPos    = position;
    gl_Position = vec4(texCoord * 2.0 - 1.0, 0.0, 1.0);   /* UV space -> clip */
}
"""

BAKE_FRAG_HEAD = ("in vec2 vUV;\nin vec4 vColor;\nin vec3 vWpos;\nin vec3 vNrm;\n"
                  "in vec3 vGenerated;\nin vec3 vObjPos;\nout vec4 fragColor;\n")
BAKE_FRAG_MAIN = "void main(){ fragColor = computeBaseColor(vUV); }\n"
