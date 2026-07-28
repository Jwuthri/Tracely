# Algorithms Reference

> Complete, commented implementations for generative art.
> Copy-paste ready. Each algorithm is self-contained.

---

## Simplex Noise 2D/3D

Compact implementation based on Stefan Gustavson's work. No external dependencies.

```js
// ─── Simplex Noise ──────────────────────────────────────────────
// Attempt to produce smooth, isotropic noise without grid-aligned
// artifacts. Works in 2D and 3D. Returns values in [-1, 1].

const SimplexNoise = (() => {
  // Gradient vectors for 2D (12 directions)
  const grad2 = [
    [1,1],[-1,1],[1,-1],[-1,-1],
    [1,0],[-1,0],[0,1],[0,-1],
    [1,1],[-1,1],[1,-1],[-1,-1]
  ];

  // Gradient vectors for 3D
  const grad3 = [
    [1,1,0],[-1,1,0],[1,-1,0],[-1,-1,0],
    [1,0,1],[-1,0,1],[1,0,-1],[-1,0,-1],
    [0,1,1],[0,-1,1],[0,1,-1],[0,-1,-1]
  ];

  // Permutation table (256 entries, doubled to avoid wrapping)
  const perm = new Uint8Array(512);
  const permMod12 = new Uint8Array(512);

  // Seed the permutation table
  // Pass any number to get reproducible results
  function seed(s) {
    const p = new Uint8Array(256);
    for (let i = 0; i < 256; i++) p[i] = i;

    // Fisher-Yates shuffle seeded with a simple LCG
    let v = s * 1664525 + 1013904223;
    for (let i = 255; i > 0; i--) {
      v = (v * 1664525 + 1013904223) | 0;
      const j = (v >>> 0) % (i + 1);
      [p[i], p[j]] = [p[j], p[i]];
    }

    for (let i = 0; i < 512; i++) {
      perm[i] = p[i & 255];
      permMod12[i] = perm[i] % 12;
    }
  }

  // Skewing factors for 2D simplex
  const F2 = 0.5 * (Math.sqrt(3) - 1);    // skew input space to grid
  const G2 = (3 - Math.sqrt(3)) / 6;       // unskew back

  // Skewing factors for 3D
  const F3 = 1 / 3;
  const G3 = 1 / 6;

  function dot2(g, x, y) { return g[0] * x + g[1] * y; }
  function dot3(g, x, y, z) { return g[0] * x + g[1] * y + g[2] * z; }

  /**
   * 2D Simplex Noise
   * @param {number} xin - x coordinate
   * @param {number} yin - y coordinate
   * @returns {number} noise value in [-1, 1]
   */
  function noise2D(xin, yin) {
    let n0, n1, n2; // contributions from 3 corners

    // Skew input to find which simplex cell we're in
    const s = (xin + yin) * F2;
    const i = Math.floor(xin + s);
    const j = Math.floor(yin + s);

    // Unskew back to get cell origin in (x,y) space
    const t = (i + j) * G2;
    const X0 = i - t;
    const Y0 = j - t;
    const x0 = xin - X0; // distance from cell origin
    const y0 = yin - Y0;

    // Determine which simplex we're in (upper or lower triangle)
    let i1, j1;
    if (x0 > y0) { i1 = 1; j1 = 0; }  // lower triangle
    else          { i1 = 0; j1 = 1; }  // upper triangle

    // Offsets for middle and last corner
    const x1 = x0 - i1 + G2;
    const y1 = y0 - j1 + G2;
    const x2 = x0 - 1 + 2 * G2;
    const y2 = y0 - 1 + 2 * G2;

    // Hash coordinates to gradient indices
    const ii = i & 255;
    const jj = j & 255;
    const gi0 = permMod12[ii + perm[jj]];
    const gi1 = permMod12[ii + i1 + perm[jj + j1]];
    const gi2 = permMod12[ii + 1 + perm[jj + 1]];

    // Calculate contribution from each corner
    // Each corner has a radial falloff of r^2 = 0.5
    let t0 = 0.5 - x0 * x0 - y0 * y0;
    n0 = t0 < 0 ? 0 : (t0 *= t0, t0 * t0 * dot2(grad2[gi0], x0, y0));

    let t1 = 0.5 - x1 * x1 - y1 * y1;
    n1 = t1 < 0 ? 0 : (t1 *= t1, t1 * t1 * dot2(grad2[gi1], x1, y1));

    let t2 = 0.5 - x2 * x2 - y2 * y2;
    n2 = t2 < 0 ? 0 : (t2 *= t2, t2 * t2 * dot2(grad2[gi2], x2, y2));

    // Scale to [-1, 1]
    return 70 * (n0 + n1 + n2);
  }

  /**
   * 3D Simplex Noise
   * @param {number} xin - x coordinate
   * @param {number} yin - y coordinate
   * @param {number} zin - z coordinate
   * @returns {number} noise value in [-1, 1]
   */
  function noise3D(xin, yin, zin) {
    let n0, n1, n2, n3;

    // Skew input space
    const s = (xin + yin + zin) * F3;
    const i = Math.floor(xin + s);
    const j = Math.floor(yin + s);
    const k = Math.floor(zin + s);

    const t = (i + j + k) * G3;
    const X0 = i - t;
    const Y0 = j - t;
    const Z0 = k - t;
    const x0 = xin - X0;
    const y0 = yin - Y0;
    const z0 = zin - Z0;

    // Determine which simplex we're in (6 possible tetrahedra)
    let i1, j1, k1, i2, j2, k2;
    if (x0 >= y0) {
      if (y0 >= z0)      { i1=1; j1=0; k1=0; i2=1; j2=1; k2=0; }
      else if (x0 >= z0) { i1=1; j1=0; k1=0; i2=1; j2=0; k2=1; }
      else               { i1=0; j1=0; k1=1; i2=1; j2=0; k2=1; }
    } else {
      if (y0 < z0)       { i1=0; j1=0; k1=1; i2=0; j2=1; k2=1; }
      else if (x0 < z0)  { i1=0; j1=1; k1=0; i2=0; j2=1; k2=1; }
      else               { i1=0; j1=1; k1=0; i2=1; j2=1; k2=0; }
    }

    const x1 = x0 - i1 + G3;
    const y1 = y0 - j1 + G3;
    const z1 = z0 - k1 + G3;
    const x2 = x0 - i2 + 2 * G3;
    const y2 = y0 - j2 + 2 * G3;
    const z2 = z0 - k2 + 2 * G3;
    const x3 = x0 - 1 + 3 * G3;
    const y3 = y0 - 1 + 3 * G3;
    const z3 = z0 - 1 + 3 * G3;

    const ii = i & 255;
    const jj = j & 255;
    const kk = k & 255;
    const gi0 = permMod12[ii + perm[jj + perm[kk]]];
    const gi1 = permMod12[ii + i1 + perm[jj + j1 + perm[kk + k1]]];
    const gi2 = permMod12[ii + i2 + perm[jj + j2 + perm[kk + k2]]];
    const gi3 = permMod12[ii + 1 + perm[jj + 1 + perm[kk + 1]]];

    let t0 = 0.6 - x0*x0 - y0*y0 - z0*z0;
    n0 = t0 < 0 ? 0 : (t0 *= t0, t0 * t0 * dot3(grad3[gi0], x0, y0, z0));

    let t1 = 0.6 - x1*x1 - y1*y1 - z1*z1;
    n1 = t1 < 0 ? 0 : (t1 *= t1, t1 * t1 * dot3(grad3[gi1], x1, y1, z1));

    let t2 = 0.6 - x2*x2 - y2*y2 - z2*z2;
    n2 = t2 < 0 ? 0 : (t2 *= t2, t2 * t2 * dot3(grad3[gi2], x2, y2, z2));

    let t3 = 0.6 - x3*x3 - y3*y3 - z3*z3;
    n3 = t3 < 0 ? 0 : (t3 *= t3, t3 * t3 * dot3(grad3[gi3], x3, y3, z3));

    return 32 * (n0 + n1 + n2 + n3);
  }

  // Auto-seed with a default
  seed(0);

  return { noise2D, noise3D, seed };
})();
```

