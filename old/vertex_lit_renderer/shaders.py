# vertex_lit_renderer/shaders.py

# Shadow map shaders removed — shadows now ray-traced by embreex GI pass.
# The GI thread bakes direct (shadow-tested) + indirect into bounceColor.

MAIN_VERT = """
uniform mat4 uViewProj;
uniform mat4 uModel;
uniform mat3 uNormalMat;

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

/* uHasGI: 0 = no GI data yet (show unoccluded direct as placeholder),
           1 = GI data available (bounceColor = direct_shadowed + indirect) */
uniform float uHasGI;

in vec3 position;
in vec3 normal;
in vec4 vertColor;
in vec2 texCoord;
in vec3 bounceColor;

out vec4 vLight;
out vec2 vUV;

void main() {
    vec4 wPos4 = uModel * vec4(position, 1.0);
    vec3 wPos  = wPos4.xyz;
    vec3 N     = normalize(uNormalMat * normal);

    vec3 light;

    if (uHasGI > 0.5) {
        /* GI data ready: bounceColor contains ray-traced direct + indirect.
           Use it as the full lighting result — shadow map no longer needed. */
        light = bounceColor * uBounceStrength;
    } else {
        /* Fallback while GI hasn't produced data yet (first ~0.5s).
           Compute unoccluded direct lighting so the scene isn't black. */
        float hemi = dot(N, vec3(0.0, 0.0, 1.0)) * 0.5 + 0.5;
        light = mix(uGroundColor, uSkyColor, hemi);

        for (int i = 0; i < 8; i++) {
            float on = (i < uNumLights) ? 1.0 : 0.0;
            vec3  L;
            float att = 1.0;
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
            light += uLCol[i] * (uLEnergy[i] * diff * att) * on;
        }
    }

    vLight      = vec4(clamp(light, 0.0, 12.0) * vertColor.rgb, vertColor.a);
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
