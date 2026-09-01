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

# Direct diffuse + shadow: per-vertex (Gouraud)
# GI bounce:               pre-computed per vertex, added to light accumulator
# Texture:                 per-fragment

MAIN_VERT = """
uniform mat4 uViewProj;
uniform mat4 uModel;
uniform mat4 uLightSpace;

/* FIX: normal matrix now passed from CPU as a uniform.
   Was computed per-vertex as transpose(inverse(mat3(uModel))) — a full
   matrix inversion inside the vertex shader for every vertex every frame.
   Computing it once on the CPU and uploading as a uniform is equivalent
   and avoids ~6x the GPU work per draw call. */
uniform mat3 uNormalMat;

uniform vec3  uLPos[8];
uniform vec3  uLDir[8];
uniform vec3  uLCol[8];
uniform float uLEnergy[8];
uniform int   uLType[8];
uniform float uLRadius[8];
uniform int   uNumLights;

/* Hemisphere fallback ambient (used when GI is disabled) */
uniform vec3 uSkyColor;
uniform vec3 uGroundColor;

/* GI */
uniform float uBounceStrength;

/* Shadow */
uniform sampler2D uShadowMap;
uniform int       uUseShadow;
uniform float     uShadowBias;
uniform float     uShadowDark;

in vec3 position;
in vec3 normal;
in vec4 vertColor;
in vec2 texCoord;
in vec3 bounceColor;   /* one-bounce GI baked at rebuild time */

out vec4 vLight;
out vec2 vUV;

void main() {
    vec4 wPos4 = uModel * vec4(position, 1.0);
    vec3 wPos  = wPos4.xyz;
    vec3 N     = normalize(uNormalMat * normal);

    /* Hemisphere ambient as fallback / fill */
    float hemi = dot(N, vec3(0.0, 0.0, 1.0)) * 0.5 + 0.5;
    vec3 light = mix(uGroundColor, uSkyColor, hemi);

    /* Direct lights */
    for (int i = 0; i < 8; i++) {
        float lightOn = (i < uNumLights) ? 1.0 : 0.0;
        vec3  L;
        float att = 1.0;
        if (uLType[i] == 1) {
            L = normalize(-uLDir[i]);
        } else {
            vec3  d  = uLPos[i] - wPos;
            float di = length(d);
            L   = d / max(di, 1e-5);
            float x  = di / max(uLRadius[i], 0.001);
            att = pow(max(1.0 - x*x*x*x, 0.0), 2.0);
        }
        float diff = max(dot(N, L), 0.0);
        light += uLCol[i] * (uLEnergy[i] * diff * att) * lightOn;
    }

    /* Add pre-computed one-bounce GI */
    light += bounceColor * uBounceStrength;

    /* Per-vertex shadow */
    float shadow = 1.0;
    if (uUseShadow != 0) {
        vec4 lsPos = uLightSpace * wPos4;
        vec3 proj  = lsPos.xyz / lsPos.w * 0.5 + 0.5;
        if (proj.x >= 0.0 && proj.x <= 1.0 &&
            proj.y >= 0.0 && proj.y <= 1.0 && proj.z <= 1.0) {
            float d = textureLod(uShadowMap, proj.xy, 0.0).r;
            shadow  = (proj.z - uShadowBias > d) ? uShadowDark : 1.0;
        }
    }

    vLight      = vec4(clamp(light, 0.0, 12.0) * shadow * vertColor.rgb, vertColor.a);
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