**Usage:**
```js
SimplexNoise.seed(42); // reproducible

const val = SimplexNoise.noise2D(x * 0.01, y * 0.01); // scale coords down!
// val is in [-1, 1]
```

---

## Particle System with Pool

Zero-allocation particle system. Pre-allocates everything. Swap-and-shrink for death.

```js
// ─── Particle Pool System ───────────────────────────────────────
// Fixed-size pool: no new/delete during runtime.
// Particles are stored contiguously. Dead particles are swapped
// to the end, keeping iteration tight.

class ParticleSystem {
  constructor(maxParticles = 10000) {
    this.max = maxParticles;
    this.count = 0; // number of alive particles

    // Struct-of-Arrays layout for cache friendliness
    // Each property is a flat Float32Array
    this.x     = new Float32Array(maxParticles);
    this.y     = new Float32Array(maxParticles);
    this.vx    = new Float32Array(maxParticles);
    this.vy    = new Float32Array(maxParticles);
    this.life  = new Float32Array(maxParticles); // current age (frames)
    this.maxLife = new Float32Array(maxParticles);
    this.size  = new Float32Array(maxParticles);
    this.alpha = new Float32Array(maxParticles);
  }

  /**
   * Spawn a particle at (x, y) with given velocity and lifespan.
   * Returns false if pool is full.
   */
  spawn(x, y, vx, vy, life, size = 2) {
    if (this.count >= this.max) return false;

    const i = this.count++;
    this.x[i] = x;
    this.y[i] = y;
    this.vx[i] = vx;
    this.vy[i] = vy;
    this.life[i] = 0;
    this.maxLife[i] = life;
    this.size[i] = size;
    this.alpha[i] = 1;
    return true;
  }

  /**
   * Spawn N particles in a burst pattern (radial).
   */
  burst(x, y, count, speed = 2, life = 60, size = 2) {
    for (let i = 0; i < count; i++) {
      const angle = (i / count) * Math.PI * 2;
      const v = speed * (0.5 + Math.random() * 0.5); // slight randomness
      this.spawn(
        x, y,
        Math.cos(angle) * v,
        Math.sin(angle) * v,
        life * (0.7 + Math.random() * 0.6),
        size
      );
    }
  }

  /**
   * Update all alive particles.
   * @param {number} dt - delta time in seconds
   * @param {number} gravity - gravity acceleration (positive = downward)
   * @param {number} friction - velocity multiplier per frame (0.99 = slight drag)
   */
  update(dt = 1/60, gravity = 0, friction = 1) {
    for (let i = this.count - 1; i >= 0; i--) {
      // Apply forces
      this.vy[i] += gravity * dt;
      this.vx[i] *= friction;
      this.vy[i] *= friction;

      // Integrate position
      this.x[i] += this.vx[i];
      this.y[i] += this.vy[i];

      // Age
      this.life[i]++;

      // Fade alpha based on remaining life
      const lifeRatio = this.life[i] / this.maxLife[i];
      this.alpha[i] = 1 - lifeRatio; // linear fade out

      // Kill if expired: swap with last alive particle
      if (this.life[i] >= this.maxLife[i]) {
        this.count--;
        if (i < this.count) {
          // Swap all properties
          this.x[i]       = this.x[this.count];
          this.y[i]       = this.y[this.count];
          this.vx[i]      = this.vx[this.count];
          this.vy[i]      = this.vy[this.count];
          this.life[i]    = this.life[this.count];
          this.maxLife[i]  = this.maxLife[this.count];
          this.size[i]    = this.size[this.count];
          this.alpha[i]   = this.alpha[this.count];
        }
      }
    }
  }

  /**
   * Render all alive particles to a Canvas 2D context.
   * @param {CanvasRenderingContext2D} ctx
   * @param {string} color - base color (rgb format, alpha applied per-particle)
   */
  render(ctx, color = '255, 255, 255') {
    for (let i = 0; i < this.count; i++) {
      ctx.beginPath();
      ctx.arc(this.x[i], this.y[i], this.size[i], 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${color}, ${this.alpha[i].toFixed(3)})`;
      ctx.fill();
    }
  }
}
```

**Usage:**
```js
const ps = new ParticleSystem(5000);

