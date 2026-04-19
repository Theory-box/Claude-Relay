SHADOW_VERT = """
uniform mat4 uLightSpace;
uniform mat4 uModel;
in vec3 position;
void main() {
    gl_Position = uLightSpace * uModel * vec4(position, 1.0);
}
"""
SHADOW_FRAG = """void main() {}"""

MAIN_VERT = """
uniform mat4 uViewProj;
uniform mat4 uModel;
uniform mat4 uLightSpace;

uniform vec3  uLPos[8];
uniform vec3  uLDir[8];
uniform vec3  uLCol[8];
uniform float uLEnergy[8];
uniform int   uLType[8];
uniform float uLRadius[8];
uniform int   uNumLights;

uniform vec3 uSkyColor;
uniform vec3 uGroundColor;

uniform sampler2D uShadowMap;
uniform int       uUseShadow;
uniform float     uShadowBias;
uniform float     uShadowDark;

in vec3 position;
in vec3 normal;
in vec4 vertColor;
in vec2 texCoord;
in vec3 bounceColor;

out vec4 vLight;
out vec2 vUV;

void main() {
    vec4 wPos4  = uModel * vec4(position, 1.0);
    vec3 wPos   = wPos4.xyz;

    /* Normal matrix computed from uModel (mat4 uniform — provably works).
       mat3 uniforms have a known Blender API issue with transposition. */
    mat3 nMat = transpose(inverse(mat3(uModel)));
    vec3 N    = normalize(nMat * normal);

    float hemi = dot(N, vec3(0.0, 0.0, 1.0)) * 0.5 + 0.5;
    vec3 light = mix(uGroundColor, uSkyColor, hemi);

    for (int i = 0; i < 8; i++) {
        if (i >= uNumLights) break;
        vec3  L;
        float att = 1.0;
        if (uLType[i] == 1) {
            L = normalize(-uLDir[i]);
        } else {
            vec3  d  = uLPos[i] - wPos;
            float di = length(d);
            L   = d / max(di, 1e-5);
            float x = di / max(uLRadius[i], 0.001);
            att = pow(max(1.0 - x * x * x * x, 0.0), 2.0);
        }
        float diff = max(dot(N, L), 0.0);
        light += uLCol[i] * (uLEnergy[i] * diff * att);
    }

    light += bounceColor;

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
