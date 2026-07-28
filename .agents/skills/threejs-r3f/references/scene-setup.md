# Scene Setup Reference

> Complete R3F boilerplate patterns with TypeScript.
> Copy-paste ready. Adapt to your project.

---

## Minimal Canvas Setup

```tsx
import { Canvas } from '@react-three/fiber'
import { Suspense } from 'react'

function App() {
  return (
    <div style={{ width: '100vw', height: '100vh' }}>
      <Canvas
        camera={{ position: [0, 2, 5], fov: 45, near: 0.1, far: 100 }}
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      >
        <Suspense fallback={null}>
          <Scene />
        </Suspense>
      </Canvas>
    </div>
  )
}
```

**Props breakdown:**
- `dpr={[1, 2]}` -- clamp device pixel ratio (retina without burning GPUs)
- `alpha: false` -- opaque background = faster compositing
- `powerPreference: 'high-performance'` -- request discrete GPU on laptops
- `frameloop="demand"` -- add for static scenes (render only on invalidate)

---

## Lighting Rigs

### Studio (product shots, clean shadows)

```tsx
function StudioLighting() {
  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight
        position={[5, 8, 3]}
        intensity={1.2}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-near={0.5}
        shadow-camera-far={50}
        shadow-camera-left={-10}
        shadow-camera-right={10}
        shadow-camera-top={10}
        shadow-camera-bottom={-10}
      />
      <directionalLight position={[-3, 4, -5]} intensity={0.3} />
    </>
  )
}
```

### Studio with HDRI (easiest, best quality)

```tsx
import { Environment } from '@react-three/drei'

function StudioHDRI() {
  return (
    <>
      <Environment preset="studio" background={false} />
      {/* Optional fill light to reduce contrast */}
      <ambientLight intensity={0.2} />
    </>
  )
}
```

**Environment presets:** `apartment`, `city`, `dawn`, `forest`, `lobby`, `night`, `park`, `studio`, `sunset`, `warehouse`

### Outdoor (natural, directional sun)

```tsx
function OutdoorLighting() {
  return (
    <>
      <Environment preset="sunset" background />
      <directionalLight
        position={[10, 15, 5]}
        intensity={2}
        castShadow
        shadow-mapSize={2048}
        color="#ffeedd"
      />
      <hemisphereLight args={['#87CEEB', '#362907', 0.3]} />
    </>
  )
}
```

### Dramatic (high contrast, noir)

```tsx
function DramaticLighting() {
  return (
    <>
      <color attach="background" args={['#000000']} />
      <fog attach="fog" args={['#000000', 5, 20]} />
      <spotLight
        position={[3, 8, 2]}
        angle={0.3}
        penumbra={0.8}
        intensity={3}
        castShadow
        color="#ff6644"
      />
      <pointLight position={[-5, 2, -3]} intensity={0.5} color="#4466ff" />
      {/* No ambient -- pure darkness outside lights */}
    </>
  )
}
```

---

## Camera Configurations

### Perspective (default, most scenes)

```tsx
<Canvas camera={{ position: [0, 2, 5], fov: 45 }}>
```

- **fov 35-45:** Natural, cinematic feel
- **fov 60-75:** Wider, more immersive
- **fov 20-30:** Telephoto, compressed depth

### Orthographic (isometric, UI, 2D-in-3D)

```tsx
<Canvas orthographic camera={{ position: [0, 5, 10], zoom: 50 }}>
```

### Animated Camera (smooth transitions)

```tsx
import { useFrame, useThree } from '@react-three/fiber'
import { useMemo } from 'react'
import * as THREE from 'three'

function CameraRig({ target }: { target: [number, number, number] }) {
  const _target = useMemo(() => new THREE.Vector3(), [])
  const _position = useMemo(() => new THREE.Vector3(), [])

  useFrame((state, delta) => {
    // Smooth lerp to target
    _target.set(...target)
    state.camera.position.lerp(_position.set(target[0], target[1] + 2, target[2] + 5), delta * 2)
    state.camera.lookAt(_target)
  })

  return null
}
```

---

## Controls

### OrbitControls (inspect / product viewer)

```tsx
import { OrbitControls } from '@react-three/drei'

<OrbitControls
  makeDefault
  enableDamping
  dampingFactor={0.05}
  minDistance={2}
  maxDistance={20}
  minPolarAngle={0}
  maxPolarAngle={Math.PI / 2}    // prevent going below ground
  autoRotate={false}
  autoRotateSpeed={0.5}
/>
```

### PresentationControls (drag-to-rotate, bounded)