// Continuous emitter
function emit() {
  ps.spawn(
    canvas.width / 2, canvas.height / 2,
    (Math.random() - 0.5) * 4,
    (Math.random() - 0.5) * 4,
    80 + Math.random() * 40
  );
}

function loop() {
  for (let i = 0; i < 5; i++) emit(); // 5 particles per frame
  ps.update(1/60, 0.1, 0.99);

  ctx.fillStyle = 'rgba(0, 0, 0, 0.05)'; // trail
  ctx.fillRect(0, 0, w, h);
  ps.render(ctx);

  requestAnimationFrame(loop);
}
```

---

## Complete Flow Field

Noise-driven vector field with particle followers. Full implementation with color and trail effects.

```js
// ─── Flow Field ─────────────────────────────────────────────────
// A grid of angle vectors derived from noise. Particles follow
// the field, creating organic line patterns.

class FlowField {
  /**
   * @param {number} width - canvas logical width
   * @param {number} height - canvas logical height
   * @param {number} cellSize - grid cell size in pixels
   * @param {object} options
   */
  constructor(width, height, cellSize = 20, options = {}) {
    this.width = width;
    this.height = height;
    this.cellSize = cellSize;

    this.cols = Math.ceil(width / cellSize);
    this.rows = Math.ceil(height / cellSize);

    // Flat array of angles (radians)
    this.field = new Float32Array(this.cols * this.rows);

    // Config
    this.noiseScale = options.noiseScale || 0.003; // how zoomed-in the noise is
    this.noiseZ     = 0;                           // animate noise over time
    this.noiseSpeed = options.noiseSpeed || 0.002;  // z-axis speed

    // Particles
    this.particleCount = options.particles || 1000;
    this.particles = [];
    this.maxSpeed  = options.maxSpeed || 2;
    this.force     = options.force || 0.3;

    this._initParticles();
  }

