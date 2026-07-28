# Shaders Reference

> Common GLSL patterns for Three.js / R3F.
> All snippets work with `shaderMaterial` or `ShaderMaterial`.

---

## ShaderMaterial in R3F

### Basic pattern with uniforms

```tsx
import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

const vertexShader = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const fragmentShader = /* glsl */ `
  uniform float uTime;
  uniform vec3 uColor;
  varying vec2 vUv;

  void main() {
    gl_FragColor = vec4(uColor * vUv.x, 1.0);
  }
`

function ShaderPlane() {
  const materialRef = useRef<THREE.ShaderMaterial>(null!)

  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uColor: { value: new THREE.Color('#ff6600') },
  }), [])

  useFrame((state) => {
    materialRef.current.uniforms.uTime.value = state.clock.elapsedTime
  })

  return (
    <mesh>
      <planeGeometry args={[2, 2, 32, 32]} />
      <shaderMaterial
        ref={materialRef}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        uniforms={uniforms}
      />
    </mesh>
  )
}
```

**Rules:**
- Always `useMemo` uniforms -- prevents creating new objects every render
- Update uniforms in `useFrame` via ref, never through props
- Use `/* glsl */` template tag for syntax highlighting in editors

### Drei's shaderMaterial helper

```tsx
import { shaderMaterial } from '@react-three/drei'
import { extend } from '@react-three/fiber'

const WaveMaterial = shaderMaterial(
  // Uniforms (defaults)
  {
    uTime: 0,
    uColor: new THREE.Color('#ff6600'),
    uAmplitude: 0.3,
  },
  // Vertex
  /* glsl */ `
    uniform float uTime;
    uniform float uAmplitude;
    varying vec2 vUv;
    void main() {
      vUv = uv;
      vec3 pos = position;
      pos.z += sin(pos.x * 4.0 + uTime) * uAmplitude;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
    }
  `,
  // Fragment
  /* glsl */ `
    uniform vec3 uColor;
    varying vec2 vUv;
    void main() {
      gl_FragColor = vec4(uColor, 1.0);
    }
  `
)

extend({ WaveMaterial })

// Usage in JSX:
// <waveMaterial ref={ref} uTime={0} uColor="hotpink" />
```

**Advantage:** Uniforms become JSX props with auto-generated setters.

---

## Noise Functions

### Simplex 2D (most common, cheap)

```glsl
// Credit: Ashima Arts (MIT license)
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec3 permute(vec3 x) { return mod289(((x * 34.0) + 1.0) * x); }

float snoise(vec2 v) {
  const vec4 C = vec4(0.211324865405187, 0.366025403784439,
                      -0.577350269189626, 0.024390243902439);
  vec2 i  = floor(v + dot(v, C.yy));
  vec2 x0 = v - i + dot(i, C.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod289(i);
  vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));
  vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.0);
  m = m * m;
  m = m * m;
  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
  vec3 g;
  g.x = a0.x * x0.x + h.x * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}
```

### Perlin 3D (classic, smooth)

```glsl
// Use for volumetric effects, 3D displacement
// Import from lygia or use npm: glsl-noise
// Signature:
float cnoise(vec3 P);   // classic noise, range [-1, 1]
float pnoise(vec3 P, vec3 rep); // periodic variant
```

### FBM (Fractal Brownian Motion)

Layer noise at different scales for organic, cloud-like patterns.

```glsl
float fbm(vec2 p) {
  float value = 0.0;
  float amplitude = 0.5;
  float frequency = 1.0;
  // 6 octaves -- reduce for performance
  for (int i = 0; i < 6; i++) {
    value += amplitude * snoise(p * frequency);
    frequency *= 2.0;
    amplitude *= 0.5;
  }
  return value;
}
```

**Usage:** terrain, clouds, water surfaces, organic textures.

---

## Fresnel Effect

Makes edges glow brighter than the center -- used for glass, energy shields, holographic UI.

```glsl
// In vertex shader:
varying vec3 vNormal;
varying vec3 vViewDir;

void main() {
  vec4 worldPos = modelMatrix * vec4(position, 1.0);
  vNormal = normalize(normalMatrix * normal);
  vViewDir = normalize(cameraPosition - worldPos.xyz);
  gl_Position = projectionMatrix * viewMatrix * worldPos;
}

// In fragment shader:
varying vec3 vNormal;
varying vec3 vViewDir;
uniform float uFresnelPower;  // typically 2.0 - 5.0
uniform vec3 uFresnelColor;

void main() {
  float fresnel = pow(1.0 - dot(vNormal, vViewDir), uFresnelPower);
  vec3 color = mix(vec3(0.0), uFresnelColor, fresnel);
  gl_FragColor = vec4(color, fresnel); // use fresnel as alpha for ghostly effect
}
```

---

## Gradient Mapping

Remap brightness to a color ramp -- useful for toon shading, heat maps, stylized rendering.

```glsl
uniform sampler2D uGradientMap;  // 1D gradient texture (256x1 px)
uniform vec3 uLightDir;
varying vec3 vNormal;

void main() {
  float NdotL = dot(normalize(vNormal), normalize(uLightDir));
  float brightness = NdotL * 0.5 + 0.5; // remap [-1,1] to [0,1]
  vec3 color = texture2D(uGradientMap, vec2(brightness, 0.5)).rgb;
  gl_FragColor = vec4(color, 1.0);
}
```

### Without texture (code-defined ramp)

