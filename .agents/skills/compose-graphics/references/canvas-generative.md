# Canvas Generative (Compose)

Generative drawing in Compose Canvas: flow fields, L-systems, particles, attractors. Native Kotlin, no GPU shaders required. Pairs well with `../../canvas-generative/SKILL.md` (web version of the same patterns).

---

## Foundation

Compose's `Canvas` composable exposes a `DrawScope`. Two animation strategies cover most cases.

### Animation via `LaunchedEffect`

Use when you control time manually (particle spawn, custom physics).

```kotlin
val time = remember { mutableFloatStateOf(0f) }
LaunchedEffect(Unit) {
    while (true) {
        withFrameMillis { ms ->
            time.floatValue = ms / 1000f
            // mutate other state here
        }
    }
}
Canvas(modifier = Modifier.fillMaxSize()) {
    // read time.floatValue, draw accordingly
}
```

### Animation via `rememberInfiniteTransition`

Use for simple cyclic loops (rotation, pulse, oscillation).

```kotlin
val infinite = rememberInfiniteTransition(label = "loop")
val phase by infinite.animateFloat(
    initialValue = 0f,
    targetValue = 2 * PI.toFloat(),
    animationSpec = infiniteRepeatable(tween(3000, easing = LinearEasing)),
    label = "phase"
)
Canvas(...) { /* read phase */ }
```

Pick based on need. `LaunchedEffect` for stateful systems, `rememberInfiniteTransition` for stateless cycles.

---

## Recipe: Flow Field

Particles advected by a noise-derived angle field. The classic generative recipe.

```kotlin
data class FlowParticle(var x: Float, var y: Float)

// Simple hash-based 2D noise (sin lookup, fast enough for runtime)
fun noise2D(x: Float, y: Float): Float {
    val n = sin(x * 12.9898f + y * 78.233f) * 43758.547f
    return n - floor(n)  // 0..1
}

@Composable
fun FlowField() {
    val particles = remember {
        Array(150) {
            FlowParticle(Random.nextFloat() * 1000f, Random.nextFloat() * 1000f)
        }
    }
    val time = remember { mutableFloatStateOf(0f) }
    LaunchedEffect(Unit) {
        while (true) {
            withFrameMillis { ms ->
                time.floatValue = ms / 1000f
                particles.forEach { p ->
                    val angle = noise2D(p.x * 0.005f, p.y * 0.005f) * 2 * PI.toFloat()
                    p.x += cos(angle) * 1.5f
                    p.y += sin(angle) * 1.5f
                    // Wrap edges
                    if (p.x < 0f) p.x += 1000f
                    if (p.x > 1000f) p.x -= 1000f
                    if (p.y < 0f) p.y += 1000f
                    if (p.y > 1000f) p.y -= 1000f
                }
            }
        }
    }
    Canvas(modifier = Modifier.fillMaxSize()) {
        particles.forEach { p ->
            drawCircle(
                color = Color.White.copy(alpha = 0.3f),
                radius = 1.5f,
                center = Offset(p.x, p.y)
            )
        }
    }
}
```

> The `sin`-hash noise is cheap but not seamless. For production, port a Perlin or Simplex implementation (or wrap one via `androidx.compose.ui.graphics.Path` precomputation).

---

## Recipe: L-System (Recursive Plant)

Encodes recursive structure as string rewriting plus turtle graphics in DrawScope.

```kotlin
fun lsystem(axiom: String, rules: Map<Char, String>, iterations: Int): String {
    var current = axiom
    repeat(iterations) {
        current = current.map { rules[it] ?: it.toString() }.joinToString("")
    }
    return current
}

@Composable
fun LSystemPlant() {
    val commands = remember {
        lsystem(
            axiom = "F",
            rules = mapOf('F' to "FF+[+F-F-F]-[-F+F+F]"),
            iterations = 4
        )
    }
    Canvas(modifier = Modifier.fillMaxSize()) {
        val stack = ArrayDeque<Triple<Float, Float, Float>>()
        var x = size.width / 2
        var y = size.height
        var angle = -PI.toFloat() / 2  // start pointing up
        val len = 4f
        val turn = PI.toFloat() / 7
        val path = Path().apply { moveTo(x, y) }
        commands.forEach { c ->
            when (c) {
                'F' -> {
                    val nx = x + cos(angle) * len
                    val ny = y + sin(angle) * len
                    path.lineTo(nx, ny)
                    x = nx; y = ny
                }
                '+' -> angle += turn
                '-' -> angle -= turn
                '[' -> stack.addLast(Triple(x, y, angle))
                ']' -> {
                    val (sx, sy, sa) = stack.removeLast()
                    x = sx; y = sy; angle = sa
                    path.moveTo(x, y)
                }
            }
        }
        drawPath(path, color = Color(0xFF2E7D32), style = Stroke(width = 1f))
    }
}
```