  _initParticles() {
    for (let i = 0; i < this.particleCount; i++) {
      this.particles.push({
        x: Math.random() * this.width,
        y: Math.random() * this.height,
        vx: 0,
        vy: 0,
        // Previous position for line drawing
        px: 0,
        py: 0,
        age: Math.floor(Math.random() * 200), // stagger lifespans
        maxAge: 200 + Math.floor(Math.random() * 100),
        hue: 0, // set during update
      });
    }
  }

  /**
   * Rebuild the angle grid from noise.
   * Call once per frame before updating particles.
   */
  updateField() {
    this.noiseZ += this.noiseSpeed;

    for (let y = 0; y < this.rows; y++) {
      for (let x = 0; x < this.cols; x++) {
        // Noise value in [-1, 1], map to full rotation
        const n = SimplexNoise.noise3D(
          x * this.noiseScale * this.cellSize,
          y * this.noiseScale * this.cellSize,
          this.noiseZ
        );
        this.field[y * this.cols + x] = n * Math.PI * 2;
      }
    }
  }

  /**
   * Get the field angle at a given pixel position.
   * Returns 0 if out of bounds.
   */
  lookup(x, y) {
    const col = Math.floor(x / this.cellSize);
    const row = Math.floor(y / this.cellSize);
    if (col < 0 || col >= this.cols || row < 0 || row >= this.rows) return 0;
    return this.field[row * this.cols + col];
  }

  /**
   * Update all particles: follow field, apply velocity, handle wrapping/respawn.
   */
  updateParticles() {
    for (const p of this.particles) {
      // Store previous position (for line drawing)
      p.px = p.x;
      p.py = p.y;

      // Get field angle at current position
      const angle = this.lookup(p.x, p.y);

      // Apply force in field direction
      p.vx += Math.cos(angle) * this.force;
      p.vy += Math.sin(angle) * this.force;

      // Clamp speed
      const speed = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
      if (speed > this.maxSpeed) {
        p.vx = (p.vx / speed) * this.maxSpeed;
        p.vy = (p.vy / speed) * this.maxSpeed;
      }

      // Move
      p.x += p.vx;
      p.y += p.vy;

      // Slight friction
      p.vx *= 0.96;
      p.vy *= 0.96;

      // Color based on angle
      p.hue = ((angle / (Math.PI * 2)) * 360 + 360) % 360;

      // Age and respawn
      p.age++;
      if (p.age > p.maxAge || p.x < 0 || p.x > this.width || p.y < 0 || p.y > this.height) {
        p.x = Math.random() * this.width;
        p.y = Math.random() * this.height;
        p.px = p.x;
        p.py = p.y;
        p.vx = 0;
        p.vy = 0;
        p.age = 0;
      }
    }
  }