```tsx
import { PresentationControls } from '@react-three/drei'

<PresentationControls
  global                         // listen on entire canvas
  snap                           // snap back to rest
  speed={1.5}
  zoom={0.8}
  rotation={[0, -Math.PI / 4, 0]}  // initial angle
  polar={[-Math.PI / 4, Math.PI / 4]}
  azimuth={[-Math.PI / 4, Math.PI / 4]}
>
  <Model />
</PresentationControls>
```

### MapControls (top-down, pan-based)

```tsx
import { MapControls } from '@react-three/drei'

<MapControls
  makeDefault
  enableRotate={false}
  minDistance={5}
  maxDistance={50}
/>
```

### Pointer-based camera (follow cursor)

```tsx
function PointerCamera() {
  useFrame((state) => {
    const { x, y } = state.pointer // normalized -1 to 1
    state.camera.position.x = THREE.MathUtils.lerp(state.camera.position.x, x * 2, 0.05)
    state.camera.position.y = THREE.MathUtils.lerp(state.camera.position.y, y * 1.5 + 1, 0.05)
    state.camera.lookAt(0, 0, 0)
  })
  return null
}
```

---

## Loading Models

### useGLTF (standard)

```tsx
import { useGLTF } from '@react-three/drei'
import type { GLTF } from 'three-stdlib'

type ModelGLTF = GLTF & {
  nodes: {
    Body: THREE.Mesh
    Eyes: THREE.Mesh
  }
  materials: {
    skin: THREE.MeshStandardMaterial
    eyes: THREE.MeshStandardMaterial
  }
}

function Model(props: JSX.IntrinsicElements['group']) {
  const { nodes, materials } = useGLTF('/model.glb') as ModelGLTF

  return (
    <group {...props} dispose={null}>
      <mesh geometry={nodes.Body.geometry} material={materials.skin} />
      <mesh geometry={nodes.Eyes.geometry} material={materials.eyes} />
    </group>
  )
}

useGLTF.preload('/model.glb')
```

**Tip:** Use [gltf.pmnd.rs](https://gltf.pmnd.rs/) to auto-generate typed R3F components from .glb files.

### useGLTF with Draco compression

```tsx
import { useGLTF } from '@react-three/drei'

// Draco decoder loaded from CDN automatically
const { nodes } = useGLTF('/model-draco.glb', true) // second arg enables Draco

useGLTF.preload('/model-draco.glb', true)
```

### useTexture

```tsx
import { useTexture } from '@react-three/drei'

function TexturedMesh() {
  const [colorMap, normalMap, roughnessMap] = useTexture([
    '/textures/color.jpg',
    '/textures/normal.jpg',
    '/textures/roughness.jpg',
  ])

  return (
    <mesh>
      <sphereGeometry args={[1, 64, 64]} />
      <meshStandardMaterial
        map={colorMap}
        normalMap={normalMap}
        roughnessMap={roughnessMap}
      />
    </mesh>
  )
}

useTexture.preload(['/textures/color.jpg', '/textures/normal.jpg', '/textures/roughness.jpg'])
```

---

## Responsive Canvas

### Fill parent container

```tsx
// Parent must have explicit dimensions
<div style={{ width: '100%', height: '100vh' }}>
  <Canvas>
    <Scene />
  </Canvas>
</div>
```

### Respond to viewport size inside scene

```tsx
function ResponsiveObject() {
  const { viewport } = useThree()
  // viewport.width/height = world units visible at z=0

  return (
    <mesh scale={viewport.width > 6 ? 1 : 0.6}>
      <boxGeometry />
      <meshStandardMaterial />
    </mesh>
  )
}
```

### Adaptive performance

```tsx
import { PerformanceMonitor } from '@react-three/drei'

<Canvas>
  <PerformanceMonitor
    onIncline={() => setDpr(2)}
    onDecline={() => setDpr(1)}
  >
    <Scene />
  </PerformanceMonitor>
</Canvas>
```

---

## Shadows Setup

```tsx
<Canvas shadows>
  <directionalLight castShadow shadow-mapSize={2048} />
  <mesh castShadow>
    <boxGeometry />
    <meshStandardMaterial />
  </mesh>
  <mesh receiveShadow rotation-x={-Math.PI / 2} position-y={-1}>
    <planeGeometry args={[20, 20]} />
    <shadowMaterial opacity={0.3} />
  </mesh>
</Canvas>
```

- `shadows` on Canvas enables the shadow system
- `castShadow` on lights and meshes that cast
- `receiveShadow` on meshes that receive
- `<shadowMaterial>` for transparent ground shadows (product shots)
- `<ContactShadows>` from drei for soft baked-look shadows without shadow maps

```tsx
import { ContactShadows } from '@react-three/drei'

<ContactShadows
  position={[0, -1, 0]}
  opacity={0.4}
  scale={10}
  blur={2}
  far={4}
/>
```