Increase `iterations` cautiously - the string length grows exponentially. 4-5 iterations is the practical ceiling for fern-like rules at 60fps.

---

## Recipe: Mouse-Following Particle System

50 particles spawned at the pointer position, each with velocity, lifetime, fade.

```kotlin
data class TrailParticle(
    var x: Float,
    var y: Float,
    var vx: Float,
    var vy: Float,
    var life: Float
)

@Composable
fun PointerTrail() {
    val particles = remember { mutableStateListOf<TrailParticle>() }
    var pointerPos by remember { mutableStateOf<Offset?>(null) }

    // Spawn on pointer move, update on each frame
    LaunchedEffect(Unit) {
        while (true) {
            withFrameMillis {
                pointerPos?.let { pos ->
                    if (particles.size < 200) {
                        particles.add(
                            TrailParticle(
                                x = pos.x,
                                y = pos.y,
                                vx = (Random.nextFloat() - 0.5f) * 4f,
                                vy = (Random.nextFloat() - 0.5f) * 4f,
                                life = 1f
                            )
                        )
                    }
                }
                val iter = particles.iterator()
                while (iter.hasNext()) {
                    val p = iter.next()
                    p.x += p.vx
                    p.y += p.vy
                    p.vy += 0.05f  // gravity
                    p.life -= 0.02f
                    if (p.life <= 0f) iter.remove()
                }
            }
        }
    }

    Canvas(
        modifier = Modifier
            .fillMaxSize()
            .pointerInput(Unit) {
                awaitPointerEventScope {
                    while (true) {
                        val event = awaitPointerEvent()
                        pointerPos = event.changes.first().position
                    }
                }
            }
    ) {
        particles.forEach { p ->
            drawCircle(
                color = Color.Cyan.copy(alpha = p.life),
                radius = 3f,
                center = Offset(p.x, p.y)
            )
        }
    }
}
```

> Cap the particle count (`if (particles.size < 200)`). Without a cap, fast pointer movement floods the list and tanks frame time.

---

## Recipe: Voronoi / Delaunay (Quick Mention)

Voronoi diagrams need a triangulation step. Compose has no built-in. Two practical paths:

1. **Pre-compute on the JVM** with a small Kotlin port of Fortune's algorithm or Bowyer-Watson, then draw the cells in DrawScope.
2. **Use a library** like [zhihaoshen/delaunator-kotlin](https://github.com/zhihaoshen/delaunator-kotlin) (port of mapbox's `delaunator`).

Voronoi at runtime (recomputing on every frame) is impractical past a few hundred points. Compute once, animate the seed positions, retriangulate on demand.

---

## Performance

| Pattern | Note |
|---|---|
| 200 simple draws per frame | Fine on most devices, 60fps comfortable |
| 1000 draws per frame | Mid-range starts to lag, profile with Macrobenchmark |
| 2000+ draws per frame | Drop to half-rate, batch into a single `Path`, or move to GPU (RuntimeShader) |
| `derivedStateOf` around volatile state | Reduces Canvas recompose triggers |
| `drawIntoCanvas { it.nativeCanvas.drawXXX }` | Escape hatch for raw `android.graphics.Canvas` (e.g. `drawTextOnPath`) |
| Precompute static paths in `remember` | Don't rebuild geometry every frame - mutate transforms only |
| Wrap heavy Canvas in its own Composable | Isolates recomposes, parent state changes don't redraw |

```kotlin
// BAD - rebuild path every frame
Canvas(modifier = Modifier.fillMaxSize()) {
    val path = Path()
    points.forEach { path.lineTo(it.x, it.y) }
    drawPath(path, color = Color.Black)
}

// GOOD - precompute, only redraw on real change
val path = remember(points) {
    Path().apply { points.forEach { lineTo(it.x, it.y) } }
}
Canvas(modifier = Modifier.fillMaxSize()) {
    drawPath(path, color = Color.Black)
}
```

---

## Sources

- [The Coding Train (Daniel Shiffman)](https://thecodingtrain.com/) - generative coding reference
- [The Nature of Code](https://natureofcode.com/) - free book on generative motion, particle systems, autonomous agents
- [Anastasia Opara's "Procedural Art"](https://anastasiaopara.com/) - field-tested techniques
- Companion skill: `../../canvas-generative/SKILL.md` (web Canvas 2D version of these patterns)