  /**
   * Render particle trails as lines.
   */
  render(ctx) {
    for (const p of this.particles) {
      // Skip first frame (no previous position)
      if (p.age === 0) continue;

      const alpha = Math.min(1, (1 - p.age / p.maxAge) * 0.8);
      ctx.beginPath();
      ctx.moveTo(p.px, p.py);
      ctx.lineTo(p.x, p.y);
      ctx.strokeStyle = `hsla(${p.hue}, 70%, 60%, ${alpha})`;
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }
}

// ─── Usage ──────────────────────────────────────────────────────
//
// const canvas = document.getElementById('canvas');
// const ctx = setupCanvas(canvas, window.innerWidth, window.innerHeight);
// SimplexNoise.seed(42);
//
// const ff = new FlowField(canvas.clientWidth, canvas.clientHeight, 20, {
//   particles: 2000,
//   noiseScale: 0.004,
//   noiseSpeed: 0.001,
//   maxSpeed: 2,
//   force: 0.2,
// });
//
// function loop() {
//   // Trail fade (no clearRect!)
//   ctx.fillStyle = 'rgba(10, 10, 15, 0.03)';
//   ctx.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight);
//
//   ff.updateField();
//   ff.updateParticles();
//   ff.render(ctx);
//
//   requestAnimationFrame(loop);
// }
// requestAnimationFrame(loop);
```

---

## L-System Renderer

Complete L-system with string expansion and turtle graphics rendering.

```js
// ─── L-System ───────────────────────────────────────────────────
// String-rewriting system + turtle graphics.
// Produces fractal plants, trees, curves.

class LSystem {
  /**
   * @param {string} axiom - starting string
   * @param {Object<string, string>} rules - production rules { 'F': 'F[+F]F[-F]F' }
   * @param {number} angle - turn angle in degrees
   */
  constructor(axiom, rules, angle) {
    this.axiom = axiom;
    this.rules = rules;
    this.angle = (angle * Math.PI) / 180; // convert to radians
    this.commands = axiom;
  }

  /**
   * Expand the L-system string by N iterations.
   * WARNING: string length grows exponentially. Keep iterations low (4-7).
   */
  generate(iterations) {
    this.commands = this.axiom;
    for (let i = 0; i < iterations; i++) {
      let next = '';
      for (const char of this.commands) {
        next += this.rules[char] || char;
      }
      this.commands = next;
    }
    return this.commands;
  }

