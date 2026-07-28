# GSAP Core API

## Tween Methods

### gsap.to(targets, vars)

Anime les proprietes VERS les valeurs specifiees.

```js
gsap.to(".box", {
  x: 200,           // translateX
  y: -50,           // translateY
  rotation: 360,    // rotate en degres
  scale: 1.5,
  opacity: 0.5,
  duration: 1,
  ease: "power2.out",
  delay: 0.3,
});
```

`targets` : selecteur CSS string, element, Array d'elements, NodeList, ou objet JS.

### gsap.from(targets, vars)

Anime DEPUIS les valeurs specifiees vers l'etat actuel.

```js
gsap.from(".box", { y: 100, opacity: 0, duration: 0.8 });
```

**Attention** : `immediateRender` est `true` par defaut sur `from()`. L'element saute aux valeurs `from` immediatement. Mettre `immediateRender: false` si necessaire.

### gsap.fromTo(targets, fromVars, toVars)

Controle total sur le depart ET l'arrivee.

```js
gsap.fromTo(".box",
  { x: -100, opacity: 0 },          // from
  { x: 0, opacity: 1, duration: 1 } // to (options ici)
);
```

### gsap.set(targets, vars)

Applique des valeurs immediatement (duration: 0). Equivalent a `gsap.to(target, { ...vars, duration: 0 })`.

```js
gsap.set(".box", { x: 0, y: 0, opacity: 1, clearProps: "all" });
```

`clearProps: "all"` supprime tous les inline styles appliques par GSAP.

## Options de Tween

| Option            | Type              | Defaut    | Description                                                 |
| ----------------- | ----------------- | --------- | ----------------------------------------------------------- |
| `duration`        | number            | `0.5`     | Duree en secondes                                           |
| `ease`            | string            | `"power1.out"` | Courbe d'animation                                     |
| `delay`           | number            | `0`       | Delai avant demarrage                                       |
| `repeat`          | number            | `0`       | Nombre de repetitions (`-1` = infini)                       |
| `yoyo`            | boolean           | `false`   | Alterne la direction a chaque repeat                        |
| `repeatDelay`     | number            | `0`       | Delai entre chaque repeat                                   |
| `stagger`         | number/object     | `0`       | Delai entre chaque target                                   |
| `overwrite`       | boolean/string    | `false`   | `true` kill les tweens en conflit, `"auto"` les proprietes  |
| `immediateRender` | boolean           | auto      | `true` sur from/fromTo, `false` sur to                      |
| `paused`          | boolean           | `false`   | Cree le tween en pause                                      |
| `reversed`        | boolean           | `false`   | Joue en reverse                                             |
| `onStart`         | function          | null      | Callback au demarrage                                       |
| `onUpdate`        | function          | null      | Callback a chaque frame                                     |
| `onComplete`      | function          | null      | Callback a la fin                                           |
| `onRepeat`        | function          | null      | Callback a chaque repeat                                    |
| `onReverseComplete` | function        | null      | Callback quand reverse atteint le debut                     |
| `callbackScope`   | object            | tween     | Scope `this` des callbacks                                  |

## Easing

Format : `"type.direction"` — ex: `"power2.out"`, `"elastic.inOut"`, `"back.in"`.

Types courants :
- `none` (lineaire), `power1`-`power4`, `back`, `elastic`, `bounce`, `circ`, `expo`, `sine`
- `steps(n)` — animation par paliers
- `"slow(0.7, 0.7, false)"` — slow-mo effect
- Custom : `CustomEase.create("myEase", "M0,0 C0.5,0 0.5,1 1,1")`

## Stagger

### Simple

```js
gsap.to(".item", { y: -20, stagger: 0.1 }); // 0.1s entre chaque element
```

### Object config

```js
gsap.to(".item", {
  y: -20,
  stagger: {
    each: 0.1,           // temps entre chaque element
    // OU amount: 0.8,   // temps TOTAL pour le stagger (divise par N elements)
    from: "center",       // "start" | "end" | "center" | "edges" | "random" | number (index)
    grid: "auto",         // active la distribution 2D, detecte la grille
    axis: "y",            // "x" | "y" | null (distance 2D)
    ease: "power2.in",   // ease de la distribution du stagger
  },
});
```

## Proprietes CSS animables

### Transforms (GPU — privilegier)

| GSAP shorthand | CSS equivalent         |
| --------------- | ---------------------- |
| `x`             | `translateX`           |
| `y`             | `translateY`           |
| `z`             | `translateZ`           |
| `rotation`      | `rotate` (en degres)   |
| `rotationX/Y`   | `rotateX/Y`           |
| `scale`         | `scale`                |
| `scaleX/Y`      | `scaleX/Y`            |
| `skewX/Y`       | `skewX/Y`              |
| `xPercent`      | `translateX(%)`        |
| `yPercent`      | `translateY(%)`        |
| `transformOrigin` | `transform-origin`   |

### Autres proprietes

- `opacity`, `borderRadius`, `backgroundColor`, `color`, `boxShadow`
- CSS variables : `gsap.to(el, { "--my-var": 100 })`
- SVG : `attr: { cx: 200, r: 50 }` pour les attributs SVG

## Utilitaires

### gsap.defaults(vars)

Applique des defauts a TOUS les tweens crees apres cet appel.

```js
gsap.defaults({ duration: 0.8, ease: "power2.out" });
```

### gsap.registerPlugin(...plugins)

Enregistre les plugins. A appeler une seule fois, au top level.

```js
import { ScrollTrigger, SplitText, Flip } from "gsap/all";
gsap.registerPlugin(ScrollTrigger, SplitText, Flip);
```

### gsap.quickTo(target, prop, vars)

Cree une fonction reutilisable pour animer une propriete (ideal pour mouse-follow).

```js
const xTo = gsap.quickTo(".cursor", "x", { duration: 0.3, ease: "power3" });
const yTo = gsap.quickTo(".cursor", "y", { duration: 0.3, ease: "power3" });

window.addEventListener("mousemove", (e) => {
  xTo(e.clientX);
  yTo(e.clientY);
});
```

### gsap.quickSetter(target, prop, unit)

Comme quickTo mais instantane (pas d'interpolation). Ultra performant pour onUpdate.

```js
const setX = gsap.quickSetter(".el", "x", "px");
```

### gsap.utils

```js
gsap.utils.toArray(".items")        // NodeList -> Array
gsap.utils.clamp(0, 100, value)     // clampe la valeur
gsap.utils.mapRange(0, 1, 0, 100, 0.5) // map 0.5 -> 50
gsap.utils.wrap([1, 2, 3], 5)       // cycle: retourne 3
gsap.utils.interpolate(0, 100, 0.5) // retourne 50
gsap.utils.random(1, 10, 1)         // random entre 1-10, step 1
gsap.utils.shuffle(array)           // melange le tableau
gsap.utils.distribute({ amount: 1, from: "center" }) // fonction de distribution
```

### gsap.context()

Scope pour cleanup facile (crucial en React/Vue). Remplace par `useGSAP()` en React.

```js
const ctx = gsap.context(() => {
  gsap.to(".box", { x: 200 });
  ScrollTrigger.create({ ... });
}, containerRef); // scope selecteurs au container

// Cleanup
ctx.revert(); // tue tout : tweens, ScrollTriggers, etc.
```

## Controle d'un Tween

```js
const tween = gsap.to(".box", { x: 200, paused: true });

tween.play();
tween.pause();
tween.reverse();
tween.restart();
tween.kill();

tween.progress(0.5);    // saute a 50%
tween.timeScale(2);     // 2x plus rapide
tween.duration();        // getter
tween.duration(2);       // setter
```