```glsl
vec3 gradientMap(float t) {
  vec3 a = vec3(0.05, 0.0, 0.15);  // shadow color
  vec3 b = vec3(0.9, 0.3, 0.1);    // mid color
  vec3 c = vec3(1.0, 0.9, 0.6);    // highlight color
  if (t < 0.5) return mix(a, b, t * 2.0);
  return mix(b, c, (t - 0.5) * 2.0);
}
```

---

## Displacement

Push vertices along their normal based on a pattern.

### Noise-based displacement (vertex shader)

```glsl
uniform float uTime;
uniform float uAmplitude;  // 0.1 - 0.5 typical
varying vec2 vUv;
varying float vDisplacement;

void main() {
  vUv = uv;
  float noise = snoise(vec2(position.x * 2.0 + uTime * 0.5, position.y * 2.0));
  vDisplacement = noise * uAmplitude;
  vec3 newPos = position + normal * vDisplacement;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(newPos, 1.0);
}
```

### Texture-based displacement

```glsl
uniform sampler2D uDisplacementMap;
uniform float uScale;

void main() {
  vUv = uv;
  float displacement = texture2D(uDisplacementMap, uv).r;
  vec3 newPos = position + normal * displacement * uScale;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(newPos, 1.0);
}
```

**Important:** Geometry needs enough subdivisions. `planeGeometry args={[2, 2, 128, 128]}` or `sphereGeometry args={[1, 128, 128]}`.

---

## UV Manipulation

### Scrolling UVs (flowing water, conveyor belt)

```glsl
uniform float uTime;
varying vec2 vUv;

void main() {
  vec2 uv = vUv;
  uv.y += uTime * 0.1;       // scroll vertically
  uv = fract(uv);             // repeat seamlessly
  // sample texture with scrolled UVs
  gl_FragColor = texture2D(uMap, uv);
}
```

### Polar coordinates (radial effects)

```glsl
vec2 toPolar(vec2 uv) {
  vec2 centered = uv - 0.5;
  float angle = atan(centered.y, centered.x);  // [-PI, PI]
  float radius = length(centered);
  return vec2(angle / (2.0 * 3.14159) + 0.5, radius * 2.0);
}
```

### Distortion (heat haze, underwater)

```glsl
uniform float uTime;
uniform float uStrength;    // 0.01 - 0.05
varying vec2 vUv;

void main() {
  vec2 uv = vUv;
  uv.x += sin(uv.y * 20.0 + uTime * 2.0) * uStrength;
  uv.y += cos(uv.x * 15.0 + uTime * 1.5) * uStrength;
  gl_FragColor = texture2D(uMap, uv);
}
```

### Tiling with scale + offset

```glsl
vec2 tiledUV(vec2 uv, float scale, vec2 offset) {
  return fract(uv * scale + offset);
}
```

---

## Common Utility Functions

```glsl
// Remap value from one range to another
float remap(float value, float inMin, float inMax, float outMin, float outMax) {
  return outMin + (outMax - outMin) * (value - inMin) / (inMax - inMin);
}

// Smooth minimum (blend between shapes)
float smin(float a, float b, float k) {
  float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
  return mix(b, a, h) - k * h * (1.0 - h);
}

// Rotate 2D
vec2 rotate2D(vec2 uv, float angle) {
  float s = sin(angle);
  float c = cos(angle);
  return mat2(c, -s, s, c) * uv;
}

// Circle SDF
float sdCircle(vec2 p, float r) {
  return length(p) - r;
}

// Box SDF
float sdBox(vec2 p, vec2 b) {
  vec2 d = abs(p) - b;
  return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
}

// Smooth step alternative (cubic)
float gain(float x, float k) {
  float a = 0.5 * pow(2.0 * ((x < 0.5) ? x : 1.0 - x), k);
  return (x < 0.5) ? a : 1.0 - a;
}
```

---

## Putting It Together: Animated Blob

Complete example combining noise displacement + fresnel + time.

```tsx
const vertexShader = /* glsl */ `
  uniform float uTime;
  uniform float uAmplitude;
  varying vec3 vNormal;
  varying vec3 vViewDir;
  varying float vDisplacement;

  ${simplex2DNoise} // paste snoise function here

  void main() {
    vNormal = normalize(normalMatrix * normal);
    float noise = snoise(vec2(
      position.x * 1.5 + uTime * 0.4,
      position.y * 1.5 + uTime * 0.3
    ));
    vDisplacement = noise * uAmplitude;
    vec3 newPos = position + normal * vDisplacement;

    vec4 worldPos = modelMatrix * vec4(newPos, 1.0);
    vViewDir = normalize(cameraPosition - worldPos.xyz);
    gl_Position = projectionMatrix * viewMatrix * worldPos;
  }
`

const fragmentShader = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform float uFresnelPower;
  varying vec3 vNormal;
  varying vec3 vViewDir;
  varying float vDisplacement;

  void main() {
    float fresnel = pow(1.0 - dot(vNormal, vViewDir), uFresnelPower);
    vec3 color = mix(uColorA, uColorB, vDisplacement + 0.5);
    color += fresnel * 0.5;
    gl_FragColor = vec4(color, 1.0);
  }
`

function Blob() {
  const ref = useRef<THREE.ShaderMaterial>(null!)

  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uAmplitude: { value: 0.3 },
    uColorA: { value: new THREE.Color('#1a0533') },
    uColorB: { value: new THREE.Color('#ff6600') },
    uFresnelPower: { value: 3.0 },
  }), [])

  useFrame((state) => {
    ref.current.uniforms.uTime.value = state.clock.elapsedTime
  })

  return (
    <mesh>
      <icosahedronGeometry args={[1.5, 64]} />
      <shaderMaterial
        ref={ref}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        uniforms={uniforms}
      />
    </mesh>
  )
}
```