  /**
   * Render the L-system commands to a canvas context.
   * @param {CanvasRenderingContext2D} ctx
   * @param {number} startX - turtle start x
   * @param {number} startY - turtle start y
   * @param {number} startAngle - initial heading in radians (default: up)
   * @param {number} stepLength - length per 'F' step
   * @param {object} style - { strokeStyle, lineWidth, depthFade }
   */
  render(ctx, startX, startY, startAngle = -Math.PI / 2, stepLength = 5, style = {}) {
    const {
      strokeStyle = '#88cc88',
      lineWidth = 1,
      depthFade = true, // fade color with stack depth
    } = style;

    // Turtle state
    let x = startX;
    let y = startY;
    let angle = startAngle;
    let depth = 0;
    const stack = []; // save/restore stack for [ ]

    ctx.save();
    ctx.lineCap = 'round';

    for (const char of this.commands) {
      switch (char) {
        // F: move forward, drawing a line
        case 'F': {
          const nx = x + Math.cos(angle) * stepLength;
          const ny = y + Math.sin(angle) * stepLength;

          ctx.beginPath();
          ctx.moveTo(x, y);
          ctx.lineTo(nx, ny);

          if (depthFade) {
            const alpha = Math.max(0.1, 1 - depth * 0.15);
            const width = Math.max(0.5, lineWidth - depth * 0.2);
            ctx.strokeStyle = strokeStyle.includes('rgba')
              ? strokeStyle
              : `rgba(136, 204, 136, ${alpha})`;
            ctx.lineWidth = width;
          } else {
            ctx.strokeStyle = strokeStyle;
            ctx.lineWidth = lineWidth;
          }

          ctx.stroke();
          x = nx;
          y = ny;
          break;
        }

        // f: move forward without drawing (pen up)
        case 'f': {
          x += Math.cos(angle) * stepLength;
          y += Math.sin(angle) * stepLength;
          break;
        }

        // +: turn right (clockwise)
        case '+':
          angle += this.angle;
          break;

        // -: turn left (counter-clockwise)
        case '-':
          angle -= this.angle;
          break;

        // [: push state (branch start)
        case '[':
          stack.push({ x, y, angle, depth });
          depth++;
          break;

        // ]: pop state (branch end)
        case ']': {
          const state = stack.pop();
          if (state) {
            x = state.x;
            y = state.y;
            angle = state.angle;
            depth = state.depth;
          }
          break;
        }
      }
    }

    ctx.restore();
  }
}

// ─── Preset L-Systems ──────────────────────────────────────────

const LSYSTEM_PRESETS = {
  // Fractal plant (bush-like)
  plant: {
    axiom: 'X',
    rules: {
      'X': 'F+[[X]-X]-F[-FX]+X',
      'F': 'FF',
    },
    angle: 25,
    iterations: 6,
    stepLength: 3,
  },

  // Koch snowflake
  koch: {
    axiom: 'F--F--F',
    rules: { 'F': 'F+F--F+F' },
    angle: 60,
    iterations: 4,
    stepLength: 3,
  },

  // Sierpinski triangle
  sierpinski: {
    axiom: 'F-G-G',
    rules: { 'F': 'F-G+F+G-F', 'G': 'GG' },
    angle: 120,
    iterations: 6,
    stepLength: 4,
  },

  // Dragon curve
  dragon: {
    axiom: 'FX',
    rules: { 'X': 'X+YF+', 'Y': '-FX-Y' },
    angle: 90,
    iterations: 12,
    stepLength: 5,
  },

  // Binary tree
  tree: {
    axiom: 'F',
    rules: { 'F': 'FF+[+F-F-F]-[-F+F+F]' },
    angle: 22.5,
    iterations: 4,
    stepLength: 8,
  },
};

// ─── Usage ──────────────────────────────────────────────────────
//
// const preset = LSYSTEM_PRESETS.plant;
// const ls = new LSystem(preset.axiom, preset.rules, preset.angle);
// ls.generate(preset.iterations);
//
// ctx.fillStyle = '#111';
// ctx.fillRect(0, 0, w, h);
// ls.render(ctx, w / 2, h, -Math.PI / 2, preset.stepLength, {
//   strokeStyle: '#88cc88',
//   lineWidth: 1.5,
//   depthFade: true,
// });
```

---

## Lorenz Attractor

The classic strange attractor. 3D system projected to 2D canvas.

```js
// ─── Lorenz Attractor ───────────────────────────────────────────
// A chaotic system of 3 coupled ODEs. The trajectory never repeats
// and never intersects itself, creating the iconic butterfly shape.
//
// dx/dt = sigma * (y - x)
// dy/dt = x * (rho - z) - y
// dz/dt = x * y - beta * z

class LorenzAttractor {
  /**
   * @param {object} options
   * @param {number} options.sigma - Prandtl number (default 10)
   * @param {number} options.rho - Rayleigh number (default 28)
   * @param {number} options.beta - geometric factor (default 8/3)
   * @param {number} options.dt - integration timestep
   * @param {number} options.trailLength - how many points to remember
   */
  constructor(options = {}) {
    this.sigma = options.sigma || 10;
    this.rho   = options.rho   || 28;
    this.beta  = options.beta  || 8 / 3;
    this.dt    = options.dt    || 0.005;

    this.trailLength = options.trailLength || 5000;

    // Current position in 3D space
    this.x = 0.01;
    this.y = 0;
    this.z = 0;

    // Trail history (ring buffer)
    this.trail = new Float32Array(this.trailLength * 3); // [x,y,z, x,y,z, ...]
    this.trailHead = 0;
    this.trailCount = 0;
  }

  /**
   * Step the simulation forward by one timestep (Runge-Kutta 4th order).
   * RK4 is crucial for chaotic systems -- Euler integration diverges fast.
   */
  step() {
    const { sigma, rho, beta, dt } = this;
    let { x, y, z } = this;

    // Derivatives function
    const f = (x, y, z) => ({
      dx: sigma * (y - x),
      dy: x * (rho - z) - y,
      dz: x * y - beta * z,
    });

    // RK4 integration
    const k1 = f(x, y, z);
    const k2 = f(
      x + k1.dx * dt * 0.5,
      y + k1.dy * dt * 0.5,
      z + k1.dz * dt * 0.5
    );
    const k3 = f(
      x + k2.dx * dt * 0.5,
      y + k2.dy * dt * 0.5,
      z + k2.dz * dt * 0.5
    );
    const k4 = f(
      x + k3.dx * dt,
      y + k3.dy * dt,
      z + k3.dz * dt
    );

    this.x += (dt / 6) * (k1.dx + 2*k2.dx + 2*k3.dx + k4.dx);
    this.y += (dt / 6) * (k1.dy + 2*k2.dy + 2*k3.dy + k4.dy);
    this.z += (dt / 6) * (k1.dz + 2*k2.dz + 2*k3.dz + k4.dz);

    // Store in trail ring buffer
    const idx = this.trailHead * 3;
    this.trail[idx]     = this.x;
    this.trail[idx + 1] = this.y;
    this.trail[idx + 2] = this.z;
    this.trailHead = (this.trailHead + 1) % this.trailLength;
    if (this.trailCount < this.trailLength) this.trailCount++;
  }

  /**
   * Step N times (useful for faster evolution per frame).
   */
  stepN(n) {
    for (let i = 0; i < n; i++) this.step();
  }

  /**
   * Project 3D point to 2D using simple orthographic projection.
   * The Lorenz attractor lives roughly in x:[-20,20], y:[-25,25], z:[0,50].
   * We map x->screen.x and z->screen.y for the classic side view.
   *
   * @param {number} cx - canvas center x
   * @param {number} cy - canvas center y
   * @param {number} scale - zoom factor
   * @returns {{ sx: number, sy: number }} screen coordinates
   */
  project(px, py, pz, cx, cy, scale = 8) {
    return {
      sx: cx + px * scale,
      sy: cy - (pz - 25) * scale, // center z around 25, flip y-axis
    };
  }

  /**
   * Render the attractor trail to a 2D canvas.
   * Older points are more transparent, creating a fade-in effect.
   */
  render(ctx, cx, cy, scale = 8) {
    if (this.trailCount < 2) return;

    // Walk the ring buffer from oldest to newest
    const start = this.trailCount < this.trailLength
      ? 0
      : this.trailHead;

    let prevIdx = start * 3;
    let prev = this.project(
      this.trail[prevIdx], this.trail[prevIdx+1], this.trail[prevIdx+2],
      cx, cy, scale
    );

    for (let i = 1; i < this.trailCount; i++) {
      const bufIdx = ((start + i) % this.trailLength) * 3;
      const cur = this.project(
        this.trail[bufIdx], this.trail[bufIdx+1], this.trail[bufIdx+2],
        cx, cy, scale
      );

      // Alpha: oldest = faint, newest = bright
      const t = i / this.trailCount;
      const alpha = t * 0.9 + 0.1;

      // Color: hue shifts along the trail
      const hue = (t * 240 + 200) % 360; // blue to purple

      ctx.beginPath();
      ctx.moveTo(prev.sx, prev.sy);
      ctx.lineTo(cur.sx, cur.sy);
      ctx.strokeStyle = `hsla(${hue}, 80%, 60%, ${alpha})`;
      ctx.lineWidth = 0.8;
      ctx.stroke();

      prev = cur;
    }
  }
}

// ─── Usage ──────────────────────────────────────────────────────
//
// const canvas = document.getElementById('canvas');
// const ctx = setupCanvas(canvas, window.innerWidth, window.innerHeight);
// const lorenz = new LorenzAttractor({ trailLength: 8000, dt: 0.005 });
//
// function loop() {
//   // Dark background with slight trail
//   ctx.fillStyle = 'rgba(5, 5, 15, 0.02)';
//   ctx.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight);
//
//   // Step multiple times per frame for faster evolution
//   lorenz.stepN(10);
//
//   // Render centered on canvas
//   lorenz.render(ctx, canvas.clientWidth / 2, canvas.clientHeight / 2, 8);
//
//   requestAnimationFrame(loop);
// }
// requestAnimationFrame(loop);
//
// ─── Classic Parameters ─────────────────────────────────────────
// sigma=10, rho=28, beta=8/3   → classic butterfly
// sigma=10, rho=99.96, beta=8/3 → tighter knots
// sigma=14, rho=28, beta=8/3   → wider wings
```
